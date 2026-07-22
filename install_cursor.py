#!/usr/bin/env python3
# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
#
# Universal Synthelion installer for Cursor
# Works on Windows, Linux, macOS — requires Python 3.11+
#
# Usage:
#   python install_cursor.py
#   python install_cursor.py --local
#   python install_cursor.py --uninstall
"""Install Synthelion MCP + privacy Rule (+ best-effort observability hook) for Cursor.

Cursor has no enforced pre-model hook today: `beforeSubmitPrompt` in
~/.cursor/hooks.json exists but is documented as informational-only in the
current beta — Cursor does not act on any JSON the hook script returns, so it
cannot block or rewrite the prompt. Real enforcement in Cursor therefore comes
from the MCP tools themselves (`synthelion_analyze_privacy`, `compress`) plus a
Rule that instructs the model to call them — the model has to choose to
comply, same as Claude Code's tool-use model without hooks. This installer
still wires the hook (for ledger visibility into Cursor usage), but never
claims it blocks anything.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
PACKAGE = "synthelion"
MIN_PYTHON = (3, 11)
RULE_FILENAME = "synthelion-privacy.mdc"
# ──────────────────────────────────────────────────────────────────────────────

IS_WINDOWS = platform.system() == "Windows"

_RULE_CONTENT = """---
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


# ── colours ──────────────────────────────────────────────────────────────────

def _c(code: str, text: str) -> str:
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
    if b.exists():
        return str(b)
    return "synthelion"


def cursor_installed() -> bool:
    return shutil.which("cursor") is not None


# ── config paths ─────────────────────────────────────────────────────────────

def mcp_json_path() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def rules_dir(local: bool) -> Path:
    return (Path(".cursor") / "rules") if local else (Path.home() / ".cursor" / "rules")


def hooks_json_path(local: bool) -> Path:
    return (Path(".cursor") / "hooks.json") if local else (Path.home() / ".cursor" / "hooks.json")


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            warn(f"{path} has invalid JSON — will back up and recreate.")
            path.rename(path.with_suffix(".json.bak"))
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ── hook command (observability-only — Cursor ignores hook output today) ─────

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


def build_hook_entry(cli_binary: str) -> dict:
    if IS_WINDOWS:
        return {"type": "command", "shell": "powershell", "command": _hook_command_windows(cli_binary)}
    return {"type": "command", "shell": "bash", "command": _hook_command_unix(cli_binary)}


# ── install flow ─────────────────────────────────────────────────────────────

def configure_cursor(binary: str | None, local: bool, add_rule: bool, add_hook: bool) -> None:
    h2("Configuring Cursor MCP…")
    mcp_path = mcp_json_path()
    info(f"MCP config: {mcp_path}")
    cfg = _load_json(mcp_path)
    cfg.setdefault("mcpServers", {})["synthelion"] = mcp_command_config(binary)
    _save_json(mcp_path, cfg)
    ok(f"MCP server configured -> {mcp_path}")

    if add_rule:
        rdir = rules_dir(local)
        rdir.mkdir(parents=True, exist_ok=True)
        rule_path = rdir / RULE_FILENAME
        rule_path.write_text(_RULE_CONTENT, encoding="utf-8")
        ok(f"Privacy rule installed -> {rule_path}")
    else:
        info("Skipping privacy rule (--no-rule)")

    if add_hook:
        cli = find_cli_binary()
        hpath = hooks_json_path(local)
        hcfg = _load_json(hpath)
        hooks = hcfg.setdefault("hooks", {})
        existing = [h for h in hooks.get("beforeSubmitPrompt", []) if "synthelion" not in h.get("command", "").lower()]
        existing.append(build_hook_entry(cli))
        hooks["beforeSubmitPrompt"] = existing
        _save_json(hpath, hcfg)
        warn(f"beforeSubmitPrompt hook wired -> {hpath} (OBSERVABILITY ONLY: Cursor does not act on hook output today — this only logs usage to Synthelion's savings ledger, it cannot block or rewrite the prompt)")
    else:
        info("Skipping hook (--no-hook)")


def remove_cursor_config(local: bool) -> None:
    h2("Removing Synthelion from Cursor…")
    mcp_path = mcp_json_path()
    if mcp_path.exists():
        cfg = _load_json(mcp_path)
        if "synthelion" in cfg.get("mcpServers", {}):
            del cfg["mcpServers"]["synthelion"]
            _save_json(mcp_path, cfg)
            ok("MCP server removed")

    rule_path = rules_dir(local) / RULE_FILENAME
    if rule_path.exists():
        rule_path.unlink()
        ok(f"Privacy rule removed -> {rule_path}")

    hpath = hooks_json_path(local)
    if hpath.exists():
        hcfg = _load_json(hpath)
        hooks = hcfg.get("hooks", {})
        before = len(hooks.get("beforeSubmitPrompt", []))
        hooks["beforeSubmitPrompt"] = [h for h in hooks.get("beforeSubmitPrompt", []) if "synthelion" not in h.get("command", "").lower()]
        if before != len(hooks["beforeSubmitPrompt"]):
            ok("Hook removed")
        if not hooks["beforeSubmitPrompt"]:
            del hooks["beforeSubmitPrompt"]
        if not hooks:
            hcfg.pop("hooks", None)
        _save_json(hpath, hcfg)


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
    parser = argparse.ArgumentParser(description="Install Synthelion MCP + privacy Rule for Cursor", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--uninstall", action="store_true", help="Remove Synthelion from Cursor config and pip")
    parser.add_argument("--local", action="store_true", help="Install the Rule/hook into the current project's .cursor/ instead of the global ~/.cursor/ (MCP is always global — Cursor has no project-local MCP config)")
    parser.add_argument("--no-rule", action="store_true", help="Skip installing the mandatory privacy Rule")
    parser.add_argument("--no-hook", action="store_true", help="Skip wiring the (observability-only) beforeSubmitPrompt hook")
    parser.add_argument("--upgrade", action="store_true", help="pip install --upgrade (update to latest version)")
    parser.add_argument("--no-pip", action="store_true", help="Skip pip install (assume Synthelion is already installed)")
    parser.add_argument("--chromadb", action="store_true", help="Also install the optional ChromaDB extra")
    args = parser.parse_args()

    h1("Synthelion Installer for Cursor")
    print(f"  Platform : {platform.system()} {platform.machine()}")
    print(f"  Python   : {sys.version.split()[0]}")

    if args.uninstall:
        remove_cursor_config(args.local)
        if not args.no_pip:
            uninstall_package()
        h1("Uninstall complete.")
        return

    check_python()

    if not cursor_installed():
        warn("`cursor` not found in PATH — continuing anyway (config is written either way).")

    if not args.no_pip:
        install_package(upgrade=args.upgrade, chromadb=args.chromadb)

    binary = find_mcp_binary()
    if binary:
        info(f"synthelion-mcp found at: {binary}")
    else:
        warn("synthelion-mcp not in PATH — will use Python module form")

    smoke_test(binary)
    configure_cursor(binary, local=args.local, add_rule=not args.no_rule, add_hook=not args.no_hook)

    h1("Installation complete!")
    print()
    print("  Next steps:")
    print("  1. Restart Cursor to pick up the new MCP server and Rule.")
    print("  2. Ask the agent to do something with sensitive-looking text — it should")
    print("     call synthelion_analyze_privacy before answering.")
    print()
    print("  IMPORTANT — capability limits (Cursor's, not Synthelion's):")
    print("  - Enforcement depends on the model choosing to call the MCP tool (no")
    print("    hard block exists in Cursor yet, unlike Claude Code's hook).")
    print("  - The beforeSubmitPrompt hook only logs to Synthelion's ledger; Cursor's")
    print("    beta does not act on hook output, so it cannot block/rewrite prompts.")
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
