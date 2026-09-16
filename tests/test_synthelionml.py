"""Tests for SynthelionML — learned per-token keep/drop compression level."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from synthelion.core import CompressionService
from synthelion.models import CompressionLevel


# ------------------------------------------------------------------
# Level registration
# ------------------------------------------------------------------

class TestLevelRegistration:
    def test_level_exists(self):
        assert hasattr(CompressionLevel, "SYNTHELION_ML")

    def test_level_value_unique(self):
        vals = [lv.value for lv in CompressionLevel]
        assert len(vals) == len(set(vals))

    def test_level_int_value(self):
        assert CompressionLevel.SYNTHELION_ML.value == 6


# ------------------------------------------------------------------
# Core dispatch — model absent → SYNTACTIC fallback
# ------------------------------------------------------------------

class TestCoreFallback:
    def test_compress_returns_string(self):
        svc = CompressionService()
        r = svc.compress("The quick brown fox jumps over the lazy dog.", CompressionLevel.SYNTHELION_ML, iso3="eng")
        assert isinstance(r.compressed_text, str)
        assert len(r.compressed_text) > 0

    def test_compress_produces_output(self):
        svc = CompressionService()
        r = svc.compress("The quick brown fox jumps over the lazy dog.", CompressionLevel.SYNTHELION_ML, iso3="eng")
        assert r.compressed_tokens > 0
        assert r.original_tokens > 0

    def test_compressed_tokens_le_original(self):
        """ML level should drop at least some tokens (or match original if model unavailable)."""
        svc = CompressionService()
        text = "The government announced new economic measures to support small businesses during the crisis."
        r = svc.compress(text, CompressionLevel.SYNTHELION_ML, iso3="eng")
        assert r.compressed_tokens <= r.original_tokens

    def test_italian_compress(self):
        svc = CompressionService()
        r = svc.compress(
            "Il governo italiano ha approvato ieri una nuova legge per sostenere le piccole imprese.",
            CompressionLevel.SYNTHELION_ML,
            iso3="ita",
        )
        assert r.compressed_tokens <= r.original_tokens
        assert len(r.compressed_text) > 0

    def test_german_compress(self):
        svc = CompressionService()
        r = svc.compress(
            "Die Bundesregierung hat gestern ein neues Gesetz verabschiedet um kleine Unternehmen zu unterstuetzen.",
            CompressionLevel.SYNTHELION_ML,
            iso3="deu",
        )
        assert r.compressed_tokens <= r.original_tokens

    def test_french_compress(self):
        svc = CompressionService()
        r = svc.compress(
            "Le gouvernement francais a approuve hier une nouvelle loi pour soutenir les petites entreprises.",
            CompressionLevel.SYNTHELION_ML,
            iso3="fra",
        )
        assert r.compressed_tokens <= r.original_tokens

    def test_spanish_compress(self):
        svc = CompressionService()
        r = svc.compress(
            "El gobierno espanol aprobo ayer una nueva ley para apoyar a las pequenas empresas.",
            CompressionLevel.SYNTHELION_ML,
            iso3="spa",
        )
        assert r.compressed_tokens <= r.original_tokens


# ------------------------------------------------------------------
# SynthelionMLCompressor unit tests
# ------------------------------------------------------------------

class TestSynthelionMLCompressor:
    def test_singleton_reset(self):
        from synthelion.synthelionml import SynthelionMLCompressor
        SynthelionMLCompressor.reset()
        c1 = SynthelionMLCompressor.get_instance()
        c2 = SynthelionMLCompressor.get_instance()
        assert c1 is c2
        SynthelionMLCompressor.reset()

    def test_is_available(self):
        from synthelion.synthelionml import SynthelionMLCompressor
        SynthelionMLCompressor.reset()
        c = SynthelionMLCompressor.get_instance()
        # may be True or False depending on whether checkpoint is present
        assert isinstance(c.is_available(), bool)
        SynthelionMLCompressor.reset()

    def test_fallback_when_no_model(self):
        """With a bogus path, the compressor should not crash."""
        from synthelion.synthelionml import SynthelionMLCompressor
        SynthelionMLCompressor.reset()
        c = SynthelionMLCompressor(model_path=Path("/nonexistent/path/to/model"))
        assert c.is_available() is False
        SynthelionMLCompressor.reset()


# ------------------------------------------------------------------
# SynthelionMLVocab — char-ngram hash determinism
# ------------------------------------------------------------------

class TestSynthelionMLVocab:
    def test_char_ngram_hash_deterministic(self):
        from synthelion.synthelionml import SynthelionMLVocab
        h1 = SynthelionMLVocab.char_ngram_hash("hello")
        h2 = SynthelionMLVocab.char_ngram_hash("hello")
        assert h1 == h2

    def test_char_ngram_hash_different_words(self):
        from synthelion.synthelionml import SynthelionMLVocab
        h1 = SynthelionMLVocab.char_ngram_hash("hello")
        h2 = SynthelionMLVocab.char_ngram_hash("world")
        assert h1 != h2

    def test_char_ngram_hash_non_negative(self):
        from synthelion.synthelionml import SynthelionMLVocab
        for word in ["test", "python", "synthelion", "compression"]:
            h = SynthelionMLVocab.char_ngram_hash(word)
            assert h >= 0


# ------------------------------------------------------------------
# resolve_ml_model_path
# ------------------------------------------------------------------

class TestResolveMLModelPath:
    def test_resolve_returns_path_or_none(self):
        from synthelion.synthelionml import resolve_ml_model_path
        result = resolve_ml_model_path()
        assert result is None or isinstance(result, Path)

    def test_resolve_explicit_name(self):
        from synthelion.synthelionml import resolve_ml_model_path
        result = resolve_ml_model_path("synthelionml")
        assert result is None or isinstance(result, Path)


# ------------------------------------------------------------------
# Proxy level mapping
# ------------------------------------------------------------------

class TestProxyLevelMapping:
    def test_synthelionml_in_proxy_map(self):
        from synthelion.plugins.proxy import _level_map
        lm = _level_map()
        assert "synthelionml" in lm

    def test_proxy_synthelionml_maps_correctly(self):
        from synthelion.plugins.proxy import _level_map
        lm = _level_map()
        assert lm["synthelionml"] == CompressionLevel.SYNTHELION_ML
