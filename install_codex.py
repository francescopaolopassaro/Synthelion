#!/usr/bin/env python3
# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
#
# Universal Synthelion installer for OpenAI Codex CLI
# Works on Windows, Linux, macOS — requires Python 3.11+
#
# Usage:
#   python install_codex.py
#   python install_codex.py --experimental-hooks
#   python install_codex.py --uninstall
"""Install Synthelion MCP + privacy instructions (+ optional experimental
hook) for OpenAI Codex CLI.

Codex CLI has a real, documented MCP client — `[mcp_servers.NAME]` in
~/.codex/config.toml — and reads ~/.codex/AGENTS.md automatically on every
session, both stable and confirmed in OpenAI's own docs. This installer wires
both by default.

Codex CLI also has an in-development hook engine (`[features].codex_hooks`,
~/.codex/hooks.json) modeled on Claude Code's UserPromptSubmit hook. As of
this writing it is explicitly marked "under development" upstream, disabled
by default, and third-party sources disagree about which events/return
values are actually honoured. Wiring a guessed schema by default risks a
silent no-op (or a startup warning) on whatever the *next* Codex release
changes — so this installer only attempts it behind an explicit
`--experimental-hooks` flag, off by default, and never as part of the normal
install path. --uninstall always removes it if present, regardless of how it
was enabled.
"""
from __future__ import annotations

import argparse
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    tomllib = None

# ──────────────────────────────────────────────────────────────────────────────
PACKAGE = "synthelion"
MIN_PYTHON = (3, 11)
AGENTS_MARKER_START = "<!-- synthelion:start -->"
AGENTS_MARKER_END = "<!-- synthelion:end -->"
# ──────────────────────────────────────────────────────────────────────────────

IS_WINDOWS = platform.system() == "Windows"

_AGENTS_BLOCK = f"""{AGENTS_MARKER_START}
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


# ── colours ──────────────────────────────────────────────────────────────────

def _c(code: str, text: str) -> str:
    import os
    if IS_WINDOWS and not os.environ.get("WT_SESSION"):
        return text
    return f"\033[{code}m{text}\033[0m"


def ok(msg: str) -> None:   print(_c("32", "  [OK] ") + msg)
def info(msg: str) -> None: print(_c("36", "   --> ") + msg)
def warn(msg: str) -> None: print(_c("33", "   !   ") + msg)
def err(msg: str) -> None:  print(_c("31", "  [X]  ") + msg)
def h1(msg: str) -> None:   print("\n" + _c("1;36", msg))
def h2(msg: str) -> None:   print("\n" + _c("1", msg))


# ── python check ─────────────────────────────────────────────────────────────

def check_python() -> None:
    h2("Checking Python version…")
    v = sys.version_info
    if v < MIN_PYTHON:
        err(f"Python {v.major}.{v.minor} found — Synthelion needs 3.11+.")
        err("Download from https://www.python.org/downloads/")
        sys.exit(1)
    ok(f"Python {v.major}.{v.minor}.{v.micro}")


# ── pip install ───────────────────────────────────────────────────────────────

def install_package(upgrade: bool = False, chromadb: bool = False) -> None:
    h2("Installing Synthelion…")
    pkg = "synthelion[chromadb]" if chromadb else PACKAGE
    cmd = [sys.executable, "-m", "pip", "install", pkg]
    if upgrade:
        cmd.append("--upgrade")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err("pip install failed:")
        print(result.stderr)
        sys.exit(1)
    ok(f"pip install {pkg} succeeded")


def uninstall_package() -> None:
    h2("Uninstalling Synthelion…")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "-y", PACKAGE],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        ok("Synthelion uninstalled")
    else:
        warn("Synthelion was not installed via pip (skipping)")


def codex_installed() -> bool:
    return shutil.which("codex") is not None


# ── find binaries ─────────────────────────────────────────────────────────────

def find_mcp_binary() -> str | None:
    if IS_WINDOWS:
        scripts = Path(sys.executable).parent / "Scripts"
        binary = scripts / "synthelion-mcp.exe"
    else:
        scripts = Path(sys.executable).parent
        binary = scripts / "synthelion-mcp"
    if binary.exists():
        return str(binary)
    found = shutil.which("synthelion-mcp")
    if found:
        return found
    return None


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
    if b.exists():
        return str(b)
    return "synthelion"


# ── config paths ─────────────────────────────────────────────────────────────

def codex_home() -> Path:
    import os
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))


def config_toml_path() -> Path:
    return codex_home() / "config.toml"


def agents_md_path() -> Path:
    return codex_home() / "AGENTS.md"


def hooks_json_path() -> Path:
    return codex_home() / "hooks.json"


# ── config.toml editing (line-based — no TOML-writer dependency) ────────────
#
# We only ever touch the `[mcp_servers.synthelion]` table (and, behind the
# experimental flag, `[features]` codex_hooks). Rewriting the whole file with
# a generic TOML library would risk reformatting/reordering everything else
# the user has in there — so, like the Aider installer's `read:` handling, we
# scan for our own block by exact table-header match and only ever replace
# that block, leaving every other line byte-for-byte untouched.

def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _find_table(lines: list[str], header: str) -> tuple[int, int]:
    """Return (start, end_exclusive) of a `[header]` table, or (-1, -1)."""
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
    result = lines[:start] + lines[end:]
    while result and result[-1] == "" and (not result or True) and len(result) > 1 and result[-1] == "" and result[-2] == "":
        result.pop()
    return result


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
        return lines + [f"[features]", f"{key} = {val_str}"]
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


def mcp_server_body(binary: str | None) -> list[str]:
    if binary:
        return [f"command = {_toml_str(binary)}", "args = []", "env = {}"]
    return [
        f"command = {_toml_str(sys.executable)}",
        'args = ["-m", "synthelion.plugins.mcp_server"]',
        "env = {}",
    ]


# ── install flow ─────────────────────────────────────────────────────────────

def configure_codex(binary: str | None, add_agents: bool, experimental_hooks: bool) -> None:
    h2("Configuring Codex CLI…")
    cfg_path = config_toml_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    lines = _read_lines(cfg_path)
    lines = _replace_table(lines, "mcp_servers.synthelion", mcp_server_body(binary))
    cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok(f"MCP server configured -> {cfg_path}")

    if add_agents:
        agents_path = agents_md_path()
        agents_path.parent.mkdir(parents=True, exist_ok=True)
        text = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
        if AGENTS_MARKER_START in text:
            text = re.sub(
                re.escape(AGENTS_MARKER_START) + r".*?" + re.escape(AGENTS_MARKER_END),
                _AGENTS_BLOCK.strip(), text, flags=re.DOTALL,
            )
        else:
            text = (text.rstrip() + "\n\n" if text.strip() else "") + _AGENTS_BLOCK
        agents_path.write_text(text.strip() + "\n", encoding="utf-8")
        ok(f"Privacy instructions written -> {agents_path}")
    else:
        info("Skipping AGENTS.md instructions (--no-agents)")

    if experimental_hooks:
        warn("Wiring EXPERIMENTAL hook support (schema not finalized upstream — may do nothing on your Codex version)")
        lines = _read_lines(cfg_path)
        lines = _set_feature_bool(lines, "codex_hooks", True)
        cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok(f"[features].codex_hooks = true set in {cfg_path}")

        cli = find_cli_binary()
        hpath = hooks_json_path()
        if IS_WINDOWS:
            cmd = (
                f"$j=[Console]::In.ReadToEnd()|ConvertFrom-Json;$p=$j.prompt;"
                f"if($p){{$r=($p| & \"{cli.replace(chr(92), chr(92)*2)}\" compress --json 2>$null)|ConvertFrom-Json;"
                f"if($r -and $r.blocked){{@{{decision='deny';reason=$r.notice}}|ConvertTo-Json -Compress}}}}"
            )
            shell = "powershell"
        else:
            cmd = (
                f"prompt=$(cat | python3 -c \"import sys,json; print(json.load(sys.stdin).get('prompt',''))\"); "
                f"if [ -n \"$prompt\" ]; then r=$(printf '%s' \"$prompt\" | \"{cli}\" compress --json 2>/dev/null); "
                f"blocked=$(printf '%s' \"$r\" | python3 -c \"import sys,json; print(json.load(sys.stdin).get('blocked', False))\" 2>/dev/null); "
                f"if [ \"$blocked\" = \"True\" ]; then printf '{{\"decision\":\"deny\"}}'; fi; fi"
            )
            shell = "bash"
        hooks_doc = {
            "hooks": {
                "UserPromptSubmit": [
                    {"type": "command", "shell": shell, "command": cmd},
                ],
            },
        }
        import json as _json
        hpath.write_text(_json.dumps(hooks_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        warn(f"Hook written -> {hpath} (best-effort: only 'deny' is confirmed honoured by any Codex build; masking/compression is NOT applied even if this works)")
    else:
        info("Experimental hooks not requested (pass --experimental-hooks to try them)")


def remove_codex_config() -> None:
    h2("Removing Synthelion from Codex CLI…")
    cfg_path = config_toml_path()
    if cfg_path.exists():
        lines = _read_lines(cfg_path)
        lines = _remove_table(lines, "mcp_servers.synthelion")
        lines = _set_feature_bool(lines, "codex_hooks", False) if _get_feature_bool(lines, "codex_hooks") else lines
        cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok(f"MCP server removed -> {cfg_path}")

    agents_path = agents_md_path()
    if agents_path.exists():
        text = agents_path.read_text(encoding="utf-8")
        if AGENTS_MARKER_START in text:
            text = re.sub(
                r"\n?" + re.escape(AGENTS_MARKER_START) + r".*?" + re.escape(AGENTS_MARKER_END) + r"\n?",
                "\n", text, flags=re.DOTALL,
            )
            agents_path.write_text(text.strip() + "\n" if text.strip() else "", encoding="utf-8")
            ok(f"Privacy instructions removed -> {agents_path}")

    hpath = hooks_json_path()
    if hpath.exists():
        hpath.unlink()
        ok(f"Hook config removed -> {hpath}")


# ── smoke test ───────────────────────────────────────────────────────────────

def smoke_test(binary: str | None) -> None:
    h2("Running smoke test…")
    try:
        import synthelion  # noqa: F401
        ok("import synthelion OK")
    except ImportError as e:
        err(f"import synthelion failed: {e}")
        sys.exit(1)
    try:
        from synthelion import CompressionService, CompressionLevel
        svc = CompressionService()
        r = svc.compress("I would like to know if it is possible to receive information.", CompressionLevel.SEMANTIC)
        assert r.compressed_text, "empty output"
        ok(f"compress OK — {r.original_tokens}->{r.compressed_tokens} tokens ({r.efficiency_pct:.0f}% saved)")
    except Exception as e:
        err(f"compress failed: {e}")
        sys.exit(1)
    cli_bin = binary or shutil.which("synthelion-mcp")
    if cli_bin:
        result = subprocess.run([cli_bin, "--help"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0 or "mcp" in result.stdout.lower() or "mcp" in result.stderr.lower():
            ok(f"synthelion-mcp reachable at {cli_bin}")
        else:
            warn(f"synthelion-mcp returned code {result.returncode} — may still work")
    else:
        warn("synthelion-mcp not found in PATH — using Python module form instead")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Install Synthelion MCP + AGENTS.md instructions for Codex CLI", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--uninstall", action="store_true", help="Remove Synthelion from Codex CLI config and pip")
    parser.add_argument("--no-agents", action="store_true", help="Skip the AGENTS.md privacy instructions")
    parser.add_argument("--experimental-hooks", action="store_true", help="Also enable [features].codex_hooks and write ~/.codex/hooks.json — UNSTABLE, off by default, may do nothing on your Codex version")
    parser.add_argument("--upgrade", action="store_true", help="pip install --upgrade (update to latest version)")
    parser.add_argument("--no-pip", action="store_true", help="Skip pip install (assume Synthelion is already installed)")
    parser.add_argument("--chromadb", action="store_true", help="Also install the optional ChromaDB extra")
    args = parser.parse_args()

    h1("Synthelion Installer for OpenAI Codex CLI")
    print(f"  Platform : {platform.system()} {platform.machine()}")
    print(f"  Python   : {sys.version.split()[0]}")

    if args.uninstall:
        remove_codex_config()
        if not args.no_pip:
            uninstall_package()
        h1("Uninstall complete.")
        return

    check_python()

    if not codex_installed():
        warn("`codex` not found in PATH — continuing anyway (config is written either way).")

    if not args.no_pip:
        install_package(upgrade=args.upgrade, chromadb=args.chromadb)

    binary = find_mcp_binary()
    if binary:
        info(f"synthelion-mcp found at: {binary}")
    else:
        warn("synthelion-mcp not in PATH — will use Python module form")

    smoke_test(binary)
    configure_codex(binary, add_agents=not args.no_agents, experimental_hooks=args.experimental_hooks)

    h1("Installation complete!")
    print()
    print("  Next steps:")
    print("  1. Restart Codex CLI (or run `codex mcp list`) to activate MCP tools.")
    print("  2. AGENTS.md now instructs the model to call synthelion_analyze_privacy")
    print("     before responding — enforcement still depends on the model complying,")
    print("     same as Cursor (no hard block exists yet outside Claude Code).")
    if args.experimental_hooks:
        print("  3. [EXPERIMENTAL] hooks.json was written — verify with `codex /hooks`")
        print("     inside a session; if it shows nothing or errors, your Codex build")
        print("     doesn't support this yet. Re-run with --uninstall to remove safely.")
    print()
    print("  Savings tracker:")
    print("    synthelion status         # show all-time token savings")
    print("    synthelion gain --days 7  # last 7 days")
    print()
    print("  To update Synthelion later:")
    print(f"    python {Path(__file__).name} --upgrade")
    print()
    print("  To uninstall:")
    print(f"    python {Path(__file__).name} --uninstall")
    print()


if __name__ == "__main__":
    main()
