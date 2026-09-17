"""Automatic model-cost synchronisation from models.dev.

Pulls the public ``models.dev/api.json`` catalog and upserts per-model
input/output token prices into the ``enterprise_model_costs`` table.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .db import get_db, _now_iso

log = logging.getLogger(__name__)

_TABLE = "enterprise_model_costs"
_MODELS_DEV_URL = "https://models.dev/api.json"


def sync_costs() -> int:
    """Fetch models.dev and upsert cost records.

    Returns the number of models upserted.
    """
    try:
        req = urllib.request.Request(_MODELS_DEV_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read())
    except Exception as exc:
        log.error("Failed to fetch models.dev: %s", exc)
        return 0

    # models.dev schema: { "openai": { "gpt-4o": { "input": 2.5e-6, "output": 10e-6 }, ... }, ... }
    db = get_db()
    now = _now_iso()
    count = 0
    for provider, models in raw.items():
        if not isinstance(models, dict):
            continue
        for model_name, pricing in models.items():
            if not isinstance(pricing, dict):
                continue
            inp = pricing.get("input") or pricing.get("input_price_per_token")
            out = pricing.get("output") or pricing.get("output_price_per_token")
            if inp is None and out is None:
                continue
            # Upsert
            existing = db.execute(
                f"SELECT 1 FROM {_TABLE} WHERE provider = ? AND model = ?",
                (provider, model_name),
            )
            data = {
                "provider": provider,
                "model": model_name,
                "input_per_token": float(inp) if inp else 0.0,
                "output_per_token": float(out) if out else 0.0,
                "last_synced_at": now,
            }
            if existing:
                db.update(_TABLE, data, "provider = ? AND model = ?", (provider, model_name))
            else:
                db.insert(_TABLE, data)
            count += 1
    log.info("Enterprise cost sync: %d models upserted from models.dev", count)
    return count


def get_cost(provider: str, model: str) -> dict[str, float] | None:
    """Return input/output per-token cost, or ``None`` if unknown."""
    rows = get_db().execute(
        f"SELECT input_per_token, output_per_token FROM {_TABLE} "
        f"WHERE provider = ? AND model = ?",
        (provider, model),
    )
    if rows:
        return {"input": rows[0]["input_per_token"], "output": rows[0]["output_per_token"]}
    return None


def estimate_cost(provider: str, model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate USD cost for a request (tokens_in + tokens_out)."""
    costs = get_cost(provider, model)
    if not costs:
        return 0.0
    return tokens_in * costs["input"] + tokens_out * costs["output"]
