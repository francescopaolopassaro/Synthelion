# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Append-only savings ledger: persists per-call token metrics to ~/.synthelion/savings.jsonl.

Mirrors tokensave's savings_ledger table concept but uses a lightweight JSONL
(newline-delimited JSON) file so that chromadb or sqlite are not required for
basic tracking.

Concurrency model: designed for many concurrent MCP server processes (one per
agent session) writing at once, as happens behind an AI provider. Each record
is appended with a single os.write() syscall on a file descriptor opened with
O_APPEND — the OS guarantees that write is atomic, so concurrent writers from
different processes never interleave or corrupt each other's lines, and no
cross-process lock (file lock, mutex, …) is needed. There is no read-modify-
write step, so there is nothing to race on.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from synthelion.analytics._atomic_append import append_line

# One id per OS process (MCP server instance, CLI invocation, hook call, …),
# generated once at import time. Every ledger record this process writes is
# tagged with it, so the dashboard can group raw requests into sessions
# without any extra plumbing at call sites.
_PROCESS_SESSION_ID = str(uuid.uuid4())
_PROCESS_PID = os.getpid()

_DEFAULT_DIR = Path.home() / ".synthelion"
_LEDGER_FILE = "savings.jsonl"
_LEGACY_LEDGER_FILE = "savings.json"  # pre-JSONL format (single JSON array)

# Sonnet 4.6 input pricing — $3.00/MTok = $0.000003 per token
# Used to estimate dollar savings from token compression.
_DEFAULT_PRICE_PER_TOKEN: float = 3e-6
# Same per-token estimate CompressionResult uses (models.py) -- kept in sync
# so the dashboard's aggregate energy/CO2 KPI matches individual call results.
_ENERGY_MWH_PER_TOKEN: float = 0.005
_CO2_MG_PER_MWH: float = 0.4


def _ledger_path(directory: Path | None = None) -> Path:
    d = directory or _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d / _LEDGER_FILE


def _append_json_line(path: Path, obj: dict) -> None:
    append_line(path, (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))


def _migrate_legacy(path: Path) -> None:
    """One-time migration from the old single-JSON-array ledger to JSONL."""
    legacy = path.with_name(_LEGACY_LEDGER_FILE)
    if path.exists() or not legacy.exists():
        return
    try:
        records = json.loads(legacy.read_text(encoding="utf-8"))
        if isinstance(records, list):
            with open(path, "a", encoding="utf-8") as fh:
                for r in records:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        legacy.rename(legacy.with_suffix(".json.migrated"))
    except (OSError, json.JSONDecodeError):
        pass


class SavingsLedger:
    """Append-only token savings log, safe for many concurrent writer processes.

    Each record stores:
        ts           — ISO-8601 UTC timestamp
        tool         — MCP tool name (compress, route_content, …)
        tokens_before — token count before compression
        tokens_after  — token count after compression
        content_type  — detected content type string (optional)
        language      — ISO 639-3 language code (optional)
        session_id    — id of the OS process that wrote this record
        pid           — that process's PID (debugging aid, PIDs get reused)
        duration_ms   — wall-clock time the call took, end to end (optional)
    """

    def __init__(self, directory: Path | None = None) -> None:
        self._path = _ledger_path(directory)
        _migrate_legacy(self._path)

    # ── write ────────────────────────────────────────────────────────────────

    def record(
        self,
        tool: str,
        tokens_before: int,
        tokens_after: int,
        content_type: str = "",
        language: str = "",
        duration_ms: float = 0.0,
    ) -> None:
        """Append one compression event to the ledger. Lock-free, non-blocking."""
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
            "session_id": _PROCESS_SESSION_ID,
            "pid": _PROCESS_PID,
            "duration_ms": round(duration_ms, 2),
        }
        _append_json_line(self._path, entry)

    # ── read ─────────────────────────────────────────────────────────────────

    def all_records(self) -> list[dict]:
        return self._load_raw()

    def records_since(self, days: int) -> list[dict]:
        cutoff = time.time() - days * 86400
        result = []
        for r in self._load_raw():
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
                "avg_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "max_latency_ms": 0.0,
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
        energy_mwh_saved = total_saved * _ENERGY_MWH_PER_TOKEN
        co2_mg_saved = energy_mwh_saved * _CO2_MG_PER_MWH

        durations = sorted(r.get("duration_ms", 0) or 0 for r in data if r.get("duration_ms"))
        avg_latency = sum(durations) / len(durations) if durations else 0.0
        p95_latency = durations[int(len(durations) * 0.95)] if durations else 0.0
        max_latency = durations[-1] if durations else 0.0

        return {
            "total_calls": len(data),
            "tokens_saved": total_saved,
            "tokens_before": total_before,
            "tokens_after": total_after,
            "avg_efficiency_pct": round(efficiency, 2),
            "cost_usd_saved": round(cost_saved, 6),
            "pricing_note": "Estimated at Sonnet 4.6 input price ($3.00/MTok)",
            "energy_mwh_saved": round(energy_mwh_saved, 3),
            "co2_mg_saved": round(co2_mg_saved, 3),
            "by_tool": by_tool,
            "by_content_type": by_type,
            "avg_latency_ms": round(avg_latency, 1),
            "p95_latency_ms": round(p95_latency, 1),
            "max_latency_ms": round(max_latency, 1),
        }

    def sessions_summary(self, records: list[dict] | None = None) -> list[dict]:
        """Group records by writer process (session_id) — most recent first."""
        data = records if records is not None else self.all_records()
        by_session: dict[str, dict] = {}
        for r in data:
            sid = r.get("session_id") or "unknown"
            s = by_session.setdefault(sid, {
                "session_id": sid,
                "pid": r.get("pid"),
                "calls": 0,
                "tokens_saved": 0,
                "tokens_before": 0,
                "tokens_after": 0,
                "tools": set(),
                "first_ts": r.get("ts"),
                "last_ts": r.get("ts"),
            })
            s["calls"] += 1
            s["tokens_saved"] += r.get("tokens_saved", 0)
            s["tokens_before"] += r.get("tokens_before", 0)
            s["tokens_after"] += r.get("tokens_after", 0)
            if r.get("tool"):
                s["tools"].add(r["tool"])
            ts = r.get("ts") or ""
            if ts and (not s["first_ts"] or ts < s["first_ts"]):
                s["first_ts"] = ts
            if ts and (not s["last_ts"] or ts > s["last_ts"]):
                s["last_ts"] = ts

        sessions = []
        for s in by_session.values():
            s["tools"] = sorted(s["tools"])
            sessions.append(s)
        sessions.sort(key=lambda s: s["last_ts"] or "", reverse=True)
        return sessions

    def reset(self) -> None:
        """Clear all saved records. Not meant to run concurrently with writers."""
        self._path.write_text("", encoding="utf-8")

    # ── internal ─────────────────────────────────────────────────────────────

    def _load_raw(self) -> list[dict]:
        if not self._path.exists():
            return []
        records: list[dict] = []
        try:
            with open(self._path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        # Tolerate a torn line from a writer caught mid-append.
                        continue
        except OSError:
            return []
        return records


# Module-level singleton (lazy, safe to import at any time). The lock only
# guards this process's first-init race — it never touches other processes
# or files, so it does not limit cross-session concurrency.
_ledger: SavingsLedger | None = None
_ledger_lock = __import__("threading").Lock()


def get_ledger() -> SavingsLedger:
    global _ledger
    if _ledger is None:
        with _ledger_lock:
            if _ledger is None:
                _ledger = SavingsLedger()
    return _ledger
