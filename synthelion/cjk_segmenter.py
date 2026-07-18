# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Dictionary-based Chinese word segmentation.

Chinese has no spaces between words, so the shared `\\p{L}\\p{M}` tokenizer used
everywhere else in Synthelion (core.py, detector.py) matches an entire run of
Han characters as a single "token" — a whole sentence collapses into one
unsplittable blob, so no function word ever matches and compression/detection
both silently no-op for Chinese beyond punctuation stripping.

This module segments a run of Han characters into real words using the same
core algorithm as jieba's dictionary mode (DAG construction + dynamic-
programming shortest-cost path, e.g. https://github.com/fxsjy/jieba) —
re-implemented here rather than taken as a dependency, per the project's
"zero ML model" positioning: jieba's dictionary path is not ML at all (a
weighted directed-acyclic-graph search over a static word list), only its
optional HMM-based unknown-word tagger is, and this module deliberately
skips that part, falling back to single-character tokens for out-of-vocabulary
runs instead.

The dictionary is built from Synthelion's own zho worddata (curated function
words + UD-derived lemma surface forms + proper nouns) rather than a bundled
frequency corpus, so segmentation quality tracks whatever vocabulary
Synthelion already ships — smaller than jieba's ~350k-word dictionary, but
zero extra weight and no additional license to track.
"""
from __future__ import annotations

from synthelion.word_provider import FunctionWordProvider

_MAX_WORD_LEN = 8

_dictionary: frozenset[str] | None = None
_max_len_cache: int | None = None


def _build_dictionary(provider: FunctionWordProvider) -> frozenset[str]:
    words: set[str] = set()
    words.update(provider.get_function_words("zho"))
    words.update(provider.get_lemma_map("zho").keys())
    words.update(provider.get_proper_nouns("zho"))
    # Lemma *values* (the canonical forms verbs/lemmas map to) are also real
    # surface-form words worth matching even if no inflected form pointed at
    # them directly in this particular text.
    words.update(provider.get_lemma_map("zho").values())
    return frozenset(w for w in words if w)


def _get_dictionary(provider: FunctionWordProvider | None = None) -> frozenset[str]:
    global _dictionary, _max_len_cache
    if _dictionary is None:
        _dictionary = _build_dictionary(provider or FunctionWordProvider())
        _max_len_cache = min(_MAX_WORD_LEN, max((len(w) for w in _dictionary), default=1))
    return _dictionary


def is_han(char: str) -> bool:
    """True for CJK Unified Ideographs (the common Han block Synthelion's zho
    worddata is built from). Deliberately narrow — punctuation, digits, and
    Latin text mixed into Chinese input are handled by the existing tokenizer
    regex, not this module."""
    cp = ord(char)
    return 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF


def segment_han_run(text: str, provider: FunctionWordProvider | None = None) -> list[str]:
    """Segments a contiguous run of Han characters into words.

    DAG + dynamic programming, longest-match-biased: for each start position,
    every dictionary word starting there is an edge to the position right
    after it; the best path end-to-start maximises the sum of each edge's
    weight (word length squared, since no real corpus frequency data is
    available here — this favours fewer, longer matched words over many
    single-character fallbacks, the same bias jieba's frequency-based scoring
    achieves via real corpus statistics). A position with no dictionary word
    starting there falls back to a single-character token, so segmentation
    always terminates and never drops content.
    """
    if not text:
        return []
    dictionary = _get_dictionary(provider)
    n = len(text)
    max_len = _max_len_cache or 1

    # dag[i] = list of end positions j (exclusive) such that text[i:j] is a
    # known dictionary word.
    dag: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        limit = min(n, i + max_len)
        for j in range(i + 1, limit + 1):
            if text[i:j] in dictionary:
                dag[i].append(j)

    # best_cost[i] = best achievable score from position i to the end.
    best_cost = [0.0] * (n + 1)
    choice: list[int] = [i + 1 for i in range(n)]  # default: single char
    for i in range(n - 1, -1, -1):
        best = -1.0
        best_j = i + 1
        candidates = dag[i] or [i + 1]
        for j in candidates:
            score = (j - i) ** 2 + best_cost[j]
            if score > best:
                best = score
                best_j = j
        best_cost[i] = best
        choice[i] = best_j

    out = []
    i = 0
    while i < n:
        j = choice[i]
        out.append(text[i:j])
        i = j
    return out


def reset_cache() -> None:
    """Test/dev helper: forces the dictionary to rebuild on next use (e.g.
    after worddata files change on disk)."""
    global _dictionary, _max_len_cache
    _dictionary = None
    _max_len_cache = None
