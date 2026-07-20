# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for `synthelion cluster init/join/status/leave`.

Home directory is redirected to tmp_path so these never touch the real
~/.synthelion/config.json, and the cluster registry singleton is reset per
test so it can't leak state (or a wrong Path.home()) across test functions —
see the equivalent comment in tests/test_dashboard_http.py's fixture.
"""
from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest


def _run(args: list[str]) -> str:
    from synthelion.cli import main
    with patch("sys.argv", ["synthelion"] + args):
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            with patch("sys.stderr", new_callable=StringIO) as mock_err:
                try:
                    main()
                except SystemExit:
                    pass
                return mock_out.getvalue() + mock_err.getvalue()


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    from synthelion.analytics import cluster_registry as cluster_registry_module
    monkeypatch.setattr(cluster_registry_module, "_registry", None)
    return tmp_path


class TestClusterInit:
    def test_init_becomes_master(self, tmp_path):
        out = _run(["cluster", "init"])
        assert "master" in out.lower()
        cfg = json.loads((tmp_path / ".synthelion" / "config.json").read_text(encoding="utf-8"))
        assert cfg["cluster"]["role"] == "master"
        assert cfg["cluster"]["node_id"]
        assert cfg["cluster"]["node_token"]

    def test_init_prints_join_command_with_token(self, tmp_path):
        out = _run(["cluster", "init"])
        cfg = json.loads((tmp_path / ".synthelion" / "config.json").read_text(encoding="utf-8"))
        assert cfg["cluster"]["node_token"] in out

    def test_init_twice_keeps_same_node_id_and_token(self, tmp_path):
        _run(["cluster", "init"])
        cfg1 = json.loads((tmp_path / ".synthelion" / "config.json").read_text(encoding="utf-8"))
        _run(["cluster", "init"])
        cfg2 = json.loads((tmp_path / ".synthelion" / "config.json").read_text(encoding="utf-8"))
        assert cfg1["cluster"]["node_id"] == cfg2["cluster"]["node_id"]
        assert cfg1["cluster"]["node_token"] == cfg2["cluster"]["node_token"]


class TestClusterStatus:
    def test_status_standalone_by_default(self):
        out = _run(["cluster", "status"])
        assert "standalone" in out.lower()

    def test_status_master_with_no_nodes(self):
        _run(["cluster", "init"])
        out = _run(["cluster", "status"])
        assert "master" in out.lower()
        assert "no nodes" in out.lower()

    def test_status_master_lists_joined_nodes(self):
        _run(["cluster", "init"])
        from synthelion.analytics.cluster_registry import get_cluster_registry
        get_cluster_registry().register("node-1", "http://node-1:8787")
        out = _run(["cluster", "status"])
        assert "node-1" in out

    def test_status_slave_shows_master_url(self, tmp_path):
        from synthelion.config import load_config, save_config
        cfg = load_config()
        cfg["cluster"]["role"] = "slave"
        cfg["cluster"]["node_id"] = "node-1"
        cfg["cluster"]["master_url"] = "http://master:8787"
        save_config(cfg)
        out = _run(["cluster", "status"])
        assert "slave" in out.lower()
        assert "http://master:8787" in out


class TestClusterJoin:
    def test_join_requires_token(self, tmp_path):
        with patch("builtins.input", return_value=""):
            with patch("getpass.getpass", return_value=""):
                out = _run(["cluster", "join", "http://master:8787"])
        assert "ERROR" in out or "token is required" in out.lower()

    def test_join_no_master_url_stays_standalone(self, tmp_path):
        with patch("builtins.input", return_value=""):
            out = _run(["cluster", "join"])
        assert "standalone" in out.lower()
        cfg = json.loads((tmp_path / ".synthelion" / "config.json").read_text(encoding="utf-8")) \
            if (tmp_path / ".synthelion" / "config.json").exists() else None
        assert cfg is None or cfg["cluster"]["role"] == "standalone"

    def test_join_success_updates_config(self, tmp_path):
        fake_result = {
            "config": {"compression": {"default_level": "aggressive"}, "wiki": {"default_depth": 3}},
            "master_node_id": "remote-master",
        }
        with patch("synthelion.cluster.join_master", return_value=fake_result):
            out = _run(["cluster", "join", "http://master:8787", "--token", "tok", "--node-id", "node-9"])
        assert "joined" in out.lower()
        cfg = json.loads((tmp_path / ".synthelion" / "config.json").read_text(encoding="utf-8"))
        assert cfg["cluster"]["role"] == "slave"
        assert cfg["cluster"]["node_id"] == "node-9"
        assert cfg["cluster"]["master_url"] == "http://master:8787"
        assert cfg["compression"]["default_level"] == "aggressive"
        assert cfg["wiki"]["default_depth"] == 3

    def test_join_failure_prints_error(self, tmp_path):
        from synthelion.cluster import ClusterJoinError
        with patch("synthelion.cluster.join_master", side_effect=ClusterJoinError("unreachable")):
            out = _run(["cluster", "join", "http://master:8787", "--token", "tok"])
        assert "ERROR" in out or "unreachable" in out


class TestClusterLeave:
    def test_leave_returns_to_standalone(self, tmp_path):
        _run(["cluster", "init"])
        _run(["cluster", "leave"])
        cfg = json.loads((tmp_path / ".synthelion" / "config.json").read_text(encoding="utf-8"))
        assert cfg["cluster"]["role"] == "standalone"
