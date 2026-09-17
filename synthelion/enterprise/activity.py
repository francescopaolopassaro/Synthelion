"""Enterprise activity logging (metadata only, no prompt content).

Every proxy request that passes the enterprise auth gate is logged with
user, provider, model, token counts, estimated cost, and duration.
"""
from __future__ import annotations

import logging
from typing import Any

from .db import get_db, _now_iso

log = logging.getLogger(__name__)

_TABLE = "enterprise_activity"


def log_request(
    *,
    user_id: str,
    provider: str,
    model: str | None = None,
    path: str | None = None,
    status_code: int | None = None,
    tokens_before: int = 0,
    tokens_after: int = 0,
    tokens_used: int = 0,
    cost_usd: float = 0.0,
    duration_ms: float = 0.0,
    compressed: bool = False,
    blocked: bool = False,
    block_reason: str | None = None,
) -> None:
    """Insert a single activity record (metadata only, no prompt content)."""
    get_db().insert(_TABLE, {
        "ts": _now_iso(),
        "user_id": user_id,
        "provider": provider,
        "model": model or "",
        "path": path or "",
        "status_code": status_code or 0,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "tokens_used": tokens_used,
        "cost_usd": cost_usd,
        "duration_ms": duration_ms,
        "compressed": 1 if compressed else 0,
        "blocked": 1 if blocked else 0,
        "block_reason": block_reason or "",
    })


def query_activity(
    user_id: str | None = None,
    since: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Query activity records, optionally filtered by user and time range."""
    db = get_db()
    clauses: list[str] = []
    params: list[Any] = []
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if since:
        clauses.append("ts >= ?")
        params.append(since)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM {_TABLE}{where} ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    return db.execute(sql, params)


def aggregate_user(user_id: str, since: str | None = None) -> dict[str, Any]:
    """Aggregate totals for a single user (total requests, tokens, cost)."""
    db = get_db()
    clauses = ["user_id = ?"]
    params: list[Any] = [user_id]
    if since:
        clauses.append("ts >= ?")
        params.append(since)
    where = " AND ".join(clauses)
    rows = db.execute(
        f"SELECT "
        f"  COUNT(*) AS total_requests, "
        f"  COALESCE(SUM(tokens_before), 0) AS total_tokens_before, "
        f"  COALESCE(SUM(tokens_after), 0) AS total_tokens_after, "
        f"  COALESCE(SUM(tokens_used), 0) AS total_tokens_used, "
        f"  COALESCE(SUM(cost_usd), 0) AS total_cost_usd, "
        f"  COALESCE(SUM(CASE WHEN compressed = 1 THEN 1 ELSE 0 END), 0) AS compressed_calls "
        f"FROM {_TABLE} WHERE {where}",
        params,
    )
    return rows[0] if rows else {
        "total_requests": 0, "total_tokens_before": 0,
        "total_tokens_after": 0, "total_tokens_used": 0,
        "total_cost_usd": 0.0, "compressed_calls": 0,
    }


def aggregate_all(since: str | None = None) -> dict[str, Any]:
    """Aggregate totals across all users."""
    db = get_db()
    if since:
        rows = db.execute(
            f"SELECT "
            f"  COUNT(*) AS total_requests, "
            f"  COALESCE(SUM(tokens_before), 0) AS total_tokens_before, "
            f"  COALESCE(SUM(tokens_after), 0) AS total_tokens_after, "
            f"  COALESCE(SUM(tokens_used), 0) AS total_tokens_used, "
            f"  COALESCE(SUM(cost_usd), 0) AS total_cost_usd, "
            f"  COALESCE(SUM(CASE WHEN compressed = 1 THEN 1 ELSE 0 END), 0) AS compressed_calls "
            f"FROM {_TABLE} WHERE ts >= ?",
            (since,),
        )
    else:
        rows = db.execute(
            f"SELECT "
            f"  COUNT(*) AS total_requests, "
            f"  COALESCE(SUM(tokens_before), 0) AS total_tokens_before, "
            f"  COALESCE(SUM(tokens_after), 0) AS total_tokens_after, "
            f"  COALESCE(SUM(tokens_used), 0) AS total_tokens_used, "
            f"  COALESCE(SUM(cost_usd), 0) AS total_cost_usd, "
            f"  COALESCE(SUM(CASE WHEN compressed = 1 THEN 1 ELSE 0 END), 0) AS compressed_calls "
            f"FROM {_TABLE}"
        )
    return rows[0] if rows else {
        "total_requests": 0, "total_tokens_before": 0,
        "total_tokens_after": 0, "total_tokens_used": 0,
        "total_cost_usd": 0.0, "compressed_calls": 0,
    }
