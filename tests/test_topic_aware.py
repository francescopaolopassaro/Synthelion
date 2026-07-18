# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for TopicSegmenter (TextTiling) and TfIdfSummarizer.summarize_topic_aware,
ported from Caveman C# 1.4.1."""
from __future__ import annotations

from synthelion.nlp.summarizer import TfIdfSummarizer
from synthelion.nlp.topic_segmenter import TopicSegmenter
from synthelion.word_provider import FunctionWordProvider

TWO_TOPIC_DOC = (
    "The stock market rallied sharply today as technology shares surged across every major index. "
    "Investors were optimistic about strong earnings reports from major software companies this quarter. "
    "Analysts raised their price targets for several leading technology firms after the announcement. "
    "Trading volume was significantly higher than the monthly average throughout the session. "
    "The central bank hinted at possible interest rate cuts later this year. "
    "Currency markets reacted immediately with the dollar weakening against major peers. "
    "Corporate bond yields also fell as investors priced in looser monetary policy. "
    "Several major banks upgraded their outlook for the technology sector. "
    "Meanwhile, a powerful storm system is moving steadily across the central plains this week. "
    "Meteorologists warn of heavy rainfall and potential flash flooding in several low-lying counties. "
    "Residents in affected areas have been urged to prepare emergency supplies and evacuation routes. "
    "The storm is expected to weaken gradually as it moves further east by Thursday evening. "
    "Local officials have opened emergency shelters in three counties ahead of the worst conditions. "
    "Power companies are pre-positioning repair crews anticipating widespread outages from high winds. "
    "Schools in the affected region have already announced closures for tomorrow. "
    "The national weather service upgraded the storm warning to its highest level overnight."
)

SINGLE_TOPIC_DOC = (
    "The cat sat quietly on the warm windowsill in the afternoon sun. "
    "It watched birds hopping across the garden fence with great interest. "
    "Later the cat stretched, yawned, and curled up for a long nap. "
    "When it woke, the same cat wandered back to the same windowsill again."
)


class TestTopicSegmenter:
    def setup_method(self):
        self.segmenter = TopicSegmenter(FunctionWordProvider())

    def test_degenerate_input_never_throws_at_most_one_segment(self):
        for text in ["", "   ", "This is one sentence.", "First sentence here. Second sentence here."]:
            segments = self.segmenter.segment(text, "eng")
            assert len(segments) <= 1

    def test_multi_topic_document_finds_more_than_one_segment(self):
        segments = self.segmenter.segment(TWO_TOPIC_DOC, "eng")
        assert len(segments) > 1
        assert segments[0].start_sentence == 0
        for prev, cur in zip(segments, segments[1:]):
            assert cur.start_sentence == prev.end_sentence

    def test_single_topic_document_stays_as_one_or_few_segments(self):
        segments = self.segmenter.segment(SINGLE_TOPIC_DOC, "eng")
        assert len(segments) <= 2


class TestSummarizeTopicAware:
    def setup_method(self):
        self.summarizer = TfIdfSummarizer(FunctionWordProvider())

    def test_single_topic_document_falls_back_to_plain_summarize(self):
        plain = self.summarizer.summarize(SINGLE_TOPIC_DOC, sentence_count=2, iso3="eng")
        topic_aware = self.summarizer.summarize_topic_aware(SINGLE_TOPIC_DOC, sentence_count=2, iso3="eng")
        assert topic_aware == plain

    def test_empty_input_returns_empty(self):
        assert self.summarizer.summarize_topic_aware("", 3, iso3="eng") == ""

    def test_multi_topic_document_never_throws_and_respects_budget(self):
        result = self.summarizer.summarize_topic_aware(TWO_TOPIC_DOC, sentence_count=4, iso3="eng")
        assert result  # non-empty
        # Roughly respects the requested budget (topic-aware rounding can be +/-1 sentence).
        assert len(result.split(". ")) <= 6
