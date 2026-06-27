# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""MCP server exposing Synthelion compression tools for Claude Code, OpenCode, and other MCP clients.

mcp is included as a core dependency — no extra install step needed.

Run as standalone server:
    synthelion-mcp
    # or
    python -m synthelion.plugins.mcp_server

Configure in Claude Code (.claude/settings.json):
    {
      "mcpServers": {
        "synthelion": { "command": "synthelion-mcp" }
      }
    }
"""
from __future__ import annotations

import asyncio
import json as _json
import subprocess
import sys
import threading
import urllib.request

from synthelion.plugins.openai_tools import execute_tool, get_tool_definitions, get_tool_list  # noqa: F401

# Tools that only read / compress — do not modify external state.
_READ_ONLY_TOOLS = frozenset({
    "compress", "detect_language", "route_content", "summarize", "compress_batch",
    "compress_for_context", "compress_conversation", "deduplicate",
    "compress_file",
    "session_recall", "synthelion_status",
})


# ── auto-update state ─────────────────────────────────────────────────────────

_update: dict = {"status": "idle", "new_version": None}  # idle | checking | updating | updated | failed


def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def _check_and_update() -> None:
    """Background thread: fetch latest version from PyPI and auto-install if newer."""
    _update["status"] = "checking"
    try:
        import synthelion as _syn
        current = _syn.__version__

        with urllib.request.urlopen(
            "https://pypi.org/pypi/synthelion/json", timeout=8
        ) as resp:
            info = _json.loads(resp.read())
        latest = info["info"]["version"]

        if _version_tuple(latest) > _version_tuple(current):
            _update["status"] = "updating"
            _update["new_version"] = latest
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "synthelion", "-q"],
                capture_output=True,
                timeout=120,
            )
            _update["status"] = "updated"
        else:
            _update["status"] = "up_to_date"
    except Exception:
        _update["status"] = "failed"


# ── server ────────────────────────────────────────────────────────────────────

def main() -> None:
    """Entry point for synthelion-mcp CLI command."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        import mcp.types as types
    except ImportError:
        print(
            "ERROR: MCP package not installed. Run: pip install 'synthelion[mcp]'",
            flush=True,
        )
        raise SystemExit(1)

    # Start version check in background — does not block server startup
    threading.Thread(target=_check_and_update, daemon=True).start()

    app = Server("synthelion")
    _tool_defs = get_tool_definitions()

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        tools = []
        for td in _tool_defs:
            fn = td["function"]
            annotation = None
            try:
                if fn["name"] in _READ_ONLY_TOOLS:
                    annotation = types.ToolAnnotations(readOnlyHint=True)
            except Exception:
                pass
            tools.append(types.Tool(
                name=fn["name"],
                description=fn["description"],
                inputSchema=fn["parameters"],
                annotations=annotation,
            ))
        return tools

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        results: list[types.TextContent] = []

        # Notify once when an update has been installed
        if _update["status"] == "updating":
            results.append(types.TextContent(
                type="text",
                text=(
                    f"⏳ Synthelion {_update['new_version']} trovato su PyPI — "
                    "installazione in corso in background. "
                    "Chiudi e riapri Claude Code al termine per attivare la nuova versione."
                ),
            ))
        elif _update["status"] == "updated":
            results.append(types.TextContent(
                type="text",
                text=(
                    f"✅ Synthelion aggiornato alla versione {_update['new_version']}. "
                    "Chiudi e riapri Claude Code per attivare la nuova versione."
                ),
            ))
            _update["status"] = "notified"  # show the message only once

        try:
            result = execute_tool(name, arguments)
            text = _json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as exc:
            text = _json.dumps({"error": str(exc)})
        results.append(types.TextContent(type="text", text=text))
        return results

    async def _serve() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(_serve())


if __name__ == "__main__":
    main()
