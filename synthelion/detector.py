# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re

from synthelion.word_provider import FunctionWordProvider

_WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)


class LanguageDetector:
    """Detects text language by stop-word frequency scoring.

    Ported from C# CavemanLanguageDetector. Backed by the embedded worddata index
    so detection never loads the large per-language blobs.
    """

    def __init__(self, word_provider: FunctionWordProvider | None = None) -> None:
        self._provider = word_provider or FunctionWordProvider()
        self._supported = self._provider.get_all_supported_iso3()

    def detect(self, text: str) -> str:
        """Return the most likely ISO 639-3 code, falling back to 'eng'."""
        if not text or not text.strip():
            return "eng"
        tokens = _WORD_RE.findall(text.lower())
        if not tokens:
            return "eng"

        scores: dict[str, int] = {}
        for iso3 in self._supported:
            fw = self._provider.get_function_words(iso3)
            if not fw:
                continue
            hits = sum(1 for t in tokens if t in fw)
            if hits > 0:
                scores[iso3] = hits

        if not scores:
            return "eng"

        best_iso3 = max(scores, key=lambda k: scores[k])
        best_score = scores[best_iso3]
        ratio = best_score / len(tokens)

        if ratio < 0.02:
            return "eng"

        second_best = max(
            (v for k, v in scores.items() if k != best_iso3), default=0
        )
        if best_score > second_best or (best_score == second_best and best_score >= 2):
            return best_iso3

        return "eng"

    def detect_with_scores(self, text: str) -> dict[str, float]:
        """Return per-language match ratios (ISO 639-3 → ratio of tokens matched)."""
        if not text or not text.strip():
            return {"eng": 1.0}
        tokens = _WORD_RE.findall(text.lower())
        if not tokens:
            return {"eng": 1.0}

        scores: dict[str, float] = {}
        total = len(tokens)
        for iso3 in self._supported:
            fw = self._provider.get_function_words(iso3)
            if not fw:
                continue
            hits = sum(1 for t in tokens if t in fw)
            if hits > 0:
                scores[iso3] = hits / total

        return scores if scores else {"eng": 1.0}
