# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re
from dataclasses import dataclass

from synthelion.detector import LanguageDetector
from synthelion.nlp.text_splitter import TextSplitter
from synthelion.word_provider import FunctionWordProvider

_BLOCK_SPLIT_RE = re.compile(r"\n\s*\n")
_MD_STRIP_RE = re.compile(r"^\s{0,3}(#{1,6}\s+|[-*+]\s+|>\s+)|(\*\*|__|`{1,3})", re.MULTILINE)


@dataclass
class RelevanceHit:
    text: str
    score: float
    index: int


def _strip_markdown(text: str) -> str:
    """Minimal markdown-syntax stripper so headings/bullets/emphasis don't skew term overlap."""
    return _MD_STRIP_RE.sub("", text)


def _split_blocks(text: str) -> list[str]:
    return [b.strip() for b in _BLOCK_SPLIT_RE.split(text) if b.strip()]


class RelevanceFilter:
    """Lightweight, embedding-free "attention": scores text blocks by content-word overlap with a query.

    Ported from C# CavemanRelevanceFilter. Given a query and a body of text, splits
    the text into paragraph blocks, scores each by lemmatized lexical overlap with the
    query, and keeps the top-K most relevant ones. Ideal for shaping a large context
    down to what actually matters for the current question.
    """

    def __init__(self, word_provider: FunctionWordProvider | None = None) -> None:
        self._word_provider = word_provider or FunctionWordProvider()
        self._detector = LanguageDetector(self._word_provider)
        self._splitter = TextSplitter()

    def focus(self, text: str, query: str, top_k: int, iso3: str | None = None) -> str:
        hits = self.rank(text, query, iso3)
        if not hits:
            return ""

        kept = sorted(hits[: max(1, top_k)], key=lambda h: h.index)
        return "\n\n".join(h.text for h in kept)

    def rank(self, text: str, query: str, iso3: str | None = None) -> list[RelevanceHit]:
        if not text or not text.strip() or not query or not query.strip():
            return []

        clean = _strip_markdown(text)
        if not clean.strip():
            return []

        lang = iso3 or self._detector.detect(query + " " + clean)
        func_words = self._word_provider.get_function_words(lang)
        lemmas = self._word_provider.get_lemma_map(lang)

        query_terms = self._content_words(query, func_words, lemmas)
        if not query_terms:
            return []

        blocks = _split_blocks(clean)
        result = []
        for i, block in enumerate(blocks):
            block_terms = self._content_words(block, func_words, lemmas)
            result.append(RelevanceHit(text=block, index=i, score=_similarity(query_terms, block_terms)))

        result.sort(key=lambda h: (-h.score, h.index))
        return result

    def score(self, text: str, query: str, iso3: str | None = None) -> float:
        if not text or not text.strip() or not query or not query.strip():
            return 0.0

        lang = iso3 or self._detector.detect(query + " " + text)
        func_words = self._word_provider.get_function_words(lang)
        lemmas = self._word_provider.get_lemma_map(lang)

        q = self._content_words(query, func_words, lemmas)
        t = self._content_words(text, func_words, lemmas)
        return _similarity(q, t)

    def _content_words(self, text: str, func_words: frozenset[str], lemmas: dict[str, str]) -> set[str]:
        words = set()
        for tok in self._splitter.parse_text(text):
            if tok["type"] != "Word":
                continue
            w = tok["text"].lower()
            if len(w) <= 1 or w in func_words:
                continue
            words.add(lemmas.get(w, w))
        return words


def _similarity(query: set[str], block: set[str]) -> float:
    """Overlap coefficient against the query (rewards blocks that cover the query terms)."""
    if not query or not block:
        return 0.0
    shared = len(query & block)
    return shared / len(query)
