# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for the agent tool-call loop guardrail."""
from __future__ import annotations

import threading

import pytest

from synthelion.loop_guard import LoopGuard, LoopVerdict, PersistentLoopGuard


class TestLoopGuard:
    def test_first_call_is_allowed(self):
        guard = LoopGuard()
        r = guard.check("run_tests", {"path": "a.py"})
        assert r.verdict == LoopVerdict.ALLOW
        assert r.should_block is False
        assert r.repeat_count == 1

    def test_blocks_after_max_repeats(self):
        guard = LoopGuard(max_repeats=2)
        args = {"cmd": "pytest"}
        assert guard.check("shell", args).verdict == LoopVerdict.ALLOW
        assert guard.check("shell", args).verdict == LoopVerdict.ALLOW
        third = guard.check("shell", args)
        assert third.verdict == LoopVerdict.BLOCK
        assert third.should_block is True
        assert "shell" in third.reason

    def test_different_arguments_do_not_count_as_repeats(self):
        guard = LoopGuard(max_repeats=2)
        assert guard.check("shell", {"cmd": "a"}).verdict == LoopVerdict.ALLOW
        assert guard.check("shell", {"cmd": "b"}).verdict == LoopVerdict.ALLOW
        assert guard.check("shell", {"cmd": "c"}).verdict == LoopVerdict.ALLOW

    def test_different_tool_names_do_not_count_as_repeats(self):
        guard = LoopGuard(max_repeats=1)
        assert guard.check("tool_a", {"x": 1}).verdict == LoopVerdict.ALLOW
        assert guard.check("tool_b", {"x": 1}).verdict == LoopVerdict.ALLOW

    def test_different_sessions_are_isolated(self):
        guard = LoopGuard(max_repeats=1)
        args = {"cmd": "pytest"}
        assert guard.check("shell", args, session_id="s1").verdict == LoopVerdict.ALLOW
        assert guard.check("shell", args, session_id="s2").verdict == LoopVerdict.ALLOW

    def test_interleaving_a_different_call_breaks_the_streak(self):
        guard = LoopGuard(max_repeats=1)
        args = {"cmd": "pytest"}
        assert guard.check("shell", args).verdict == LoopVerdict.ALLOW
        assert guard.check("shell", {"cmd": "other"}).verdict == LoopVerdict.ALLOW
        # streak of identical "pytest" calls is broken, so it's allowed again
        assert guard.check("shell", args).verdict == LoopVerdict.ALLOW

    def test_reset_clears_history_for_session(self):
        guard = LoopGuard(max_repeats=1)
        args = {"cmd": "pytest"}
        assert guard.check("shell", args).verdict == LoopVerdict.ALLOW
        assert guard.check("shell", args).verdict == LoopVerdict.BLOCK
        guard.reset()
        assert guard.check("shell", args).verdict == LoopVerdict.ALLOW

    def test_per_call_max_repeats_override(self):
        guard = LoopGuard(max_repeats=5)
        args = {"cmd": "pytest"}
        assert guard.check("shell", args).verdict == LoopVerdict.ALLOW
        assert guard.check("shell", args, max_repeats=1).verdict == LoopVerdict.BLOCK

    def test_empty_tool_name_is_allowed(self):
        guard = LoopGuard()
        assert guard.check("").verdict == LoopVerdict.ALLOW

    def test_rejects_invalid_max_repeats(self):
        with pytest.raises(ValueError):
            LoopGuard(max_repeats=0)

    def test_thread_safe_under_concurrent_calls(self):
        guard = LoopGuard(max_repeats=1000)
        errors = []

        def hammer(i):
            try:
                for _ in range(50):
                    guard.check("shell", {"cmd": str(i)})
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=hammer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


class TestPersistentLoopGuard:
    def test_blocks_after_max_repeats_across_fresh_instances(self, tmp_path):
        path = tmp_path / "loop_guard.jsonl"
        args = {"cmd": "pytest"}
        # Each check() uses a brand-new instance, simulating a fresh CLI process per call.
        assert PersistentLoopGuard(path=path, max_repeats=2).check("shell", args).verdict == LoopVerdict.ALLOW
        assert PersistentLoopGuard(path=path, max_repeats=2).check("shell", args).verdict == LoopVerdict.ALLOW
        third = PersistentLoopGuard(path=path, max_repeats=2).check("shell", args)
        assert third.verdict == LoopVerdict.BLOCK
        assert third.should_block is True

    def test_different_sessions_are_isolated(self, tmp_path):
        path = tmp_path / "loop_guard.jsonl"
        args = {"cmd": "pytest"}
        assert PersistentLoopGuard(path=path, max_repeats=1).check("shell", args, session_id="s1").verdict == LoopVerdict.ALLOW
        assert PersistentLoopGuard(path=path, max_repeats=1).check("shell", args, session_id="s2").verdict == LoopVerdict.ALLOW

    def test_reset_appends_sentinel_and_clears_streak(self, tmp_path):
        path = tmp_path / "loop_guard.jsonl"
        args = {"cmd": "pytest"}
        assert PersistentLoopGuard(path=path, max_repeats=1).check("shell", args).verdict == LoopVerdict.ALLOW
        assert PersistentLoopGuard(path=path, max_repeats=1).check("shell", args).verdict == LoopVerdict.BLOCK
        PersistentLoopGuard(path=path).reset()
        assert PersistentLoopGuard(path=path, max_repeats=1).check("shell", args).verdict == LoopVerdict.ALLOW

    def test_history_file_is_created_and_appended(self, tmp_path):
        path = tmp_path / "nested" / "loop_guard.jsonl"
        assert not path.exists()
        PersistentLoopGuard(path=path).check("shell", {"cmd": "a"})
        assert path.exists()
        assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 1
        PersistentLoopGuard(path=path).check("shell", {"cmd": "b"})
        assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2

    def test_rejects_invalid_max_repeats(self, tmp_path):
        with pytest.raises(ValueError):
            PersistentLoopGuard(path=tmp_path / "x.jsonl", max_repeats=0)
