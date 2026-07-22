# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Cross-agent shared memory: notes any agent (Claude Code, Cursor, Aider,
Codex CLI, ...) can add or read, deduplicated by exact content hash — the
same note added twice (e.g. two different agent sessions both learning
"this repo uses pnpm, not npm") is stored once.

SQLite-backed (~/.synthelion/shared_memory.db), same reasoning as
ccr_store.py: different agents run as different OS processes, so this has to
survive across process boundaries, not just live in one process's memory.

This is a flat, unranked note list — not RAG/embedding-based retrieval (that
already exists per-session via `vector_store`, see synthelion/analytics/
session_db.py). It's for small, durable, cross-agent facts, not semantic
search over a large corpus.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path


def _default_db_path() -> Path:
    d = Path.home() / ".synthelion"
    d.mkdir(parents=True, exist_ok=True)
    return d / "shared_memory.db"


class SharedMemory:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_db_path()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS notes ("
                "content_hash TEXT PRIMARY KEY, text TEXT NOT NULL, "
                "agent TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL)"
            )

    def add(self, text: str, agent: str = "") -> bool:
        """Returns True if a new note was stored, False if it already existed
        (exact-text dedup)."""
        content_hash = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
        with self._connect() as conn:
            existing = conn.execute("SELECT 1 FROM notes WHERE content_hash = ?", (content_hash,)).fetchone()
            if existing:
                return False
            conn.execute(
                "INSERT INTO notes (content_hash, text, agent, created_at) VALUES (?, ?, ?, ?)",
                (content_hash, text.strip(), agent, time.time()),
            )
        return True

    def recent(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT text, agent, created_at FROM notes ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {"text": t, "agent": a, "ts": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()}
            for t, a, ts in rows
        ]

    def clear(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM notes")
            return cur.rowcount


_default_memory: SharedMemory | None = None


def get_shared_memory() -> SharedMemory:
    global _default_memory
    if _default_memory is None:
        _default_memory = SharedMemory()
    return _default_memory
