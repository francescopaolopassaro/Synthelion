# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""When the same tool is called again with identical arguments — the same signal
`LoopGuard` already fingerprints to decide whether to block a retry loop — this
module decides how to *show* the repeated output: as a diff against the previous
call's result instead of the full text again, when that's actually shorter.

Deliberately a separate module from `loop_guard.py` rather than folding this into
`LoopGuard` itself: LoopGuard's job is "should this call be blocked", this module's
job is "how should this call's output be rendered" — different questions, so a caller
that only wants loop protection (or only wants diffing) can use either independently.
Reuses `loop_guard._fingerprint` so both modules agree on what counts as "the same
call" without duplicating the hashing logic.
"""
from __future__ import annotations

import difflib
import threading
import time

from synthelion.loop_guard import _fingerprint

_TTL = 600.0  # matches LoopGuard's default ttl_seconds


class RepeatOutputDiffer:
    """Tracks the last output per (session_id, tool) and, on a repeated call with the
    same arguments, returns a unified diff against that last output instead of the
    full text — but only when the diff is actually shorter (never worse than just
    returning the output verbatim)."""

    def __init__(self, ttl_seconds: float = _TTL) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        # (session_id, tool) -> (fingerprint, last_output, timestamp)
        self._last: dict[tuple[str, str], tuple[str, str, float]] = {}

    def diff_if_repeated(
        self,
        tool: str,
        arguments: dict | None,
        output: str,
        session_id: str = "default",
    ) -> tuple[str, bool]:
        fp = _fingerprint(tool, arguments)
        now = time.time()
        key = (session_id, tool)

        with self._lock:
            prev = self._last.get(key)
            self._last[key] = (fp, output, now)

        if prev is None:
            return output, False

        prev_fp, prev_output, prev_ts = prev
        if now - prev_ts > self._ttl or prev_fp != fp:
            return output, False

        diff_text = "\n".join(
            difflib.unified_diff(
                prev_output.splitlines(), output.splitlines(), lineterm="",
            )
        )
        if diff_text and len(diff_text) < len(output):
            return diff_text, True
        return output, False

    def reset(self, session_id: str = "default") -> None:
        with self._lock:
            for key in [k for k in self._last if k[0] == session_id]:
                del self._last[key]


_differ: RepeatOutputDiffer | None = None
_differ_lock = threading.Lock()


def get_repeat_differ() -> RepeatOutputDiffer:
    global _differ
    if _differ is None:
        with _differ_lock:
            if _differ is None:
                _differ = RepeatOutputDiffer()
    return _differ
