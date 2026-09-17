"""Enterprise subscription management.

Subscription types:

* **consumo** — pay-per-use, ``max_tokens`` set by admin, cumulative until
  exhausted (no monthly reset).
* **mensile** — monthly plan, ``max_monthly_cost_usd`` set by admin, counters
  reset automatically every 30 days from ``period_start``.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import get_db, _now_iso

log = logging.getLogger(__name__)

_TABLE = "enterprise_subscriptions"


def _gen_id() -> str:
    return f"sub_{secrets.token_hex(8)}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_sub(row: dict[str, Any]) -> dict[str, Any]:
    """Map ``id`` → ``sub_id`` in returned dicts."""
    out = dict(row)
    out["sub_id"] = out.pop("id", "")
    return out


# ── CRUD ───────────────────────────────────────────────────────────────────

def list_subscriptions(
    user_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    db = get_db()
    clauses: list[str] = []
    params: list[Any] = []
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = db.execute(f"SELECT * FROM {_TABLE}{where} ORDER BY created_at", params or None)
    return [_normalize_sub(r) for r in rows]


def get_subscription(sub_id: str) -> dict[str, Any] | None:
    rows = get_db().execute(f"SELECT * FROM {_TABLE} WHERE id = ?", (sub_id,))
    return _normalize_sub(rows[0]) if rows else None


def add_subscription(
    user_id: str,
    provider_key_id: str,
    sub_type: str,
    model: str | None = None,
    max_tokens: int = 0,
    max_monthly_cost_usd: float = 0.0,
) -> dict[str, Any]:
    """Create a subscription.  ``sub_type`` must be ``consumo`` or ``mensile``."""
    if sub_type not in ("consumo", "mensile"):
        raise ValueError(f"Invalid subscription type: {sub_type!r}")
    sub_id = _gen_id()
    now = _now_iso()
    get_db().insert(_TABLE, {
        "id": sub_id,
        "user_id": user_id,
        "provider_key_id": provider_key_id,
        "type": sub_type,
        "model": model or "",
        "max_tokens": max_tokens,
        "max_monthly_cost_usd": max_monthly_cost_usd,
        "current_tokens_used": 0,
        "current_month_cost_usd": 0.0,
        "period_start": now,
        "status": "active",
        "created_at": now,
    })
    return get_subscription(sub_id)  # type: ignore[return-value]


def update_subscription(sub_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {
        "type", "model", "max_tokens", "max_monthly_cost_usd",
        "status", "period_start",
    }
    sets = {k: v for k, v in fields.items() if k in allowed}
    if sets:
        get_db().update(_TABLE, sets, "id = ?", (sub_id,))
    return get_subscription(sub_id)


def suspend_subscription(sub_id: str) -> dict[str, Any] | None:
    return update_subscription(sub_id, status="suspended")


def reactivate_subscription(sub_id: str) -> dict[str, Any] | None:
    return update_subscription(sub_id, status="active")


def delete_subscription(sub_id: str) -> int:
    return get_db().delete(_TABLE, "id = ?", (sub_id,))


# ── Quota enforcement ──────────────────────────────────────────────────────

def _reset_period(sub: dict[str, Any]) -> None:
    """Reset counters for a mensile subscription whose window expired."""
    now = _utcnow()
    get_db().update(
        _TABLE,
        {
            "current_tokens_used": 0,
            "current_month_cost_usd": 0.0,
            "period_start": now.isoformat(),
        },
        "id = ?",
        (sub["id"],),
    )


def quota_check(sub: dict[str, Any]) -> bool:
    """Return ``True`` if the subscription still has budget remaining.

    For **consumo**: cumulative, no reset — checks ``current_tokens_used <
    max_tokens``.

    For **mensile**: rolling 30-day window — auto-resets when expired, then
    checks ``current_month_cost_usd < max_monthly_cost_usd``.
    """
    if sub["status"] != "active":
        return False

    if sub["type"] == "consumo":
        return sub["current_tokens_used"] < sub["max_tokens"]

    if sub["type"] == "mensile":
        period_start = datetime.fromisoformat(sub["period_start"])
        if period_start.tzinfo is None:
            period_start = period_start.replace(tzinfo=timezone.utc)
        if _utcnow() > period_start + timedelta(days=30):
            _reset_period(sub)
            return True
        return sub["current_month_cost_usd"] < sub["max_monthly_cost_usd"]

    return False


def record_usage(sub_id: str, tokens_used: int, cost_usd: float) -> None:
    """Increment usage counters for a subscription."""
    sub = get_subscription(sub_id)
    if not sub:
        return
    db = get_db()
    if sub["type"] == "consumo":
        db.execute_no_return(
            f"UPDATE {_TABLE} SET "
            f"current_tokens_used = current_tokens_used + ?, "
            f"current_month_cost_usd = current_month_cost_usd + ? "
            f"WHERE id = ?",
            (tokens_used, cost_usd, sub_id),
        )
        # Auto-suspend if exhausted
        updated = get_subscription(sub_id)
        if updated and updated["current_tokens_used"] >= updated["max_tokens"]:
            db.execute_no_return(
                f"UPDATE {_TABLE} SET status = 'exhausted' WHERE id = ?",
                (sub_id,),
            )
    elif sub["type"] == "mensile":
        db.execute_no_return(
            f"UPDATE {_TABLE} SET "
            f"current_month_cost_usd = current_month_cost_usd + ? "
            f"WHERE id = ?",
            (cost_usd, sub_id),
        )


def find_active_sub(user_id: str, provider: str, model: str | None = None) -> dict[str, Any] | None:
    """Find an active subscription for *user_id* + *provider* + optional *model*.

    If *model* is ``None``, matches subscriptions with empty/null model
    (covers-all).  Subscriptions with a specific model are preferred.
    """
    db = get_db()
    # Try model-specific first
    if model:
        rows = db.execute(
            f"SELECT * FROM {_TABLE} "
            f"WHERE user_id = ? AND provider_key_id IN "
            f"(SELECT id FROM enterprise_provider_keys WHERE provider = ?) "
            f"AND status = 'active' AND model = ?",
            (user_id, provider, model),
        )
        if rows:
            return rows[0]
    # Fallback: cover-all subscription (empty model)
    rows = db.execute(
        f"SELECT * FROM {_TABLE} "
        f"WHERE user_id = ? AND provider_key_id IN "
        f"(SELECT id FROM enterprise_provider_keys WHERE provider = ?) "
        f"AND status = 'active' AND (model = '' OR model IS NULL)",
        (user_id, provider),
    )
    return rows[0] if rows else None
