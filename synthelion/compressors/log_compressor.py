# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re

_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?|"
    r"\d{2}:\d{2}:\d{2}(?:\.\d+)?",
)
_HEX_ADDR = re.compile(r"\b0x[0-9a-fA-F]{4,}\b")
_THREAD_ID = re.compile(r"\[(?:Thread|thread|TID|PID)[\s-]?\d+\]|Thread-\d+|pid=\d+")


def _normalize(line: str) -> str:
    s = _TIMESTAMP.sub("<TS>", line)
    s = _HEX_ADDR.sub("<ADDR>", s)
    s = _THREAD_ID.sub("<THR>", s)
    # Collapse numbers in paths and bracket content
    s = re.sub(r"\b\d{4,}\b", "<N>", s)
    return s.strip()


class LogCompressor:
    """Deduplicates log/stacktrace output by collapsing repeated patterns.

    Ported from C# CavemanLogCompressor. Normalises timestamps/addresses,
    keeps first occurrence of each pattern with a repeat counter.
    """

    def compress(self, log: str, max_lines: int = 200) -> tuple[str, bool]:
        """Return (compressed, was_compressed)."""
        if not log or not log.strip():
            return log, False

        lines = log.splitlines()
        seen: dict[str, int] = {}
        out: list[str] = []

        for line in lines:
            if not line.strip():
                continue
            key = _normalize(line)
            if key in seen:
                seen[key] += 1
            else:
                seen[key] = 1
                out.append(line)
                if len(out) >= max_lines:
                    break

        # Annotate repeated lines
        annotated: list[str] = []
        key_iter = iter(seen.items())
        for orig_line in out:
            key = _normalize(orig_line)
            count = seen.get(key, 1)
            if count > 1:
                annotated.append(f"{orig_line}  [×{count}]")
            else:
                annotated.append(orig_line)

        result = "\n".join(annotated)
        return result, len(out) < len(lines)
