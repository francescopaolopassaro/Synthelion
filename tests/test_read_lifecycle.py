# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for read_lifecycle.py (file-read freshness tracking)."""
from __future__ import annotations

from synthelion.read_lifecycle import ReadLifecycleTracker


class TestReadLifecycleTracker:
    def test_first_read_is_fresh(self):
        t = ReadLifecycleTracker()
        r = t.record_read("a.py", turn=1)
        assert r == {"status": "fresh", "read_count": 1}

    def test_unknown_path_classifies_unknown(self):
        t = ReadLifecycleTracker()
        assert t.classify("never-read.py") == "unknown"

    def test_reread_without_write_classifies_superseded(self):
        t = ReadLifecycleTracker()
        t.record_read("a.py", turn=1)
        t.record_read("a.py", turn=2)
        assert t.classify("a.py") == "superseded"

    def test_write_after_read_classifies_stale(self):
        t = ReadLifecycleTracker()
        t.record_read("a.py", turn=1)
        t.record_write("a.py", turn=2)
        assert t.classify("a.py") == "stale"

    def test_read_after_write_is_fresh_again(self):
        t = ReadLifecycleTracker()
        t.record_read("a.py", turn=1)
        t.record_write("a.py", turn=2)
        t.record_read("a.py", turn=3)
        assert t.classify("a.py") == "fresh"

    def test_record_read_reports_stale_when_write_already_landed(self):
        t = ReadLifecycleTracker()
        t.record_write("a.py", turn=5)
        r = t.record_read("a.py", turn=5)
        assert r["status"] == "stale"

    def test_should_mature_false_before_quiescence(self):
        t = ReadLifecycleTracker(quiesce_turns=3)
        t.record_read("a.py", turn=1)
        t.record_write("a.py", turn=2)
        assert t.should_mature("a.py", current_turn=3) is False

    def test_should_mature_true_after_quiescence(self):
        t = ReadLifecycleTracker(quiesce_turns=3)
        t.record_read("a.py", turn=1)
        t.record_write("a.py", turn=2)
        assert t.should_mature("a.py", current_turn=5) is True

    def test_should_mature_false_for_fresh_read(self):
        t = ReadLifecycleTracker(quiesce_turns=3)
        t.record_read("a.py", turn=1)
        assert t.should_mature("a.py", current_turn=10) is False

    def test_should_mature_false_for_unknown_path(self):
        t = ReadLifecycleTracker()
        assert t.should_mature("never-read.py", current_turn=100) is False

    def test_maturation_marker_mentions_path_and_status(self):
        t = ReadLifecycleTracker(quiesce_turns=3)
        marker = t.maturation_marker("a.py", "stale")
        assert "a.py" in marker
        assert "stale" in marker

    def test_sessions_are_isolated(self):
        t = ReadLifecycleTracker()
        t.record_read("a.py", turn=1, session_id="s1")
        assert t.classify("a.py", session_id="s2") == "unknown"
        assert t.classify("a.py", session_id="s1") == "fresh"
