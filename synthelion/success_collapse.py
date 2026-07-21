# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""For a small set of well-known, low-signal shell commands that completed
successfully, collapses their (often long) output to 1-3 salient facts instead of
routing it through generic log compression — a full `npm install` transcript almost
never matters once it succeeded; "added 42 packages, 2 vulnerabilities" is the entire
useful content.

Deliberately conservative: `collapse()` only ever returns a summary when it actually
recognizes a salient fact in the output. If nothing matches, it returns None and the
caller falls back to the normal detection/compression pipeline — never fabricates a
summary from output it doesn't understand.
"""
from __future__ import annotations

import re

_KNOWN_PREFIXES: tuple[str, ...] = (
    "git push",
    "git pull",
    "npm install",
    "npm ci",
    "yarn install",
    "pip install",
    "docker build",
    "docker push",
    "terraform apply",
    "terraform plan",
)

# Each pattern is tried in order against the full output; the first 3 distinct matches
# (across all patterns) become the collapsed summary.
_SALIENT_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"^\s*added \d+ packages?.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*removed \d+ packages?.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*changed \d+ packages?.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^.*\d+ vulnerabilit\w+.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*Successfully installed .*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*Successfully built [0-9a-f]+\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*Successfully tagged \S+\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*\S+\.\.\S+\s+\S+\s*->\s*\S+\s*$", re.MULTILINE),  # git ref-update line
    re.compile(r"^\s*Everything up-to-date\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*Apply complete!.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*Plan:\s*\d+ to add.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*No changes\. Your infrastructure matches.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*(?:Already up to date|Already up-to-date)\.?\s*$", re.MULTILINE | re.IGNORECASE),
)


def is_known_low_signal(command: str) -> bool:
    """True if *command* matches one of the known low-signal-on-success families."""
    if not command:
        return False
    normalized = command.strip().lower()
    return any(normalized.startswith(prefix) for prefix in _KNOWN_PREFIXES)


def collapse(content: str, command: str) -> str | None:
    """Returns a 1-3 line summary of *content* if it recognizes salient facts for
    *command*'s output, or None if nothing matched (caller should fall back to the
    normal compression pipeline in that case)."""
    if not content or not is_known_low_signal(command):
        return None

    facts: list[str] = []
    for pattern in _SALIENT_PATTERNS:
        for match in pattern.finditer(content):
            line = match.group(0).strip()
            if line and line not in facts:
                facts.append(line)
            if len(facts) >= 3:
                break
        if len(facts) >= 3:
            break

    if not facts:
        return None
    return "\n".join(facts)
