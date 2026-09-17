"""Synthelion Enterprise module.

Provides multi-user, per-provider quota, and usage tracking on top of
the local reverse proxy.  The database is created automatically on first
use (SQLite by default, external DB optional).

Bootstrapping happens lazily on first ``get_db()`` call: if the
``enterprise_users`` table is empty the module creates:

* An **admin** user from the existing dashboard single-credential.
* A **test** user with credentials ``user`` / ``user``.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import EnterpriseDB

log = logging.getLogger(__name__)

_bootstrapped = False


def ensure_enterprise(config: dict | None = None) -> "EnterpriseDB":
    """Ensure the enterprise module is initialised and tables exist.

    * Creates the database (SQLite local or external).
    * Runs ``CREATE TABLE IF NOT EXISTS`` for all enterprise tables.
    * Bootstraps the admin + test user on the very first call.

    Returns the ``EnterpriseDB`` instance.
    """
    global _bootstrapped
    from .db import get_db

    db = get_db(config)

    if not _bootstrapped:
        _bootstrap_users(db)
        _bootstrapped = True

    return db


def _bootstrap_users(db: "EnterpriseDB") -> None:
    """Create admin + test user if the users table is empty."""
    if db.count("enterprise_users") > 0:
        return

    import secrets
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()

    # ── admin ───────────────────────────────────────────────────────────
    try:
        from synthelion.plugins.dashboard_auth import current_username
        admin_label = current_username()
    except Exception:
        admin_label = "admin"

    admin_id = f"u_{secrets.token_hex(8)}"
    admin_token = f"sxv_{secrets.token_hex(24)}"
    db.insert("enterprise_users", {
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

    # ── test user (user / user) ────────────────────────────────────────
    test_id = f"u_{secrets.token_hex(8)}"
    test_token = f"sxv_{secrets.token_hex(24)}"
    db.insert("enterprise_users", {
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
