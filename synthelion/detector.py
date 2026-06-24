# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re

from synthelion.word_provider import FunctionWordProvider

_WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)

# When a curated language scores >= this fraction of the best YAML-derived score,
# prefer the curated language. Prevents Italian/Catalan/Portuguese confusion on
# short texts where "per", "un" appear in multiple worddata files.
_CURATED_PREFERENCE_THRESHOLD = 0.75


class LanguageDetector:
    """Detects text language by stop-word frequency scoring.

    Ported from C# CavemanLanguageDetector. Backed by the embedded worddata index
    so detection never loads the large per-language blobs.

    Curated languages (eng, ita, fra, deu, spa, por, nld) are preferred over
    YAML-derived ones when scores are close, avoiding false positives from
    overlapping Romance-language vocabulary.
    """

    def __init__(self, word_provider: FunctionWordProvider | None = None) -> None:
        self._provider = word_provider or FunctionWordProvider()
        self._supported = self._provider.get_all_supported_iso3()
        self._curated_iso3s = self._provider.get_curated_iso3s()

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

        # If the top result is not from the curated set, check whether a curated
        # language scores close enough to prefer it (avoids ita→cat confusion).
        if best_iso3 not in self._curated_iso3s:
            best_curated = max(
                ((iso3, s) for iso3, s in scores.items() if iso3 in self._curated_iso3s),
                key=lambda x: x[1],
                default=None,
            )
            if best_curated and best_curated[1] >= best_score * _CURATED_PREFERENCE_THRESHOLD:
                best_iso3 = best_curated[0]
                best_score = best_curated[1]

        second_best = max(
            (v for k, v in scores.items() if k != best_iso3), default=0
        )
        if best_score > second_best or (best_score == second_best and best_score >= 2):
            return best_iso3

        # Tiebreak: if both languages are tied and one is curated, prefer it
        tied_curated = [
            iso3 for iso3, s in scores.items()
            if s == best_score and iso3 in self._curated_iso3s
        ]
        if tied_curated:
            return tied_curated[0]

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
