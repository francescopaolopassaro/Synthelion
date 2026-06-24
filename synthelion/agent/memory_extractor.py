# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re

from synthelion.nlp.text_rank import TextRankSummarizer
from synthelion.word_provider import FunctionWordProvider


class MemoryExtractor:
    """Distils salient sentences and key terms from a conversation.

    Ported from C# CavemanMemoryExtractor. Returns {summary, keywords}.
    No embeddings — pure lexical extraction.
    """

    def __init__(self, word_provider: FunctionWordProvider | None = None) -> None:
        self._provider = word_provider or FunctionWordProvider()
        self._summarizer = TextRankSummarizer(self._provider)

    def extract(self, text: str, max_sentences: int = 5) -> dict:
        if not text or not text.strip():
            return {"summary": "", "keywords": []}

        summary = self._summarizer.summarize(text, sentence_count=max_sentences)
        keywords = self._extract_keywords(text)
        return {"summary": summary, "keywords": keywords[:20]}

    def _extract_keywords(self, text: str) -> list[str]:
        # Extract capitalized words (likely proper nouns / entities) and frequent nouns
        from collections import Counter
        words = re.findall(r"\b[A-Z][a-z]{2,}\b", text)
        # Add most frequent content words
        all_words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
        common = [w for w, _ in Counter(all_words).most_common(30)]
        seen: set[str] = set()
        result: list[str] = []
        for w in words + common:
            low = w.lower()
            if low not in seen:
                seen.add(low)
                result.append(w)
        return result
