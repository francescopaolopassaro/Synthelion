# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for command_rewrite.py (advisory low-verbosity command suggestions)."""
from __future__ import annotations

from synthelion.command_rewrite import rewrite_command


class TestRewriteCommand:
    def test_git_log_gets_no_pager_after_git(self):
        cmd, rewritten = rewrite_command("git log -5")
        assert rewritten is True
        assert cmd == "git --no-pager log -5"

    def test_git_show_bare(self):
        cmd, rewritten = rewrite_command("git show")
        assert rewritten is True
        assert cmd == "git --no-pager show"

    def test_git_diff(self):
        cmd, rewritten = rewrite_command("git diff HEAD~1")
        assert rewritten is True
        assert cmd == "git --no-pager diff HEAD~1"

    def test_npm_install_gets_flags_appended(self):
        cmd, rewritten = rewrite_command("npm install lodash")
        assert rewritten is True
        assert cmd == "npm install --no-fund --no-audit lodash"

    def test_npm_ci(self):
        cmd, rewritten = rewrite_command("npm ci")
        assert rewritten is True
        assert cmd == "npm ci --no-fund --no-audit"

    def test_pip_install(self):
        cmd, rewritten = rewrite_command("pip install requests")
        assert rewritten is True
        assert cmd == "pip install --quiet requests"

    def test_flag_already_present_not_duplicated(self):
        cmd, rewritten = rewrite_command("git log --no-pager -5")
        assert rewritten is False
        assert cmd == "git log --no-pager -5"

    def test_unknown_command_unchanged(self):
        cmd, rewritten = rewrite_command("python manage.py migrate")
        assert rewritten is False
        assert cmd == "python manage.py migrate"

    def test_empty_command(self):
        cmd, rewritten = rewrite_command("")
        assert rewritten is False
        assert cmd == ""

    def test_refuses_command_with_pipe(self):
        cmd, rewritten = rewrite_command("git log | grep foo")
        assert rewritten is False
        assert cmd == "git log | grep foo"

    def test_refuses_command_with_and_and(self):
        cmd, rewritten = rewrite_command("npm install && npm test")
        assert rewritten is False

    def test_refuses_command_with_semicolon(self):
        cmd, rewritten = rewrite_command("npm install; echo done")
        assert rewritten is False

    def test_refuses_command_with_backtick(self):
        cmd, rewritten = rewrite_command("git log `echo -5`")
        assert rewritten is False

    def test_refuses_command_with_subshell(self):
        cmd, rewritten = rewrite_command("git log $(echo -5)")
        assert rewritten is False

    def test_refuses_command_with_redirect(self):
        cmd, rewritten = rewrite_command("git log > out.txt")
        assert rewritten is False

    def test_prefix_must_match_word_boundary(self):
        # "git logger" should not match the "git log" rule
        cmd, rewritten = rewrite_command("git logger")
        assert rewritten is False
        assert cmd == "git logger"
