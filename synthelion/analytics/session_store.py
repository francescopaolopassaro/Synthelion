# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Configurable session-tracking backend: local file (default, single-machine),
Redis, or Postgres (for cross-node visibility when Synthelion runs behind a load
balancer or in a Kubernetes/Swarm cluster — an AI provider's MCP servers each run
in their own process/pod, so "active sessions" and aggregate stats only mean
anything cluster-wide if every node writes to the same shared store).

All three backends implement the same `SessionStore` interface, selected via
`synthelion.config` (`session_store.backend`: "local" | "redis" | "postgres").
Redis/Postgres client libraries are imported lazily, only when that backend is
actually selected, so a default local install never needs them.
"""
from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from synthelion.analytics.ledger import SavingsLedger

# A session with no recorded call in this many seconds is no longer "active".
_DEFAULT_ACTIVE_TTL_SECONDS = 300


@dataclass
class SessionCall:
    session_id: str
    tool: str
    tokens_before: int
    tokens_after: int
    ts: float = field(default_factory=time.time)
    content_type: str | None = None
    language: str | None = None
    duration_ms: float | None = None

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)


@dataclass
class SessionInfo:
    session_id: str
    first_seen: float
    last_seen: float
    call_count: int
    tokens_saved: int


class SessionStore(ABC):
    """Common interface every backend implements."""

    @abstractmethod
    def record_call(self, call: SessionCall) -> None: ...

    @abstractmethod
    def active_sessions(self, ttl_seconds: int = _DEFAULT_ACTIVE_TTL_SECONDS) -> list[SessionInfo]: ...

    @abstractmethod
    def aggregate_stats(self, since: float | None = None) -> dict[str, Any]: ...

    def backend_name(self) -> str:
        return type(self).__name__


# ---------------------------------------------------------------------------
# Local file backend (default) — wraps the existing append-only JSONL ledger.
# Single-machine only: multiple processes on the *same* host share visibility
# via the shared file, but a second node has its own separate file.
# ---------------------------------------------------------------------------

class LocalFileSessionStore(SessionStore):
    """Session identity for this backend is the OS process (SavingsLedger tags
    every record with the writing process's own id automatically) — matching the
    existing single-machine ledger design. `call.session_id` is accepted for
    interface compatibility with the other backends but not used here; on a
    single machine, "one process = one session" is already what every other
    Synthelion component (dashboard, CLI `status`/`gain`) assumes.
    """

    def __init__(self, directory: str | Path | None = None) -> None:
        self._ledger = SavingsLedger(Path(directory) if directory else None)

    def record_call(self, call: SessionCall) -> None:
        self._ledger.record(
            tool=call.tool,
            tokens_before=call.tokens_before,
            tokens_after=call.tokens_after,
            content_type=call.content_type or "",
            language=call.language or "",
            duration_ms=call.duration_ms or 0.0,
        )

    def active_sessions(self, ttl_seconds: int = _DEFAULT_ACTIVE_TTL_SECONDS) -> list[SessionInfo]:
        cutoff = time.time() - ttl_seconds
        result = []
        for s in self._ledger.sessions_summary():
            last_ts = _parse_iso_ts(s.get("last_ts"))
            if last_ts is None or last_ts < cutoff:
                continue
            first_ts = _parse_iso_ts(s.get("first_ts")) or last_ts
            result.append(SessionInfo(
                session_id=s["session_id"], first_seen=first_ts, last_seen=last_ts,
                call_count=s["calls"], tokens_saved=s["tokens_saved"],
            ))
        return result

    def aggregate_stats(self, since: float | None = None) -> dict[str, Any]:
        records = self._ledger.all_records()
        if since is not None:
            records = [r for r in records if (_parse_iso_ts(r.get("ts")) or 0) >= since]
        summary = self._ledger.summary(records)
        return {
            "backend": "local",
            "calls": summary["total_calls"],
            "tokens_before": summary["tokens_before"],
            "tokens_after": summary["tokens_after"],
            "tokens_saved": summary["tokens_saved"],
            "sessions": len({r.get("session_id") for r in records}),
        }


def _parse_iso_ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Redis backend — shared, low-latency, ideal for "active sessions" (native TTL
# keys) and multi-node deployments. Requires `pip install synthelion[redis]`.
# ---------------------------------------------------------------------------

class RedisSessionStore(SessionStore):
    def __init__(self, url: str = "redis://localhost:6379/0", key_prefix: str = "synthelion:",
                 active_ttl_seconds: int = _DEFAULT_ACTIVE_TTL_SECONDS) -> None:
        try:
            import redis  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "RedisSessionStore requires the 'redis' package: pip install 'synthelion[redis]'"
            ) from exc
        self._redis = redis.Redis.from_url(url, decode_responses=True)
        self._prefix = key_prefix
        self._active_ttl = active_ttl_seconds

    def _k(self, *parts: str) -> str:
        return self._prefix + ":".join(parts)

    def record_call(self, call: SessionCall) -> None:
        pipe = self._redis.pipeline()
        session_key = self._k("session", call.session_id)
        # Per-session heartbeat hash, TTL-refreshed on every call — a session
        # "expires" (stops counting as active) automatically when it goes quiet,
        # no separate cleanup job needed.
        pipe.hset(session_key, mapping={
            "first_seen": call.ts, "last_seen": call.ts,
        })
        pipe.hincrby(session_key, "call_count", 1)
        pipe.hincrby(session_key, "tokens_saved", call.tokens_saved)
        pipe.hsetnx(session_key, "first_seen", call.ts)
        pipe.expire(session_key, self._active_ttl)
        pipe.sadd(self._k("sessions"), call.session_id)
        # Cluster-wide running totals (all nodes increment the same keys).
        pipe.incr(self._k("stats", "calls"))
        pipe.incrby(self._k("stats", "tokens_before"), call.tokens_before)
        pipe.incrby(self._k("stats", "tokens_after"), call.tokens_after)
        pipe.execute()

    def active_sessions(self, ttl_seconds: int = _DEFAULT_ACTIVE_TTL_SECONDS) -> list[SessionInfo]:
        session_ids = self._redis.smembers(self._k("sessions"))
        result = []
        for sid in session_ids:
            data = self._redis.hgetall(self._k("session", sid))
            if not data:
                # Key expired (TTL) since being added to the set — prune lazily.
                self._redis.srem(self._k("sessions"), sid)
                continue
            result.append(SessionInfo(
                session_id=sid,
                first_seen=float(data.get("first_seen", 0)),
                last_seen=float(data.get("last_seen", 0)),
                call_count=int(data.get("call_count", 0)),
                tokens_saved=int(data.get("tokens_saved", 0)),
            ))
        return result

    def aggregate_stats(self, since: float | None = None) -> dict[str, Any]:
        # `since` is not supported by the running-counter design (would need a
        # time-series store); cluster-wide *all-time* totals are always available.
        calls = int(self._redis.get(self._k("stats", "calls")) or 0)
        tokens_before = int(self._redis.get(self._k("stats", "tokens_before")) or 0)
        tokens_after = int(self._redis.get(self._k("stats", "tokens_after")) or 0)
        return {
            "backend": "redis",
            "calls": calls,
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "tokens_saved": max(0, tokens_before - tokens_after),
            "sessions": self._redis.scard(self._k("sessions")),
        }


# ---------------------------------------------------------------------------
# Postgres backend — shared, durable, supports arbitrary historical queries
# (unlike Redis's running counters). Requires `pip install synthelion[postgres]`.
# ---------------------------------------------------------------------------

_POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS synthelion_calls (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    tokens_before INTEGER NOT NULL,
    tokens_after INTEGER NOT NULL,
    content_type TEXT,
    language TEXT,
    duration_ms DOUBLE PRECISION,
    ts DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_synthelion_calls_session ON synthelion_calls (session_id);
CREATE INDEX IF NOT EXISTS idx_synthelion_calls_ts ON synthelion_calls (ts);
"""


class PostgresSessionStore(SessionStore):
    def __init__(self, dsn: str) -> None:
        try:
            import psycopg  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "PostgresSessionStore requires the 'psycopg' package: pip install 'synthelion[postgres]'"
            ) from exc
        self._psycopg = psycopg
        self._dsn = dsn
        with self._connect() as conn:
            conn.execute(_POSTGRES_SCHEMA)
            conn.commit()

    def _connect(self):
        return self._psycopg.connect(self._dsn)

    def record_call(self, call: SessionCall) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO synthelion_calls "
                "(session_id, tool, tokens_before, tokens_after, content_type, language, duration_ms, ts) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (call.session_id, call.tool, call.tokens_before, call.tokens_after,
                 call.content_type, call.language, call.duration_ms, call.ts),
            )
            conn.commit()

    def active_sessions(self, ttl_seconds: int = _DEFAULT_ACTIVE_TTL_SECONDS) -> list[SessionInfo]:
        cutoff = time.time() - ttl_seconds
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id, MIN(ts), MAX(ts), COUNT(*), "
                "SUM(GREATEST(tokens_before - tokens_after, 0)) "
                "FROM synthelion_calls WHERE ts >= %s GROUP BY session_id",
                (cutoff,),
            ).fetchall()
        return [
            SessionInfo(session_id=r[0], first_seen=r[1], last_seen=r[2], call_count=r[3], tokens_saved=r[4] or 0)
            for r in rows
        ]

    def aggregate_stats(self, since: float | None = None) -> dict[str, Any]:
        query = "SELECT COUNT(*), COALESCE(SUM(tokens_before),0), COALESCE(SUM(tokens_after),0), " \
                "COUNT(DISTINCT session_id) FROM synthelion_calls"
        params: tuple = ()
        if since is not None:
            query += " WHERE ts >= %s"
            params = (since,)
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        calls, tokens_before, tokens_after, sessions = row
        return {
            "backend": "postgres",
            "calls": calls,
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "tokens_saved": max(0, tokens_before - tokens_after),
            "sessions": sessions,
        }


def create_session_store(config: dict[str, Any] | None = None) -> SessionStore:
    """Factory: builds the configured SessionStore backend from a Synthelion
    config dict (see synthelion.config). Defaults to LocalFileSessionStore when
    no config is given."""
    if config is None:
        from synthelion.config import load_config
        config = load_config()

    store_cfg = config.get("session_store", {})
    backend = store_cfg.get("backend", "local")

    if backend == "redis":
        redis_cfg = store_cfg.get("redis", {})
        return RedisSessionStore(
            url=redis_cfg.get("url", "redis://localhost:6379/0"),
            key_prefix=redis_cfg.get("key_prefix", "synthelion:"),
            active_ttl_seconds=redis_cfg.get("active_ttl_seconds", _DEFAULT_ACTIVE_TTL_SECONDS),
        )
    if backend == "postgres":
        pg_cfg = store_cfg.get("postgres", {})
        return PostgresSessionStore(dsn=pg_cfg["dsn"])

    local_cfg = store_cfg.get("local", {})
    return LocalFileSessionStore(directory=local_cfg.get("directory"))
