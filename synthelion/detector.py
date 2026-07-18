# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import regex

from synthelion.word_provider import FunctionWordProvider

# Ported from Caveman C# 1.4.1: the stdlib-`re`-based pattern this used to be
# ([^\W\d_]+...) excludes Unicode combining marks (category M*), fragmenting words in
# scripts like Kannada/Hindi/Tamil/Thai that attach vowel signs/virama as separate
# codepoints. `regex` (already a dependency) supports \p{L}/\p{M} Unicode property escapes
# directly, matching the C# fix.
_WORD_RE = regex.compile(r"[\p{L}\p{M}]+(?:'[\p{L}\p{M}]+)?", regex.UNICODE)

# (threshold removed — the exclusive-marker pass now uses a uniqueness check:
# a language wins if it has MORE exclusive-marker hits than any other language)

# A curated language is preferred over a YAML-only result when its score is
# at least this fraction of the best YAML score.
_CURATED_PREFERENCE_THRESHOLD = 0.75


class LanguageDetector:
    """Detects text language by stop-word frequency scoring.

    Ported from C# CavemanLanguageDetector. Uses a two-pass strategy:
      1. Raw function-word hit count per language.
      2. Exclusive-marker boost: if a language has exclusive markers in the text
         (words that exist in *no* other curated language), it wins over languages
         that only matched shared/ambiguous words.

    This eliminates false positives caused by words like 'per', 'a', 'in', 'via'
    that appear in both English and Italian/Dutch function-word lists.
    """

    def __init__(self, word_provider: FunctionWordProvider | None = None) -> None:
        self._provider = word_provider or FunctionWordProvider()
        # For detection scoring use the full YAML-derived index (not curated FW).
        # Curated FW (.fw.yaml.br) is a small, precise compression set; the full
        # YAML index has 5-10x more words and gives better detection recall.
        self._detection_supported = set(self._provider._load_index().keys())
        self._curated_iso3s = self._provider.get_curated_iso3s()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, text: str) -> str:
        """Return the most likely ISO 639-3 code, falling back to 'eng'."""
        if not text or not text.strip():
            return "eng"
        tokens = _WORD_RE.findall(text.lower())
        if not tokens:
            return "eng"

        raw_scores: dict[str, int] = {}
        idx = self._provider._load_index()
        for iso3, (_, _, fw) in idx.items():
            if not fw:
                continue
            hits = sum(1 for t in tokens if t in fw)
            if hits > 0:
                raw_scores[iso3] = hits

        if not raw_scores:
            return "eng"

        # --- Pass 2: exclusive-marker boost ---
        # For each curated language, count how many exclusive markers appear.
        # An exclusive marker is a word that exists in this language's worddata
        # but in none of the other curated languages.
        excl_scores: dict[str, int] = {}
        for iso3 in self._curated_iso3s:
            excl = self._provider.get_exclusive_markers(iso3)
            if not excl:
                continue
            hits = sum(1 for t in tokens if t in excl)
            if hits > 0:
                excl_scores[iso3] = hits

        # If one language has STRICTLY MORE exclusive-marker hits than all others,
        # prefer it — even 1 hit is enough if no other language has any.
        if excl_scores:
            best_excl_lang = max(excl_scores, key=lambda k: excl_scores[k])
            second_excl = max(
                (v for k, v in excl_scores.items() if k != best_excl_lang), default=0
            )
            if excl_scores[best_excl_lang] > second_excl:
                return best_excl_lang

        # --- Pass 1 winner ---
        best_iso3 = max(raw_scores, key=lambda k: raw_scores[k])
        best_score = raw_scores[best_iso3]
        ratio = best_score / len(tokens)

        if ratio < 0.02:
            return "eng"

        # If the top result is not from the curated set, prefer a close curated one.
        if best_iso3 not in self._curated_iso3s:
            best_curated = max(
                ((iso3, s) for iso3, s in raw_scores.items() if iso3 in self._curated_iso3s),
                key=lambda x: x[1],
                default=None,
            )
            if best_curated and best_curated[1] >= best_score * _CURATED_PREFERENCE_THRESHOLD:
                best_iso3 = best_curated[0]
                best_score = best_curated[1]

        second_best = max(
            (v for k, v in raw_scores.items() if k != best_iso3), default=0
        )
        if best_score > second_best or (best_score == second_best and best_score >= 2):
            return best_iso3

        # Tiebreak: prefer a curated language.
        tied_curated = [
            iso3 for iso3, s in raw_scores.items()
            if s == best_score and iso3 in self._curated_iso3s
        ]
        if tied_curated:
            return tied_curated[0]

        return "eng"

    def detect_with_scores(self, text: str) -> dict[str, float]:
        """Return per-language scores (ISO 639-3 → normalised hit ratio).

        Scores are the raw function-word hit ratio; exclusive-marker bonus is
        applied as a synthetic +0.5 boost so callers can see which language
        the exclusive-marker pass favoured.
        """
        if not text or not text.strip():
            return {"eng": 1.0}
        tokens = _WORD_RE.findall(text.lower())
        if not tokens:
            return {"eng": 1.0}

        total = len(tokens)
        scores: dict[str, float] = {}
        idx = self._provider._load_index()
        for iso3, (_, _, fw) in idx.items():
            if not fw:
                continue
            hits = sum(1 for t in tokens if t in fw)
            if hits > 0:
                scores[iso3] = hits / total

        if not scores:
            return {"eng": 1.0}

        # Apply exclusive-marker boost to curated languages (for external callers).
        for iso3 in self._curated_iso3s:
            excl = self._provider.get_exclusive_markers(iso3)
            if not excl:
                continue
            excl_hits = sum(1 for t in tokens if t in excl)
            if excl_hits >= 1:
                scores[iso3] = scores.get(iso3, 0.0) + (excl_hits / total) * 0.5

        return scores
