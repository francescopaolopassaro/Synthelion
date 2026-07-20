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


@dataclass
class AlignmentResult:
    prompt: str
    reordered: bool
    moved_blocks: int


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

    def _is_volatile(self, block: str) -> bool:
        return any(pattern.search(block) for pattern, _ in _DETECTORS)

    def align(self, system_prompt: str) -> AlignmentResult:
        """Rewrite *system_prompt* so blocks containing volatile tokens sink to the end.

        Providers match a prompt's KV-cache against the *prefix* shared with the
        previous call, so a stable prefix gets reused (and billed cheaper) even if
        content later in the prompt is different on every call. This splits the
        prompt into paragraphs (falling back to lines if there's only one
        paragraph), keeps each group's relative order, and moves every
        UUID/timestamp/JWT/hash-bearing block after every stable one — diagnosis
        via `scan()` alone doesn't fix that, only reordering does.
        """
        if not system_prompt or not system_prompt.strip():
            return AlignmentResult(prompt=system_prompt, reordered=False, moved_blocks=0)

        sep = "\n\n"
        blocks = [b for b in system_prompt.split(sep) if b.strip()]
        if len(blocks) < 2:
            sep = "\n"
            blocks = [b for b in system_prompt.split(sep) if b.strip()]
        if len(blocks) < 2:
            return AlignmentResult(prompt=system_prompt, reordered=False, moved_blocks=0)

        stable = [b for b in blocks if not self._is_volatile(b)]
        volatile = [b for b in blocks if self._is_volatile(b)]
        if not volatile or not stable:
            return AlignmentResult(prompt=system_prompt, reordered=False, moved_blocks=0)

        reordered_prompt = sep.join(stable + volatile)
        if reordered_prompt == system_prompt:
            return AlignmentResult(prompt=system_prompt, reordered=False, moved_blocks=0)
        return AlignmentResult(prompt=reordered_prompt, reordered=True, moved_blocks=len(volatile))
