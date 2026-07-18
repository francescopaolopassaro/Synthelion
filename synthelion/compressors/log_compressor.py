# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re

from synthelion import simhash

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

    def compress(
        self,
        log: str,
        max_lines: int = 200,
        fuzzy: bool = False,
        fuzzy_max_distance: int = 18,
    ) -> tuple[str, bool]:
        """Return (compressed, was_compressed).

        `fuzzy` (ported from Caveman C# 1.4.1's CavemanLogCompressor.FuzzyFold, default
        off): groups a line with an earlier one whose SimHash fingerprint is within
        `fuzzy_max_distance` bits (of 64), not just an exact match after normalisation —
        e.g. templated lines that substitute a username or IP address. Off by default:
        exact-match normalisation is the safer, already-proven behaviour; fuzzy grouping
        can occasionally group two genuinely distinct lines that just happen to share
        most of their wording. `fuzzy_max_distance` defaults to 18, calibrated
        empirically on ~10-word templated lines (see CavemanSimHash / simhash.py):
        substituted-value lines land ~10-20 bits apart, unrelated lines 30+ bits apart.
        """
        if not log or not log.strip():
            return log, False

        lines = log.splitlines()

        if not fuzzy:
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
            annotated = [
                f"{line}  [×{seen[_normalize(line)]}]" if seen[_normalize(line)] > 1 else line
                for line in out
            ]
        else:
            # groups: list of [representative_line, fingerprint, count]
            groups: list[list] = []
            for line in lines:
                if not line.strip():
                    continue
                fp = simhash.compute(line)
                matched = None
                for group in groups:
                    if simhash.hamming_distance(fp, group[1]) <= fuzzy_max_distance:
                        matched = group
                        break
                if matched is not None:
                    matched[2] += 1
                else:
                    groups.append([line, fp, 1])
                    if len(groups) >= max_lines:
                        break
            annotated = [
                f"{rep}  [×{count}]" if count > 1 else rep
                for rep, _fp, count in groups
            ]
            out = [g[0] for g in groups]

        result = "\n".join(annotated)
        return result, len(out) < len(lines)
