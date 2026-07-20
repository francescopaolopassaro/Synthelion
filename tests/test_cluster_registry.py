# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for the master-side cluster node registry."""
from __future__ import annotations

import time

from synthelion.analytics.cluster_registry import ClusterRegistry


class TestClusterRegistry:
    def test_register_adds_node(self, tmp_path):
        reg = ClusterRegistry(tmp_path)
        reg.register("node-1", "http://node-1:8787")
        nodes = reg.list_nodes()
        assert len(nodes) == 1
        assert nodes[0]["node_id"] == "node-1"
        assert nodes[0]["url"] == "http://node-1:8787"
        assert "joined_at" in nodes[0]
        assert "last_seen" in nodes[0]

    def test_register_twice_keeps_original_joined_at(self, tmp_path):
        reg = ClusterRegistry(tmp_path)
        reg.register("node-1", "http://node-1:8787")
        first = reg.list_nodes()[0]["joined_at"]
        time.sleep(0.01)
        reg.register("node-1", "http://node-1:9999")
        second = reg.list_nodes()[0]
        assert second["joined_at"] == first
        assert second["url"] == "http://node-1:9999"

    def test_heartbeat_updates_last_seen(self, tmp_path):
        reg = ClusterRegistry(tmp_path)
        reg.register("node-1", "http://node-1:8787")
        before = reg.list_nodes()[0]["last_seen"]
        time.sleep(0.01)
        ok = reg.heartbeat("node-1", stats={"total_calls": 5})
        assert ok is True
        after = reg.list_nodes()[0]
        assert after["last_seen"] > before
        assert after["stats"] == {"total_calls": 5}

    def test_heartbeat_unknown_node_returns_false(self, tmp_path):
        reg = ClusterRegistry(tmp_path)
        assert reg.heartbeat("ghost") is False

    def test_list_nodes_sorted_by_id(self, tmp_path):
        reg = ClusterRegistry(tmp_path)
        reg.register("node-b", "http://b:8787")
        reg.register("node-a", "http://a:8787")
        nodes = reg.list_nodes()
        assert [n["node_id"] for n in nodes] == ["node-a", "node-b"]

    def test_remove_deletes_node(self, tmp_path):
        reg = ClusterRegistry(tmp_path)
        reg.register("node-1", "http://node-1:8787")
        assert reg.remove("node-1") is True
        assert reg.list_nodes() == []

    def test_remove_unknown_node_returns_false(self, tmp_path):
        reg = ClusterRegistry(tmp_path)
        assert reg.remove("ghost") is False

    def test_persists_across_instances(self, tmp_path):
        ClusterRegistry(tmp_path).register("node-1", "http://node-1:8787")
        reg2 = ClusterRegistry(tmp_path)
        assert len(reg2.list_nodes()) == 1
