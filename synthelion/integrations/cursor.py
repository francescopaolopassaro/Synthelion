# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Synthelion integration for Cursor: MCP server + mandatory privacy Rule +
best-effort observability hook.

Cursor has no enforced pre-model hook today: `beforeSubmitPrompt` in
~/.cursor/hooks.json is documented as informational-only in the current
beta — Cursor does not act on any JSON the hook script returns, so it cannot
block or rewrite the prompt. Real enforcement in Cursor comes from the MCP
tools themselves (`synthelion_analyze_privacy`, `compress`) plus a Rule that
instructs the model to call them — the model has to choose to comply, same as
any tool-use model without hooks. The hook is still wired (for ledger
visibility into Cursor usage) but never claims to block anything.
"""
from __future__ import annotations

import json
import platform
import shutil
import sys
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

RULE_FILENAME = "synthelion-privacy.mdc"

RULE_CONTENT = """---
description: Synthelion privacy filter — mandatory PII/injection check before responding
globs:
alwaysApply: true
---

# Privacy Filter — Mandatory (Synthelion)

BEFORE responding to any user message, you MUST follow this procedure.

## 1. Analyze every message
Call the `synthelion_analyze_privacy` MCP tool with:
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


# ── paths ──────────────────────────────────────────────────────────────────

def mcp_json_path() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def rules_dir(local: bool) -> Path:
    return (Path(".cursor") / "rules") if local else (Path.home() / ".cursor" / "rules")


def hooks_json_path(local: bool) -> Path:
    return (Path(".cursor") / "hooks.json") if local else (Path.home() / ".cursor" / "hooks.json")


def cursor_installed() -> bool:
    return shutil.which("cursor") is not None


def find_mcp_binary() -> str | None:
    if IS_WINDOWS:
        scripts = Path(sys.executable).parent / "Scripts"
        binary = scripts / "synthelion-mcp.exe"
    else:
        scripts = Path(sys.executable).parent
        binary = scripts / "synthelion-mcp"
    if binary.exists():
        return str(binary)
    return shutil.which("synthelion-mcp")


def mcp_command_config(binary: str | None) -> dict:
    if binary:
        return {"command": binary}
    return {"command": sys.executable, "args": ["-m", "synthelion.plugins.mcp_server"]}


def find_cli_binary() -> str:
    found = shutil.which("synthelion")
    if found:
        return found
    if IS_WINDOWS:
        scripts = Path(sys.executable).parent / "Scripts"
        b = scripts / "synthelion.exe"
    else:
        scripts = Path(sys.executable).parent
        b = scripts / "synthelion"
    return str(b) if b.exists() else "synthelion"


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            path.rename(path.with_suffix(".json.bak"))
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _hook_command_windows(cli: str) -> str:
    cli_q = cli.replace("\\", "\\\\")
    return (
        f"$j=[Console]::In.ReadToEnd()|ConvertFrom-Json;"
        f"$p=$j.prompt;"
        f"if($p){{$p| & \"{cli_q}\" compress --json 2>$null | Out-Null}}"
    )


def _hook_command_unix(cli: str) -> str:
    return (
        f"prompt=$(cat | python3 -c \"import sys,json; print(json.load(sys.stdin).get('prompt',''))\"); "
        f"[ -n \"$prompt\" ] && printf '%s' \"$prompt\" | \"{cli}\" compress --json >/dev/null 2>&1; "
        f"true"
    )


def _build_hook_entry(cli_binary: str) -> dict:
    if IS_WINDOWS:
        return {"type": "command", "shell": "powershell", "command": _hook_command_windows(cli_binary)}
    return {"type": "command", "shell": "bash", "command": _hook_command_unix(cli_binary)}


# ── public API ──────────────────────────────────────────────────────────────

def configure(binary: str | None, local: bool = False, add_rule: bool = True, add_hook: bool = True) -> dict:
    """Write MCP config (always global) + Rule + observability hook. Returns
    a summary dict of what was written, for callers to report to the user."""
    result: dict = {}

    mcp_path = mcp_json_path()
    cfg = _load_json(mcp_path)
    cfg.setdefault("mcpServers", {})["synthelion"] = mcp_command_config(binary)
    _save_json(mcp_path, cfg)
    result["mcp_path"] = str(mcp_path)

    if add_rule:
        rdir = rules_dir(local)
        rdir.mkdir(parents=True, exist_ok=True)
        rule_path = rdir / RULE_FILENAME
        rule_path.write_text(RULE_CONTENT, encoding="utf-8")
        result["rule_path"] = str(rule_path)

    if add_hook:
        cli = find_cli_binary()
        hpath = hooks_json_path(local)
        hcfg = _load_json(hpath)
        hooks = hcfg.setdefault("hooks", {})
        existing = [h for h in hooks.get("beforeSubmitPrompt", []) if "synthelion" not in h.get("command", "").lower()]
        existing.append(_build_hook_entry(cli))
        hooks["beforeSubmitPrompt"] = existing
        _save_json(hpath, hcfg)
        result["hooks_path"] = str(hpath)

    return result


def remove(local: bool = False) -> dict:
    result: dict = {}

    mcp_path = mcp_json_path()
    if mcp_path.exists():
        cfg = _load_json(mcp_path)
        if "synthelion" in cfg.get("mcpServers", {}):
            del cfg["mcpServers"]["synthelion"]
            _save_json(mcp_path, cfg)
            result["mcp_removed"] = True

    rule_path = rules_dir(local) / RULE_FILENAME
    if rule_path.exists():
        rule_path.unlink()
        result["rule_removed"] = True

    hpath = hooks_json_path(local)
    if hpath.exists():
        hcfg = _load_json(hpath)
        hooks = hcfg.get("hooks", {})
        before = len(hooks.get("beforeSubmitPrompt", []))
        hooks["beforeSubmitPrompt"] = [h for h in hooks.get("beforeSubmitPrompt", []) if "synthelion" not in h.get("command", "").lower()]
        if before != len(hooks["beforeSubmitPrompt"]):
            result["hook_removed"] = True
        if not hooks["beforeSubmitPrompt"]:
            del hooks["beforeSubmitPrompt"]
        if not hooks:
            hcfg.pop("hooks", None)
        _save_json(hpath, hcfg)

    return result
