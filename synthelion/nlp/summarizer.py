# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import math
from collections import Counter

from synthelion.detector import LanguageDetector
from synthelion.nlp.sentence_detector import SentenceDetector
from synthelion.word_provider import FunctionWordProvider

_POSITION_FIRST = 1.5
_POSITION_LAST = 1.2
_POSITION_DEFAULT = 1.0


def _tokenize(text: str, fw: frozenset[str]) -> list[str]:
    import re
    words = re.findall(r"[^\W\d_]+", text.lower(), re.UNICODE)
    return [w for w in words if w not in fw and len(w) > 1]


def _tfidf_scores(sentences: list[str], fw: frozenset[str]) -> list[float]:
    n = len(sentences)
    tokenized = [_tokenize(s, fw) for s in sentences]
    df: Counter[str] = Counter()
    for words in tokenized:
        for w in set(words):
            df[w] += 1

    scores = []
    for i, words in enumerate(tokenized):
        if not words:
            scores.append(0.0)
            continue
        tf = Counter(words)
        score = sum(
            (tf[w] / len(words)) * math.log((n + 1) / (df[w] + 1))
            for w in tf
        )
        # Position bias
        pos_factor = (
            _POSITION_FIRST if i == 0 else
            _POSITION_LAST if i == n - 1 else
            _POSITION_DEFAULT
        )
        scores.append(score * pos_factor)

    return scores


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _mmr_select(
    sentences: list[str],
    scores: list[float],
    fw: frozenset[str],
    k: int,
    lam: float = 0.6,
) -> list[str]:
    """Maximum Marginal Relevance selection with Jaccard similarity."""
    if k >= len(sentences):
        order = sorted(range(len(sentences)), key=lambda i: scores[i], reverse=True)
        return [sentences[i] for i in order]

    tok_sets = [set(_tokenize(s, fw)) for s in sentences]
    selected_idx: list[int] = []
    candidates = list(range(len(sentences)))

    for _ in range(k):
        best_idx, best_score = -1, float("-inf")
        for ci in candidates:
            if not selected_idx:
                mmr = scores[ci]
            else:
                max_sim = max(_jaccard(tok_sets[ci], tok_sets[si]) for si in selected_idx)
                mmr = lam * scores[ci] - (1 - lam) * max_sim
            if mmr > best_score:
                best_score = mmr
                best_idx = ci
        if best_idx < 0:
            break
        selected_idx.append(best_idx)
        candidates.remove(best_idx)

    # Return in original document order
    selected_idx.sort()
    return [sentences[i] for i in selected_idx]


class TfIdfSummarizer:
    """Extractive summarizer using TF-IDF + position bias + MMR diversity.

    Ported from C# CavemanSummarizer. Best for factual/report text.
    """

    def __init__(self, word_provider: FunctionWordProvider | None = None) -> None:
        self._provider = word_provider or FunctionWordProvider()
        self._detector = LanguageDetector(self._provider)
        self._splitter = SentenceDetector(self._provider)

    def summarize(
        self,
        text: str,
        sentence_count: int | None = None,
        ratio: float | None = None,
        iso3: str | None = None,
    ) -> str:
        if not text or not text.strip():
            return ""

        lang = iso3 or self._detector.detect(text)
        fw = self._provider.get_function_words(lang)
        sentences = self._splitter.split_text(text, lang)

        if not sentences:
            return text

        k = sentence_count
        if k is None and ratio is not None:
            k = max(1, round(len(sentences) * ratio))
        if k is None:
            k = max(1, len(sentences) // 3)

        if len(sentences) <= k:
            return text

        scores = _tfidf_scores(sentences, fw)
        selected = _mmr_select(sentences, scores, fw, k)
        return " ".join(selected)
