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

_DEFAULT_CONFIG: dict[str, Any] = {
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
}


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
    overriding `session_store.backend`) is enough — every other key keeps its default."""
    target = path or config_path()
    if target is None or not target.exists():
        return default_config()

    try:
        with open(target, encoding="utf-8") as fh:
            user_config = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid Synthelion config at {target}: {exc}") from exc

    merged = _deep_merge(_DEFAULT_CONFIG, user_config)
    return _expand(merged)


def save_config(config: dict[str, Any], path: Path | None = None) -> Path:
    target = path or default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return target
