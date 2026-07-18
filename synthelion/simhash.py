# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Charikar SimHash: a 64-bit near-duplicate fingerprint for text.

Ported from Caveman C# 1.4.1's CavemanSimHash. Used to detect near-duplicates (two
texts that differ in wording but are structurally almost the same) that exact-match
comparison misses. Two fingerprints with a small Hamming distance correspond to
near-duplicate inputs; the reverse is not guaranteed (SimHash is a locality-sensitive
hash, not a checksum). Stdlib only (hashlib), no external dependency.
"""
from __future__ import annotations

import hashlib

import regex

_WORD_SPLIT = regex.compile(r"[\p{L}\p{M}\p{N}]+", regex.UNICODE)

_BITS = 64
_MASK = (1 << _BITS) - 1


def _fnv1a64(s: str) -> int:
    # FNV-1a 64-bit: small, stable, dependency-free non-cryptographic hash.
    # Deterministic across runs/processes (unlike Python's built-in hash(), which is
    # salted per-process for strings unless PYTHONHASHSEED is fixed).
    h = 0xCBF29CE484222325
    prime = 0x100000001B3
    for ch in s.encode("utf-8"):
        h ^= ch
        h = (h * prime) & _MASK
    return h


def compute(text: str, shingle_size: int = 1) -> int:
    """Computes the 64-bit SimHash of `text` over word-level features.

    `shingle_size` > 1 groups consecutive words into shingles instead of unigrams.
    """
    if not text or not text.strip():
        return 0

    words = [w.lower() for w in _WORD_SPLIT.findall(text)]
    if not words:
        return 0

    n = max(1, shingle_size)
    features: dict[str, int] = {}
    for i in range(0, len(words) - n + 1):
        shingle = words[i] if n == 1 else " ".join(words[i:i + n])
        features[shingle] = features.get(shingle, 0) + 1
    if not features:
        for w in words:
            features[w] = features.get(w, 0) + 1

    bit_weights = [0] * _BITS
    for feature, weight in features.items():
        h = _fnv1a64(feature)
        for bit in range(_BITS):
            bit_weights[bit] += weight if (h >> bit) & 1 else -weight

    fingerprint = 0
    for bit in range(_BITS):
        if bit_weights[bit] > 0:
            fingerprint |= 1 << bit
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    """Number of differing bits between two fingerprints (0 = identical, 64 = maximally different)."""
    return bin((a ^ b) & _MASK).count("1")


def are_near_duplicates(a: str, b: str, max_distance: int = 3, shingle_size: int = 1) -> bool:
    """True when the two texts' fingerprints differ by at most `max_distance` bits."""
    return hamming_distance(compute(a, shingle_size), compute(b, shingle_size)) <= max_distance
