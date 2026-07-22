# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Synthelion integration for Aider: an advisory conventions file only.

Aider has no MCP client and no pre-send hook of any kind — the LLM inside an
Aider session cannot call an external tool, and no script runs before a
message reaches the model. There is therefore no way to *enforce* PII masking
or compression for Aider today. The only real lever is Aider's `read:`
conventions mechanism (a file auto-loaded into every session, same idea as
CLAUDE.md/AGENTS.md). This writes an *advisory* instruction only — it cannot
mask or block anything automatically, and callers should say so plainly
rather than overstating what it does.
"""
from __future__ import annotations

import shutil
from pathlib import Path

CONVENTIONS_FILENAME = "synthelion_conventions.md"

CONVENTIONS_CONTENT = """# Synthelion Privacy Advisory (for Aider)

Aider has no automated PII-masking or compression step — this note only asks
you (the model) to be careful, it cannot enforce anything.

## Guidance
- If the user's message appears to contain personal data, credentials, API
  keys, financial details, or other sensitive information, warn them before
  proceeding and suggest they run `synthelion compress --text "<their text>"`
  in a terminal first (it reports a PII/privacy score and returns a masked
  version) rather than pasting sensitive data directly into the chat.
- If asked to write code that returns or logs sensitive fields verbatim,
  prefer masked/placeholder examples and say why.

## Why this file exists
Synthelion (https://github.com/francescopaolopassaro/synthelion) provides
prompt compression and PII/privacy analysis for AI coding agents. Aider itself
cannot call external tools or run a pre-send hook, so this is advisory text
only — for enforced masking/blocking, use Claude Code, Cursor, or OpenAI
Codex CLI instead, where Synthelion registers as an MCP tool or a hook.
"""


def aider_installed() -> bool:
    return shutil.which("aider") is not None


def conventions_dir(local: bool) -> Path:
    return Path.cwd() if local else Path.home() / ".synthelion"


def conf_yml_path(local: bool) -> Path:
    return Path(".aider.conf.yml") if local else Path.home() / ".aider.conf.yml"


def _load_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _find_read_entries(lines: list[str]) -> tuple[list[str], int, int]:
    """Return (entries, start_line, end_line_exclusive). end==start if absent."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "read:" or stripped.startswith("read:"):
            rest = stripped[len("read:"):].strip()
            if rest.startswith("[") and rest.endswith("]"):
                items = [x.strip().strip('"\'') for x in rest[1:-1].split(",") if x.strip()]
                return items, i, i + 1
            if rest and rest not in ("", "|", ">"):
                return [rest.strip('"\'')], i, i + 1
            items = []
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("- "):
                items.append(lines[j].strip()[2:].strip('"\''))
                j += 1
            return items, i, j
    return [], -1, -1


def add_read_entry(path: Path, entry: str) -> None:
    lines = _load_lines(path)
    items, start, end = _find_read_entries(lines)
    if entry in items:
        return
    items.append(entry)
    block = ["read:"] + [f"  - {it}" for it in items]
    if start == -1:
        lines.append("read:")
        lines.extend(f"  - {it}" for it in items)
    else:
        lines[start:end] = block
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def remove_read_entry(path: Path, entry: str) -> bool:
    if not path.exists():
        return False
    lines = _load_lines(path)
    items, start, end = _find_read_entries(lines)
    if entry not in items:
        return False
    items = [it for it in items if it != entry]
    block = (["read:"] + [f"  - {it}" for it in items]) if items else []
    lines[start:end] = block
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


# ── public API ──────────────────────────────────────────────────────────────

def configure(local: bool = False) -> dict:
    cdir = conventions_dir(local)
    cdir.mkdir(parents=True, exist_ok=True)
    conv_path = cdir / CONVENTIONS_FILENAME
    conv_path.write_text(CONVENTIONS_CONTENT, encoding="utf-8")

    conf_path = conf_yml_path(local)
    entry = str(conv_path).replace("\\", "/")
    add_read_entry(conf_path, entry)

    return {"conventions_path": str(conv_path), "conf_path": str(conf_path)}


def remove(local: bool = False) -> dict:
    conf_path = conf_yml_path(local)
    cdir = conventions_dir(local)
    conv_path = cdir / CONVENTIONS_FILENAME
    entry = str(conv_path).replace("\\", "/")
    result: dict = {}
    if remove_read_entry(conf_path, entry):
        result["conf_updated"] = True
    if conv_path.exists():
        conv_path.unlink()
        result["conventions_removed"] = True
    return result
