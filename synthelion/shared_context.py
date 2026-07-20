# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock

from synthelion.core import CompressionService
from synthelion.models import CompressionLevel
from synthelion.tokenizer import LlmModel, ModelTokenizer

_DEFAULT_TTL_SECONDS = 30 * 60  # 30 minutes
_DEFAULT_MAX_ENTRIES = 500


@dataclass
class SharedContextEntry:
    key: str
    original: str
    compressed: str
    tokens_before: int
    tokens_after: int
    agent_name: str | None = None


@dataclass
class SharedContextStats:
    entries: int = 0
    total_tokens_before: int = 0
    total_tokens_after: int = 0

    @property
    def total_saved(self) -> int:
        return self.total_tokens_before - self.total_tokens_after


class SharedContext:
    """Inter-agent compressed context store with TTL eviction.

    Ported from C# CavemanSharedContext. On `put`, content is NLP-compressed and both
    the original and the compressed copy are stored. On `get`, callers receive the
    compressed version by default (saving tokens) or the original with `full=True`.
    Entries expire after `ttl_seconds` (default 30 minutes); thread-safe.
    """

    def __init__(
        self,
        compression: CompressionService | None = None,
        tokenizer: ModelTokenizer | None = None,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._compression = compression or CompressionService()
        self._tokenizer = tokenizer or ModelTokenizer()
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._store: dict[str, tuple[SharedContextEntry, float]] = {}
        self._lock = Lock()

    def put(self, key: str, content: str, agent_name: str | None = None) -> SharedContextEntry:
        with self._lock:
            self._evict_locked()
            self._enforce_capacity_locked()

        tokens_before = self._tokenizer.count_tokens(content, LlmModel.GPT4)
        result = self._compression.compress(content, CompressionLevel.SEMANTIC)
        tokens_after = self._tokenizer.count_tokens(result.compressed_text, LlmModel.GPT4)

        entry = SharedContextEntry(
            key=key,
            original=content,
            compressed=result.compressed_text,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            agent_name=agent_name,
        )

        with self._lock:
            self._store[key] = (entry, time.monotonic() + self.ttl_seconds)
        return entry

    def get(self, key: str, full: bool = False) -> str | None:
        entry = self.get_entry(key)
        if entry is None:
            return None
        return entry.original if full else entry.compressed

    def get_entry(self, key: str) -> SharedContextEntry | None:
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            entry, expires_at = item
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return entry

    def evict(self) -> None:
        with self._lock:
            self._evict_locked()

    @property
    def stats(self) -> SharedContextStats:
        with self._lock:
            self._evict_locked()
            result = SharedContextStats()
            for entry, _ in self._store.values():
                result.entries += 1
                result.total_tokens_before += entry.tokens_before
                result.total_tokens_after += entry.tokens_after
            return result

    def _evict_locked(self) -> None:
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]

    def _enforce_capacity_locked(self) -> None:
        if len(self._store) < self.max_entries:
            return
        oldest_key = min(self._store, key=lambda k: self._store[k][1], default=None)
        if oldest_key is not None:
            del self._store[oldest_key]


_instance: SharedContext | None = None
_instance_lock = Lock()


def get_instance() -> SharedContext:
    """Process-wide singleton, mirroring C# CavemanSharedContext.Instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SharedContext()
    return _instance
