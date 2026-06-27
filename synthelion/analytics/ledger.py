# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Append-only savings ledger: persists per-call token metrics to ~/.synthelion/savings.json.

Mirrors tokensave's savings_ledger table concept but uses a lightweight JSON file
so that chromadb or sqlite are not required for basic tracking.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_DEFAULT_DIR = Path.home() / ".synthelion"
_LEDGER_FILE = "savings.json"
_lock = threading.Lock()

# Sonnet 4.6 input pricing — $3.00/MTok = $0.000003 per token
# Used to estimate dollar savings from token compression.
_DEFAULT_PRICE_PER_TOKEN: float = 3e-6


def _ledger_path(directory: Path | None = None) -> Path:
    d = directory or _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d / _LEDGER_FILE


class SavingsLedger:
    """Thread-safe append-only token savings log.

    Each record stores:
        ts           — ISO-8601 UTC timestamp
        tool         — MCP tool name (compress, route_content, …)
        tokens_before — token count before compression
        tokens_after  — token count after compression
        content_type  — detected content type string (optional)
        language      — ISO 639-3 language code (optional)
    """

    def __init__(self, directory: Path | None = None) -> None:
        self._path = _ledger_path(directory)

    # ── write ────────────────────────────────────────────────────────────────

    def record(
        self,
        tool: str,
        tokens_before: int,
        tokens_after: int,
        content_type: str = "",
        language: str = "",
    ) -> None:
        """Append one compression event to the ledger."""
        saved = max(0, tokens_before - tokens_after)
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "tokens_saved": saved,
            "cost_usd_saved": round(saved * _DEFAULT_PRICE_PER_TOKEN, 8),
            "content_type": content_type,
            "language": language,
        }
        with _lock:
            records = self._load_raw()
            records.append(entry)
            self._path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    # ── read ─────────────────────────────────────────────────────────────────

    def all_records(self) -> list[dict]:
        with _lock:
            return self._load_raw()

    def records_since(self, days: int) -> list[dict]:
        cutoff = time.time() - days * 86400
        with _lock:
            raw = self._load_raw()
        result = []
        for r in raw:
            try:
                ts = datetime.fromisoformat(r["ts"]).timestamp()
                if ts >= cutoff:
                    result.append(r)
            except (KeyError, ValueError):
                pass
        return result

    def summary(self, records: list[dict] | None = None) -> dict:
        """Return aggregate statistics over *records* (or all records)."""
        data = records if records is not None else self.all_records()
        if not data:
            return {
                "total_calls": 0,
                "tokens_saved": 0,
                "tokens_before": 0,
                "tokens_after": 0,
                "avg_efficiency_pct": 0.0,
                "by_tool": {},
                "by_content_type": {},
            }

        total_before = sum(r.get("tokens_before", 0) for r in data)
        total_after = sum(r.get("tokens_after", 0) for r in data)
        total_saved = sum(r.get("tokens_saved", 0) for r in data)

        by_tool: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for r in data:
            by_tool[r.get("tool", "")] = by_tool.get(r.get("tool", ""), 0) + r.get("tokens_saved", 0)
            ct = r.get("content_type", "") or "unknown"
            by_type[ct] = by_type.get(ct, 0) + r.get("tokens_saved", 0)

        efficiency = (total_saved / total_before * 100) if total_before > 0 else 0.0
        cost_saved = sum(r.get("cost_usd_saved", r.get("tokens_saved", 0) * _DEFAULT_PRICE_PER_TOKEN) for r in data)

        return {
            "total_calls": len(data),
            "tokens_saved": total_saved,
            "tokens_before": total_before,
            "tokens_after": total_after,
            "avg_efficiency_pct": round(efficiency, 2),
            "cost_usd_saved": round(cost_saved, 6),
            "pricing_note": "Estimated at Sonnet 4.6 input price ($3.00/MTok)",
            "by_tool": by_tool,
            "by_content_type": by_type,
        }

    def reset(self) -> None:
        """Clear all saved records."""
        with _lock:
            self._path.write_text("[]", encoding="utf-8")

    # ── internal ─────────────────────────────────────────────────────────────

    def _load_raw(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []


# Module-level singleton (lazy, safe to import at any time)
_ledger: SavingsLedger | None = None
_ledger_lock = threading.Lock()


def get_ledger() -> SavingsLedger:
    global _ledger
    if _ledger is None:
        with _ledger_lock:
            if _ledger is None:
                _ledger = SavingsLedger()
    return _ledger
