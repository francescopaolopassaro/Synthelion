# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Append-only proxy request log: metadata only, never prompt content.

Mirrors `synthelion/analytics/ledger.py`'s atomic-append pattern (same
concurrency reasoning — many requests hitting one proxy process, no
cross-process lock needed since every write is a single atomic append). Each
record answers "did this call happen, how long did it take, did it succeed" —
never "what was in it": no request/response body, no compressed or masked
text, nothing an operator watching the dashboard could use to reconstruct a
prompt.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from synthelion.analytics._atomic_append import append_line

_LOG_FILE = "proxy_log.jsonl"
_MAX_READ_LINES = 5000  # cap for `recent()` — plenty for a dashboard feed, bounds memory


def _log_path(directory: Path | None = None) -> Path:
    d = directory or (Path.home() / ".synthelion")
    d.mkdir(parents=True, exist_ok=True)
    return d / _LOG_FILE


class ProxyLog:
    def __init__(self, directory: Path | None = None) -> None:
        self._path = _log_path(directory)

    def record(
        self,
        method: str,
        path: str,
        upstream: str,
        status_code: int | None,
        duration_ms: float,
        responded: bool,
        blocked: bool = False,
        tokens_before: int = 0,
        tokens_after: int = 0,
        error: str | None = None,
        client_ip: str = "",
    ) -> None:
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "method": method,
            "path": path,
            "upstream": upstream,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 1),
            "responded": responded,
            "blocked": blocked,
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "error": error,
            "client_ip": client_ip,
        }
        append_line(self._path, (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))

    def recent(self, limit: int = 100) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()[-_MAX_READ_LINES:]
        except OSError:
            return []
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        records.reverse()  # newest first, matching how the dashboard's other feeds render
        return records[:limit]

    def prune_older_than(self, days: int) -> int:
        if not self._path.exists():
            return 0
        cutoff = time.time() - days * 86400
        kept: list[str] = []
        removed = 0
        for line in self._path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry["ts"]).timestamp()
            except (json.JSONDecodeError, KeyError, ValueError):
                kept.append(line)
                continue
            if ts >= cutoff:
                kept.append(line)
            else:
                removed += 1
        if removed:
            self._path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        return removed


_default_log: ProxyLog | None = None


def get_proxy_log() -> ProxyLog:
    global _default_log
    if _default_log is None:
        _default_log = ProxyLog()
    return _default_log
