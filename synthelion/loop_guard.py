# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from synthelion.analytics._atomic_append import append_line


class LoopVerdict(Enum):
    ALLOW = "Allow"
    BLOCK = "Block"


@dataclass
class LoopCheckResult:
    verdict: LoopVerdict = LoopVerdict.ALLOW
    repeat_count: int = 1
    reason: str = ""

    @property
    def should_block(self) -> bool:
        return self.verdict == LoopVerdict.BLOCK


def _fingerprint(tool: str, arguments: dict | None) -> str:
    try:
        payload = json.dumps(arguments or {}, sort_keys=True, default=str, ensure_ascii=False)
    except TypeError:
        payload = str(arguments)
    return hashlib.sha256(f"{tool}:{payload}".encode("utf-8")).hexdigest()


def _result_for_streak(tool: str, streak: int, limit: int) -> LoopCheckResult:
    if streak >= limit:
        return LoopCheckResult(
            verdict=LoopVerdict.BLOCK,
            repeat_count=streak + 1,
            reason=(
                f"Tool '{tool}' called with identical arguments {streak + 1} times in a row — "
                "likely stuck in a retry loop. Change approach or ask the user before retrying."
            ),
        )
    return LoopCheckResult(repeat_count=streak + 1)


@dataclass
class _CallRecord:
    fingerprint: str
    timestamp: float


class LoopGuard:
    """Blocks an agent from repeating the same tool call past a retry ceiling.

    Ported concept from the Caveman C# agent-loop guardrail discussion: an agent that
    calls the same tool with identical (or near-identical, via argument fingerprinting)
    arguments more than `max_repeats` times in a row is almost certainly stuck retrying
    a failed approach rather than making progress. `check()` is meant to run as a
    pre-tool hook — before the call reaches the LLM/tool — so a detected loop is stopped
    before it burns the round-trip tokens, not after.

    In-process, per-`session_id` sliding window. This is ephemeral call history, not
    persisted shared state, so a plain `threading.Lock` is enough — it does not need the
    atomic-append / claim-file patterns used for Synthelion's persisted stores (ledger,
    session DB), which exist specifically to coordinate many *processes* writing to the
    same file.
    """

    def __init__(self, max_repeats: int = 2, window: int = 10, ttl_seconds: float = 600.0) -> None:
        if max_repeats < 1:
            raise ValueError("max_repeats must be >= 1")
        self._max_repeats = max_repeats
        self._window = window
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._history: dict[str, deque[_CallRecord]] = {}

    def check(
        self,
        tool: str,
        arguments: dict | None = None,
        session_id: str = "default",
        max_repeats: int | None = None,
    ) -> LoopCheckResult:
        if not tool:
            return LoopCheckResult()

        limit = max_repeats if max_repeats is not None else self._max_repeats
        fp = _fingerprint(tool, arguments)
        now = time.time()

        with self._lock:
            hist = self._history.setdefault(session_id, deque(maxlen=self._window))
            while hist and now - hist[0].timestamp > self._ttl:
                hist.popleft()

            streak = 0
            for rec in reversed(hist):
                if rec.fingerprint != fp:
                    break
                streak += 1

            result = _result_for_streak(tool, streak, limit)
            hist.append(_CallRecord(fingerprint=fp, timestamp=now))
            return result

    def reset(self, session_id: str = "default") -> None:
        with self._lock:
            self._history.pop(session_id, None)


class PersistentLoopGuard:
    """File-backed LoopGuard for callers that are a fresh OS process per check.

    `LoopGuard`'s history lives in one process's memory, which is fine for an MCP
    server (long-lived, calls `check()` in-process) but useless for a shell-level
    pre-tool hook, since a hook script is invoked as a brand-new process per tool
    call — an in-memory history would reset every single time. This variant persists
    call history to `~/.synthelion/loop_guard.jsonl` instead, so `synthelion
    loop-check` (see cli.py) keeps counting streaks across invocations.

    Same atomic-append-only pattern as the rest of Synthelion's persisted state
    ([[feedback_synthelion]]: no cross-process locks) — every check reads the
    existing history, then appends its own record with a single atomic
    os.write()/CreateFileW call; `reset()` appends a sentinel record rather than
    truncating the file, since safe cross-process truncation isn't possible without
    a lock. Two processes racing on the exact same tool call may each read the
    history before the other's write lands and both allow it — an accepted
    trade-off for a heuristic guardrail: worst case is one extra allowed retry, and
    the streak is picked up correctly on the very next check.
    """

    def __init__(self, path: Path | None = None, max_repeats: int = 2, ttl_seconds: float = 600.0) -> None:
        if max_repeats < 1:
            raise ValueError("max_repeats must be >= 1")
        self._path = path or (Path.home() / ".synthelion" / "loop_guard.jsonl")
        self._max_repeats = max_repeats
        self._ttl = ttl_seconds

    def _read_records(self) -> list[dict]:
        if not self._path.exists():
            return []
        records = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def _append(self, record: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        append_line(self._path, (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))

    def check(
        self,
        tool: str,
        arguments: dict | None = None,
        session_id: str = "default",
        max_repeats: int | None = None,
    ) -> LoopCheckResult:
        if not tool:
            return LoopCheckResult()

        limit = max_repeats if max_repeats is not None else self._max_repeats
        fp = _fingerprint(tool, arguments)
        now = time.time()

        streak = 0
        for rec in reversed(self._read_records()):
            if rec.get("session") != session_id:
                continue
            if now - rec.get("ts", 0) > self._ttl:
                break
            if rec.get("type") == "reset":
                break
            if rec.get("fingerprint") != fp:
                break
            streak += 1

        result = _result_for_streak(tool, streak, limit)
        self._append({"type": "call", "session": session_id, "tool": tool, "fingerprint": fp, "ts": now})
        return result

    def reset(self, session_id: str = "default") -> None:
        self._append({"type": "reset", "session": session_id, "ts": time.time()})
