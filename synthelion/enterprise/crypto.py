"""AES-256-GCM encryption/decryption for enterprise provider API keys.

The master key is never written to disk as a plaintext file. It is
generated automatically the first time the enterprise DB is created
(`db.py`'s schema init calls `ensure_key()`) and stored in the OS-native
credential store via the ``keyring`` package — Windows Credential Locker,
macOS Keychain, or the Linux Secret Service/KWallet. Only whoever has OS-level
access to that store (i.e. the machine's administrator account) can ever
retrieve it, via ``synthelion enterprise show-key`` — there is no dashboard/
HTTP endpoint that returns it, and Synthelion never offers to change it once
generated (rotating it would make every already-encrypted provider key
undecryptable).

Previously this was a plaintext file (first ``documentochiave.txt`` at the
repo root, then ``~/.synthelion/enterprise_key.hex``) — both are gone now:
a file, gitignored or not, is one accidental copy/backup/archive away from
exposing every provider API key encrypted with it. `migrate_from_file()`
below is the one-shot escape hatch for a deployment that already generated
one of those files before this change.
"""
from __future__ import annotations

import logging
import secrets

_log = logging.getLogger(__name__)

_SERVICE_NAME = "synthelion-enterprise"
_KEY_USERNAME = "aes_master_key"


class EnterpriseKeyUnavailable(RuntimeError):
    pass


def _keyring():
    try:
        import keyring
    except ImportError:
        raise EnterpriseKeyUnavailable(
            "keyring is required for the enterprise module's key storage. "
            "Install with: pip install 'synthelion[enterprise]'"
        )
    return keyring


def ensure_key() -> None:
    """Generate the master key if one doesn't exist yet. Called once from
    `db.py` when the enterprise schema is first created. Idempotent —
    does nothing if a key is already stored (the key is never rotated)."""
    kr = _keyring()
    if kr.get_password(_SERVICE_NAME, _KEY_USERNAME) is None:
        kr.set_password(_SERVICE_NAME, _KEY_USERNAME, secrets.token_bytes(32).hex())
        _log.info("Enterprise encryption key generated and stored in the OS credential store.")


def show_key() -> str:
    """Return the current key, hex-encoded, generating one first if none
    exists yet. For the admin-only `synthelion enterprise show-key` CLI
    command — never exposed over the dashboard/HTTP API."""
    ensure_key()
    return _keyring().get_password(_SERVICE_NAME, _KEY_USERNAME)


def migrate_from_file(path) -> bool:
    """One-shot migration for a deployment that already has a plaintext key
    file (the old `documentochiave.txt` / `enterprise_key.hex` locations).
    Reads it into the OS credential store and leaves the file untouched —
    the caller (CLI command) is responsible for telling the admin to delete
    it by hand once they've confirmed the new location works. No-ops if a
    key is already stored. Returns True if it stored a key."""
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return False
    kr = _keyring()
    if kr.get_password(_SERVICE_NAME, _KEY_USERNAME) is not None:
        return False
    raw = p.read_text(encoding="utf-8").strip()
    if len(raw) != 64 or not all(c in "0123456789abcdef" for c in raw.lower()):
        raise ValueError(f"{p} does not contain a valid 64-char hex key")
    kr.set_password(_SERVICE_NAME, _KEY_USERNAME, raw)
    return True


def _get_key() -> bytes:
    raw = _keyring().get_password(_SERVICE_NAME, _KEY_USERNAME)
    if raw is None:
        raise EnterpriseKeyUnavailable(
            "No enterprise encryption key found in the OS credential store. "
            "It should have been created automatically with the enterprise "
            "DB — run `synthelion enterprise show-key` to generate one now."
        )
    return bytes.fromhex(raw)


# ---------------------------------------------------------------------------
# AES-256-GCM helpers  (requires ``cryptography`` package)
# ---------------------------------------------------------------------------

def encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* → hex string  (nonce ‖ tag ‖ ciphertext)."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise ImportError(
            "cryptography>=42.0 is required for enterprise provider-key "
            "encryption.  Install with: pip install 'synthelion[enterprise]'"
        )
    nonce = secrets.token_bytes(12)
    ct = AESGCM(_get_key()).encrypt(nonce, plaintext.encode(), None)
    return (nonce + ct).hex()


def decrypt(ciphertext_hex: str) -> str:
    """Decrypt hex string (nonce ‖ tag ‖ ciphertext) → plaintext."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise ImportError(
            "cryptography>=42.0 is required for enterprise provider-key "
            "decryption.  Install with: pip install 'synthelion[enterprise]'"
        )
    raw = bytes.fromhex(ciphertext_hex)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(_get_key()).decrypt(nonce, ct, None).decode()
