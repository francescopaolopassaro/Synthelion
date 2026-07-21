# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Auto-install Synthelion privacy rules into OpenCode's global config.

Detects whether OpenCode is installed on the system and, if so, writes a
`rules/privacy.md` instruction file into `~/.config/opencode/` and adds it
to the `instructions` list in `~/.config/opencode/opencode.json`.

The rule instructs the LLM to always call ``synthelion_analyze_privacy``
with ``auto_masking=true`` before processing any user message, and to honour
the ``blocked`` flag returned by the tool.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

RULES_FILENAME = "rules/privacy.md"

_RULE_CONTENT = r"""# Privacy Filter — Mandatory (Synthelion)

BEFORE responding to any user message, you MUST follow this procedure.

## 1. Analyze every message
Call `synthelion_analyze_privacy` with:
- `text`: the full user message
- `auto_masking`: `true`
- `language`: auto-detect or `"it"` for Italian, `"en"` otherwise

## 2. Honour the block decision
- If `result.blocked` is **true**:
  → Do NOT process the message. Respond ONLY with `result.warning_message`.
  → Do NOT reference, repeat, or reason about the original text.
- If `result.blocked` is **false**:
  → Use `result.masked_text` as the effective user input from this point on.
  → Treat the original message as if you never saw it — all subsequent
     reasoning MUST use only the masked version.

## 3. Why this exists
This rule protects sensitive data (PII, financial info, credentials) from
being processed by the LLM. The Synthelion privacy engine scores every
message and blocks or masks content based on your configured threshold.
"""


# ── helpers ─────────────────────────────────────────────────────────


def _opencode_installed() -> bool:
    return shutil.which("opencode") is not None


def _opencode_config_dir() -> Path:
    """Return the global OpenCode config directory, creating it if needed."""
    home = Path.home()
    candidates = [
        home / ".config" / "opencode",
        Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "opencode",
    ]
    for d in candidates:
        if d.exists() and d.is_dir():
            return d
    first = candidates[0]
    first.mkdir(parents=True, exist_ok=True)
    return first


def _opencode_json_path() -> Path:
    return _opencode_config_dir() / "opencode.json"


def _read_opencode_json() -> dict:
    path = _opencode_json_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _write_opencode_json(cfg: dict) -> None:
    path = _opencode_json_path()
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _privacy_rules_path() -> Path:
    return _opencode_config_dir() / RULES_FILENAME


def _write_privacy_rules() -> None:
    target = _privacy_rules_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_RULE_CONTENT, encoding="utf-8")


def _ensure_instruction(cfg: dict) -> dict:
    instructions = cfg.get("instructions", [])
    entry = RULES_FILENAME.replace("\\", "/")
    if entry not in instructions:
        instructions.append(entry)
    cfg["instructions"] = instructions
    return cfg


# ── public API ──────────────────────────────────────────────────────


def install_or_update() -> bool:
    """Detect OpenCode, write privacy rules, and update opencode.json.

    Returns True if the integration was installed/updated, False if
    OpenCode is not installed on this system.
    """
    if not _opencode_installed():
        return False

    _write_privacy_rules()
    cfg = _read_opencode_json()
    cfg = _ensure_instruction(cfg)

    if "mcp" not in cfg:
        cfg["mcp"] = {}
    if "synthelion" not in cfg.get("mcp", {}):
        cfg.setdefault("mcp", {})["synthelion"] = {
            "type": "local",
            "command": ["synthelion-mcp"],
            "enabled": True,
        }

    _write_opencode_json(cfg)
    return True


def uninstall() -> bool:
    """Remove the privacy instruction from opencode.json (but leave the
    rules file in place for existing sessions). Returns True if anything
    was removed."""
    if not _opencode_installed():
        return False

    cfg = _read_opencode_json()
    entry = RULES_FILENAME.replace("\\", "/")
    instructions = cfg.get("instructions", [])
    if entry in instructions:
        instructions.remove(entry)
    cfg["instructions"] = instructions
    _write_opencode_json(cfg)
    return True
