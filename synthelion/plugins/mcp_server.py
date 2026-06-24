# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""MCP server exposing Synthelion compression tools for Claude Code, OpenCode, and other MCP clients.

Requires: pip install "synthelion[mcp]"

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

from synthelion.plugins.openai_tools import execute_tool, get_tool_definitions, get_tool_list


def get_tool_list() -> list[str]:  # noqa: F811
    """Return names of all exposed MCP tools."""
    from synthelion.plugins.openai_tools import get_tool_list as _gtl
    return _gtl()


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

    app = Server("synthelion")
    _tool_defs = get_tool_definitions()

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        tools = []
        for td in _tool_defs:
            fn = td["function"]
            tools.append(types.Tool(
                name=fn["name"],
                description=fn["description"],
                inputSchema=fn["parameters"],
            ))
        return tools

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        try:
            result = execute_tool(name, arguments)
            text = _json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as exc:
            text = _json.dumps({"error": str(exc)})
        return [types.TextContent(type="text", text=text)]

    async def _serve() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(_serve())


if __name__ == "__main__":
    main()
