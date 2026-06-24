# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re

_HUNK_HEADER = re.compile(r"^@@[^@]*@@", re.MULTILINE)
_FILE_HEADER = re.compile(r"^(---|\+\+\+)\s", re.MULTILINE)

MAX_CONTEXT_LINES = 2
MAX_HUNKS_PER_FILE = 10
MAX_FILES = 20


class DiffCompressor:
    """Compresses unified diffs by trimming pure context lines.

    Ported from C# CavemanDiffCompressor. Preserves all +/- lines,
    trims context to MAX_CONTEXT_LINES per side, drops context-only hunks.
    """

    def compress(
        self,
        diff: str,
        max_context: int = MAX_CONTEXT_LINES,
        max_hunks: int = MAX_HUNKS_PER_FILE,
        max_files: int = MAX_FILES,
    ) -> tuple[str, bool]:
        """Return (compressed, was_compressed)."""
        if not diff or not diff.strip():
            return diff, False

        # Split into per-file sections on --- / +++ headers
        files = _split_files(diff)
        if not files:
            return diff, False

        out_parts: list[str] = []
        files_kept = 0

        for file_block in files[:max_files]:
            compressed_file = _compress_file(file_block, max_context, max_hunks)
            if compressed_file:
                out_parts.append(compressed_file)
                files_kept += 1

        if not out_parts:
            return diff, False

        result = "\n".join(out_parts)
        return result, result != diff


def _split_files(diff: str) -> list[str]:
    positions = [m.start() for m in _FILE_HEADER.finditer(diff) if m.group().startswith("---")]
    if not positions:
        return [diff]
    parts = []
    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(diff)
        parts.append(diff[pos:end])
    return parts


def _compress_file(block: str, max_context: int, max_hunks: int) -> str:
    lines = block.splitlines(keepends=True)
    # Find file header lines (--- / +++)
    header_lines: list[str] = []
    hunk_start_idx = 0
    for i, l in enumerate(lines):
        if l.startswith("---") or l.startswith("+++"):
            header_lines.append(l)
            hunk_start_idx = i + 1
        elif l.startswith("@@"):
            break

    body = lines[hunk_start_idx:]
    # Split into hunks
    hunks = _split_hunks(body)
    if not hunks:
        return block

    kept_hunks: list[list[str]] = []
    for hunk in hunks[:max_hunks]:
        trimmed = _trim_hunk(hunk, max_context)
        if trimmed:
            kept_hunks.append(trimmed)

    if not kept_hunks:
        return ""

    result_lines = header_lines[:]
    for h in kept_hunks:
        result_lines.extend(h)
    return "".join(result_lines)


def _split_hunks(lines: list[str]) -> list[list[str]]:
    hunks: list[list[str]] = []
    current: list[str] = []
    for l in lines:
        if l.startswith("@@") and current:
            hunks.append(current)
            current = []
        current.append(l)
    if current:
        hunks.append(current)
    return hunks


def _trim_hunk(hunk: list[str], max_context: int) -> list[str]:
    header = hunk[0] if hunk and hunk[0].startswith("@@") else None
    body = hunk[1:] if header else hunk

    # Check if hunk has any +/- lines
    has_changes = any(l.startswith(("+", "-")) for l in body)
    if not has_changes:
        return []

    # Trim leading context
    ctx_before = 0
    start = 0
    for i, l in enumerate(body):
        if not l.startswith(("+", "-")):
            ctx_before += 1
        else:
            start = max(0, i - max_context)
            break

    # Trim trailing context
    end = len(body)
    for i in range(len(body) - 1, -1, -1):
        if not body[i].startswith(("+", "-")):
            pass
        else:
            end = min(len(body), i + 1 + max_context)
            break

    trimmed_body = body[start:end]
    return ([header] if header else []) + trimmed_body
