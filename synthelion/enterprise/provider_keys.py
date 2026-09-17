"""Enterprise provider API-key management.

Keys are stored encrypted (AES-256-GCM) in the database.  Only the
ciphertext is persisted; decryption happens in memory via the
``enterprise/crypto`` module.
"""
from __future__ import annotations

import logging
from typing import Any

from .crypto import encrypt, decrypt
from .db import get_db, _now_iso

log = logging.getLogger(__name__)

_TABLE = "enterprise_provider_keys"

# Default upstream URLs per provider
_DEFAULT_UPSTREAMS: dict[str, str] = {
    "openai":     "https://api.openai.com",
    "anthropic":  "https://api.anthropic.com",
    "gemini":     "https://generativelanguage.googleapis.com",
    "groq":       "https://api.groq.com/openai",
    "mistral":    "https://api.mistral.ai",
    "deepseek":   "https://api.deepseek.com",
    "xai":        "https://api.x.ai",
    "together":   "https://api.together.xyz",
    "openrouter": "https://openrouter.ai/api",
}


def _normalize_key(row: dict[str, Any]) -> dict[str, Any]:
    """Map ``id`` → ``pk_id`` in returned dicts."""
    out = dict(row)
    out["pk_id"] = out.pop("id", "")
    return out


def list_provider_keys(provider: str | None = None) -> list[dict[str, Any]]:
    """Return all provider keys (without the real key value)."""
    db = get_db()
    if provider:
        rows = db.execute(
            f"SELECT id, provider, label, upstream_url, enabled, created_at "
            f"FROM {_TABLE} WHERE provider = ?", (provider,)
        )
    else:
        rows = db.execute(
            f"SELECT id, provider, label, upstream_url, enabled, created_at "
            f"FROM {_TABLE} ORDER BY provider, created_at"
        )
    return [_normalize_key(r) for r in rows]


def get_provider_key(pk_id: str) -> dict[str, Any] | None:
    rows = get_db().execute(f"SELECT * FROM {_TABLE} WHERE id = ?", (pk_id,))
    return _normalize_key(rows[0]) if rows else None


def get_real_key(pk_id: str) -> str:
    """Decrypt and return the real API key for *pk_id*."""
    row = get_provider_key(pk_id)
    if not row:
        raise KeyError(f"Provider key {pk_id!r} not found")
    return decrypt(row["api_key_enc"])


def add_provider_key(
    provider: str,
    label: str,
    api_key: str,
    upstream_url: str | None = None,
) -> dict[str, Any]:
    """Create a new encrypted provider key."""
    pk_id = f"pk_{__import__('secrets').token_hex(8)}"
    url = upstream_url or _DEFAULT_UPSTREAMS.get(provider, "")
    if not url:
        raise ValueError(f"Unknown provider {provider!r}; supply upstream_url")
    enc = encrypt(api_key)
    get_db().insert(_TABLE, {
        "id": pk_id,
        "provider": provider,
        "label": label,
        "api_key_enc": enc,
        "upstream_url": url,
        "enabled": 1,
        "created_at": _now_iso(),
    })
    return get_provider_key(pk_id)  # type: ignore[return-value]


def update_provider_key(pk_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"label", "upstream_url", "enabled"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if "api_key" in fields:
        sets["api_key_enc"] = encrypt(fields["api_key"])
    if sets:
        get_db().update(_TABLE, sets, "id = ?", (pk_id,))
    return get_provider_key(pk_id)


def delete_provider_key(pk_id: str) -> int:
    db = get_db()
    db.execute_no_return("DELETE FROM enterprise_user_providers WHERE provider_key_id = ?", (pk_id,))
    return db.delete(_TABLE, "id = ?", (pk_id,))


def find_key_for_user(user_id: str, provider: str) -> dict[str, Any] | None:
    """Find the first enabled provider key assigned to *user_id* for *provider*."""
    rows = get_db().execute(
        "SELECT epk.* FROM enterprise_provider_keys epk "
        "JOIN enterprise_user_providers eup ON eup.provider_key_id = epk.id "
        "WHERE eup.user_id = ? AND epk.provider = ? AND epk.enabled = 1 "
        "LIMIT 1",
        (user_id, provider),
    )
    return rows[0] if rows else None


def _gen_id() -> str:
    import secrets
    return f"pk_{secrets.token_hex(8)}"
