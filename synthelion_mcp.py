#!/usr/bin/env python3
# Synthelion MCP Server — standalone launcher
# Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
#
# This file lets you run the MCP server without installing the package:
#   python synthelion_mcp.py
#
# For the standard (installed) usage see docs/claude-code-plugin.md
"""Synthelion MCP server — standalone entry point.

Exposes five tools to Claude Code and any MCP-compatible agent:
  compress          — reduce token count (Light / Semantic / Aggressive)
  detect_language   — identify language, returns ISO 639-3 code
  route_content     — auto-detect type and apply best compressor
  summarize         — extractive summarization (TF-IDF or TextRank)
  compress_batch    — compress a list of texts in one call

For public plugin setup instructions see:
  https://github.com/francescopaolopassaro/synthelion/blob/main/docs/claude-code-plugin.md
"""
from __future__ import annotations

import os
import sys

# When run as a script, add the package root to sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

if __name__ == "__main__":
    try:
        from synthelion.plugins.mcp_server import main
    except ImportError as e:
        print(
            f"[synthelion-mcp] Import error: {e}\n"
            "Run: pip install synthelion",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)
    main()
