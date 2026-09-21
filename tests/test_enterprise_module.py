# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# (c) 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for the Enterprise module: users, provider keys, subscriptions,
activity logging, cost sync, and middleware."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _isolate_home(tmp_path, monkeypatch):
    """Redirect HOME so the enterprise module creates its DB in a temp dir.
    On Windows, Path.home() ignores HOME — it uses USERPROFILE, so we
    must monkeypatch Path.home directly."""
    from pathlib import Path
    from synthelion.enterprise.db import reset_db
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    reset_db()
    return home


def _init_db(home):
    """Force-initialise the enterprise DB tables in the isolated home."""
    from synthelion.enterprise.db import get_db
    db = get_db()
    return db


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class TestEnterpriseUsers:
    def test_add_user(self, tmp_path, monkeypatch):
        home = _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.users import add_user, list_users
        u = add_user(label="Alice", role="admin")
        assert u["label"] == "Alice"
        assert u["role"] == "admin"
        assert u["status"] == "active"
        assert u["virtual_token"].startswith("sxv_")
        users = list_users()
        assert len(users) == 1
        assert users[0]["user_id"] == u["user_id"]

    def test_add_multiple_users(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.users import add_user, list_users
        add_user(label="A", role="admin")
        add_user(label="B", role="user")
        add_user(label="C", role="user")
        users = list_users()
        assert len(users) == 3

    def test_add_user_role_filter(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.users import add_user, list_users
        add_user(label="A", role="admin")
        add_user(label="B", role="user")
        admins = list_users(role="admin")
        assert len(admins) == 1
        users = list_users(role="user")
        assert len(users) == 1

    def test_delete_user(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.users import add_user, delete_user, list_users
        u = add_user(label="Del", role="user")
        n = delete_user(u["user_id"])
        assert n == 1
        assert len(list_users()) == 0

    def test_rotate_token(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.users import add_user, rotate_token
        u = add_user(label="R", role="user")
        old = u["virtual_token"]
        new = rotate_token(u["user_id"])
        assert new != old
        assert new.startswith("sxv_")

    def test_assign_and_remove_provider(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.users import add_user, assign_provider, remove_provider
        from synthelion.enterprise.provider_keys import add_provider_key
        u = add_user(label="U", role="user")
        pk = add_provider_key(provider="openai", label="K", api_key="sk-test")
        assign_provider(u["user_id"], pk["pk_id"])
        # assigning again is idempotent
        assign_provider(u["user_id"], pk["pk_id"])
        n = remove_provider(u["user_id"], pk["pk_id"])
        assert n >= 1

    def test_get_user(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.users import add_user, get_user
        u = add_user(label="G", role="user")
        fetched = get_user(u["user_id"])
        assert fetched is not None
        assert fetched["label"] == "G"

    def test_get_user_not_found(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.users import get_user
        assert get_user("nonexistent") is None


# ---------------------------------------------------------------------------
# Provider Keys
# ---------------------------------------------------------------------------

class TestEnterpriseProviderKeys:
    def test_add_provider_key(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.provider_keys import add_provider_key, list_provider_keys
        pk = add_provider_key(provider="anthropic", label="Prod", api_key="sk-ant-xxx")
        assert pk["provider"] == "anthropic"
        assert pk["label"] == "Prod"
        keys = list_provider_keys()
        assert len(keys) == 1

    def test_add_with_upstream(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.provider_keys import add_provider_key
        pk = add_provider_key(provider="openai", label="Custom", api_key="sk-xxx", upstream_url="https://custom.api.com")
        assert pk["upstream_url"] == "https://custom.api.com"

    def test_delete_provider_key(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.provider_keys import add_provider_key, delete_provider_key, list_provider_keys
        pk = add_provider_key(provider="groq", label="Del", api_key="gsk-xxx")
        n = delete_provider_key(pk["pk_id"])
        assert n == 1
        assert len(list_provider_keys()) == 0

    def test_provider_filter(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.provider_keys import add_provider_key, list_provider_keys
        add_provider_key(provider="openai", label="A", api_key="sk-a")
        add_provider_key(provider="anthropic", label="B", api_key="sk-b")
        openai_keys = list_provider_keys(provider="openai")
        assert len(openai_keys) == 1
        assert openai_keys[0]["provider"] == "openai"

    def test_key_encryption_roundtrip(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.provider_keys import add_provider_key, get_provider_key, get_real_key
        secret = "sk-super-secret-key-12345"
        pk = add_provider_key(provider="openai", label="Enc", api_key=secret)
        stored = get_provider_key(pk["pk_id"])
        # stored api_key_enc should be encrypted, not plaintext
        assert "api_key_enc" in stored
        assert stored["api_key_enc"] != secret
        assert len(stored["api_key_enc"]) > 0
        # get_real_key should decrypt back to the original
        decrypted = get_real_key(pk["pk_id"])
        assert decrypted == secret


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------

class TestEnterpriseSubscriptions:
    def _setup_user_and_key(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.users import add_user
        from synthelion.enterprise.provider_keys import add_provider_key
        u = add_user(label="SubUser", role="user")
        pk = add_provider_key(provider="openai", label="SubKey", api_key="sk-test")
        return u, pk

    def test_add_consumo_subscription(self, tmp_path, monkeypatch):
        u, pk = self._setup_user_and_key(tmp_path, monkeypatch)
        from synthelion.enterprise.subscriptions import add_subscription, list_subscriptions
        s = add_subscription(user_id=u["user_id"], provider_key_id=pk["pk_id"],
                            sub_type="consumo", max_tokens=100000)
        assert s["type"] == "consumo"
        assert s["max_tokens"] == 100000
        assert s["status"] == "active"
        subs = list_subscriptions()
        assert len(subs) == 1

    def test_add_mensile_subscription(self, tmp_path, monkeypatch):
        u, pk = self._setup_user_and_key(tmp_path, monkeypatch)
        from synthelion.enterprise.subscriptions import add_subscription
        s = add_subscription(user_id=u["user_id"], provider_key_id=pk["pk_id"],
                            sub_type="mensile", max_monthly_cost_usd=50.0)
        assert s["type"] == "mensile"
        assert s["max_monthly_cost_usd"] == 50.0

    def test_suspend_and_reactivate(self, tmp_path, monkeypatch):
        u, pk = self._setup_user_and_key(tmp_path, monkeypatch)
        from synthelion.enterprise.subscriptions import add_subscription, suspend_subscription, reactivate_subscription
        s = add_subscription(user_id=u["user_id"], provider_key_id=pk["pk_id"], sub_type="consumo")
        suspended = suspend_subscription(s["sub_id"])
        assert suspended["status"] == "suspended"
        reactivated = reactivate_subscription(s["sub_id"])
        assert reactivated["status"] == "active"

    def test_quota_check_active(self, tmp_path, monkeypatch):
        u, pk = self._setup_user_and_key(tmp_path, monkeypatch)
        from synthelion.enterprise.subscriptions import add_subscription, get_subscription, quota_check
        s = add_subscription(user_id=u["user_id"], provider_key_id=pk["pk_id"],
                            sub_type="consumo", max_tokens=1000)
        sub = get_subscription(s["sub_id"])
        assert quota_check(sub) is True

    def test_quota_check_no_subscription(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.subscriptions import quota_check
        # quota_check requires a sub dict — with no active sub, the middleware
        # would not even reach this point, so test the False path directly
        fake_sub = {"status": "suspended", "type": "consumo", "current_tokens_used": 0, "max_tokens": 1000,
                     "current_month_cost_usd": 0.0, "max_monthly_cost_usd": 0.0, "period_start": "2026-01-01T00:00:00+00:00"}
        assert quota_check(fake_sub) is False


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------

class TestEnterpriseActivity:
    def test_record_and_query(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.activity import log_request, query_activity
        log_request(user_id="test-user", provider="openai", model="gpt-4",
                    path="/v1/chat", status_code=200,
                    tokens_before=100, tokens_after=50, tokens_used=70,
                    cost_usd=0.001, duration_ms=123.4)
        rows = query_activity(limit=10)
        assert len(rows) == 1
        assert rows[0]["provider"] == "openai"
        assert rows[0]["model"] == "gpt-4"
        assert rows[0]["status_code"] == 200

    def test_activity_user_filter(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.activity import log_request, query_activity
        log_request(user_id="alice", provider="openai", model="gpt-4",
                    path="/v1", status_code=200, tokens_before=100, tokens_after=80,
                    tokens_used=100, cost_usd=0.0, duration_ms=10)
        log_request(user_id="bob", provider="anthropic", model="claude-3",
                    path="/v1", status_code=200, tokens_before=200, tokens_after=160,
                    tokens_used=200, cost_usd=0.0, duration_ms=10)
        alice_rows = query_activity(user_id="alice")
        assert len(alice_rows) == 1
        assert alice_rows[0]["user_id"] == "alice"

    def test_activity_aggregate_all(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.activity import log_request, aggregate_all
        log_request(user_id="u1", provider="openai", model="gpt-4",
                    path="/v1", status_code=200, tokens_before=100, tokens_after=80,
                    tokens_used=100, cost_usd=0.0, duration_ms=50)
        log_request(user_id="u2", provider="openai", model="gpt-4",
                    path="/v1", status_code=200, tokens_before=200, tokens_after=160,
                    tokens_used=200, cost_usd=0.0, duration_ms=80)
        agg = aggregate_all()
        assert agg["total_requests"] == 2

    def test_activity_aggregate_user(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.activity import log_request, aggregate_user
        log_request(user_id="alice", provider="openai", model="gpt-4",
                    path="/v1", status_code=200, tokens_before=100, tokens_after=80,
                    tokens_used=100, cost_usd=0.0, duration_ms=50)
        log_request(user_id="bob", provider="openai", model="gpt-4",
                    path="/v1", status_code=200, tokens_before=200, tokens_after=160,
                    tokens_used=200, cost_usd=0.0, duration_ms=80)
        agg = aggregate_user("alice")
        assert agg["total_requests"] == 1


# ---------------------------------------------------------------------------
# Cost Sync
# ---------------------------------------------------------------------------

class TestEnterpriseCostSync:
    def test_get_cost_returns_none_or_default(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.cost_sync import get_cost
        cost = get_cost("openai", "gpt-4")
        # May be None (no costs synced yet) or a dict with pricing
        if cost is not None:
            assert "input_per_mtok" in cost
            assert "output_per_mtok" in cost


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class TestEnterpriseMiddleware:
    def test_check_enterprise_auth_no_token(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.middleware import check_enterprise_auth
        result = check_enterprise_auth(None, "openai")
        assert result.allowed is False
        assert result.error_code == "missing_token"

    def test_check_enterprise_auth_invalid_token(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.middleware import check_enterprise_auth
        result = check_enterprise_auth("sxv_nonexistent", "openai")
        assert result.allowed is False
        assert result.error_code == "invalid_token"

    def test_check_enterprise_auth_empty_string(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.middleware import check_enterprise_auth
        result = check_enterprise_auth("", "openai")
        assert result.allowed is False
        assert result.error_code == "missing_token"

    def _setup_active_sub(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.users import add_user
        from synthelion.enterprise.provider_keys import add_provider_key
        from synthelion.enterprise.subscriptions import add_subscription
        from synthelion.enterprise.db import get_db
        user = add_user(label="alice")
        pk = add_provider_key(provider="openai", label="k", api_key="sk-x")
        # Seed a known price so estimate_cost() is deterministic in the test
        get_db().insert("enterprise_model_costs", {
            "provider": "openai", "model": "gpt-4o",
            "input_per_token": 0.001, "output_per_token": 0.002,
            "last_synced_at": "2026-01-01T00:00:00Z",
        })
        add_subscription(user_id=user["user_id"], provider_key_id=pk["pk_id"],
                          sub_type="consumo", max_tokens=100000)
        return user

    def test_record_proxy_usage_prefers_real_usage_over_estimate(self, tmp_path, monkeypatch):
        user = self._setup_active_sub(tmp_path, monkeypatch)
        from synthelion.enterprise.middleware import record_proxy_usage
        from synthelion.enterprise.subscriptions import find_active_sub
        # tokens_before/after describe Synthelion's own request compression
        # (100 -> 60 tokens); real_input/output_tokens is what the provider
        # actually billed. The real numbers must win, not the compression
        # savings — a provider bills for what was sent + what it generated,
        # not for what compression happened to save on the input side.
        record_proxy_usage(
            user=user, provider="openai", model="gpt-4o", path="/v1/chat/completions",
            status_code=200, tokens_before=100, tokens_after=60,
            duration_ms=5.0, compressed=True,
            real_input_tokens=60, real_output_tokens=40,
        )
        sub = find_active_sub(user["user_id"], "openai", "gpt-4o")
        assert sub["current_tokens_used"] == 100  # 60 input + 40 output, not 100 + savings

    def test_record_proxy_usage_falls_back_when_no_real_usage(self, tmp_path, monkeypatch):
        user = self._setup_active_sub(tmp_path, monkeypatch)
        from synthelion.enterprise.middleware import record_proxy_usage
        from synthelion.enterprise.subscriptions import find_active_sub
        record_proxy_usage(
            user=user, provider="openai", model="gpt-4o", path="/v1/chat/completions",
            status_code=200, tokens_before=100, tokens_after=60,
            duration_ms=5.0, compressed=True,
        )
        sub = find_active_sub(user["user_id"], "openai", "gpt-4o")
        # No real usage available (e.g. a streaming response) -> fall back to
        # tokens actually sent upstream, not the old before+savings formula
        # (which would have recorded 140).
        assert sub["current_tokens_used"] == 60


class TestExtractUsage:
    def test_openai_style_usage(self):
        from synthelion.plugins.proxy import _extract_usage
        import json
        body = json.dumps({"usage": {"prompt_tokens": 12, "completion_tokens": 34}}).encode()
        assert _extract_usage(body) == (12, 34)

    def test_anthropic_style_usage(self):
        from synthelion.plugins.proxy import _extract_usage
        import json
        body = json.dumps({"usage": {"input_tokens": 5, "output_tokens": 9}}).encode()
        assert _extract_usage(body) == (5, 9)

    def test_missing_usage_returns_none(self):
        from synthelion.plugins.proxy import _extract_usage
        import json
        body = json.dumps({"choices": []}).encode()
        assert _extract_usage(body) is None

    def test_malformed_json_returns_none(self):
        from synthelion.plugins.proxy import _extract_usage
        assert _extract_usage(b"not json{{{") is None


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

class TestEnterpriseBootstrap:
    def test_ensure_enterprise_creates_admin_and_test(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise import ensure_enterprise
        ensure_enterprise()
        from synthelion.enterprise.users import list_users
        users = list_users()
        labels = {u["label"] for u in users}
        roles = {u["role"] for u in users}
        assert "admin" in roles
        assert "user" in roles
        # The test user has label "user" and role "user"
        assert "admin" in labels
        assert "user" in labels

    def test_ensure_enterprise_idempotent(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise import ensure_enterprise
        from synthelion.enterprise.users import list_users
        ensure_enterprise()
        count1 = len(list_users())
        ensure_enterprise()
        count2 = len(list_users())
        assert count1 == count2


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

class TestEnterpriseDB:
    def test_get_db_singleton(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.db import get_db
        db1 = get_db()
        db2 = get_db()
        assert db1 is db2

    def test_tables_created(self, tmp_path, monkeypatch):
        _isolate_home(tmp_path, monkeypatch)
        from synthelion.enterprise.db import get_db
        db = get_db()
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = {r["name"] for r in tables}
        assert "enterprise_users" in table_names
        assert "enterprise_provider_keys" in table_names
        assert "enterprise_subscriptions" in table_names
        assert "enterprise_activity" in table_names
        assert "enterprise_model_costs" in table_names
        assert "enterprise_user_providers" in table_names


# ---------------------------------------------------------------------------
# Crypto — the master key lives in the OS credential store, never a file
# ---------------------------------------------------------------------------

class _FakeKeyring:
    """In-memory stand-in for the `keyring` module, so these tests don't
    read/write the real machine's OS credential store on every run."""
    def __init__(self):
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self._store.get((service, username))

    def set_password(self, service, username, value):
        self._store[(service, username)] = value


class TestEnterpriseCrypto:
    def _patch_keyring(self, monkeypatch):
        import synthelion.enterprise.crypto as crypto
        fake = _FakeKeyring()
        monkeypatch.setattr(crypto, "_keyring", lambda: fake)
        return crypto, fake

    def test_ensure_key_generates_once(self, monkeypatch):
        crypto, fake = self._patch_keyring(monkeypatch)
        crypto.ensure_key()
        first = fake.get_password(crypto._SERVICE_NAME, crypto._KEY_USERNAME)
        assert first is not None and len(first) == 64
        crypto.ensure_key()  # idempotent — must not regenerate/rotate
        second = fake.get_password(crypto._SERVICE_NAME, crypto._KEY_USERNAME)
        assert second == first

    def test_show_key_creates_if_missing_and_returns_hex(self, monkeypatch):
        crypto, fake = self._patch_keyring(monkeypatch)
        key = crypto.show_key()
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key.lower())

    def test_encrypt_decrypt_roundtrip_with_fake_keyring(self, monkeypatch):
        crypto, fake = self._patch_keyring(monkeypatch)
        crypto.ensure_key()
        ct = crypto.encrypt("sk-real-secret")
        assert ct != "sk-real-secret"
        assert crypto.decrypt(ct) == "sk-real-secret"

    def test_get_key_raises_clear_error_when_unconfigured(self, monkeypatch):
        crypto, fake = self._patch_keyring(monkeypatch)
        with pytest.raises(crypto.EnterpriseKeyUnavailable):
            crypto._get_key()

    def test_migrate_from_file_imports_and_does_not_delete(self, tmp_path, monkeypatch):
        crypto, fake = self._patch_keyring(monkeypatch)
        key_file = tmp_path / "old_key.hex"
        key_file.write_text("ab" * 32, encoding="utf-8")
        moved = crypto.migrate_from_file(key_file)
        assert moved is True
        assert fake.get_password(crypto._SERVICE_NAME, crypto._KEY_USERNAME) == "ab" * 32
        assert key_file.exists()  # migration never auto-deletes the source file

    def test_migrate_from_file_noop_if_key_already_present(self, tmp_path, monkeypatch):
        crypto, fake = self._patch_keyring(monkeypatch)
        crypto.ensure_key()
        existing = fake.get_password(crypto._SERVICE_NAME, crypto._KEY_USERNAME)
        key_file = tmp_path / "old_key.hex"
        key_file.write_text("cd" * 32, encoding="utf-8")
        moved = crypto.migrate_from_file(key_file)
        assert moved is False
        assert fake.get_password(crypto._SERVICE_NAME, crypto._KEY_USERNAME) == existing

    def test_migrate_from_file_rejects_malformed_key(self, tmp_path, monkeypatch):
        crypto, fake = self._patch_keyring(monkeypatch)
        key_file = tmp_path / "bad_key.hex"
        key_file.write_text("not-a-hex-key", encoding="utf-8")
        with pytest.raises(ValueError):
            crypto.migrate_from_file(key_file)
