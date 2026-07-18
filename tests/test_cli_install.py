# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for `synthelion install --agent ...` (MCP config registration).

Home directory is redirected to tmp_path so these never touch the real
~/.claude, ~/.gemini, ~/.config/opencode, ~/.cursor, or ~/.codeium configs.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def _run(args: list[str]) -> None:
    from synthelion.cli import main
    with patch("sys.argv", ["synthelion"] + args):
        main()


class TestInstallAgents:
    @pytest.fixture(autouse=True)
    def _isolated_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        return tmp_path

    def test_claude_registers_mcp_server(self, tmp_path):
        _run(["install", "--agent", "claude"])
        cfg = json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))
        assert "synthelion" in cfg["mcpServers"]

    def test_gemini_registers_mcp_server(self, tmp_path):
        _run(["install", "--agent", "gemini"])
        cfg = json.loads((tmp_path / ".gemini" / "settings.json").read_text(encoding="utf-8"))
        assert "synthelion" in cfg["mcpServers"]

    def test_opencode_registers_local_command(self, tmp_path):
        _run(["install", "--agent", "opencode"])
        cfg = json.loads((tmp_path / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8"))
        entry = cfg["mcp"]["synthelion"]
        assert entry["type"] == "local"
        assert isinstance(entry["command"], list)

    def test_cursor_registers_mcp_server(self, tmp_path):
        _run(["install", "--agent", "cursor"])
        cfg = json.loads((tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
        assert "synthelion" in cfg["mcpServers"]

    def test_windsurf_registers_mcp_server(self, tmp_path):
        _run(["install", "--agent", "windsurf"])
        cfg = json.loads((tmp_path / ".codeium" / "windsurf" / "mcp_config.json").read_text(encoding="utf-8"))
        assert "synthelion" in cfg["mcpServers"]

    def test_default_agent_is_claude(self, tmp_path):
        _run(["install"])
        cfg = json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))
        assert "synthelion" in cfg["mcpServers"]

    def test_install_preserves_existing_entries(self, tmp_path):
        cursor_dir = tmp_path / ".cursor"
        cursor_dir.mkdir(parents=True)
        (cursor_dir / "mcp.json").write_text(
            json.dumps({"mcpServers": {"other-tool": {"command": "other"}}}), encoding="utf-8"
        )
        _run(["install", "--agent", "cursor"])
        cfg = json.loads((cursor_dir / "mcp.json").read_text(encoding="utf-8"))
        assert "other-tool" in cfg["mcpServers"]
        assert "synthelion" in cfg["mcpServers"]

    def test_install_repairs_invalid_json(self, tmp_path):
        cursor_dir = tmp_path / ".cursor"
        cursor_dir.mkdir(parents=True)
        (cursor_dir / "mcp.json").write_text("NOT VALID JSON {{{", encoding="utf-8")
        _run(["install", "--agent", "cursor"])
        cfg = json.loads((cursor_dir / "mcp.json").read_text(encoding="utf-8"))
        assert "synthelion" in cfg["mcpServers"]
