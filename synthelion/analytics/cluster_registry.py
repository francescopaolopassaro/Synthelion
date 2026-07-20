# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Master-side registry of joined cluster nodes: ~/.synthelion/cluster_nodes.json.

Unlike the savings ledger (append-only, many concurrent writer processes),
this is small, mutates in place (heartbeats update `last_seen` for an
existing entry), and is only ever written by the master node's own dashboard
process — so a plain read-modify-write with a temp-file + atomic `os.replace`
is enough; there is no concurrent-writer scenario to design around the way
there is for the ledger.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


def _registry_path(directory: Path | None = None) -> Path:
    # Path.home() re-read here, not cached at module import time — see the
    # incident/comment in synthelion/analytics/ledger.py for why that matters.
    d = directory or (Path.home() / ".synthelion")
    d.mkdir(parents=True, exist_ok=True)
    return d / "cluster_nodes.json"


class ClusterRegistry:
    """The master's view of which nodes have joined the cluster and when each
    was last heard from."""

    def __init__(self, directory: Path | None = None) -> None:
        self._path = _registry_path(directory)
        self._lock = threading.Lock()

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, nodes: dict[str, dict[str, Any]]) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(nodes, fh, indent=2, ensure_ascii=False)
        import os
        os.replace(tmp, self._path)

    def register(self, node_id: str, url: str) -> dict[str, Any]:
        """Adds or updates a node's registration (join, or a re-join after restart)."""
        with self._lock:
            nodes = self._read()
            now = time.time()
            entry = nodes.get(node_id, {})
            entry.update({"url": url, "joined_at": entry.get("joined_at", now), "last_seen": now})
            nodes[node_id] = entry
            self._write(nodes)
            return entry

    def heartbeat(self, node_id: str, stats: dict[str, Any] | None = None) -> bool:
        """Updates `last_seen` (and optional `stats`) for an already-registered node.
        Returns False if the node was never registered (it should re-join)."""
        with self._lock:
            nodes = self._read()
            if node_id not in nodes:
                return False
            nodes[node_id]["last_seen"] = time.time()
            if stats is not None:
                nodes[node_id]["stats"] = stats
            self._write(nodes)
            return True

    def list_nodes(self) -> list[dict[str, Any]]:
        nodes = self._read()
        return [{"node_id": nid, **info} for nid, info in sorted(nodes.items())]

    def remove(self, node_id: str) -> bool:
        with self._lock:
            nodes = self._read()
            if node_id not in nodes:
                return False
            del nodes[node_id]
            self._write(nodes)
            return True


_registry: ClusterRegistry | None = None
_registry_lock = threading.Lock()


def get_cluster_registry() -> ClusterRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ClusterRegistry()
    return _registry
