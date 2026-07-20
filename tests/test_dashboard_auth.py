# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for the dashboard's HTTP Basic Auth credential store."""
from __future__ import annotations

import json

import pytest

from synthelion.plugins import dashboard_auth


class TestDashboardAuth:
    def test_ensure_default_credentials_creates_admin_admin(self, tmp_path):
        path = tmp_path / "auth.json"
        assert not path.exists()
        dashboard_auth.ensure_default_credentials(path)
        assert path.exists()
        assert dashboard_auth.verify("admin", "admin", path)

    def test_credentials_are_not_stored_in_plaintext(self, tmp_path):
        path = tmp_path / "auth.json"
        dashboard_auth.ensure_default_credentials(path)
        raw = path.read_text(encoding="utf-8")
        assert "admin" not in json.loads(raw)["hash"]
        data = json.loads(raw)
        assert "hash" in data and "salt" in data
        assert data["hash"] != "admin"

    def test_ensure_default_credentials_is_noop_if_file_exists(self, tmp_path):
        path = tmp_path / "auth.json"
        dashboard_auth.set_credentials("alice", "s3cret", path)
        dashboard_auth.ensure_default_credentials(path)
        assert dashboard_auth.current_username(path) == "alice"
        assert not dashboard_auth.verify("admin", "admin", path)

    def test_verify_rejects_wrong_password(self, tmp_path):
        path = tmp_path / "auth.json"
        dashboard_auth.ensure_default_credentials(path)
        assert not dashboard_auth.verify("admin", "wrong", path)

    def test_verify_rejects_wrong_username(self, tmp_path):
        path = tmp_path / "auth.json"
        dashboard_auth.ensure_default_credentials(path)
        assert not dashboard_auth.verify("nobody", "admin", path)

    def test_set_credentials_changes_login(self, tmp_path):
        path = tmp_path / "auth.json"
        dashboard_auth.ensure_default_credentials(path)
        dashboard_auth.set_credentials("bob", "hunter2", path)
        assert dashboard_auth.verify("bob", "hunter2", path)
        assert not dashboard_auth.verify("admin", "admin", path)
        assert dashboard_auth.current_username(path) == "bob"

    def test_set_credentials_rejects_empty_username_or_password(self, tmp_path):
        path = tmp_path / "auth.json"
        with pytest.raises(ValueError):
            dashboard_auth.set_credentials("", "x", path)
        with pytest.raises(ValueError):
            dashboard_auth.set_credentials("bob", "", path)

    def test_is_using_default_password(self, tmp_path):
        path = tmp_path / "auth.json"
        dashboard_auth.ensure_default_credentials(path)
        assert dashboard_auth.is_using_default_password(path)
        dashboard_auth.set_credentials("admin", "somethingelse", path)
        assert not dashboard_auth.is_using_default_password(path)

    def test_current_username_defaults_when_no_file(self, tmp_path):
        path = tmp_path / "missing.json"
        assert dashboard_auth.current_username(path) == "admin"

    def test_verify_lazily_creates_defaults_when_missing(self, tmp_path):
        path = tmp_path / "auth.json"
        assert not path.exists()
        assert dashboard_auth.verify("admin", "admin", path)
        assert path.exists()

    def test_credentials_fingerprint_changes_on_password_change(self, tmp_path):
        path = tmp_path / "auth.json"
        dashboard_auth.ensure_default_credentials(path)
        before = dashboard_auth.credentials_fingerprint(path)
        dashboard_auth.set_credentials("admin", "rotated-password", path)
        after = dashboard_auth.credentials_fingerprint(path)
        assert before != after

    def test_credentials_fingerprint_lazily_creates_defaults(self, tmp_path):
        path = tmp_path / "missing.json"
        assert not path.exists()
        fp = dashboard_auth.credentials_fingerprint(path)
        assert fp
        assert path.exists()

    def test_different_passwords_produce_different_hashes(self, tmp_path):
        p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
        dashboard_auth.set_credentials("admin", "password1", p1)
        dashboard_auth.set_credentials("admin", "password2", p2)
        h1 = json.loads(p1.read_text(encoding="utf-8"))["hash"]
        h2 = json.loads(p2.read_text(encoding="utf-8"))["hash"]
        assert h1 != h2
