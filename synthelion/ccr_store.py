# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import time
from threading import Lock

_DEFAULT_TTL_SECONDS = 5 * 60  # 5 minutes


class CcrStore:
    """Thread-safe in-memory store for CCR (Cache-Compress-Retrieve) dropped content.

    Ported from C# CavemanCcrStore. Holds the rows dropped by `JsonCrusher`'s lossy
    BM25 row-drop, keyed by the `ccr_hash` embedded in the compressed output, so a
    caller that needs the original data back can retrieve it within the TTL window.
    Entries expire after `ttl_seconds` (default 5 minutes).
    """

    def __init__(self, ttl_seconds: float = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[str, float]] = {}
        self._lock = Lock()

    def store(self, hash_key: str, original_json: str) -> None:
        with self._lock:
            self._evict_locked()
            self._store[hash_key] = (original_json, time.monotonic() + self._ttl)

    def retrieve(self, hash_key: str) -> str | None:
        with self._lock:
            entry = self._store.get(hash_key)
            if entry is None:
                return None
            json_text, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[hash_key]
                return None
            return json_text

    def evict(self) -> None:
        with self._lock:
            self._evict_locked()

    def _evict_locked(self) -> None:
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]


_instance: CcrStore | None = None
_instance_lock = Lock()


def get_instance() -> CcrStore:
    """Process-wide singleton, mirroring C# CavemanCcrStore.Instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = CcrStore()
    return _instance
