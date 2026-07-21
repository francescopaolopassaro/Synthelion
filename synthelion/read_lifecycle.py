# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tracks the freshness of file-read tool calls across a session, so a caller can
decide when an earlier Read's output sitting in context is safe to collapse into a
compact marker instead of paying for its tokens on every subsequent turn.

Three states, computed per (session, file path):
- **fresh** — the most recent read of this path, nothing has touched the file since.
- **stale** — the file was written *after* this read; the read's content no longer
  reflects reality.
- **superseded** — the file has been read again since; an earlier copy of its
  content is redundant, the newer read already has it.

A stale/superseded read isn't matured (marked safe to collapse) the moment it
becomes one, though — a file mid-edit is likely to be read again in a turn or two,
and maturing it right away just means immediately un-maturing it, sitting right at
a provider's KV-cache breakpoint that then invalidates on every turn anyway.
`should_mature()` waits for `quiesce_turns` turns of silence on that path first —
the same "let it settle before treating it as done" idea as a cache breakpoint that
only moves once a section of the prompt has stopped changing.
"""
from __future__ import annotations

import threading

_DEFAULT_QUIESCE_TURNS = 3


class ReadLifecycleTracker:
    """Thread-safe. Nothing here reads or writes actual files — turns and file
    paths are supplied by the caller (the tool-call layer), this module only
    tracks the bookkeeping."""

    def __init__(self, quiesce_turns: int = _DEFAULT_QUIESCE_TURNS) -> None:
        self._quiesce_turns = quiesce_turns
        self._lock = threading.Lock()
        # (session_id, path) -> {"last_read_turn", "last_write_turn", "read_count"}
        self._state: dict[tuple[str, str], dict] = {}

    def _entry(self, session_id: str, path: str) -> dict:
        return self._state.setdefault(
            (session_id, path),
            {"last_read_turn": None, "last_write_turn": None, "read_count": 0},
        )

    def record_write(self, path: str, turn: int, session_id: str = "default") -> None:
        with self._lock:
            self._entry(session_id, path)["last_write_turn"] = turn

    def record_read(self, path: str, turn: int, session_id: str = "default") -> dict:
        """Records a read at *turn*. Returns this read's own status — always
        "fresh" for itself (it's the newest copy) unless a write already landed
        at or after this same turn, plus how many total reads this path has had."""
        with self._lock:
            entry = self._entry(session_id, path)
            entry["read_count"] += 1
            entry["last_read_turn"] = turn
            status = "stale" if entry["last_write_turn"] is not None and entry["last_write_turn"] >= turn else "fresh"
            return {"status": status, "read_count": entry["read_count"]}

    def classify(self, path: str, session_id: str = "default") -> str:
        """Current status of the most recent recorded read for *path*, or
        "unknown" if it's never been read in this session."""
        with self._lock:
            entry = self._state.get((session_id, path))
            if entry is None or entry["last_read_turn"] is None:
                return "unknown"
            if entry["last_write_turn"] is not None and entry["last_write_turn"] > entry["last_read_turn"]:
                return "stale"
            if entry["read_count"] > 1:
                return "superseded"
            return "fresh"

    def should_mature(self, path: str, current_turn: int, session_id: str = "default") -> bool:
        with self._lock:
            entry = self._state.get((session_id, path))
            if entry is None:
                return False
        status = self.classify(path, session_id)
        if status not in ("stale", "superseded"):
            return False
        last_turns = [t for t in (entry["last_read_turn"], entry["last_write_turn"]) if t is not None]
        if not last_turns:
            return False
        return (current_turn - max(last_turns)) >= self._quiesce_turns

    def maturation_marker(self, path: str, status: str) -> str:
        return f"[Read of {path} — {status}, collapsed after {self._quiesce_turns} quiet turns — re-read the file if you need its current contents]"


_tracker: ReadLifecycleTracker | None = None
_tracker_lock = threading.Lock()


def get_read_lifecycle_tracker() -> ReadLifecycleTracker:
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = ReadLifecycleTracker()
    return _tracker
