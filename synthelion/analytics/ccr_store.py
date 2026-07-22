# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Reversible-compression store (CCR — "compress, cache, retrieve"): when text
is compressed away, the original is kept here, keyed by a short token, so an
agent that later decides it actually needs the full detail can ask for it back
instead of the information being permanently lost.

SQLite-backed (not in-memory) because the proxy and the MCP server are
different OS processes — an agent calling `synthelion_retrieve`/`synthelion
retrieve` runs in a different process than the one that did the compressing,
so the store has to survive across process boundaries the same way the
savings ledger and session DB already do.

Entries expire after `ttl_seconds` (default 1h) — this is a working-memory
aid for the current conversation, not permanent storage of everything ever
compressed.
"""
from __future__ import annotations

import secrets
import sqlite3
import time
from pathlib import Path


def _default_db_path() -> Path:
    d = Path.home() / ".synthelion"
    d.mkdir(parents=True, exist_ok=True)
    return d / "ccr.db"


class CcrStore:
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
                "CREATE TABLE IF NOT EXISTS ccr ("
                "token TEXT PRIMARY KEY, original TEXT NOT NULL, created_at REAL NOT NULL)"
            )

    def store(self, text: str, ttl_seconds: float = 3600.0) -> str:
        token = secrets.token_hex(4)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ccr (token, original, created_at) VALUES (?, ?, ?)",
                (token, text, time.time()),
            )
        self._purge_expired(ttl_seconds)
        return token

    def retrieve(self, token: str, ttl_seconds: float = 3600.0) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT original, created_at FROM ccr WHERE token = ?", (token,)
            ).fetchone()
        if not row:
            return None
        original, created_at = row
        if time.time() - created_at > ttl_seconds:
            self.delete(token)
            return None
        return original

    def delete(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM ccr WHERE token = ?", (token,))

    def _purge_expired(self, ttl_seconds: float) -> int:
        cutoff = time.time() - ttl_seconds
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM ccr WHERE created_at < ?", (cutoff,))
            return cur.rowcount


_default_store: CcrStore | None = None


def get_ccr_store() -> CcrStore:
    global _default_store
    if _default_store is None:
        _default_store = CcrStore()
    return _default_store
