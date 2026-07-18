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
from synthelion.config import default_config, load_config, save_config


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
