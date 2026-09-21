# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Minimal, dependency-free PDF writer for compliance reports.

Synthelion ships offline and vendors everything it needs, so a report
generator that requires a PDF library at install time would be the only part
of the product with an external runtime dependency for its core output. The
documents this module produces are headings, paragraphs, key/value blocks,
tables and horizontal bars — all of which fit comfortably inside hand-written
PDF using the base-14 fonts every reader has built in, with no font embedding
and no third-party code.

Scope, stated honestly: this emits valid **PDF 1.4**, not PDF/A. PDF/A
archival conformance additionally requires embedded font programs, an
XMP metadata packet and an output-intent profile; claiming it without those
would be false. Where a regulator demands PDF/A specifically, run the output
through a converter — the content is complete either way, and the same report
is always available as JSON.

Text is WinAnsi-encoded: characters outside that range are transliterated
rather than dropped, so an accented name never silently disappears from a
compliance document.
"""
from __future__ import annotations

import struct
import unicodedata
import zlib
from pathlib import Path

# Base-14 fonts — no embedding required.
FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"

PAGE_W, PAGE_H = 595.28, 841.89      # A4 in points
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 56.0, 56.0, 56.0

# Widths of the Helvetica base-14 glyphs, in 1/1000 em. Only what's needed to
# wrap text correctly; anything unlisted falls back to the average.
_W_DEFAULT = 556
_W_NARROW = {" ": 278, "i": 222, "j": 222, "l": 222, "t": 278, "f": 278, "r": 333,
             "I": 278, ".": 278, ",": 278, ":": 278, ";": 278, "'": 191, "!": 278,
             "|": 260, "(": 333, ")": 333, "[": 278, "]": 278, "/": 278, "-": 333}
_W_WIDE = {"m": 833, "w": 722, "M": 833, "W": 944, "@": 1015, "%": 889}


def _char_width(ch: str, bold: bool) -> float:
    w = _W_NARROW.get(ch) or _W_WIDE.get(ch) or _W_DEFAULT
    return w * (1.05 if bold else 1.0)


def text_width(text: str, size: float, bold: bool = False) -> float:
    return sum(_char_width(c, bold) for c in text) * size / 1000.0


def _to_winansi(text: str) -> str:
    """Fold text into the WinAnsi range, transliterating instead of dropping."""
    out = []
    for ch in text:
        if ord(ch) < 128:
            out.append(ch)
            continue
        if ch in "€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ":
            out.append({"‘": "'", "’": "'", "“": '"', "”": '"',
                        "–": "-", "—": "-", "…": "...", "•": "-"}.get(ch, ch))
            continue
        if 160 <= ord(ch) <= 255:
            out.append(ch)
            continue
        decomposed = unicodedata.normalize("NFKD", ch)
        stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
        out.append(stripped if stripped.isprintable() and stripped else "?")
    return "".join(out)


def _escape(text: str) -> str:
    return _to_winansi(text).replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def wrap(text: str, size: float, max_width: float, bold: bool = False) -> list[str]:
    """Greedy word wrap. A single word longer than the line is hard-split so it
    can never run off the page edge."""
    lines: list[str] = []
    for paragraph in (text or "").split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if text_width(candidate, size, bold) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            while text_width(word, size, bold) > max_width and len(word) > 1:
                cut = len(word)
                while cut > 1 and text_width(word[:cut], size, bold) > max_width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        if current:
            lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# PNG -> RGB, stdlib only
#
# PDF can carry a PNG's compressed data almost verbatim, but only without an
# alpha channel unless a separate soft-mask object is added. The brand mark is
# RGBA, so it is decoded here and composited onto white — the page background
# it sits on anyway — which keeps one code path instead of two and avoids
# pulling in an imaging library just to place a logo.
# ---------------------------------------------------------------------------

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def png_to_rgb(path: "str | Path") -> tuple[bytes, int, int] | None:
    """Return (raw RGB bytes, width, height), or None if unsupported.

    Handles the 8-bit truecolour and greyscale forms (with or without alpha)
    that the brand assets use. Anything else — palettes, 16-bit samples,
    interlacing — returns None so the caller simply omits the logo rather than
    emitting a corrupt image.
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if not data.startswith(_PNG_MAGIC):
        return None

    width = height = 0
    bit_depth = colour_type = interlace = 0
    idat = bytearray()
    pos = 8
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bit_depth, colour_type, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break
        pos += 12 + length          # length + type + data + CRC

    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(colour_type)
    if channels is None or bit_depth != 8 or interlace != 0 or not idat:
        return None

    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error:
        return None

    stride = width * channels
    out = bytearray(stride * height)
    prev = bytearray(stride)
    at = 0
    for row in range(height):
        if at >= len(raw):
            return None
        filt = raw[at]
        at += 1
        line = bytearray(raw[at:at + stride])
        if len(line) < stride:
            return None
        at += stride
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = prev[i]
            upleft = prev[i - channels] if i >= channels else 0
            if filt == 1:
                line[i] = (line[i] + left) & 0xFF
            elif filt == 2:
                line[i] = (line[i] + up) & 0xFF
            elif filt == 3:
                line[i] = (line[i] + ((left + up) >> 1)) & 0xFF
            elif filt == 4:
                line[i] = (line[i] + _paeth(left, up, upleft)) & 0xFF
            elif filt != 0:
                return None
        out[row * stride:(row + 1) * stride] = line
        prev = line

    # Composite onto white and normalise to 3 channels.
    rgb = bytearray(width * height * 3)
    for i in range(width * height):
        px = out[i * channels:(i + 1) * channels]
        if channels == 1:
            r = g = b = px[0]
            alpha = 255
        elif channels == 2:
            r = g = b = px[0]
            alpha = px[1]
        elif channels == 3:
            r, g, b = px
            alpha = 255
        else:
            r, g, b, alpha = px
        if alpha != 255:
            r = (r * alpha + 255 * (255 - alpha)) // 255
            g = (g * alpha + 255 * (255 - alpha)) // 255
            b = (b * alpha + 255 * (255 - alpha)) // 255
        rgb[i * 3:i * 3 + 3] = bytes((r, g, b))
    return bytes(rgb), width, height


def default_logo_path() -> Path:
    """The brand mark shipped with the dashboard assets."""
    return Path(__file__).resolve().parents[1] / "plugins" / "dashboard_assets" / "img" / "logo.png"


class PdfDocument:
    """Flowing single-column document with automatic pagination."""

    def __init__(self, title: str = "", subtitle: str = "", footer: str = "",
                 logo: "str | Path | None" = None) -> None:
        self.title = title
        self.subtitle = subtitle
        self.footer = footer
        self._pages: list[list[str]] = []
        self._ops: list[str] = []
        self._y = PAGE_H - MARGIN_TOP
        self._content_w = PAGE_W - 2 * MARGIN_X
        # None means "use the shipped brand mark"; pass "" to omit it entirely.
        source = default_logo_path() if logo is None else logo
        self._logo = png_to_rgb(source) if source else None
        self._start_page()

    # -- page handling ----------------------------------------------------

    def _start_page(self) -> None:
        self._ops = []
        self._y = PAGE_H - MARGIN_TOP
        if self._pages or not self.title:
            return
        self._draw_logo()
        self.heading(self.title, size=20)
        if self.subtitle:
            self.paragraph(self.subtitle, size=10, gray=0.35)
        self.rule()

    def _draw_logo(self, height: float = 26.0) -> None:
        """Brand mark at the top of the first page, scaled to `height` points."""
        if not self._logo:
            return
        _, px_w, px_h = self._logo
        width = height * (px_w / px_h)
        y = self._y - height
        # `cm` sets the transform: an XObject image draws into the unit square,
        # so the matrix is literally the placed width/height and origin.
        self._ops.append(
            f"q {width:.2f} 0 0 {height:.2f} {MARGIN_X:.2f} {y:.2f} cm /Im0 Do Q")
        self._y -= height + 14

    def _end_page(self) -> None:
        self._pages.append(self._ops)
        self._ops = []

    def _need(self, height: float) -> None:
        if self._y - height < MARGIN_BOTTOM:
            self._end_page()
            self._ops = []
            self._y = PAGE_H - MARGIN_TOP

    def _draw_text(self, text: str, x: float, y: float, size: float,
                   bold: bool = False, gray: float = 0.0) -> None:
        font = "F2" if bold else "F1"
        self._ops.append(
            f"BT /{font} {size:.2f} Tf {gray:.2f} g {x:.2f} {y:.2f} Td ({_escape(text)}) Tj ET")

    # -- content blocks ---------------------------------------------------

    def heading(self, text: str, size: float = 14, space_before: float = 10) -> None:
        self._need(size + space_before + 6)
        self._y -= space_before
        self._draw_text(text, MARGIN_X, self._y - size, size, bold=True)
        self._y -= size + 4

    def paragraph(self, text: str, size: float = 9.5, gray: float = 0.15,
                  leading: float = 1.45, indent: float = 0.0) -> None:
        for line in wrap(text, size, self._content_w - indent):
            if not line:
                self._y -= size * leading * 0.5
                continue
            self._need(size * leading)
            self._draw_text(line, MARGIN_X + indent, self._y - size, size, gray=gray)
            self._y -= size * leading
        self._y -= 3

    def key_values(self, pairs: list[tuple[str, str]], size: float = 9.5) -> None:
        label_w = max((text_width(k, size, True) for k, _ in pairs), default=0) + 14
        for key, value in pairs:
            for i, line in enumerate(wrap(str(value), size, self._content_w - label_w)):
                self._need(size * 1.5)
                if i == 0:
                    self._draw_text(key, MARGIN_X, self._y - size, size, bold=True, gray=0.25)
                self._draw_text(line, MARGIN_X + label_w, self._y - size, size, gray=0.1)
                self._y -= size * 1.5
        self._y -= 4

    def table(self, headers: list[str], rows: list[list[str]],
              widths: list[float] | None = None, size: float = 8.5) -> None:
        """Column widths are fractions of the content width; text is wrapped
        per cell and the row grows to fit the tallest one."""
        cols = len(headers)
        fractions = widths or [1.0 / cols] * cols
        col_w = [f * self._content_w for f in fractions]

        def draw_row(cells: list[str], bold: bool, gray: float) -> None:
            wrapped = [wrap(str(c), size, col_w[i] - 8, bold) or [""] for i, c in enumerate(cells)]
            height = max(len(w) for w in wrapped) * size * 1.4
            self._need(height + 4)
            top = self._y
            for i, lines in enumerate(wrapped):
                x = MARGIN_X + sum(col_w[:i])
                for j, line in enumerate(lines):
                    self._draw_text(line, x + 2, top - size - j * size * 1.4, size, bold, gray)
            self._y = top - height - 3
            self._ops.append(
                f"0.88 G 0.5 w {MARGIN_X:.2f} {self._y + 1:.2f} m "
                f"{MARGIN_X + self._content_w:.2f} {self._y + 1:.2f} l S")

        draw_row(headers, True, 0.35)
        for row in rows:
            draw_row(row, False, 0.1)
        self._y -= 5

    def bar_chart(self, data: list[tuple[str, float]], size: float = 8.5,
                  bar_h: float = 11, label_w: float = 130) -> None:
        """Horizontal bars with the value printed at the end of each — the
        report has no interactive layer, so every bar carries its number."""
        if not data:
            self.paragraph("No data recorded for this period.", gray=0.45)
            return
        peak = max(v for _, v in data) or 1
        track = self._content_w - label_w - 52
        for label, value in data:
            self._need(bar_h + 5)
            y = self._y - bar_h
            self._draw_text(str(label)[:34], MARGIN_X, y + 2.5, size, gray=0.2)
            width = max(1.0, (value / peak) * track)
            self._ops.append(
                f"0.0 0.443 0.890 rg {MARGIN_X + label_w:.2f} {y:.2f} "
                f"{width:.2f} {bar_h:.2f} re f")
            self._draw_text(f"{value:,.0f}", MARGIN_X + label_w + width + 6, y + 2.5, size, gray=0.25)
            self._y -= bar_h + 5
        self._y -= 4

    def rule(self) -> None:
        self._need(8)
        self._y -= 4
        self._ops.append(f"0.85 G 0.6 w {MARGIN_X:.2f} {self._y:.2f} m "
                         f"{MARGIN_X + self._content_w:.2f} {self._y:.2f} l S")
        self._y -= 8

    def spacer(self, height: float = 8) -> None:
        self._need(height)
        self._y -= height

    # -- serialisation ----------------------------------------------------

    def _page_streams(self) -> list[str]:
        pages = self._pages + ([self._ops] if self._ops else [])
        if not pages:
            pages = [[]]
        out = []
        for index, ops in enumerate(pages, start=1):
            body = list(ops)
            if self.footer:
                body.append(
                    f"BT /F1 7.50 Tf 0.55 g {MARGIN_X:.2f} {MARGIN_BOTTOM - 22:.2f} Td "
                    f"({_escape(self.footer)}) Tj ET")
            label = f"Page {index} of {len(pages)}"
            body.append(
                f"BT /F1 7.50 Tf 0.55 g "
                f"{PAGE_W - MARGIN_X - text_width(label, 7.5):.2f} {MARGIN_BOTTOM - 22:.2f} Td "
                f"({_escape(label)}) Tj ET")
            out.append("\n".join(body))
        return out

    def to_bytes(self) -> bytes:
        streams = self._page_streams()
        n_pages = len(streams)

        objects: list[bytes] = []          # 1-indexed on write
        font_regular = 3 + 2 * n_pages + 1
        font_bold = font_regular + 1
        image_ref = font_bold + 1 if self._logo else None

        # Only the first page draws the logo, but naming the XObject in every
        # page's resources is harmless and keeps one dictionary shape.
        xobject = f"/XObject << /Im0 {image_ref} 0 R >> " if image_ref else ""

        kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objects.append(f"<< /Type /Pages /Count {n_pages} /Kids [{kids}] >>".encode())

        for i, stream in enumerate(streams):
            content_ref = 4 + 2 * i
            objects.append((
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:.2f} {PAGE_H:.2f}] "
                f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> "
                f"{xobject}>> "
                f"/Contents {content_ref} 0 R >>").encode())
            data = stream.encode("latin-1", "replace")
            objects.append(b"<< /Length " + str(len(data)).encode() + b" >>\nstream\n"
                           + data + b"\nendstream")

        objects.append(f"<< /Type /Font /Subtype /Type1 /BaseFont /{FONT_REGULAR} "
                       f"/Encoding /WinAnsiEncoding >>".encode())
        objects.append(f"<< /Type /Font /Subtype /Type1 /BaseFont /{FONT_BOLD} "
                       f"/Encoding /WinAnsiEncoding >>".encode())

        if self._logo:
            rgb, px_w, px_h = self._logo
            packed = zlib.compress(rgb, 9)
            objects.append(
                (f"<< /Type /XObject /Subtype /Image /Width {px_w} /Height {px_h} "
                 f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
                 f"/Length {len(packed)} >>\nstream\n").encode() + packed + b"\nendstream")
        objects.append(("<< /Title (" + _escape(self.title) + ") /Producer (Synthelion Compliance Engine) "
                        "/Creator (Synthelion) >>").encode())

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

        xref_at = len(out)
        count = len(objects) + 1
        out += f"xref\n0 {count}\n".encode()
        out += b"0000000000 65535 f \n"
        for offset in offsets[1:]:
            out += f"{offset:010d} 00000 n \n".encode()
        out += (f"trailer\n<< /Size {count} /Root 1 0 R /Info {len(objects)} 0 R >>\n"
                f"startxref\n{xref_at}\n%%EOF\n").encode()
        return bytes(out)

    def save(self, path: "str | Path") -> Path:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(self.to_bytes())
        return p
