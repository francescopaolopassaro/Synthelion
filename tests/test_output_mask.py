# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for output_mask.py (masking older tool-call output with hash retrieval)."""
from __future__ import annotations

import re
import time

from synthelion.output_mask import OutputMaskStore, mask_old_outputs

_HASH_RE = re.compile(r"hash='([0-9a-f]+)'")


class TestOutputMaskStore:
    def test_store_and_retrieve_roundtrip(self):
        store = OutputMaskStore()
        h = store.store("some tool output")
        assert store.retrieve(h) == "some tool output"

    def test_retrieve_unknown_hash_returns_none(self):
        store = OutputMaskStore()
        assert store.retrieve("deadbeef") is None

    def test_ttl_expiry(self):
        store = OutputMaskStore(ttl_seconds=0.01)
        h = store.store("expires soon")
        time.sleep(0.05)
        assert store.retrieve(h) is None

    def test_eviction_when_over_capacity(self):
        store = OutputMaskStore(max_entries=4)
        hashes = [store.store(f"text {i}") for i in range(6)]
        # Oldest 25% of max (1 entry) evicted each time capacity is exceeded —
        # at minimum the very first stored entries should be gone.
        assert store.retrieve(hashes[0]) is None


class TestMaskOldOutputs:
    def test_keeps_last_n_untouched(self):
        outputs = [{"tool": "t", "output": f"output {i}"} for i in range(5)]
        result = mask_old_outputs(outputs, keep_last=2)
        assert result[-1]["output"] == "output 4"
        assert result[-2]["output"] == "output 3"

    def test_masks_older_entries_with_placeholder(self):
        outputs = [{"tool": "t", "output": f"output {i}"} for i in range(5)]
        result = mask_old_outputs(outputs, keep_last=2)
        for entry in result[:3]:
            assert "masked" in entry["output"]
            assert _HASH_RE.search(entry["output"])

    def test_masked_hash_is_retrievable(self):
        store = OutputMaskStore()
        outputs = [{"tool": "t", "output": f"unique output {i}"} for i in range(4)]
        result = mask_old_outputs(outputs, keep_last=1, store=store)
        h = _HASH_RE.search(result[0]["output"]).group(1)
        assert store.retrieve(h) == "unique output 0"

    def test_preserves_other_keys(self):
        outputs = [{"tool": "npm", "output": "long output", "exit_code": 0}]
        result = mask_old_outputs(outputs, keep_last=0)
        assert result[0]["tool"] == "npm"
        assert result[0]["exit_code"] == 0

    def test_preserves_order(self):
        outputs = [{"tool": "t", "output": str(i)} for i in range(5)]
        result = mask_old_outputs(outputs, keep_last=5)
        assert result == outputs

    def test_keep_last_greater_than_length_masks_nothing(self):
        outputs = [{"tool": "t", "output": "a"}, {"tool": "t", "output": "b"}]
        result = mask_old_outputs(outputs, keep_last=10)
        assert result == outputs

    def test_empty_list(self):
        assert mask_old_outputs([], keep_last=3) == []
