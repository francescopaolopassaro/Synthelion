# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for synthelion.config and synthelion.analytics.session_store.

Redis/Postgres backends are tested with mocks (their command/query shape), not
against a live server — none is available in this test environment. Full
integration coverage against real Redis/Postgres instances is a natural next
step once one is provisioned in CI.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from synthelion.analytics.session_store import (
    LocalFileSessionStore, PostgresSessionStore, RedisSessionStore,
    SessionCall, create_session_store,
)
from synthelion.config import (
    default_compression_level, default_config, default_wiki_depth, load_config, merge_config,
    new_cluster_token, new_node_id, privacy_config, save_config, waf_config,
)


class TestConfig:
    def test_default_config_has_expected_shape(self):
        cfg = default_config()
        assert cfg["session_store"]["backend"] == "local"
        assert cfg["vector_store"]["backend"] == "chromadb"
        assert cfg["dashboard"]["realtime"] == "websocket"

    def test_save_and_load_roundtrip(self, tmp_path: Path):
        cfg = default_config()
        cfg["session_store"]["backend"] = "redis"
        cfg["session_store"]["redis"]["url"] = "redis://example:6379/1"
        path = save_config(cfg, tmp_path / "config.json")

        loaded = load_config(path)
        assert loaded["session_store"]["backend"] == "redis"
        assert loaded["session_store"]["redis"]["url"] == "redis://example:6379/1"

    def test_partial_config_merges_over_defaults(self, tmp_path: Path):
        path = tmp_path / "config.json"
        path.write_text('{"session_store": {"backend": "postgres"}}', encoding="utf-8")

        loaded = load_config(path)
        assert loaded["session_store"]["backend"] == "postgres"
        # Untouched keys keep their default.
        assert loaded["dashboard"]["port"] == 8787
        assert "dsn" in loaded["session_store"]["postgres"]

    def test_missing_config_file_returns_defaults(self, tmp_path: Path):
        loaded = load_config(tmp_path / "does_not_exist.json")
        assert loaded == default_config()

    def test_invalid_json_raises_clear_error(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ValueError):
            load_config(path)

    def test_default_compression_level_defaults_to_semantic(self):
        assert default_compression_level(default_config()) == "semantic"

    def test_default_compression_level_reads_configured_value(self):
        cfg = default_config()
        cfg["compression"]["default_level"] = "aggressive"
        assert default_compression_level(cfg) == "aggressive"

    def test_default_compression_level_rejects_unknown_value(self):
        cfg = default_config()
        cfg["compression"]["default_level"] = "not-a-real-level"
        assert default_compression_level(cfg) == "semantic"

    def test_default_wiki_depth_defaults_to_2(self):
        assert default_wiki_depth(default_config()) == 2

    def test_default_wiki_depth_reads_configured_value(self):
        cfg = default_config()
        cfg["wiki"]["default_depth"] = 4
        assert default_wiki_depth(cfg) == 4

    def test_default_wiki_depth_rejects_out_of_range_value(self):
        cfg = default_config()
        cfg["wiki"]["default_depth"] = 7
        assert default_wiki_depth(cfg) == 2

    def test_privacy_config_defaults(self):
        pcfg = privacy_config(default_config())
        assert pcfg["enabled"] is True
        assert pcfg["auto_masking"] is True
        assert pcfg["prompt_injection_guard"] is True
        assert pcfg["ai_transparency_notice"] is False
        assert pcfg["transparency_custom_message"] == ""
        assert pcfg["whitelist"] == []

    def test_privacy_config_whitelist_roundtrip(self, tmp_path: Path):
        cfg = default_config()
        cfg["privacy"]["whitelist"] = ["support@company.com"]
        path = save_config(cfg, tmp_path / "config.json")
        loaded = load_config(path)
        assert privacy_config(loaded)["whitelist"] == ["support@company.com"]

    def test_privacy_config_can_be_disabled(self):
        cfg = default_config()
        cfg["privacy"]["enabled"] = False
        assert privacy_config(cfg)["enabled"] is False

    def test_privacy_config_partial_override_keeps_other_defaults(self):
        cfg = default_config()
        cfg["privacy"] = {"auto_masking": False}
        pcfg = privacy_config(cfg)
        assert pcfg["auto_masking"] is False
        assert pcfg["enabled"] is True  # untouched default preserved

    def test_waf_config_defaults(self):
        wcfg = waf_config(default_config())
        assert wcfg["enabled"] is True
        assert wcfg["block_mode"] is False
        assert wcfg["rule_sql_injection"] is True
        assert wcfg["auto_ban_threshold"] == 8
        assert wcfg["rate_limit_requests_per_minute"] == 120
        assert wcfg["excluded_paths"] == []

    def test_waf_config_can_be_disabled(self):
        cfg = default_config()
        cfg["waf"]["enabled"] = False
        assert waf_config(cfg)["enabled"] is False

    def test_waf_config_block_mode_roundtrip(self, tmp_path: Path):
        cfg = default_config()
        cfg["waf"]["block_mode"] = True
        path = save_config(cfg, tmp_path / "config.json")
        loaded = load_config(path)
        assert waf_config(loaded)["block_mode"] is True

    def test_waf_config_partial_override_keeps_other_defaults(self):
        cfg = default_config()
        cfg["waf"] = {"block_mode": True}
        wcfg = waf_config(cfg)
        assert wcfg["block_mode"] is True
        assert wcfg["enabled"] is True  # untouched default preserved

    def test_merge_config_overrides_only_given_keys(self):
        base = default_config()
        merged = merge_config(base, {"session_store": {"backend": "redis"}})
        assert merged["session_store"]["backend"] == "redis"
        assert merged["dashboard"]["port"] == 8787
        assert merged["compression"]["default_level"] == "semantic"

    def test_merge_config_does_not_mutate_base(self):
        base = default_config()
        merge_config(base, {"session_store": {"backend": "postgres"}})
        assert base["session_store"]["backend"] == "local"


class TestClusterConfig:
    def test_default_config_has_standalone_cluster_role(self):
        cfg = default_config()
        assert cfg["cluster"]["role"] == "standalone"
        assert cfg["cluster"]["node_id"] == ""
        assert cfg["cluster"]["node_token"] == ""

    def test_load_config_applies_cluster_env_overrides(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SYNTHELION_ROLE", "slave")
        monkeypatch.setenv("SYNTHELION_NODE_ID", "node-7")
        monkeypatch.setenv("SYNTHELION_NODE_TOKEN", "secret-token")
        monkeypatch.setenv("SYNTHELION_MASTER_URL", "http://master:8787")
        loaded = load_config(tmp_path / "does_not_exist.json")
        assert loaded["cluster"]["role"] == "slave"
        assert loaded["cluster"]["node_id"] == "node-7"
        assert loaded["cluster"]["node_token"] == "secret-token"
        assert loaded["cluster"]["master_url"] == "http://master:8787"

    def test_load_config_env_override_wins_over_file(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        path.write_text('{"cluster": {"role": "master"}}', encoding="utf-8")
        monkeypatch.setenv("SYNTHELION_ROLE", "slave")
        loaded = load_config(path)
        assert loaded["cluster"]["role"] == "slave"

    def test_no_cluster_env_vars_leaves_defaults(self, tmp_path, monkeypatch):
        for var in ("SYNTHELION_ROLE", "SYNTHELION_NODE_ID", "SYNTHELION_NODE_TOKEN", "SYNTHELION_MASTER_URL", "SYNTHELION_SELF_URL"):
            monkeypatch.delenv(var, raising=False)
        loaded = load_config(tmp_path / "does_not_exist.json")
        assert loaded["cluster"]["role"] == "standalone"

    def test_new_node_id_is_unique_and_short(self):
        a = new_node_id()
        b = new_node_id()
        assert a != b
        assert len(a) < 40

    def test_new_cluster_token_is_unique_and_long(self):
        a = new_cluster_token()
        b = new_cluster_token()
        assert a != b
        assert len(a) >= 32


class TestLocalFileSessionStore:
    def test_record_and_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalFileSessionStore(directory=tmp)
            store.record_call(SessionCall("s1", "compress", 100, 40))
            store.record_call(SessionCall("s1", "compress", 50, 20))

            active = store.active_sessions(ttl_seconds=60)
            assert len(active) == 1
            assert active[0].call_count == 2
            assert active[0].tokens_saved == 90

            stats = store.aggregate_stats()
            assert stats["calls"] == 2
            assert stats["tokens_saved"] == 90
            assert stats["backend"] == "local"

    def test_ttl_expires_old_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalFileSessionStore(directory=tmp)
            store.record_call(SessionCall("s1", "compress", 100, 40))
            # A TTL of 0 seconds means "active in the last 0s" — a call that
            # just happened should already be outside that window an instant later.
            time.sleep(0.05)
            active = store.active_sessions(ttl_seconds=0)
            assert active == []


class TestRedisSessionStoreShape:
    """Verifies command construction against a mocked redis.Redis client — not
    a live server."""

    def test_missing_package_raises_clear_error(self):
        with patch.dict("sys.modules", {"redis": None}):
            with pytest.raises(ImportError, match="pip install"):
                RedisSessionStore()

    def test_record_call_issues_expected_pipeline_commands(self):
        mock_redis_module = MagicMock()
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        mock_redis_module.Redis.from_url.return_value = mock_client

        with patch.dict("sys.modules", {"redis": mock_redis_module}):
            store = RedisSessionStore(url="redis://localhost:6379/0")
            store.record_call(SessionCall("s1", "compress", 100, 40))

        mock_pipe.hset.assert_called_once()
        mock_pipe.hincrby.assert_any_call("synthelion:session:s1", "call_count", 1)
        mock_pipe.sadd.assert_called_once_with("synthelion:sessions", "s1")
        mock_pipe.execute.assert_called_once()


class TestPostgresSessionStoreShape:
    """Verifies query construction against a mocked psycopg connection — not a
    live database."""

    def test_missing_package_raises_clear_error(self):
        with patch.dict("sys.modules", {"psycopg": None}):
            with pytest.raises(ImportError, match="pip install"):
                PostgresSessionStore(dsn="postgresql://x")

    def test_init_creates_schema(self):
        mock_psycopg = MagicMock()
        mock_conn = MagicMock()
        mock_psycopg.connect.return_value.__enter__.return_value = mock_conn

        with patch.dict("sys.modules", {"psycopg": mock_psycopg}):
            PostgresSessionStore(dsn="postgresql://x")

        assert mock_conn.execute.called
        schema_call = mock_conn.execute.call_args[0][0]
        assert "CREATE TABLE" in schema_call
        assert "synthelion_calls" in schema_call


class TestCreateSessionStoreFactory:
    def test_defaults_to_local_backend(self, tmp_path: Path):
        cfg = default_config()
        cfg["session_store"]["local"]["directory"] = str(tmp_path)
        store = create_session_store(cfg)
        assert isinstance(store, LocalFileSessionStore)

    def test_unknown_extra_keys_do_not_break_construction(self, tmp_path: Path):
        cfg = default_config()
        cfg["session_store"]["local"]["directory"] = str(tmp_path)
        cfg["some_future_key"] = {"whatever": True}
        store = create_session_store(cfg)
        assert isinstance(store, LocalFileSessionStore)
