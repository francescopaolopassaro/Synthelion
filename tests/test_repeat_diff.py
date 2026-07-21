# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for repeat_diff.py (diff-on-repeat for identical tool calls)."""
from __future__ import annotations

import time

from synthelion.repeat_diff import RepeatOutputDiffer


class TestRepeatOutputDiffer:
    def test_first_call_returns_output_unchanged(self):
        differ = RepeatOutputDiffer()
        output, was_diffed = differ.diff_if_repeated("npm test", {"cwd": "."}, "line1\nline2\nline3")
        assert output == "line1\nline2\nline3"
        assert was_diffed is False

    def test_repeated_call_same_args_returns_shorter_diff(self):
        differ = RepeatOutputDiffer()
        long_output = "\n".join(f"unchanged line {i}" for i in range(50))
        differ.diff_if_repeated("pytest", {"path": "tests/"}, long_output)
        changed_output = long_output + "\nONE NEW LINE AT THE END"
        output, was_diffed = differ.diff_if_repeated("pytest", {"path": "tests/"}, changed_output)
        assert was_diffed is True
        assert len(output) < len(changed_output)
        assert "ONE NEW LINE AT THE END" in output

    def test_different_arguments_no_diff(self):
        differ = RepeatOutputDiffer()
        differ.diff_if_repeated("pytest", {"path": "tests/a"}, "same output")
        output, was_diffed = differ.diff_if_repeated("pytest", {"path": "tests/b"}, "same output")
        assert was_diffed is False
        assert output == "same output"

    def test_different_tool_name_no_diff(self):
        differ = RepeatOutputDiffer()
        differ.diff_if_repeated("npm test", {}, "output")
        output, was_diffed = differ.diff_if_repeated("npm build", {}, "output")
        assert was_diffed is False

    def test_different_session_no_diff(self):
        differ = RepeatOutputDiffer()
        differ.diff_if_repeated("pytest", {}, "output", session_id="s1")
        output, was_diffed = differ.diff_if_repeated("pytest", {}, "output", session_id="s2")
        assert was_diffed is False

    def test_completely_different_output_falls_back_to_full(self):
        """When the diff would be longer than just returning the new output (e.g.
        totally unrelated short outputs), fall back to the full text — never worse."""
        differ = RepeatOutputDiffer()
        differ.diff_if_repeated("t", {}, "a")
        output, was_diffed = differ.diff_if_repeated("t", {}, "b")
        assert was_diffed is False
        assert output == "b"

    def test_ttl_expiry_treated_as_first_call(self):
        differ = RepeatOutputDiffer(ttl_seconds=0.01)
        differ.diff_if_repeated("t", {}, "output one")
        time.sleep(0.05)
        output, was_diffed = differ.diff_if_repeated("t", {}, "output one")
        assert was_diffed is False
        assert output == "output one"

    def test_reset_clears_session_history(self):
        differ = RepeatOutputDiffer()
        long_output = "\n".join(f"line {i}" for i in range(50))
        differ.diff_if_repeated("pytest", {}, long_output, session_id="s1")
        differ.reset(session_id="s1")
        output, was_diffed = differ.diff_if_repeated("pytest", {}, long_output + "\nmore", session_id="s1")
        assert was_diffed is False

    def test_identical_repeated_call_no_change_still_no_diff_needed(self):
        """Identical output twice in a row: unified_diff produces an empty diff
        (falsy), so the (safe) fallback to full output kicks in rather than
        returning an empty string."""
        differ = RepeatOutputDiffer()
        differ.diff_if_repeated("t", {}, "same output")
        output, was_diffed = differ.diff_if_repeated("t", {}, "same output")
        assert was_diffed is False
        assert output == "same output"
