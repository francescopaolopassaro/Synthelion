# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""HTTP Basic Auth credentials for the local web dashboard.

Credentials are stored salted+hashed (PBKDF2-HMAC-SHA256, stdlib only — no extra
dependency) at ~/.synthelion/dashboard_auth.json, never in plaintext. On first use
the dashboard creates a default admin/admin login so it works out of the box; the
user is expected to change it with `synthelion dashboard-passwd`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path

_DEFAULT_USERNAME = "admin"
_DEFAULT_PASSWORD = "admin"
_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16


def _auth_path() -> Path:
    return Path.home() / ".synthelion" / "dashboard_auth.json"


def _hash_password(password: str, salt: bytes, iterations: int = _PBKDF2_ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def _write_credentials(username: str, password: str, path: Path | None = None) -> Path:
    target = path or _auth_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(_SALT_BYTES)
    data = {
        "username": username,
        "salt": salt.hex(),
        "hash": _hash_password(password, salt),
        "iterations": _PBKDF2_ITERATIONS,
    }
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    try:
        os.chmod(target, 0o600)  # best-effort on Windows; meaningful on POSIX
    except OSError:
        pass
    return target


def _read(path: Path | None = None) -> dict | None:
    target = path or _auth_path()
    if not target.exists():
        return None
    try:
        with open(target, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def ensure_default_credentials(path: Path | None = None) -> Path:
    """Creates the default admin/admin login on first run. No-op if a file already exists."""
    target = path or _auth_path()
    if target.exists():
        return target
    return _write_credentials(_DEFAULT_USERNAME, _DEFAULT_PASSWORD, target)


def set_credentials(username: str, password: str, path: Path | None = None) -> Path:
    if not username or not username.strip():
        raise ValueError("username must not be empty")
    if not password:
        raise ValueError("password must not be empty")
    return _write_credentials(username.strip(), password, path)


def current_username(path: Path | None = None) -> str:
    data = _read(path)
    return data.get("username", _DEFAULT_USERNAME) if data else _DEFAULT_USERNAME


def credentials_fingerprint(path: Path | None = None) -> str:
    """Opaque value that changes whenever the stored credentials change.

    Used by the dashboard's session store to invalidate already-issued login
    sessions the moment `synthelion dashboard-passwd` rotates the password —
    the stored password hash already changes on every rotation, so it doubles
    as the fingerprint without exposing anything the hash itself didn't.
    """
    data = _read(path)
    if data is None:
        ensure_default_credentials(path)
        data = _read(path)
    return data.get("hash", "") if data else ""


def is_using_default_password(path: Path | None = None) -> bool:
    """True if the dashboard still has the out-of-the-box admin/admin login."""
    return verify(_DEFAULT_USERNAME, _DEFAULT_PASSWORD, path)


def verify(username: str, password: str, path: Path | None = None) -> bool:
    data = _read(path)
    if data is None:
        ensure_default_credentials(path)
        data = _read(path)
        if data is None:
            return False
    try:
        salt = bytes.fromhex(data["salt"])
        iterations = int(data.get("iterations", _PBKDF2_ITERATIONS))
        computed = _hash_password(password, salt, iterations)
    except (KeyError, ValueError):
        return False
    return hmac.compare_digest(data.get("username", ""), username) and hmac.compare_digest(data["hash"], computed)
