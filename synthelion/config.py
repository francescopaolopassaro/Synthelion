# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""JSON-based configuration for Synthelion: session storage backend, vector-store
backend (for RAG cross-session memory), and dashboard settings.

Config resolution order (first match wins):
  1. `SYNTHELION_CONFIG` env var — an explicit path (useful for mounting a
     per-node/per-container config file, e.g. a Kubernetes ConfigMap volume).
  2. `./synthelion.config.json` — project-local, for per-repo overrides.
  3. `~/.synthelion/config.json` — the user/machine default.
  4. Built-in defaults (single-node, local file storage) if none of the above exist.

Every backend is optional at the code level: choosing "redis"/"postgres"/"qdrant"
only imports that client library when actually selected, so installing Synthelion
without those extras still works for the default local/chromadb setup.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

_VALID_COMPRESSION_LEVELS = ("none", "light", "semantic", "aggressive", "statistical", "syntactic")

_DEFAULT_CONFIG: dict[str, Any] = {
    "compression": {
        "default_level": "semantic",
    },
    "wiki": {
        "default_depth": 2,
    },
    "session_store": {
        # "local" | "redis" | "postgres"
        "backend": "local",
        "local": {"directory": "~/.synthelion"},
        "redis": {"url": "redis://localhost:6379/0", "key_prefix": "synthelion:", "active_ttl_seconds": 300},
        "postgres": {"dsn": "postgresql://synthelion:synthelion@localhost:5432/synthelion"},
    },
    "vector_store": {
        # "chromadb" | "qdrant" | "lexical" (no external service, cosine bag-of-words fallback)
        "backend": "chromadb",
        "chromadb": {"directory": "~/.synthelion/sessions"},
        "qdrant": {"url": "http://localhost:6333", "collection": "synthelion_decisions", "api_key": None},
    },
    "dashboard": {
        "host": "127.0.0.1",
        "port": 8787,
        # "websocket" | "polling"
        "realtime": "websocket",
        "websocket_port": 8788,
    },
    "cluster": {
        # "standalone" (default) | "master" | "slave"
        "role": "standalone",
        "node_id": "",
        # Shared secret for node-to-node calls (join/heartbeat/self-status) —
        # every node in a cluster must carry the same token. Never sent to the
        # browser; the dashboard's Cluster page only ever shows it masked.
        "node_token": "",
        # Slaves only: the master's base URL, e.g. "http://master-host:8787".
        "master_url": "",
        # This node's own reachable URL, reported to the master on join/heartbeat
        # so the master's Cluster page can link to it. Optional for a slave that
        # only the master needs to reach — set it if slaves should reach each
        # other directly too.
        "self_url": "",
    },
}

_VALID_CLUSTER_ROLES = ("standalone", "master", "slave")

# Container-native overrides — set at deploy time via environment variables
# rather than baking a config.json into the image, matching how the Dockerfile
# / docker-compose / k8s manifests configure everything else (SYNTHELION_CONFIG
# already works this way for the config *path*; these are for the cluster
# fields specifically, which are usually per-replica and awkward to template
# into a single shared JSON file).
_CLUSTER_ENV_VARS = {
    "role": "SYNTHELION_ROLE",
    "node_id": "SYNTHELION_NODE_ID",
    "node_token": "SYNTHELION_NODE_TOKEN",
    "master_url": "SYNTHELION_MASTER_URL",
    "self_url": "SYNTHELION_SELF_URL",
}


def _apply_cluster_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    for key, env_var in _CLUSTER_ENV_VARS.items():
        value = os.environ.get(env_var)
        if value:
            config["cluster"][key] = value
    return config


def _expand(value: Any) -> Any:
    """Recursively expands ~ and env vars in string config values (e.g. directory paths)."""
    if isinstance(value, str):
        return os.path.expandvars(os.path.expanduser(value))
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merges a partial config *override* over a full *base* config, keeping
    every key *override* doesn't touch. Used by the dashboard's Settings panel to
    apply a partial POST body over the currently effective config."""
    return _deep_merge(base, override)


def default_config() -> dict[str, Any]:
    return copy.deepcopy(_DEFAULT_CONFIG)


def config_path() -> Path | None:
    """Returns the config file path that would be used, or None if none exists
    (in which case built-in defaults apply)."""
    env_path = os.environ.get("SYNTHELION_CONFIG")
    if env_path:
        return Path(env_path)
    local = Path.cwd() / "synthelion.config.json"
    if local.exists():
        return local
    home = Path.home() / ".synthelion" / "config.json"
    if home.exists():
        return home
    return None


def default_config_path() -> Path:
    """Where `save_config()` writes when no explicit path is given — the
    user/machine default location, not the project-local override."""
    return Path.home() / ".synthelion" / "config.json"


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Loads config, merging over the built-in defaults so a partial file (e.g. just
    overriding `session_store.backend`) is enough — every other key keeps its default.
    `cluster.*` env vars (see `_CLUSTER_ENV_VARS`), if set, override whatever the
    file or defaults say — applied last, every call, so a container's env is
    always authoritative for its own node identity."""
    target = path or config_path()
    if target is None or not target.exists():
        return _apply_cluster_env_overrides(default_config())

    try:
        with open(target, encoding="utf-8") as fh:
            user_config = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid Synthelion config at {target}: {exc}") from exc

    merged = _deep_merge(_DEFAULT_CONFIG, user_config)
    return _apply_cluster_env_overrides(_expand(merged))


def default_compression_level(config: dict[str, Any] | None = None) -> str:
    """The configured default `--level`/`level=` value for compress/compress_batch
    when the caller doesn't specify one. Falls back to "semantic" if the
    configured value isn't recognized."""
    cfg = config if config is not None else load_config()
    level = cfg.get("compression", {}).get("default_level", "semantic")
    return level if level in _VALID_COMPRESSION_LEVELS else "semantic"


def default_wiki_depth(config: dict[str, Any] | None = None) -> int:
    """The configured default `depth` (1-4) for `synthelion wiki` / the
    `generate_project_wiki` MCP tool when the caller doesn't specify one —
    same "config sets the default, explicit argument always wins" pattern as
    `default_compression_level`. Falls back to 2 if the configured value is
    out of range."""
    cfg = config if config is not None else load_config()
    depth = cfg.get("wiki", {}).get("default_depth", 2)
    return depth if depth in (1, 2, 3, 4) else 2


def new_node_id() -> str:
    """A short, human-scannable node identifier: hostname + a short random
    suffix, so two nodes on the same machine (e.g. two containers named the
    same by an orchestrator) still get distinct IDs."""
    import secrets
    import socket
    host = (socket.gethostname() or "node").lower().replace(" ", "-")[:24]
    return f"{host}-{secrets.token_hex(3)}"


def new_cluster_token() -> str:
    """Shared secret nodes present to each other for cluster API calls
    (join/heartbeat/self-status) — generated once by whichever node calls
    `synthelion cluster init` and handed to every node that joins it."""
    import secrets
    return secrets.token_urlsafe(32)


def save_config(config: dict[str, Any], path: Path | None = None) -> Path:
    target = path or default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return target
