# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for `synthelion loop-check` / `synthelion loop-reset` (PreToolUse-hook-style CLI).

Home directory is redirected to tmp_path so these never touch the real
~/.synthelion/loop_guard.jsonl.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def _run(args: list[str]) -> int:
    from synthelion.cli import main
    with patch("sys.argv", ["synthelion"] + args):
        try:
            main()
        except SystemExit as exc:
            return exc.code or 0
    return 0


class TestLoopCheckCli:
    @pytest.fixture(autouse=True)
    def _isolated_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        return tmp_path

    def test_first_call_allows_exit_zero(self, capsys):
        code = _run(["loop-check", "--tool", "shell", "--args", '{"cmd":"pytest"}', "--json"])
        assert code == 0
        out = json.loads(capsys.readouterr().out)
        assert out["verdict"] == "Allow"

    def test_repeated_calls_block_with_exit_two(self, capsys):
        args = ["loop-check", "--tool", "shell", "--args", '{"cmd":"pytest"}', "--max-repeats", "2", "--json"]
        assert _run(args) == 0
        capsys.readouterr()
        assert _run(args) == 0
        capsys.readouterr()
        code = _run(args)
        out = json.loads(capsys.readouterr().out)
        assert code == 2
        assert out["verdict"] == "Block"
        assert out["reason"]

    def test_invalid_json_args_exits_one(self):
        code = _run(["loop-check", "--tool", "shell", "--args", "not json"])
        assert code == 1

    def test_no_args_flag_defaults_to_empty_object(self, capsys):
        code = _run(["loop-check", "--tool", "shell", "--json"])
        assert code == 0
        out = json.loads(capsys.readouterr().out)
        assert out["verdict"] == "Allow"

    def test_loop_reset_clears_streak(self, capsys):
        args = ["loop-check", "--tool", "shell", "--args", '{"cmd":"x"}', "--max-repeats", "1", "--json"]
        assert _run(args) == 0
        capsys.readouterr()
        assert _run(args) == 2
        capsys.readouterr()
        assert _run(["loop-reset"]) == 0
        capsys.readouterr()
        assert _run(args) == 0

    def test_sessions_are_isolated(self, capsys):
        base = ["loop-check", "--tool", "shell", "--args", '{"cmd":"x"}', "--max-repeats", "1", "--json"]
        assert _run(base + ["--session", "s1"]) == 0
        capsys.readouterr()
        assert _run(base + ["--session", "s2"]) == 0
