# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""TextTiling-style topic segmentation.

Ported from Caveman C# 1.4.1's CavemanTopicSegmenter. Splits a document into
topically-coherent segments (Hearst, 1997): group sentences into fixed-size blocks,
score the vocabulary similarity between every pair of adjacent blocks, and cut at the
"valleys" where similarity drops sharply relative to the similarity peaks on both
sides. Pure term-frequency cosine similarity — no external dependency, no model.

Segmentation on its own doesn't compress anything; it exists so other components can
treat a long, multi-topic document as what it actually is instead of one
undifferentiated bag of sentences — e.g. a summarizer can allocate its sentence
budget per topic instead of letting one statistically dense topic dominate the whole
summary.
"""
from __future__ import annotations

from dataclasses import dataclass

import regex

from synthelion.nlp.sentence_detector import SentenceDetector
from synthelion.word_provider import FunctionWordProvider

_WORD_ONLY = regex.compile(r"[\p{L}\p{M}\p{N}_]+", regex.UNICODE)


@dataclass(frozen=True)
class TopicSegment:
    """A contiguous, topically-coherent run of sentences within a document."""
    start_sentence: int
    end_sentence: int
    text: str
    sentence_count: int


class TopicSegmenter:
    def __init__(
        self,
        word_provider: FunctionWordProvider | None = None,
        sentences_per_block: int = 3,
        depth_threshold_factor: float = 0.5,
    ) -> None:
        """sentences_per_block: sentences grouped into one comparison block (default 3);
        larger = coarser, more stable boundaries. depth_threshold_factor: boundary
        depth-score threshold as (mean - factor * stddev) of all depth scores (default
        0.5 = liberal, matching the original TextTiling paper)."""
        self._provider = word_provider
        self._detector = SentenceDetector()
        self.sentences_per_block = sentences_per_block
        self.depth_threshold_factor = depth_threshold_factor

    def segment(self, text: str, iso3: str = "eng") -> list[TopicSegment]:
        """Segments `text` into topic blocks. A document too short to form at least 3
        comparison blocks is returned as a single segment spanning the whole text."""
        if not text or not text.strip():
            return []

        sentences = self._detector.split_text(text, iso3)
        if not sentences:
            return []

        blocks = [
            sentences[i:i + self.sentences_per_block]
            for i in range(0, len(sentences), self.sentences_per_block)
        ]
        if len(blocks) < 3:
            return [self._whole_document(sentences)]

        fw = self._provider.get_function_words(iso3) if self._provider else None
        vectors = [self._term_vector(block, fw) for block in blocks]

        similarities = [
            self._cosine_similarity(vectors[i], vectors[i + 1])
            for i in range(len(vectors) - 1)
        ]
        depths = self._compute_depth_scores(similarities)
        if not depths:
            return [self._whole_document(sentences)]

        mean = sum(depths) / len(depths)
        variance = sum((d - mean) ** 2 for d in depths) / len(depths)
        stddev = variance ** 0.5
        threshold = mean - self.depth_threshold_factor * stddev

        boundaries: list[int] = []
        for i, depth in enumerate(depths):
            if depth <= threshold:
                continue
            sentence_idx = sum(len(b) for b in blocks[:i + 1])
            if 0 < sentence_idx < len(sentences):
                boundaries.append(sentence_idx)

        return self._build_segments(sentences, boundaries)

    @staticmethod
    def _term_vector(block: list[str], function_words) -> dict[str, int]:
        vector: dict[str, int] = {}
        for sentence in block:
            for w in _WORD_ONLY.findall(sentence.lower()):
                if function_words is not None and w in function_words:
                    continue
                vector[w] = vector.get(w, 0) + 1
        return vector

    @staticmethod
    def _cosine_similarity(a: dict[str, int], b: dict[str, int]) -> float:
        if not a or not b:
            return 0.0
        dot = sum(weight * b.get(term, 0) for term, weight in a.items())
        norm_a = sum(w * w for w in a.values()) ** 0.5
        norm_b = sum(w * w for w in b.values()) ** 0.5
        return 0.0 if norm_a == 0 or norm_b == 0 else dot / (norm_a * norm_b)

    @staticmethod
    def _compute_depth_scores(similarities: list[float]) -> list[float]:
        # Depth score at gap i: how far similarity dips below the nearest similarity
        # peak on each side. A deep, isolated valley is a strong topic-boundary
        # signal; a shallow dip (or a valley that's part of a long, gradual decline)
        # is not.
        depths = []
        n = len(similarities)
        for i in range(n):
            left_peak = similarities[i]
            j = i - 1
            while j >= 0 and similarities[j] >= left_peak:
                left_peak = similarities[j]
                j -= 1

            right_peak = similarities[i]
            j = i + 1
            while j < n and similarities[j] >= right_peak:
                right_peak = similarities[j]
                j += 1

            depths.append((left_peak - similarities[i]) + (right_peak - similarities[i]))
        return depths

    def _build_segments(self, sentences: list[str], boundaries: list[int]) -> list[TopicSegment]:
        segments = []
        start = 0
        for boundary in sorted(set(boundaries)):
            segments.append(self._make_segment(sentences, start, boundary))
            start = boundary
        segments.append(self._make_segment(sentences, start, len(sentences)))
        return segments

    @staticmethod
    def _make_segment(sentences: list[str], start: int, end: int) -> TopicSegment:
        return TopicSegment(
            start_sentence=start,
            end_sentence=end,
            text=" ".join(s.strip() for s in sentences[start:end]),
            sentence_count=end - start,
        )

    def _whole_document(self, sentences: list[str]) -> TopicSegment:
        return self._make_segment(sentences, 0, len(sentences))
