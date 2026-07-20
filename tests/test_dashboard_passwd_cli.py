# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for `synthelion dashboard-passwd`.

Home directory is redirected to tmp_path so these never touch the real
~/.synthelion/dashboard_auth.json.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from synthelion.plugins import dashboard_auth


def _run(args: list[str]) -> int:
    from synthelion.cli import main
    with patch("sys.argv", ["synthelion"] + args):
        try:
            main()
        except SystemExit as exc:
            return exc.code or 0
    return 0


class TestDashboardPasswdCli:
    @pytest.fixture(autouse=True)
    def _isolated_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        return tmp_path

    def test_change_password_via_flag(self, capsys):
        code = _run(["dashboard-passwd", "--password", "newpass123"])
        assert code == 0
        assert "updated" in capsys.readouterr().out.lower()
        assert dashboard_auth.verify("admin", "newpass123")
        assert not dashboard_auth.verify("admin", "admin")

    def test_change_username_and_password(self, capsys):
        code = _run(["dashboard-passwd", "--username", "bob", "--password", "newpass123"])
        assert code == 0
        assert dashboard_auth.verify("bob", "newpass123")
        assert dashboard_auth.current_username() == "bob"

    def test_keeps_current_username_if_not_given(self, capsys):
        _run(["dashboard-passwd", "--username", "carol", "--password", "first-pass"])
        _run(["dashboard-passwd", "--password", "second-pass"])
        assert dashboard_auth.current_username() == "carol"
        assert dashboard_auth.verify("carol", "second-pass")
