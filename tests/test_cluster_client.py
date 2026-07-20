# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for synthelion.cluster: the node-to-node join/heartbeat client and
the docker-compose/k8s deploy-file templates."""
from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from synthelion.cluster import (
    ClusterJoinError, join_master, render_docker_compose, render_k8s_manifest, send_heartbeat,
)


class TestJoinMaster:
    def test_join_master_success(self):
        fake_response = MagicMock()
        fake_response.__enter__.return_value.read.return_value = json.dumps(
            {"config": {"compression": {"default_level": "aggressive"}}, "master_node_id": "master-1"}
        ).encode()
        with patch("urllib.request.urlopen", return_value=fake_response) as mock_urlopen:
            result = join_master("http://master:8787", "tok", "node-1", "http://node-1:8787")
        assert result["master_node_id"] == "master-1"
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://master:8787/api/cluster/join"
        assert req.get_header("Authorization") == "Bearer tok"

    def test_join_master_strips_trailing_slash(self):
        fake_response = MagicMock()
        fake_response.__enter__.return_value.read.return_value = b'{"master_node_id": "m"}'
        with patch("urllib.request.urlopen", return_value=fake_response) as mock_urlopen:
            join_master("http://master:8787/", "tok", "node-1")
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://master:8787/api/cluster/join"

    def test_join_master_http_error_raises_cluster_join_error(self):
        err = urllib.error.HTTPError("http://master:8787/api/cluster/join", 401, "Unauthorized", None, None)
        err.read = lambda: b'{"error": "Unauthorized"}'
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(ClusterJoinError):
                join_master("http://master:8787", "wrong-tok", "node-1")

    def test_join_master_unreachable_raises_cluster_join_error(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no route to host")):
            with pytest.raises(ClusterJoinError):
                join_master("http://unreachable:8787", "tok", "node-1")


class TestSendHeartbeat:
    def test_send_heartbeat_success(self):
        fake_response = MagicMock()
        fake_response.__enter__.return_value.read.return_value = b'{"status": "ok"}'
        with patch("urllib.request.urlopen", return_value=fake_response) as mock_urlopen:
            result = send_heartbeat("http://master:8787", "tok", "node-1", stats={"total_calls": 3})
        assert result["status"] == "ok"
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://master:8787/api/cluster/heartbeat"

    def test_send_heartbeat_unregistered_node_raises(self):
        err = urllib.error.HTTPError("http://master:8787/api/cluster/heartbeat", 500, "Error", None, None)
        err.read = lambda: b'{"error": "node not registered"}'
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(ClusterJoinError):
                send_heartbeat("http://master:8787", "tok", "ghost-node")


class TestDeployTemplates:
    def test_render_docker_compose_includes_master_and_slaves(self):
        out = render_docker_compose(slave_count=3)
        assert "synthelion-master" in out
        assert "synthelion-node-1" in out
        assert "synthelion-node-2" in out
        assert "synthelion-node-3" in out
        assert "SYNTHELION_NODE_TOKEN" in out
        assert "SYNTHELION_MASTER_URL=http://synthelion-master:8787" in out

    def test_render_docker_compose_zero_slaves(self):
        out = render_docker_compose(slave_count=0)
        assert "synthelion-master" in out
        assert "synthelion-node-1" not in out

    def test_render_docker_compose_clamps_slave_count(self):
        out = render_docker_compose(slave_count=999)
        assert "synthelion-node-20" in out
        assert "synthelion-node-21" not in out

    def test_render_k8s_manifest_has_secret_and_deployments(self):
        out = render_k8s_manifest(slave_count=2)
        assert "kind: Secret" in out
        assert "kind: Deployment" in out
        assert "name: synthelion-master" in out
        assert "replicas: 2" in out
        assert "secretKeyRef" in out  # token comes from the Secret, never a literal value in the manifest
