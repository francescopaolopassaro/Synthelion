#!/usr/bin/env python3
# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
#
# Universal Synthelion installer for OpenCode
# Works on Windows, Linux, macOS — requires Python 3.11+
#
# Usage:
#   python install_opencode.py
#   python install_opencode.py --local
#   python install_opencode.py --uninstall
"""Install Synthelion MCP + auto-compression plugin + privacy rules for OpenCode."""
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
RULES_FILENAME = "rules/privacy.md"
# ──────────────────────────────────────────────────────────────────────────────

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

_PLUGIN_CODE = r"""import { type Plugin } from "@opencode-ai/plugin"

const MIN_LEN = 10
const MIN_EFF = 15

async function syn($: any, subcmd: string, flags: Record<string, any> = {}): Promise<any> {
  const args: string[] = [subcmd, "--json"]
  for (const [k, v] of Object.entries(flags)) {
    if (v === undefined || v === null) continue
    const flag = k.length === 1 ? `-${k}` : `--${k.replace(/_/g, "-")}`
    args.push(flag)
    if (v !== true) args.push(typeof v === "string" ? v : JSON.stringify(v))
  }
  for (const bin of ["synthelion", "python -m synthelion.cli"]) {
    try {
      const out = await $`${bin} ${args}`.text()
      const parsed = JSON.parse(out.trim())
      if (parsed.error) continue
      return parsed
    } catch {}
  }
  return { error: "synthelion not available" }
}

export const SynthelionPlugin: Plugin = async (ctx) => {
  const { $ } = ctx

  return {
    "chat.message": async (_input, output) => {
      const textParts = output.parts.filter(
        (p): p is { type: "text"; text: string } =>
          "text" in p && typeof (p as any).text === "string",
      )
      if (textParts.length === 0) return
      const fullText = textParts.map((p) => p.text).join("\n").trim()
      if (fullText.length < MIN_LEN) return
      try {
        const r = await syn($, "compress", { text: fullText })
        if (r.error || !r.compressed_text || r.efficiency_pct <= MIN_EFF) return
        for (const p of textParts) p.text = r.compressed_text
        output.parts.push({
          type: "text",
          text: `\n\n[⚡ Synthelion: ${r.original_tokens}→${r.compressed_tokens} tok, ${r.efficiency_pct}% saved]`,
        })
      } catch {}
    },

    "experimental.chat.system.transform": async (_input, output) => {
      const text = output.system.join("\n")
      if (text.length < 50) return
      try {
        const r = await syn($, "shape_output", { system_prompt: text, level: "no_restatement" })
        if (r.system_prompt) output.system = [r.system_prompt]
      } catch {}
    },

    "experimental.chat.messages.transform": async (_input, output) => {
      const msgs = output.messages
      if (msgs.length === 0) return

      const last = msgs[msgs.length - 1]
      if (last.info.role === "user") {
        const text = last.parts
          .filter((p): p is { type: "text"; text: string } => "text" in p && typeof (p as any).text === "string")
          .map((p) => p.text)
          .join("\n")
          .trim()
        if (text.length >= MIN_LEN) {
          try {
            const r = await syn($, "compress", { text })
            if (!r.error && r.blocked) {
              last.parts = [{ type: "text", text: r.notice || "[Blocked by Synthelion: PII detected]" }]
              return
            }
            if (!r.error && r.privacy_masked && r.compressed_text) {
              for (const p of last.parts) {
                if ("text" in p && typeof (p as any).text === "string") (p as any).text = r.compressed_text
              }
            }
          } catch {}
        }
      }

      if (msgs.length < 6) return
      const keep = Math.max(2, Math.floor(msgs.length / 2))
      const old = msgs.slice(0, -keep)
      if (old.length === 0) return
      const oldText = old.map((m) => `${m.info.role}: ${m.parts.filter((p) => "text" in p).map((p: any) => p.text).join(" ")}`).join("\n")
      if (oldText.length < 100) return
      try {
        const r = await syn($, "compress", { text: oldText, level: "aggressive" })
        if (r.compressed_text && r.efficiency_pct > 20) {
          const tail = msgs.slice(-keep)
          output.messages = [{
            info: { role: "system" } as any,
            parts: [{ type: "text", text: `[Compressed conversation — ${r.original_tokens}→${r.compressed_tokens} tok, ${r.efficiency_pct}% saved]\n${r.compressed_text}` }],
          }, ...tail]
        }
      } catch {}
    },

    "experimental.session.compacting": async (_input, output) => {
      output.context.push("## Synthelion Plugin\nActive Synthelion MCP tools: compression, PII masking, summarization, and more.")
    },
  }
}
"""

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


# ── colours ──────────────────────────────────────────────────────────────────

def _c(code: str, text: str) -> str:
    if IS_WINDOWS and not os.environ.get("WT_SESSION"):
        return text          # plain CMD — skip ANSI
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
    """Return the best command string to run synthelion-mcp."""
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

    return None  # caller will use module form


def mcp_command_config(binary: str | None) -> dict:
    """Return the OpenCode `mcp.synthelion` entry — command is always an array."""
    if binary:
        return {"type": "local", "command": [binary], "enabled": True}
    return {
        "type": "local",
        "command": [sys.executable, "-m", "synthelion.plugins.mcp_server"],
        "enabled": True,
    }


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


def opencode_installed() -> bool:
    return shutil.which("opencode") is not None


# ── config paths ─────────────────────────────────────────────────────────────

def opencode_config_dir(local: bool) -> Path:
    if local:
        return Path.cwd()
    home = Path.home()
    d = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "opencode"
    d.mkdir(parents=True, exist_ok=True)
    return d


def opencode_json_path(local: bool) -> Path:
    d = opencode_config_dir(local)
    return d / "opencode.json" if local else d / "opencode.json"


def plugin_dir_path(local: bool) -> Path:
    if local:
        return Path(".opencode") / "plugins"
    return opencode_config_dir(local) / "plugins"


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            warn(f"{path} has invalid JSON — will back up and recreate.")
            path.rename(path.with_suffix(".json.bak"))
    return {"$schema": "https://opencode.ai/config.json"}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ── install flow ─────────────────────────────────────────────────────────────

def configure_opencode(binary: str | None, local: bool, add_plugin: bool, add_rules: bool) -> None:
    h2("Configuring OpenCode…")
    config_path = opencode_json_path(local)
    info(f"Config file: {config_path}")

    cfg = _load_json(config_path)

    # MCP server
    cfg.setdefault("mcp", {})["synthelion"] = mcp_command_config(binary)
    ok(f"MCP server configured: {cfg['mcp']['synthelion']}")

    # Privacy rules instruction
    if add_rules:
        rules_path = opencode_config_dir(local) / RULES_FILENAME
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        rules_path.write_text(_RULE_CONTENT, encoding="utf-8")
        entry = RULES_FILENAME.replace("\\", "/")
        instructions = cfg.get("instructions", [])
        if entry not in instructions:
            instructions.append(entry)
        cfg["instructions"] = instructions
        ok(f"Privacy rules written -> {rules_path}")
    else:
        info("Skipping privacy rules (--no-rules)")

    _save_json(config_path, cfg)
    ok(f"Saved -> {config_path}")

    # Plugin file (auto-compression + PII hook on every chat message)
    if add_plugin:
        plugin_dir = plugin_dir_path(local)
        plugin_dir.mkdir(parents=True, exist_ok=True)
        plugin_file = plugin_dir / "synthelion.ts"
        plugin_file.write_text(_PLUGIN_CODE.strip(), encoding="utf-8")
        ok(f"Plugin installed -> {plugin_file}")
    else:
        info("Skipping plugin (--no-plugin)")


def remove_opencode_config(local: bool) -> None:
    h2("Removing Synthelion from OpenCode…")
    config_path = opencode_json_path(local)
    if not config_path.exists():
        warn(f"{config_path} not found — nothing to remove.")
        return
    cfg = _load_json(config_path)

    mcp = cfg.get("mcp", {})
    if "synthelion" in mcp:
        del mcp["synthelion"]
        ok("MCP server removed")

    entry = RULES_FILENAME.replace("\\", "/")
    instructions = cfg.get("instructions", [])
    if entry in instructions:
        instructions.remove(entry)
        cfg["instructions"] = instructions
        ok("Privacy rules instruction removed")

    _save_json(config_path, cfg)
    ok(f"Saved -> {config_path}")

    plugin_file = plugin_dir_path(local) / "synthelion.ts"
    if plugin_file.exists():
        plugin_file.unlink()
        ok(f"Plugin removed -> {plugin_file}")


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
        r = svc.compress(
            "I would like to know if it is possible to receive information.",
            CompressionLevel.SEMANTIC,
        )
        assert r.compressed_text, "empty output"
        ok(f"compress OK — {r.original_tokens}->{r.compressed_tokens} tokens ({r.efficiency_pct:.0f}% saved)")
    except Exception as e:
        err(f"compress failed: {e}")
        sys.exit(1)

    cli_bin = binary or shutil.which("synthelion-mcp")
    if cli_bin:
        result = subprocess.run(
            [cli_bin, "--help"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 or "mcp" in result.stdout.lower() or "mcp" in result.stderr.lower():
            ok(f"synthelion-mcp reachable at {cli_bin}")
        else:
            warn(f"synthelion-mcp returned code {result.returncode} — may still work")
    else:
        warn("synthelion-mcp not found in PATH — using Python module form instead")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install Synthelion MCP + plugin for OpenCode",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--uninstall", action="store_true", help="Remove Synthelion from OpenCode config and pip")
    parser.add_argument("--local", action="store_true", help="Install in project-local .opencode/opencode.json instead of the global config")
    parser.add_argument("--no-plugin", action="store_true", help="Skip the auto-compression/PII chat plugin")
    parser.add_argument("--no-rules", action="store_true", help="Skip the privacy.md instruction rule")
    parser.add_argument("--upgrade", action="store_true", help="pip install --upgrade (update to latest version)")
    parser.add_argument("--no-pip", action="store_true", help="Skip pip install (assume Synthelion is already installed)")
    parser.add_argument("--chromadb", action="store_true", help="Also install the optional ChromaDB extra")
    args = parser.parse_args()

    h1("Synthelion Installer for OpenCode")
    print(f"  Platform : {platform.system()} {platform.machine()}")
    print(f"  Python   : {sys.version.split()[0]}")

    if args.uninstall:
        remove_opencode_config(args.local)
        if not args.no_pip:
            uninstall_package()
        h1("Uninstall complete.")
        return

    check_python()

    if not opencode_installed():
        warn("`opencode` not found in PATH — continuing anyway (config is written either way).")

    if not args.no_pip:
        install_package(upgrade=args.upgrade, chromadb=args.chromadb)

    binary = find_mcp_binary()
    if binary:
        info(f"synthelion-mcp found at: {binary}")
    else:
        warn("synthelion-mcp not in PATH — will use Python module form")

    smoke_test(binary)
    configure_opencode(binary, local=args.local, add_plugin=not args.no_plugin, add_rules=not args.no_rules)

    h1("Installation complete!")
    print()
    print("  Next steps:")
    print("  1. Restart OpenCode (or run `opencode mcp list`) to activate MCP tools.")
    print("  2. The plugin auto-compresses every chat message and masks PII.")
    print("  3. Run `opencode doctor` to verify everything loaded.")
    print()
    print("  Savings tracker:")
    print("    synthelion status         # show all-time token savings")
    print("    synthelion gain --days 7  # last 7 days")
    print("    synthelion bench          # benchmark on sample corpus")
    print()
    print("  To update Synthelion later:")
    print(f"    python {Path(__file__).name} --upgrade")
    print()
    print("  To uninstall:")
    print(f"    python {Path(__file__).name} --uninstall")
    print()


if __name__ == "__main__":
    main()
