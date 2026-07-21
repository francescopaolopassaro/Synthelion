# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Masks older tool-call output in a conversation history behind a short placeholder,
keeping the original recoverable by hash — a long-running agent session accumulates
tool outputs whose exact bytes stop mattering a few turns later (the same content just
sits in context burning tokens on every subsequent turn), but occasionally an agent
does need to go back and re-read one exactly.

Same TTL/max-entry/eviction shape as `ContentRouter`/`CompressionService`'s caches, but
storing the *original* verbatim (not a compressed variant) — this is a placeholder +
recall mechanism, not a compression strategy, so unlike `SharedContext` it never
rewrites the content itself, only decides whether callers see it or a stand-in.
"""
from __future__ import annotations

import hashlib
import threading
import time

_TTL = 1800   # 30 minutes — matches ContentRouter/CompressionService/SharedContext
_MAX = 500    # max entries — evict oldest 25% when full


class OutputMaskStore:
    """Thread-safe hash → original-text store backing masked tool output."""

    def __init__(self, ttl_seconds: float = _TTL, max_entries: int = _MAX) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._lock = threading.Lock()
        self._data: dict[str, tuple[str, float]] = {}

    def store(self, text: str) -> str:
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        with self._lock:
            self._data[key] = (text, time.time())
            if len(self._data) > self._max:
                sorted_keys = sorted(self._data, key=lambda k: self._data[k][1])
                for k in sorted_keys[: self._max // 4]:
                    del self._data[k]
        return key

    def retrieve(self, hash_key: str) -> str | None:
        with self._lock:
            entry = self._data.get(hash_key)
            if entry is None:
                return None
            text, ts = entry
            if time.time() - ts > self._ttl:
                del self._data[hash_key]
                return None
            return text


_store: OutputMaskStore | None = None
_store_lock = threading.Lock()


def get_output_mask_store() -> OutputMaskStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = OutputMaskStore()
    return _store


def mask_old_outputs(
    outputs: list[dict], keep_last: int = 3, store: OutputMaskStore | None = None,
) -> list[dict]:
    """Replaces `output` in every entry except the last *keep_last* with a short
    placeholder, storing the original in *store* (module singleton by default) keyed
    by hash. Entries are otherwise returned unchanged (same keys, same order)."""
    store = store or get_output_mask_store()
    n = len(outputs)
    cutoff = max(0, n - keep_last)
    result = []
    for i, entry in enumerate(outputs):
        if i >= cutoff:
            result.append(entry)
            continue
        text = entry.get("output", "")
        h = store.store(text)
        masked = dict(entry)
        masked["output"] = (
            f"[Tool output masked — {len(text)} chars — "
            f"retrieve with expand_masked_output(hash='{h}')]"
        )
        result.append(masked)
    return result
