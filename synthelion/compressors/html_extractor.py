# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import html
import re
from html.parser import HTMLParser


_BLOCK_TAGS = frozenset({
    "p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "main", "aside", "nav",
    "blockquote", "pre", "ul", "ol", "table",
})
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_SKIP_TAGS = frozenset({"script", "style", "head", "noscript", "iframe", "svg"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._heading: str | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if self._skip_depth:
            return
        if tag in _HEADING_TAGS:
            self._heading = tag
            self._parts.append("\n# ")
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if self._heading and tag == self._heading:
            self._heading = None
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        lines = [l.rstrip() for l in raw.splitlines()]
        # Collapse multiple blank lines
        result, prev_blank = [], False
        for l in lines:
            is_blank = not l.strip()
            if is_blank and prev_blank:
                continue
            result.append(l)
            prev_blank = is_blank
        return "\n".join(result).strip()


class HtmlExtractor:
    """Extracts plain text from HTML content.

    Ported from C# CavemanHtmlExtractor. Uses stdlib html.parser, no dependencies.
    """

    def extract(self, html_content: str) -> str:
        if not html_content or not html_content.strip():
            return ""
        parser = _TextExtractor()
        try:
            parser.feed(html_content)
            return parser.get_text()
        except Exception:
            # Fallback: strip tags with regex
            clean = re.sub(r"<[^>]+>", " ", html_content)
            return html.unescape(re.sub(r"\s+", " ", clean).strip())
