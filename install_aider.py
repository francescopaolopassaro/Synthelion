#!/usr/bin/env python3
# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
#
# Universal Synthelion installer for Aider
# Works on Windows, Linux, macOS — requires Python 3.11+
#
# Usage:
#   python install_aider.py
#   python install_aider.py --local
#   python install_aider.py --uninstall
"""Install a Synthelion privacy/compression conventions file for Aider.

Aider has no MCP client and no pre-send hook of any kind — the LLM inside an
Aider session cannot call an external tool, and there is no script that runs
before a message reaches the model. There is therefore no way to *enforce*
PII masking or compression for Aider today, unlike Cursor/Codex CLI (which at
least expose MCP tools the model can choose to call) or Claude Code (which has
a real blocking hook).

The only real lever is Aider's `read:` conventions mechanism (a file
auto-loaded into every session, same as CLAUDE.md/AGENTS.md). This installer
writes an *advisory* instruction: it asks the model to flag likely-sensitive
user input and suggest running `synthelion compress`/`synthelion doctor`
manually in the terminal. This is weaker than the other integrations — no
masking or blocking actually happens automatically — and the installer says
so plainly rather than overstating what it does.
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
PACKAGE = "synthelion"
MIN_PYTHON = (3, 11)
CONVENTIONS_FILENAME = "synthelion_conventions.md"
# ──────────────────────────────────────────────────────────────────────────────

IS_WINDOWS = platform.system() == "Windows"

_CONVENTIONS_CONTENT = """# Synthelion Privacy Advisory (for Aider)

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


def aider_installed() -> bool:
    return shutil.which("aider") is not None


# ── config paths ─────────────────────────────────────────────────────────────

def conventions_dir(local: bool) -> Path:
    return Path.cwd() if local else Path.home() / ".synthelion"


def conf_yml_path(local: bool) -> Path:
    return Path(".aider.conf.yml") if local else Path.home() / ".aider.conf.yml"


def _load_yaml_lines(path: Path) -> list[str]:
    if path.exists():
        return path.read_text(encoding="utf-8").splitlines()
    return []


# ── read: key merge (minimal YAML editing — no external yaml dependency) ────
#
# We only ever touch the `read:` key. Aider's YAML supports either a scalar
# (`read: file.md`) or a block/flow list. To avoid pulling in a YAML parser
# dependency for one key, and to avoid corrupting whatever formatting the user
# already has for every *other* key, we parse just the `read:` block with plain
# line scanning and leave the rest of the file untouched byte-for-byte.

def _find_read_entries(lines: list[str]) -> tuple[list[str], int, int]:
    """Return (entries, start_line, end_line_exclusive). end==start if absent."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "read:" or stripped.startswith("read:"):
            rest = stripped[len("read:"):].strip()
            if rest.startswith("[") and rest.endswith("]"):
                # flow list: read: [a.md, b.md]
                items = [x.strip().strip('"\'') for x in rest[1:-1].split(",") if x.strip()]
                return items, i, i + 1
            if rest and rest not in ("", "|", ">"):
                # scalar: read: a.md
                return [rest.strip('"\'')], i, i + 1
            # block list on following lines: read:\n  - a.md\n  - b.md
            items = []
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("- "):
                items.append(lines[j].strip()[2:].strip('"\''))
                j += 1
            return items, i, j
    return [], -1, -1


def add_read_entry(path: Path, entry: str) -> None:
    lines = _load_yaml_lines(path)
    items, start, end = _find_read_entries(lines)
    if entry in items:
        return  # already present
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
    lines = _load_yaml_lines(path)
    items, start, end = _find_read_entries(lines)
    if entry not in items:
        return False
    items = [it for it in items if it != entry]
    if items:
        block = ["read:"] + [f"  - {it}" for it in items]
    else:
        block = []
    lines[start:end] = block
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


# ── install flow ─────────────────────────────────────────────────────────────

def configure_aider(local: bool) -> None:
    h2("Configuring Aider…")
    cdir = conventions_dir(local)
    cdir.mkdir(parents=True, exist_ok=True)
    conv_path = cdir / CONVENTIONS_FILENAME
    conv_path.write_text(_CONVENTIONS_CONTENT, encoding="utf-8")
    ok(f"Conventions file written -> {conv_path}")

    conf_path = conf_yml_path(local)
    entry = str(conv_path).replace("\\", "/")
    add_read_entry(conf_path, entry)
    ok(f"Registered in {conf_path} (read: {entry})")


def remove_aider_config(local: bool) -> None:
    h2("Removing Synthelion from Aider…")
    conf_path = conf_yml_path(local)
    cdir = conventions_dir(local)
    conv_path = cdir / CONVENTIONS_FILENAME
    entry = str(conv_path).replace("\\", "/")
    if remove_read_entry(conf_path, entry):
        ok(f"Removed read: entry from {conf_path}")
    else:
        warn(f"No matching read: entry found in {conf_path}")
    if conv_path.exists():
        conv_path.unlink()
        ok(f"Conventions file removed -> {conv_path}")


# ── smoke test ───────────────────────────────────────────────────────────────

def smoke_test() -> None:
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


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Install Synthelion conventions for Aider", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--uninstall", action="store_true", help="Remove Synthelion from Aider config and pip")
    parser.add_argument("--local", action="store_true", help="Install into the current project's .aider.conf.yml instead of the global ~/.aider.conf.yml")
    parser.add_argument("--upgrade", action="store_true", help="pip install --upgrade (update to latest version)")
    parser.add_argument("--no-pip", action="store_true", help="Skip pip install (assume Synthelion is already installed)")
    parser.add_argument("--chromadb", action="store_true", help="Also install the optional ChromaDB extra")
    args = parser.parse_args()

    h1("Synthelion Installer for Aider")
    print(f"  Platform : {platform.system()} {platform.machine()}")
    print(f"  Python   : {sys.version.split()[0]}")

    if args.uninstall:
        remove_aider_config(args.local)
        if not args.no_pip:
            uninstall_package()
        h1("Uninstall complete.")
        return

    check_python()

    if not aider_installed():
        warn("`aider` not found in PATH — continuing anyway (config is written either way).")

    if not args.no_pip:
        install_package(upgrade=args.upgrade, chromadb=args.chromadb)

    smoke_test()
    configure_aider(local=args.local)

    h1("Installation complete!")
    print()
    print("  IMPORTANT — this is advisory only, not enforcement:")
    print("  Aider has no MCP client and no pre-send hook, so there is no way")
    print("  to actually mask PII or block a message automatically. The")
    print("  installed conventions file only asks the model to warn the user")
    print("  and suggest running `synthelion compress` manually in a terminal.")
    print("  For real enforcement, use Claude Code, Cursor, or Codex CLI.")
    print()
    print("  Next steps:")
    print("  1. Start (or restart) an Aider session in this project/home dir.")
    print("  2. Manually check text before pasting it: synthelion compress -t \"...\"")
    print()
    print("  Savings tracker:")
    print("    synthelion status         # show all-time token savings")
    print()
    print("  To update Synthelion later:")
    print(f"    python {Path(__file__).name} --upgrade")
    print()
    print("  To uninstall:")
    print(f"    python {Path(__file__).name} --uninstall")
    print()


if __name__ == "__main__":
    main()
