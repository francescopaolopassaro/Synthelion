# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Synthelion integration for OpenAI Codex CLI: MCP server + AGENTS.md
instructions + an optional experimental hook.

Codex CLI has a real, documented MCP client — `[mcp_servers.NAME]` in
~/.codex/config.toml — and reads ~/.codex/AGENTS.md automatically on every
session, both stable and confirmed in OpenAI's own docs. This is wired by
default.

Codex CLI also has an in-development hook engine (`[features].codex_hooks`,
~/.codex/hooks.json) modeled on Claude Code's UserPromptSubmit hook. As of
this writing it is explicitly marked "under development" upstream, disabled
by default, and third-party sources disagree about which events/return
values are actually honoured. Wiring a guessed schema by default risks a
silent no-op (or a startup warning) on whatever the *next* Codex release
changes — so `configure()` only writes it when `experimental_hooks=True` is
passed explicitly, never by default.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

AGENTS_MARKER_START = "<!-- synthelion:start -->"
AGENTS_MARKER_END = "<!-- synthelion:end -->"

AGENTS_BLOCK = f"""{AGENTS_MARKER_START}
## Privacy Filter — Mandatory (Synthelion)

BEFORE responding to any user message, you MUST follow this procedure.

### 1. Analyze every message
Call the `synthelion_analyze_privacy` MCP tool with:
- `text`: the full user message
- `auto_masking`: `true`
- `language`: auto-detect or `"it"` for Italian, `"en"` otherwise

### 2. Honour the block decision
- If `result.blocked` is **true**:
  -> Do NOT process the message. Respond ONLY with `result.warning_message`.
  -> Do NOT reference, repeat, or reason about the original text.
- If `result.blocked` is **false**:
  -> Use `result.masked_text` as the effective user input from this point on.
  -> Treat the original message as if you never saw it — all subsequent
     reasoning MUST use only the masked version.

### 3. Why this exists
This rule protects sensitive data (PII, financial info, credentials) from
being processed by the LLM. The Synthelion privacy engine scores every
message and blocks or masks content based on your configured threshold.
{AGENTS_MARKER_END}
"""


def codex_installed() -> bool:
    return shutil.which("codex") is not None


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))


def config_toml_path() -> Path:
    return codex_home() / "config.toml"


def agents_md_path() -> Path:
    return codex_home() / "AGENTS.md"


def hooks_json_path() -> Path:
    return codex_home() / "hooks.json"


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


# ── config.toml editing (line-based — no TOML-writer dependency) ────────────
#
# We only ever touch the `[mcp_servers.synthelion]` table (and, behind the
# experimental flag, `[features]`). Rewriting the whole file with a generic
# TOML library would risk reformatting/reordering everything else the user
# has in there, so we scan for our own table by exact header match and only
# ever replace that block, leaving every other line byte-for-byte untouched.

def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _find_table(lines: list[str], header: str) -> tuple[int, int]:
    pattern = re.compile(rf"^\[{re.escape(header)}\]\s*$")
    for i, line in enumerate(lines):
        if pattern.match(line.strip()):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("["):
                j += 1
            return i, j
    return -1, -1


def _replace_table(lines: list[str], header: str, body: list[str]) -> list[str]:
    start, end = _find_table(lines, header)
    block = [f"[{header}]"] + body
    if start == -1:
        if lines and lines[-1].strip():
            lines.append("")
        return lines + block
    return lines[:start] + block + lines[end:]


def _remove_table(lines: list[str], header: str) -> list[str]:
    start, end = _find_table(lines, header)
    if start == -1:
        return lines
    return lines[:start] + lines[end:]


def _get_feature_bool(lines: list[str], key: str) -> bool:
    start, end = _find_table(lines, "features")
    if start == -1:
        return False
    for line in lines[start + 1:end]:
        m = re.match(rf"^{re.escape(key)}\s*=\s*(true|false)", line.strip())
        if m:
            return m.group(1) == "true"
    return False


def _set_feature_bool(lines: list[str], key: str, value: bool) -> list[str]:
    start, end = _find_table(lines, "features")
    val_str = "true" if value else "false"
    if start == -1:
        if lines and lines[-1].strip():
            lines.append("")
        return lines + ["[features]", f"{key} = {val_str}"]
    body = lines[start + 1:end]
    found = False
    new_body = []
    for line in body:
        if re.match(rf"^{re.escape(key)}\s*=", line.strip()):
            new_body.append(f"{key} = {val_str}")
            found = True
        else:
            new_body.append(line)
    if not found:
        new_body.append(f"{key} = {val_str}")
    return lines[:start + 1] + new_body + lines[end:]


def _toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _mcp_server_body(binary: str | None) -> list[str]:
    if binary:
        return [f"command = {_toml_str(binary)}", "args = []", "env = {}"]
    return [
        f"command = {_toml_str(sys.executable)}",
        'args = ["-m", "synthelion.plugins.mcp_server"]',
        "env = {}",
    ]


def _hook_command(cli: str) -> tuple[str, str]:
    if IS_WINDOWS:
        cmd = (
            f"$j=[Console]::In.ReadToEnd()|ConvertFrom-Json;$p=$j.prompt;"
            f"if($p){{$r=($p| & \"{cli.replace(chr(92), chr(92) * 2)}\" compress --json 2>$null)|ConvertFrom-Json;"
            f"if($r -and $r.blocked){{@{{decision='deny';reason=$r.notice}}|ConvertTo-Json -Compress}}}}"
        )
        return cmd, "powershell"
    cmd = (
        f"prompt=$(cat | python3 -c \"import sys,json; print(json.load(sys.stdin).get('prompt',''))\"); "
        f"if [ -n \"$prompt\" ]; then r=$(printf '%s' \"$prompt\" | \"{cli}\" compress --json 2>/dev/null); "
        f"blocked=$(printf '%s' \"$r\" | python3 -c \"import sys,json; print(json.load(sys.stdin).get('blocked', False))\" 2>/dev/null); "
        f"if [ \"$blocked\" = \"True\" ]; then printf '{{\"decision\":\"deny\"}}'; fi; fi"
    )
    return cmd, "bash"


# ── public API ──────────────────────────────────────────────────────────────

def configure(binary: str | None, add_agents: bool = True, experimental_hooks: bool = False) -> dict:
    result: dict = {}

    cfg_path = config_toml_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    lines = _read_lines(cfg_path)
    lines = _replace_table(lines, "mcp_servers.synthelion", _mcp_server_body(binary))
    cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result["config_path"] = str(cfg_path)

    if add_agents:
        agents_path = agents_md_path()
        agents_path.parent.mkdir(parents=True, exist_ok=True)
        text = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
        if AGENTS_MARKER_START in text:
            text = re.sub(
                re.escape(AGENTS_MARKER_START) + r".*?" + re.escape(AGENTS_MARKER_END),
                AGENTS_BLOCK.strip(), text, flags=re.DOTALL,
            )
        else:
            text = (text.rstrip() + "\n\n" if text.strip() else "") + AGENTS_BLOCK
        agents_path.write_text(text.strip() + "\n", encoding="utf-8")
        result["agents_md_path"] = str(agents_path)

    if experimental_hooks:
        lines = _read_lines(cfg_path)
        lines = _set_feature_bool(lines, "codex_hooks", True)
        cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        cli = find_cli_binary()
        hpath = hooks_json_path()
        cmd, shell = _hook_command(cli)
        hooks_doc = {"hooks": {"UserPromptSubmit": [{"type": "command", "shell": shell, "command": cmd}]}}
        hpath.write_text(json.dumps(hooks_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        result["hooks_path"] = str(hpath)
        result["experimental"] = True

    return result


def remove() -> dict:
    result: dict = {}

    cfg_path = config_toml_path()
    if cfg_path.exists():
        lines = _read_lines(cfg_path)
        lines = _remove_table(lines, "mcp_servers.synthelion")
        if _get_feature_bool(lines, "codex_hooks"):
            lines = _set_feature_bool(lines, "codex_hooks", False)
        cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result["mcp_removed"] = True

    agents_path = agents_md_path()
    if agents_path.exists():
        text = agents_path.read_text(encoding="utf-8")
        if AGENTS_MARKER_START in text:
            text = re.sub(
                r"\n?" + re.escape(AGENTS_MARKER_START) + r".*?" + re.escape(AGENTS_MARKER_END) + r"\n?",
                "\n", text, flags=re.DOTALL,
            )
            agents_path.write_text(text.strip() + "\n" if text.strip() else "", encoding="utf-8")
            result["agents_md_removed"] = True

    hpath = hooks_json_path()
    if hpath.exists():
        hpath.unlink()
        result["hooks_removed"] = True

    return result
