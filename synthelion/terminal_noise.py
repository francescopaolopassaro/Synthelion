# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Strips terminal control noise (ANSI escapes, spinner frames, progress bars,
in-place carriage-return overwrites) from captured shell output before it reaches
detection/compression.

A captured `npm install`/`vite`/`cargo build` transcript is full of characters that
carry zero information once flattened to plain text: color codes, cursor-movement
sequences, single spinner glyphs cycling on their own line, and `\\r`-driven progress
bars that a real terminal renders as one line but a naive capture stores as thousands
of overwritten variants. None of `LogCompressor`'s dedup logic ever collapses this,
because each raw variant is byte-for-byte distinct before this pass runs.
"""
from __future__ import annotations

import re

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[@-Z\\-_]")

# Braille-pattern spinner frames (the de facto standard for npm/yarn/vite/cargo
# spinners today) when they are the only non-whitespace content on a line — i.e. one
# spinner tick captured in isolation. Deliberately Unicode-only, not the ASCII
# "|/-\\" cycle some older tools use: a bare "-" or "|" alone on a line is common
# enough in ordinary text (list markers, table separators) that stripping it would
# risk losing real content, whereas a lone braille glyph never legitimately appears.
_SPINNER_LINE_RE = re.compile(r"^\s*[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]\s*$")

# A line made up of Unicode block/progress-bar fill characters (unambiguous — these
# never appear in ordinary prose), optionally with a trailing percentage, e.g.
# "████████████░░░░░░░░ 60%". ASCII bar styles ("[=====>   ] 60%") are matched only
# inside brackets with a percentage, since a bare run of "-" or "=" alone is a common,
# legitimate divider/underline in plain text and must not be stripped.
_PROGRESS_BAR_RE = re.compile(
    r"^\s*[█▓▒░▏▎▍▌▋▊▉]{3,}(?:\s+\d{1,3}%)?\s*$"
    r"|^\s*\[[=#\-> ]{3,}\]\s*\d{1,3}%\s*$"
)


def _collapse_carriage_returns(text: str) -> str:
    """A terminal overwrites a line every time it sees `\\r` without a following
    `\\n` — a naive capture instead stores every intermediate frame back to back.
    Keep only what a real terminal would actually be showing: the segment after the
    last `\\r` on each such run."""
    out_lines = []
    for line in text.split("\n"):
        if "\r" in line:
            line = line.rsplit("\r", 1)[-1]
        out_lines.append(line)
    return "\n".join(out_lines)


def strip_ansi_noise(text: str) -> str:
    """Removes ANSI escape sequences, isolated spinner-frame lines, progress-bar
    lines, and in-place carriage-return overwrites. Ordinary text without any of
    this is returned unchanged."""
    if not text:
        return text
    cleaned = _ANSI_ESCAPE_RE.sub("", text)
    cleaned = _collapse_carriage_returns(cleaned)
    kept_lines = [
        line for line in cleaned.split("\n")
        if not _SPINNER_LINE_RE.match(line) and not _PROGRESS_BAR_RE.match(line)
    ]
    return "\n".join(kept_lines)
