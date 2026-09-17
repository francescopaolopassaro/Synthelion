"""Enterprise user management.

Users are identified by a random ``id`` (``u_XXXXXXXX``) and authenticated
at the proxy via a ``virtual_token`` (``sxv_XXXXXXXX``).

Two users are bootstrapped automatically on first run:

* **admin** — role ``admin``, credentials match the existing dashboard admin.
* **test**  — role ``user``,  login ``user`` / ``password ``user``.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any

from .db import get_db, _now_iso

log = logging.getLogger(__name__)

_TABLE = "enterprise_users"

# ── Token / ID generation ──────────────────────────────────────────────────

def _gen_id(prefix: str = "u_") -> str:
    return f"{prefix}{secrets.token_hex(8)}"


def _gen_virtual_token() -> str:
    return f"sxv_{secrets.token_hex(24)}"


def _normalize_user(row: dict[str, Any]) -> dict[str, Any]:
    """Map DB columns to the API contract: ``id`` → ``user_id``,
    ``enabled`` → ``status``."""
    out = dict(row)
    out["user_id"] = out.pop("id", "")
    out["status"] = "active" if out.pop("enabled", 1) else "disabled"
    return out


# ── Bootstrap ──────────────────────────────────────────────────────────────

def bootstrap_enterprise_users() -> None:
    """Create the initial admin + test user if the table is empty.

    * The admin is created from the existing single-credential dashboard user
      (via ``synthelion.plugins.dashboard_auth``).
    * The test user gets login ``user`` / ``user`` and role ``user``.
    """
    db = get_db()
    if db.count(_TABLE) > 0:
        return  # already bootstrapped

    now = _now_iso()

    # ── admin ───────────────────────────────────────────────────────────
    try:
        from synthelion.plugins.dashboard_auth import current_username
        admin_label = current_username()
    except Exception:
        admin_label = "admin"

    admin_id = _gen_id()
    admin_token = _gen_virtual_token()
    db.insert(_TABLE, {
        "id": admin_id,
        "label": admin_label,
        "role": "admin",
        "enabled": 1,
        "virtual_token": admin_token,
        "synthelion_enabled": 1,
        "created_at": now,
        "updated_at": now,
    })
    log.info(
        "Enterprise admin created: id=%s  label=%s  token=%s",
        admin_id, admin_label, admin_token,
    )

    # ── test user ───────────────────────────────────────────────────────
    test_id = _gen_id()
    test_token = _gen_virtual_token()
    db.insert(_TABLE, {
        "id": test_id,
        "label": "user",
        "role": "user",
        "enabled": 1,
        "virtual_token": test_token,
        "synthelion_enabled": 1,
        "created_at": now,
        "updated_at": now,
    })
    log.info(
        "Enterprise test user created: id=%s  label=user  token=%s",
        test_id, test_token,
    )


# ── CRUD ───────────────────────────────────────────────────────────────────

def list_users(role: str | None = None) -> list[dict[str, Any]]:
    """Return all users (optionally filtered by role)."""
    db = get_db()
    if role:
        return [_normalize_user(r) for r in db.execute(f"SELECT * FROM {_TABLE} WHERE role = ?", (role,))]
    return [_normalize_user(r) for r in db.execute(f"SELECT * FROM {_TABLE} ORDER BY created_at")]


def get_user(user_id: str) -> dict[str, Any] | None:
    """Return a single user by id, or ``None``."""
    rows = get_db().execute(f"SELECT * FROM {_TABLE} WHERE id = ?", (user_id,))
    return _normalize_user(rows[0]) if rows else None


def get_user_by_token(virtual_token: str) -> dict[str, Any] | None:
    """Look up a user by their proxy virtual_token."""
    rows = get_db().execute(
        f"SELECT * FROM {_TABLE} WHERE virtual_token = ?", (virtual_token,)
    )
    return _normalize_user(rows[0]) if rows else None


def add_user(label: str, role: str = "user", **extra: Any) -> dict[str, Any]:
    """Create a new user and return the created record."""
    now = _now_iso()
    user_id = _gen_id()
    token = _gen_virtual_token()
    data = {
        "id": user_id,
        "label": label,
        "role": role,
        "enabled": 1,
        "virtual_token": token,
        "synthelion_enabled": 1,
        "created_at": now,
        "updated_at": now,
    }
    data.update(extra)
    get_db().insert(_TABLE, data)
    return get_user(user_id)  # type: ignore[return-value]


def update_user(user_id: str, **fields: Any) -> dict[str, Any] | None:
    """Update fields on an existing user.  Returns updated record."""
    allowed = {"label", "role", "enabled", "synthelion_enabled"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return get_user(user_id)
    sets["updated_at"] = _now_iso()
    get_db().update(_TABLE, sets, "id = ?", (user_id,))
    return get_user(user_id)


def rotate_token(user_id: str) -> str:
    """Generate a new virtual_token for *user_id* and return it."""
    new_token = _gen_virtual_token()
    get_db().update(_TABLE, {"virtual_token": new_token, "updated_at": _now_iso()},
                    "id = ?", (user_id,))
    return new_token


def delete_user(user_id: str) -> int:
    """Delete a user and cascade their assignments / subscriptions."""
    db = get_db()
    db.execute_no_return("DELETE FROM enterprise_user_providers WHERE user_id = ?", (user_id,))
    db.execute_no_return("DELETE FROM enterprise_subscriptions WHERE user_id = ?", (user_id,))
    return db.delete(_TABLE, "id = ?", (user_id,))


def enable_user(user_id: str) -> dict[str, Any] | None:
    return update_user(user_id, enabled=1)


def disable_user(user_id: str) -> dict[str, Any] | None:
    return update_user(user_id, enabled=0)


# ── Provider assignment (multi) ────────────────────────────────────────────

def assign_provider(user_id: str, provider_key_id: str) -> None:
    """Assign a provider key to a user (idempotent)."""
    db = get_db()
    existing = db.execute(
        "SELECT 1 FROM enterprise_user_providers "
        "WHERE user_id = ? AND provider_key_id = ?",
        (user_id, provider_key_id),
    )
    if not existing:
        db.insert("enterprise_user_providers", {
            "user_id": user_id,
            "provider_key_id": provider_key_id,
            "assigned_at": _now_iso(),
        })


def remove_provider(user_id: str, provider_key_id: str) -> int:
    return get_db().delete(
        "enterprise_user_providers",
        "user_id = ? AND provider_key_id = ?",
        (user_id, provider_key_id),
    )


def get_user_providers(user_id: str) -> list[dict[str, Any]]:
    """Return the provider-key records assigned to *user_id*."""
    return get_db().execute(
        "SELECT epk.* FROM enterprise_provider_keys epk "
        "JOIN enterprise_user_providers eup ON eup.provider_key_id = epk.id "
        "WHERE eup.user_id = ?",
        (user_id,),
    )
