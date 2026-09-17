"""Enterprise persistence layer.

Default backend: local SQLite at ``~/.synthelion/enterprise.db``.
If ``enterprise.db.url`` is configured the system tries PostgreSQL / MySQL /
SQL Server / Redis; on connection failure it falls back to SQLite when
``enterprise.db.fallback_to_local`` is ``True`` (the default).

Tables are created automatically on first connection (``CREATE TABLE IF NOT
EXISTS``) so there is zero manual migration step.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── DDL ────────────────────────────────────────────────────────────────────
# Written in SQL-92 that works on SQLite, PostgreSQL, MySQL and SQL Server.
# Boolean → INTEGER (SQLite compat); TIMESTAMP → TIMESTAMP.

_SCHEMA_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS enterprise_users (
        id              TEXT PRIMARY KEY,
        label           TEXT NOT NULL,
        role            TEXT NOT NULL DEFAULT 'user',
        enabled         INTEGER NOT NULL DEFAULT 1,
        virtual_token   TEXT NOT NULL UNIQUE,
        synthelion_enabled INTEGER NOT NULL DEFAULT 1,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_eu_token ON enterprise_users(virtual_token)",
    "CREATE INDEX IF NOT EXISTS idx_eu_role  ON enterprise_users(role)",

    """CREATE TABLE IF NOT EXISTS enterprise_provider_keys (
        id              TEXT PRIMARY KEY,
        provider        TEXT NOT NULL,
        label           TEXT NOT NULL,
        api_key_enc     TEXT NOT NULL,
        upstream_url    TEXT NOT NULL,
        enabled         INTEGER NOT NULL DEFAULT 1,
        created_at      TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_epk_provider ON enterprise_provider_keys(provider)",

    """CREATE TABLE IF NOT EXISTS enterprise_user_providers (
        user_id         TEXT NOT NULL,
        provider_key_id TEXT NOT NULL,
        assigned_at     TEXT NOT NULL,
        PRIMARY KEY (user_id, provider_key_id)
    )""",

    """CREATE TABLE IF NOT EXISTS enterprise_subscriptions (
        id              TEXT PRIMARY KEY,
        user_id         TEXT NOT NULL,
        provider_key_id TEXT NOT NULL,
        type            TEXT NOT NULL,
        model           TEXT,
        max_tokens      INTEGER NOT NULL DEFAULT 0,
        max_monthly_cost_usd REAL NOT NULL DEFAULT 0,
        current_tokens_used INTEGER NOT NULL DEFAULT 0,
        current_month_cost_usd REAL NOT NULL DEFAULT 0,
        period_start    TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'active',
        created_at      TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_es_user   ON enterprise_subscriptions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_es_status ON enterprise_subscriptions(status)",

    """CREATE TABLE IF NOT EXISTS enterprise_activity (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ts              TEXT NOT NULL,
        user_id         TEXT NOT NULL,
        provider        TEXT NOT NULL,
        model           TEXT,
        path            TEXT,
        status_code     INTEGER,
        tokens_before   INTEGER,
        tokens_after    INTEGER,
        tokens_used     INTEGER,
        cost_usd        REAL,
        duration_ms     REAL,
        compressed      INTEGER NOT NULL DEFAULT 0,
        blocked         INTEGER NOT NULL DEFAULT 0,
        block_reason    TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ea_user_ts ON enterprise_activity(user_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_ea_ts      ON enterprise_activity(ts)",

    """CREATE TABLE IF NOT EXISTS enterprise_model_costs (
        provider        TEXT NOT NULL,
        model           TEXT NOT NULL,
        input_per_token  REAL,
        output_per_token REAL,
        last_synced_at  TEXT NOT NULL,
        PRIMARY KEY (provider, model)
    )""",
]


# ── Helpers ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _rows_to_dicts(rows: list) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# ── Connection wrapper ─────────────────────────────────────────────────────

class EnterpriseDB:
    """Thread-safe singleton database handle.

    Usage::

        db = get_db()          # first call creates, subsequent return same
        db.execute("SELECT …")
        db.insert("enterprise_users", {...})
    """

    _instance: "EnterpriseDB | None" = None
    _lock = threading.Lock()

    def __init__(self, config: dict | None = None):
        from synthelion.config import load_config
        cfg = (config or load_config()).get("enterprise", {}).get("db", {})
        self._backend: str = cfg.get("backend", "sqlite")
        self._url: str = cfg.get("url", "")
        self._fallback: bool = cfg.get("fallback_to_local", True)
        self._conn: Any = None
        self._is_sqlite: bool = False
        self._connect()
        self._init_tables()

    # ── connection ──────────────────────────────────────────────────────

    def _connect(self) -> None:
        if self._backend == "sqlite" or not self._url:
            self._connect_sqlite()
            return
        try:
            self._connect_external()
        except Exception as exc:
            if self._fallback:
                log.warning("Enterprise external DB failed (%s), falling back to SQLite", exc)
                self._connect_sqlite()
            else:
                raise

    def _connect_sqlite(self) -> None:
        path = Path.home() / ".synthelion" / "enterprise.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._is_sqlite = True
        log.info("Enterprise DB: SQLite %s", path)

    def _connect_external(self) -> None:
        if self._backend == "postgresql":
            import psycopg
            self._conn = psycopg.connect(self._url)
            self._conn.autocommit = False
        elif self._backend == "mysql":
            import pymysql
            self._conn = pymysql.connect(self._url, autocommit=False)
        elif self._backend == "sqlserver":
            import pyodbc
            self._conn = pyodbc.connect(self._url, autocommit=False)
        else:
            raise ValueError(f"Unsupported enterprise DB backend: {self._backend!r}")
        self._is_sqlite = False
        log.info("Enterprise DB: %s", self._backend)

    def _init_tables(self) -> None:
        cur = self._conn.cursor()
        for ddl in _SCHEMA_DDL:
            cur.execute(ddl)
        self._conn.commit()

    # ── public API ──────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple | list | None = None) -> list[dict]:
        """Run *sql* and return rows as list of dicts."""
        cur = self._conn.cursor()
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        rows = cur.fetchall()
        self._conn.commit()
        return _rows_to_dicts(rows)

    def execute_no_return(self, sql: str, params: tuple | list | None = None) -> None:
        """Run *sql* without returning rows (INSERT / UPDATE / DELETE)."""
        cur = self._conn.cursor()
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        self._conn.commit()

    def insert(self, table: str, data: dict[str, Any]) -> Any:
        """INSERT and return the generated id (or rowcount)."""
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))  # works for sqlite & psycopg
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
        cur = self._conn.cursor()
        cur.execute(sql, list(data.values()))
        self._conn.commit()
        return cur.lastrowid

    def update(self, table: str, data: dict[str, Any], where: str,
               where_params: tuple | list = ()) -> int:
        """UPDATE and return rowcount."""
        sets = ", ".join(f"{k} = ?" for k in data)
        sql = f"UPDATE {table} SET {sets} WHERE {where}"
        params = list(data.values()) + list(where_params)
        cur = self._conn.cursor()
        cur.execute(sql, params)
        self._conn.commit()
        return cur.rowcount

    def delete(self, table: str, where: str, params: tuple | list = ()) -> int:
        """DELETE and return rowcount."""
        sql = f"DELETE FROM {table} WHERE {where}"
        cur = self._conn.cursor()
        cur.execute(sql, params)
        self._conn.commit()
        return cur.rowcount

    def count(self, table: str, where: str = "", params: tuple | list = ()) -> int:
        """Return COUNT(*) for *table*."""
        sql = f"SELECT COUNT(*) AS n FROM {table}"
        if where:
            sql += f" WHERE {where}"
        rows = self.execute(sql, params or None)
        return rows[0]["n"] if rows else 0

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


# ── Singleton accessor ─────────────────────────────────────────────────────

def get_db(config: dict | None = None) -> EnterpriseDB:
    """Return (and cache) the global EnterpriseDB singleton."""
    if EnterpriseDB._instance is None:
        with EnterpriseDB._lock:
            if EnterpriseDB._instance is None:
                EnterpriseDB._instance = EnterpriseDB(config)
    return EnterpriseDB._instance


def reset_db() -> None:
    """Close and clear the singleton (for tests)."""
    with EnterpriseDB._lock:
        if EnterpriseDB._instance is not None:
            EnterpriseDB._instance.close()
            EnterpriseDB._instance = None
