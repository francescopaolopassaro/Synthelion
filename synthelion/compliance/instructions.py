# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""System-instruction registry with version history.

The organisation-level instructions injected ahead of every model call are a
compliance artefact in their own right: the technical file has to state what
the model was told, and Annex IV asks for that history, not just the current
text. A value sitting in a config file answers "what is it now" and nothing
about "what was it when that decision was made".

So each change is appended to `~/.synthelion/system_instructions.jsonl` with
its content hash, and the audit trail records which version was in force. The
same append-only, no-cross-process-locks discipline as the rest of Synthelion's
persisted state.

The text itself is stored, unlike the payload hashes in the audit trail — these
are instructions the operator wrote, not user data, and a version history you
cannot read is not a version history.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from synthelion.analytics._atomic_append import append_line

_FILE = "system_instructions.jsonl"


def _path(directory: "Path | None" = None) -> Path:
    d = directory or (Path.home() / ".synthelion")
    d.mkdir(parents=True, exist_ok=True)
    return d / _FILE


def _digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def history(directory: "Path | None" = None) -> list[dict]:
    """Every recorded version, oldest first."""
    path = _path(directory)
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out


def current_version(directory: "Path | None" = None) -> dict | None:
    versions = history(directory)
    return versions[-1] if versions else None


def active_instructions() -> str:
    """The text to inject, from `compliance.system_prompt_override`.

    Reading the config rather than the history keeps the config the single
    source of truth — the history records what it has been, it does not
    override it. Recording happens here too, so a change made by editing the
    config file directly is still captured the first time it is used.
    """
    try:
        from synthelion.config import load_config
        text = (load_config().get("compliance", {}).get("system_prompt_override") or "").strip()
    except Exception:  # noqa: BLE001
        return ""
    if text:
        record(text)
    return text


def record(text: str, author: str = "", directory: "Path | None" = None) -> dict | None:
    """Append a new version if the text actually changed.

    Idempotent by content hash: this is called on every proxied request, so
    re-appending an unchanged value would turn the history into a request log.
    """
    text = (text or "").strip()
    if not text:
        return None
    digest = _digest(text)
    latest = current_version(directory)
    if latest and latest.get("hash") == digest:
        return latest

    entry = {
        "version": (latest.get("version", 0) + 1) if latest else 1,
        "hash": digest,
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ts": time.time(),
        "author": author,
        "text": text,
    }
    try:
        append_line(_path(directory), (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))
    except OSError:
        return None
    return entry


def registry_summary(directory: "Path | None" = None) -> dict:
    """Shape the technical file embeds (Annex IV system-prompt registry)."""
    versions = history(directory)
    current = versions[-1] if versions else None
    return {
        "configured": bool(current),
        "current_version": current.get("version") if current else None,
        "current_hash": current.get("hash") if current else None,
        "current_text": current.get("text") if current else "",
        "changed_at": current.get("ts_utc") if current else None,
        "version_count": len(versions),
        "history": [
            {k: v for k, v in entry.items() if k != "ts"}
            for entry in versions
        ],
    }
