# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re
from collections import Counter

from synthelion.detector import LanguageDetector
from synthelion.nlp.sentence_detector import SentenceDetector
from synthelion.nlp.summarizer import _jaccard, _mmr_select, _tokenize
from synthelion.word_provider import FunctionWordProvider

_DAMPING = 0.85
_MAX_ITER = 100
_TOL = 1e-4
_MAX_SENTENCES = 200  # cap to avoid O(n²) blowup on very long documents

# Chat-aware thresholds (same as C# ChatSummarizeOptions defaults)
_MIN_DISCOURSE_WORDS = 60
_MIN_FW_RATIO = 0.05
_MIN_DISCOURSE_SENTENCES = 3
_DEFAULT_SUMMARY_RATIO = 0.4


def _pagerank(sim_matrix: list[list[float]], max_iter: int = _MAX_ITER, tol: float = _TOL) -> list[float]:
    n = len(sim_matrix)
    if n == 0:
        return []
    scores = [1.0 / n] * n
    for _ in range(max_iter):
        new_scores = []
        for i in range(n):
            col_sum = [sim_matrix[j][i] for j in range(n)]
            total = sum(col_sum)
            rank = (1 - _DAMPING) / n
            if total > 0:
                rank += _DAMPING * sum(
                    scores[j] * sim_matrix[j][i] / sum(sim_matrix[j]) if sum(sim_matrix[j]) > 0 else 0
                    for j in range(n)
                )
            new_scores.append(rank)
        diff = sum(abs(new_scores[i] - scores[i]) for i in range(n))
        scores = new_scores
        if diff < tol:
            break
    return scores


def _word_overlap_sim(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / (len(sa) + len(sb) - len(sa & sb) + 1e-9)


class TextRankSummarizer:
    """Graph-based extractive summarizer using TextRank + MMR.

    Ported from C# CavemanTextRank. PageRank damping=0.85, 100 iterations,
    tol=1e-4. Best for narrative text. Also provides chat-aware mode.
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

        # Cap sentence count to avoid O(n²) blowup; keep first _MAX_SENTENCES sentences
        if len(sentences) > _MAX_SENTENCES:
            sentences = sentences[:_MAX_SENTENCES]

        tok = [_tokenize(s, fw) for s in sentences]
        n = len(sentences)
        sim = [[_word_overlap_sim(tok[i], tok[j]) for j in range(n)] for i in range(n)]
        scores = _pagerank(sim)
        selected = _mmr_select(sentences, scores, fw, k)
        return " ".join(selected)

    def summarize_chat(
        self,
        conversation: str,
        ratio: float = _DEFAULT_SUMMARY_RATIO,
        iso3: str | None = None,
        min_words: int = _MIN_DISCOURSE_WORDS,
        min_sentences: int = _MIN_DISCOURSE_SENTENCES,
        min_fw_ratio: float = _MIN_FW_RATIO,
    ) -> str:
        """Summarize only long natural-language passages; leave short/structured blocks verbatim."""
        if not conversation or not conversation.strip():
            return conversation

        lang = iso3 or self._detector.detect(conversation)
        fw = self._provider.get_function_words(lang)
        blocks = _split_blocks(conversation)
        out_parts: list[str] = []

        for block in blocks:
            words = re.findall(r"\S+", block)
            word_count = len(words)
            if word_count < min_words:
                out_parts.append(block)
                continue
            fw_ratio = sum(1 for w in words if w.lower() in fw) / max(word_count, 1)
            if fw_ratio < min_fw_ratio:
                out_parts.append(block)
                continue
            sentences = self._splitter.split_text(block, lang)
            if len(sentences) < min_sentences:
                out_parts.append(block)
                continue
            out_parts.append(self.summarize(block, ratio=ratio, iso3=lang))

        return "\n\n".join(out_parts)


def _split_blocks(text: str) -> list[str]:
    """Split on double newlines to produce logical blocks."""
    return [b.strip() for b in re.split(r"\n{2,}", text) if b.strip()]
