# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

_HTML_NOISE_RE = re.compile(r"<[^>]{1,200}>|<!--[\s\S]*?-->")
_BASE64_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{50,}={0,2}")
_EXCESS_WHITESPACE_RE = re.compile(r"[ \t]{4,}|\n{3,}")
_JSON_BLOAT_RE = re.compile(r"\{[\s\S]{500,}\}")


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class WasteAnalysis:
    html_noise_tokens: int = 0
    base64_tokens: int = 0
    whitespace_tokens: int = 0
    json_bloat_tokens: int = 0

    @property
    def total_waste_tokens(self) -> int:
        return self.html_noise_tokens + self.base64_tokens + self.whitespace_tokens + self.json_bloat_tokens


class WasteAnalyzer:
    """Detects and estimates token waste: HTML noise, base64 blobs, excess whitespace, large JSON.

    Ported from C# CavemanWasteAnalyzer. Read-only — does not modify content; use
    alongside a compressor to act on the findings.
    """

    def analyze(self, content: str) -> WasteAnalysis:
        if not content:
            return WasteAnalysis()

        html = sum(_estimate_tokens(m.group()) for m in _HTML_NOISE_RE.finditer(content))
        b64 = sum(_estimate_tokens(m.group()) for m in _BASE64_BLOB_RE.finditer(content))
        ws = sum(_estimate_tokens(m.group()) for m in _EXCESS_WHITESPACE_RE.finditer(content))
        jb = sum(_estimate_tokens(m.group()) for m in _JSON_BLOAT_RE.finditer(content))

        return WasteAnalysis(html_noise_tokens=html, base64_tokens=b64, whitespace_tokens=ws, json_bloat_tokens=jb)

    def analyze_messages(self, message_contents: Iterable[str]) -> WasteAnalysis:
        html = b64 = ws = jb = 0
        for msg in message_contents:
            a = self.analyze(msg)
            html += a.html_noise_tokens
            b64 += a.base64_tokens
            ws += a.whitespace_tokens
            jb += a.json_bloat_tokens
        return WasteAnalysis(html_noise_tokens=html, base64_tokens=b64, whitespace_tokens=ws, json_bloat_tokens=jb)
