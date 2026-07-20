# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re
from dataclasses import dataclass

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_ISO8601_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:\d{2})?")
_JWT_RE = re.compile(r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")
_HEX_HASH_RE = re.compile(r"\b[0-9a-fA-F]{32}\b|\b[0-9a-fA-F]{40}\b|\b[0-9a-fA-F]{64}\b")

_DETECTORS = (
    (_UUID_RE, "UUID"),
    (_ISO8601_RE, "ISO8601"),
    (_JWT_RE, "JWT"),
    (_HEX_HASH_RE, "HexHash"),
)


@dataclass
class VolatileFinding:
    label: str
    sample: str


class CacheAligner:
    """Detects tokens in a system prompt that invalidate the LLM provider's KV-cache prefix.

    Ported from C# CavemanCacheAligner. Flags UUIDs, ISO-8601 datetimes, JWTs and hex
    hashes — anything that changes on every invocation and therefore breaks prompt-cache
    reuse if placed before the stable part of a system prompt. Stateless.
    """

    def scan(self, system_prompt: str) -> list[VolatileFinding]:
        if not system_prompt:
            return []
        findings = []
        for pattern, label in _DETECTORS:
            m = pattern.search(system_prompt)
            if m:
                sample = m.group()[:40]
                findings.append(VolatileFinding(label=label, sample=sample))
        return findings

    def has_volatile_tokens(self, system_prompt: str) -> bool:
        return len(self.scan(system_prompt)) > 0
