"""AES-256-GCM encryption/decryption for enterprise provider API keys.

Key is auto-generated on first use and stored in the source-root file
``documentochiave.txt``.  The key is NOT configurable — it lives in a
single fixed location so there is exactly one place to look.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from pathlib import Path

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Key file — fixed path, not configurable
# ---------------------------------------------------------------------------
_KEY_FILENAME = "documentochiave.txt"
_KEY_PATH = Path(__file__).resolve().parents[2] / _KEY_FILENAME  # repo root


def _load_or_create_key() -> bytes:
    """Return the 32-byte AES key, generating + writing it on first run."""
    if _KEY_PATH.exists():
        raw = _KEY_PATH.read_text(encoding="utf-8").strip()
        # Accept hex-encoded (64 chars) or raw 32-byte base64
        if len(raw) == 64 and all(c in "0123456789abcdef" for c in raw.lower()):
            return bytes.fromhex(raw)
        # Fallback: derive from whatever is in the file
        return hashlib.sha256(raw.encode()).digest()
    # First run — generate and persist
    key = secrets.token_bytes(32)
    _KEY_PATH.write_text(key.hex(), encoding="utf-8")
    try:
        _KEY_PATH.chmod(0o600)
    except OSError:
        pass
    _log.info("Enterprise encryption key generated: %s", _KEY_PATH)
    return key


AES_KEY: bytes = _load_or_create_key()


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
    ct = AESGCM(AES_KEY).encrypt(nonce, plaintext.encode(), None)
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
    return AESGCM(AES_KEY).decrypt(nonce, ct, None).decode()
