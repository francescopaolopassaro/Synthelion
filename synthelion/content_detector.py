# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import json
import re

from synthelion.models import ContentDetectionResult, ContentType

_LOG_LEVEL = re.compile(r"\b(ERROR|WARN(?:ING)?|INFO|DEBUG|FATAL|TRACE)\b", re.IGNORECASE)
_STACK_FRAME = re.compile(r"^\s+at\s+\S", re.MULTILINE)
_DIFF_HEADER = re.compile(r"^(\+\+\+|---)\s", re.MULTILINE)
_SEARCH_RESULT = re.compile(r"^\s*\d+\.\s+\S", re.MULTILINE)
_GREP_RESULT = re.compile(r"^[A-Za-z0-9_./@\-\\][^:\n]*:\d+:\S", re.MULTILINE)

_HTML_MARKERS = ("<html", "<!doctype", "<body", "<div", "<p>")
_CODE_INDICATORS = ("{", "}", ";", "=>", "->", "def ", "function ", "class ", "import ", "#include", "public ", "private ")


class ContentDetector:
    """Classifies content type using purely structural/lexical heuristics.

    Ported from C# CavemanContentDetector. Stateless — instantiate once and reuse.
    """

    def detect(self, content: str) -> ContentDetectionResult:
        if not content or not content.strip():
            return ContentDetectionResult(ContentType.PLAIN_TEXT, 1.0)

        trimmed = content.strip()
        first = trimmed[0]

        # 1 — JSON Array
        if first == "[" and trimmed[-1] == "]":
            try:
                parsed = json.loads(content)
                if isinstance(parsed, list):
                    return ContentDetectionResult(ContentType.JSON_ARRAY, 0.98)
            except json.JSONDecodeError:
                pass

        # 2 — JSON Object
        if first == "{" and trimmed[-1] == "}":
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    return ContentDetectionResult(ContentType.JSON_OBJECT, 0.95)
            except json.JSONDecodeError:
                pass

        # 3 — Git diff
        if _DIFF_HEADER.search(content):
            return ContentDetectionResult(ContentType.GIT_DIFF, 0.93)

        # 4 — Log / stack trace
        lines = content.splitlines()
        log_hits = sum(1 for l in lines if _LOG_LEVEL.search(l))
        stack_hits = len(_STACK_FRAME.findall(content))
        if log_hits >= 2 or stack_hits >= 2:
            return ContentDetectionResult(ContentType.LOG_OR_STACKTRACE, 0.88)

        # 5 — HTML
        low = content.lower()
        if any(m in low for m in _HTML_MARKERS):
            return ContentDetectionResult(ContentType.HTML, 0.90)

        # 6 — Search results (numbered list or grep output)
        if _SEARCH_RESULT.search(content) or _GREP_RESULT.search(content):
            return ContentDetectionResult(ContentType.SEARCH_RESULTS, 0.80)

        # 7 — Markdown table (| header | … |)
        if content.count("|") > 4 and any(l.startswith("|") for l in lines[:5]):
            return ContentDetectionResult(ContentType.TABULAR, 0.75)

        # 8 — Code (structural indicators)
        code_score = sum(1 for ind in _CODE_INDICATORS if ind in content)
        if code_score >= 3:
            return ContentDetectionResult(ContentType.CODE, 0.70)

        return ContentDetectionResult(ContentType.PLAIN_TEXT, 1.0)
