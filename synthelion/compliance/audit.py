# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tamper-evident audit trail for compliance decisions (EU AI Act Art. 12).

Each entry carries the hash of the one before it, so the log is a chain: an
entry that is edited or removed after the fact breaks every link after it, and
`verify_chain()` reports exactly where. This is *tamper-evident*, not
tamper-proof — anyone who can write the file can also rewrite the whole chain.
Genuine immutability needs an append-only medium or an external notary; what
this gives an auditor is the ability to prove the log has not been quietly
edited in place, which is what Art. 12 record-keeping is actually asked to
demonstrate.

Same append-only JSONL discipline as the rest of Synthelion's persisted state
(no cross-process locks): every writer appends one line with a single atomic
write, because the CLI, the MCP server and the proxy are separate processes.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from synthelion.analytics._atomic_append import append_line

_AUDIT_FILE = "compliance_audit.jsonl"
_GENESIS = "0" * 64


def _audit_path(directory: "Path | None" = None) -> Path:
    # Path.home() resolved per call, never cached at import — same rule as
    # loop_guard/ledger, so tests that redirect it stay isolated.
    d = directory or (Path.home() / ".synthelion")
    d.mkdir(parents=True, exist_ok=True)
    return d / _AUDIT_FILE


def _entry_hash(entry: dict) -> str:
    """Hash over the entry's content excluding its own hash field, with keys
    sorted so the digest doesn't depend on dict ordering."""
    payload = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def read_entries(limit: int | None = None, directory: "Path | None" = None) -> list[dict]:
    path = _audit_path(directory)
    if not path.exists():
        return []
    entries: list[dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return entries[-limit:] if limit else entries


def _last_hash(directory: "Path | None" = None) -> str:
    entries = read_entries(directory=directory)
    return entries[-1].get("hash", _GENESIS) if entries else _GENESIS


def record(
    *,
    scope: str,
    decision: str,
    findings: list[dict],
    request_hash: str = "",
    response_hash: str = "",
    user_id: str = "",
    client_ip: str = "",
    model: str = "",
    request_id: str = "",
    sources: "list[str] | None" = None,
    latency_ms: float = 0.0,
    directory: "Path | None" = None,
) -> dict:
    """Append one decision to the chain and return the entry written.

    Deliberately stores a *hash* of the processed text, never the text itself:
    an audit log of prompts would recreate the very exposure the privacy rules
    exist to prevent, and would itself become personal data under GDPR.
    """
    entry = {
        "ts": time.time(),
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # Correlates this decision with the caller's own request logs. Generated
        # here when the caller doesn't supply one, so the field is never empty.
        "request_id": request_id or uuid.uuid4().hex,
        "scope": scope,
        "decision": decision,
        "request_hash": request_hash,
        "response_hash": response_hash,
        "user_id": user_id,
        "client_ip": client_ip,
        "model": model,
        "latency_ms": round(latency_ms, 3),
        # Retrieval provenance (AI Act Art. 13): which sources the answer was
        # built from. Identifiers only — never the retrieved text.
        "sources": list(sources or []),
        "findings": findings,
        "prev_hash": _last_hash(directory),
        "pid": os.getpid(),
    }
    entry["hash"] = _entry_hash(entry)
    try:
        append_line(
            _audit_path(directory),
            (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"),
        )
    except OSError:
        pass
    return entry


def text_fingerprint(text: str) -> str:
    """Stable identifier for a payload, safe to store in the audit log."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


@dataclass
class ChainVerification:
    valid: bool
    entries: int
    broken_at: int | None = None
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "valid": self.valid, "entries": self.entries,
            "broken_at": self.broken_at, "reason": self.reason,
        }


def verify_chain(directory: "Path | None" = None) -> ChainVerification:
    """Walk the chain and report the first entry that doesn't line up.

    Two independent checks per entry: its recorded `prev_hash` must match the
    previous entry's hash (nothing removed or reordered), and its own hash must
    match a fresh digest of its content (nothing edited in place).
    """
    entries = read_entries(directory=directory)
    prev = _GENESIS
    for index, entry in enumerate(entries):
        if entry.get("prev_hash") != prev:
            return ChainVerification(False, len(entries), index,
                                     "prev_hash does not match the preceding entry — an entry was removed, reordered or inserted")
        if entry.get("hash") != _entry_hash(entry):
            return ChainVerification(False, len(entries), index,
                                     "entry hash does not match its content — the entry was edited after it was written")
        prev = entry["hash"]
    return ChainVerification(True, len(entries))


def statistics(since: float | None = None, directory: "Path | None" = None) -> dict:
    """Aggregates for the executive report."""
    entries = read_entries(directory=directory)
    if since is not None:
        entries = [e for e in entries if e.get("ts", 0) >= since]

    by_category: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    by_decision: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    latencies: list[float] = []

    for entry in entries:
        by_decision[entry.get("decision", "unknown")] = by_decision.get(entry.get("decision", "unknown"), 0) + 1
        if entry.get("latency_ms"):
            latencies.append(entry["latency_ms"])
        for finding in entry.get("findings", []):
            by_category[finding.get("category", "unknown")] = by_category.get(finding.get("category", "unknown"), 0) + 1
            by_risk[finding.get("risk_level", "unknown")] = by_risk.get(finding.get("risk_level", "unknown"), 0) + 1
            by_rule[finding.get("rule_id", "unknown")] = by_rule.get(finding.get("rule_id", "unknown"), 0) + 1

    latencies.sort()
    total = len(entries)
    violations = sum(1 for e in entries if e.get("findings"))
    return {
        "total_calls": total,
        "calls_with_findings": violations,
        "violation_rate_pct": round(violations / total * 100, 2) if total else 0.0,
        "by_category": by_category,
        "by_risk_level": by_risk,
        "by_decision": by_decision,
        "by_rule": by_rule,
        "latency_ms": {
            "avg": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            "p95": round(latencies[int(len(latencies) * 0.95)], 2) if latencies else 0.0,
            "max": round(latencies[-1], 2) if latencies else 0.0,
        },
    }


def conformity_receipt(entry: dict) -> dict:
    """Signed-style receipt attesting one response cleared every guardrail.

    The "signature" is the audit entry's own chain hash — it proves the
    attestation belongs to this specific decision at this specific position in
    the log, and cannot be moved onto another one. It is not a cryptographic
    signature under a private key: that would need a key-management story this
    module deliberately does not own.
    """
    return {
        "receipt_version": "1",
        "issued_at": entry.get("ts_utc"),
        "request_id": entry.get("request_id"),
        "request_hash": entry.get("request_hash"),
        "response_hash": entry.get("response_hash"),
        "decision": entry.get("decision"),
        "findings": len(entry.get("findings", [])),
        "chain_hash": entry.get("hash"),
        "attestation": "All enabled compliance guardrails were evaluated for this transaction.",
    }
