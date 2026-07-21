# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Credential-shape detector — a first line of defense against accidentally
persisting a secret verbatim to disk.

`SafetyGuard` (safety_guard.py) checks whether a message is *about* a security
topic (keywords like "vulnerability", "sql injection") to decide whether to skip
compressing it — a fidelity decision, not a persistence one. This module is
different and narrower: it looks for the actual *shape* of real credentials
(AWS keys, GitHub/Slack tokens, PEM key blocks, Bearer headers, bulk .env dumps)
so callers that persist text to disk (`SessionDB.record_decision`) can refuse to
write it verbatim instead of leaving a secret sitting in
`~/.synthelion/sessions/decisions_fallback.jsonl` (or ChromaDB/Qdrant) indefinitely.

Deliberately conservative (biased against false positives) over exhaustive —
this is a guard rail, not a full DLP scanner. Only the first 64 KiB is scanned:
a secret that matters overwhelmingly appears near the top of what a tool call
would ever pass in here (a `.env` file, a key file, a truncated error blob).
"""
from __future__ import annotations

import re

_SCAN_CAP_BYTES = 64 * 1024

_PRIVATE_KEY_RE = re.compile(r"-----BEGIN[\s\S]*?PRIVATE KEY-----")
_AWS_ACCESS_KEY_RE = re.compile(r"(?<![A-Z0-9])AKIA[A-Z0-9]{16,}(?![A-Z0-9])")
_GITHUB_TOKEN_RE = re.compile(r"\bghp_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b")
_SLACK_TOKEN_RE = re.compile(r"\bxox[bp]-[A-Za-z0-9-]{10,}\b")
# Real keys are always preceded by a delimiter (quote/=/whitespace/start) — excludes
# ordinary prose ending a word in "sk" before a hyphen ("desk-based", "risk-averse").
_API_SECRET_KEY_RE = re.compile(r"(?<![A-Za-z])sk-[A-Za-z0-9]{20,}\b")
_BEARER_TOKEN_RE = re.compile(r"Authorization:\s*Bearer\s+[A-Za-z0-9._-]{20,}")
_AWS_SECRET_LINE_RE = re.compile(
    r"(?:aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*=\s*[A-Za-z0-9/+=]{30,}"
)
_DOTENV_MARKERS = ("SECRET", "TOKEN", "PASSWORD", "APIKEY", "API_KEY")
_DOTENV_LINE_RE = re.compile(r"^([A-Z0-9_]+)=(.+)$")


def _has_dotenv_bulk_secrets(text: str) -> bool:
    """Three or more `KEY=value` lines whose KEY mentions SECRET/TOKEN/PASSWORD/
    APIKEY — a single such line is common enough in ordinary output (a log line
    mentioning "API_TOKEN=set") to not be alarming alone; three or more is the
    shape of an actual `.env` dump."""
    count = 0
    for line in text.splitlines():
        m = _DOTENV_LINE_RE.match(line.strip())
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if not value:
            continue
        if any(marker in key for marker in _DOTENV_MARKERS):
            count += 1
            if count >= 3:
                return True
    return False


_DETECTORS: tuple[tuple[re.Pattern, str], ...] = (
    (_PRIVATE_KEY_RE, "private-key-block"),
    (_AWS_ACCESS_KEY_RE, "aws-access-key"),
    (_GITHUB_TOKEN_RE, "github-token"),
    (_SLACK_TOKEN_RE, "slack-token"),
    (_API_SECRET_KEY_RE, "api-secret-key"),
    (_BEARER_TOKEN_RE, "bearer-token"),
    (_AWS_SECRET_LINE_RE, "aws-secret-line"),
)


def find_sensitive(text: str) -> str | None:
    """Scans *text* for credential-shaped content. Returns a stable class name
    (for logging/tests) if something tripped, or None. Callers should treat a
    non-None result as "do not persist this verbatim."."""
    if not text:
        return None
    scan = text[:_SCAN_CAP_BYTES]
    for pattern, label in _DETECTORS:
        if pattern.search(scan):
            return label
    if _has_dotenv_bulk_secrets(scan):
        return "dotenv-bulk-secrets"
    return None
