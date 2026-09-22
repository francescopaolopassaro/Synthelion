# Synthelion — Python port of Caveman.PrivacyGuard (https://github.com/francescopaolopassaro/Caveman.PrivacyGuard)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for PrivacyGuardML — Synthelion's own PII-confirmation model.

Training itself (devtools/train_privacyguardml.py, real corpora) is out of
scope for the suite; these tests cover the runtime architecture, vocab, model
resolution, and the detect() contract against a small checkpoint built
in-process (no real training run, no network).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")


# ---------------------------------------------------------------------------
# Tag vocabulary
# ---------------------------------------------------------------------------

class TestTagVocab:
    def test_o_is_first(self):
        from synthelion.privacyguardml import TAGS
        assert TAGS[0] == "O"

    def test_every_category_has_b_and_i(self):
        from synthelion.privacyguardml import TAGS, CATEGORIES
        for cat in CATEGORIES:
            assert f"B-{cat}" in TAGS
            assert f"I-{cat}" in TAGS

    def test_tag_count(self):
        from synthelion.privacyguardml import TAGS, CATEGORIES
        assert len(TAGS) == 1 + 2 * len(CATEGORIES)

    def test_tag2id_is_a_bijection(self):
        from synthelion.privacyguardml import TAGS, TAG2ID
        assert len(TAG2ID) == len(TAGS)
        assert all(TAGS[i] == t for t, i in TAG2ID.items())

    def test_ml_label_of_covers_every_category(self):
        from synthelion.privacyguardml import CATEGORIES, ML_LABEL_OF
        assert set(ML_LABEL_OF) == set(CATEGORIES)


# ---------------------------------------------------------------------------
# Vocab — char-ngram hash determinism (same scheme as SynthelionML)
# ---------------------------------------------------------------------------

class TestPrivacyGuardMLVocab:
    def test_char_ngram_hash_deterministic(self):
        from synthelion.privacyguardml import PrivacyGuardMLVocab
        assert PrivacyGuardMLVocab.char_ngram_hash("hello") == PrivacyGuardMLVocab.char_ngram_hash("hello")

    def test_char_ngram_hash_varies(self):
        from synthelion.privacyguardml import PrivacyGuardMLVocab
        assert PrivacyGuardMLVocab.char_ngram_hash("hello") != PrivacyGuardMLVocab.char_ngram_hash("world")

    def test_encode_known_word(self):
        from synthelion.privacyguardml import PrivacyGuardMLVocab
        vocab = PrivacyGuardMLVocab({"<pad>": 0, "<unk>": 1, "email": 2}, {0: "<pad>", 1: "<unk>", 2: "email"})
        assert vocab.encode_word("email") == 2

    def test_encode_oov_word_falls_back_to_hash(self):
        from synthelion.privacyguardml import PrivacyGuardMLVocab
        vocab = PrivacyGuardMLVocab({"<pad>": 0, "<unk>": 1}, {0: "<pad>", 1: "<unk>"})
        wid = vocab.encode_word("zzzznotinvocab")
        assert wid >= vocab.vocab_size

    def test_save_and_load_roundtrip(self, tmp_path):
        from synthelion.privacyguardml import PrivacyGuardMLVocab
        vocab = PrivacyGuardMLVocab({"<pad>": 0, "<unk>": 1, "iban": 2}, {0: "<pad>", 1: "<unk>", 2: "iban"})
        path = tmp_path / "vocab.json"
        vocab.save(path)
        loaded = PrivacyGuardMLVocab.load(path)
        assert loaded.word2id == vocab.word2id


# ---------------------------------------------------------------------------
# Word features
# ---------------------------------------------------------------------------

class TestWordFeatures:
    def test_feature_length(self):
        from synthelion.privacyguardml import word_features, N_FEATURES
        assert len(word_features("test@example.com")) == N_FEATURES

    def test_has_at_flag(self):
        from synthelion.privacyguardml import word_features
        f = word_features("a@b.com")
        assert f[1] == 1.0  # has_at

    def test_has_digit_flag(self):
        from synthelion.privacyguardml import word_features
        f = word_features("IT60X05428")
        assert f[0] == 1.0  # has_digit

    def test_plain_word_has_no_shape_flags(self):
        from synthelion.privacyguardml import word_features
        f = word_features("hello")
        assert f[0] == 0.0 and f[1] == 0.0 and f[2] == 0.0


# ---------------------------------------------------------------------------
# Model resolution — offline only
# ---------------------------------------------------------------------------

class TestResolveModelPath:
    def test_returns_none_or_path(self):
        from synthelion.privacyguardml import resolve_model_path
        result = resolve_model_path()
        assert result is None or isinstance(result, Path)

    def _isolate_packaged_dir(self, tmp_path, monkeypatch):
        """A real checkpoint now ships in synthelion/ml_models/privacyguardml —
        resolve_model_path() checks every root, so a bare env-var override
        doesn't hide it; the packaged root itself must be pointed elsewhere
        for these tests to see a clean "nothing installed" state."""
        import synthelion.privacy_ml as pm
        empty_packaged = tmp_path / "no_packaged_models"
        monkeypatch.setattr(pm, "packaged_models_dir", lambda: empty_packaged)

    def test_resolve_finds_installed_checkpoint(self, tmp_path, monkeypatch, isolated_home):
        from synthelion.privacyguardml import resolve_model_path, _MODEL_DIR_NAME
        self._isolate_packaged_dir(tmp_path, monkeypatch)
        monkeypatch.setenv("SYNTHELION_ML_MODELS_DIR", str(tmp_path))
        d = tmp_path / _MODEL_DIR_NAME
        d.mkdir()
        (d / "config.json").write_text("{}", encoding="utf-8")
        (d / "model.bin").write_bytes(b"\x00")
        assert resolve_model_path() == d

    def test_resolve_none_without_weights(self, tmp_path, monkeypatch, isolated_home):
        """No local checkpoint anywhere (env root has config but no weights,
        user/packaged roots are isolated) and no network (autouse
        no_network_asset_download fixture) -> None, same degradation as a
        genuinely offline install."""
        from synthelion.privacyguardml import resolve_model_path, _MODEL_DIR_NAME
        self._isolate_packaged_dir(tmp_path, monkeypatch)
        monkeypatch.setenv("SYNTHELION_ML_MODELS_DIR", str(tmp_path))
        d = tmp_path / _MODEL_DIR_NAME
        d.mkdir()
        (d / "config.json").write_text("{}", encoding="utf-8")
        assert resolve_model_path() is None


# ---------------------------------------------------------------------------
# Detector degradation — no checkpoint present
# ---------------------------------------------------------------------------

class TestDetectorDegradation:
    def test_no_model_returns_empty(self, tmp_path):
        """A checkpoint may legitimately be installed (packaged or local) in
        the environment running this suite — the degradation contract is
        about an explicitly *absent* model, so point at one that provably
        isn't there rather than relying on auto-resolution finding nothing."""
        from synthelion.privacyguardml import PrivacyGuardMLDetector
        det = PrivacyGuardMLDetector(model_path=tmp_path / "not-installed")
        assert det.detect("call me at +39 333 1234567") == []
        assert det.is_available() is False

    def test_bogus_path_does_not_crash(self, tmp_path):
        from synthelion.privacyguardml import PrivacyGuardMLDetector
        det = PrivacyGuardMLDetector(model_path=tmp_path / "does-not-exist")
        assert det.detect("some text") == []


# ---------------------------------------------------------------------------
# A tiny real checkpoint, built in-process — exercises save/load/forward/
# BIO-decode/MLSpan construction end to end without a real training run.
# ---------------------------------------------------------------------------

@pytest.fixture
def tiny_checkpoint(tmp_path):
    from synthelion.privacyguardml import (
        PrivacyGuardMLModel, PrivacyGuardMLVocab, TAGS, N_FEATURES,
    )

    words = ["<pad>", "<unk>", "email", "iban", "call"]
    word2id = {w: i for i, w in enumerate(words)}
    vocab = PrivacyGuardMLVocab(word2id, {i: w for w, i in word2id.items()})

    model = PrivacyGuardMLModel(
        actual_vocab_size=len(word2id),
        d_model=16, n_heads=2, n_layers=1, ffn_dim=32,
        dropout=0.0, n_features=N_FEATURES, n_tags=len(TAGS), max_seq_len=32,
    )
    out_dir = tmp_path / "privacyguardml"
    out_dir.mkdir()
    config = {
        "model_name": "PrivacyGuardML", "model_type": "privacyguardml",
        "d_model": 16, "n_heads": 2, "n_layers": 1, "ffn_dim": 32,
        "dropout": 0.0, "n_features": N_FEATURES, "n_tags": len(TAGS),
        "max_seq_len": 32, "min_confidence": 0.0,
    }
    (out_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    vocab.save(out_dir / "vocab.json")
    torch.save(model.state_dict(), out_dir / "model.bin")
    return out_dir


class TestDetectorWithCheckpoint:
    def test_is_available(self, tiny_checkpoint):
        from synthelion.privacyguardml import PrivacyGuardMLDetector
        det = PrivacyGuardMLDetector(tiny_checkpoint, min_confidence=0.0)
        assert det.is_available() is True

    def test_detect_returns_mlspans_or_empty(self, tiny_checkpoint):
        from synthelion.privacyguardml import PrivacyGuardMLDetector
        from synthelion.privacy_ml import MLSpan
        det = PrivacyGuardMLDetector(tiny_checkpoint, min_confidence=0.0)
        spans = det.detect("Send it to test@example.com or call me at IT60X0542811101000000123456")
        assert isinstance(spans, list)
        for s in spans:
            assert isinstance(s, MLSpan)
            assert 0 <= s.start < s.end <= len("Send it to test@example.com or call me at IT60X0542811101000000123456")

    def test_high_confidence_threshold_filters_everything(self, tiny_checkpoint):
        """An untrained (random-weight) model's confidences are whatever they
        are; a threshold above 1.0 can never be met, so the filter must empty
        the result regardless of what the forward pass produced."""
        from synthelion.privacyguardml import PrivacyGuardMLDetector
        det = PrivacyGuardMLDetector(tiny_checkpoint, min_confidence=1.5)
        assert det.detect("test@example.com") == []

    def test_empty_text_returns_empty(self, tiny_checkpoint):
        from synthelion.privacyguardml import PrivacyGuardMLDetector
        det = PrivacyGuardMLDetector(tiny_checkpoint, min_confidence=0.0)
        assert det.detect("") == []
        assert det.detect("   ") == []

    def test_model_survives_reload(self, tiny_checkpoint):
        """Two independent detector instances loading the same checkpoint must
        produce identical predictions — no hidden randomness at inference."""
        from synthelion.privacyguardml import PrivacyGuardMLDetector
        text = "contact test@example.com now"
        det1 = PrivacyGuardMLDetector(tiny_checkpoint, min_confidence=0.0)
        det2 = PrivacyGuardMLDetector(tiny_checkpoint, min_confidence=0.0)
        assert det1.detect(text) == det2.detect(text)


# ---------------------------------------------------------------------------
# privacy_ml.get_ml_detector() dispatch
# ---------------------------------------------------------------------------

class TestDetectorDispatch:
    def test_default_dispatches_to_privacyguardml(self, monkeypatch):
        import synthelion.privacy_ml as pm
        pm._detectors.clear()
        det = pm.get_ml_detector()
        from synthelion.privacyguardml import PrivacyGuardMLDetector
        assert isinstance(det, PrivacyGuardMLDetector)
        pm._detectors.clear()

    def test_explicit_privacyguardml_checkpoint_dispatches_correctly(self, tiny_checkpoint, monkeypatch):
        import synthelion.privacy_ml as pm
        pm._detectors.clear()
        monkeypatch.setenv("SYNTHELION_ML_MODELS_DIR", str(tiny_checkpoint.parent))
        det = pm.get_ml_detector(model_name="privacyguardml")
        from synthelion.privacyguardml import PrivacyGuardMLDetector
        assert isinstance(det, PrivacyGuardMLDetector)
        pm._detectors.clear()

    def test_unknown_model_name_still_returns_privacyguardml_detector(self, monkeypatch):
        """No other backend exists: an unresolvable name degrades to an
        unavailable PrivacyGuardMLDetector rather than raising or falling
        back to a third-party model."""
        import synthelion.privacy_ml as pm
        pm._detectors.clear()
        det = pm.get_ml_detector(model_name="some-unknown-model")
        from synthelion.privacyguardml import PrivacyGuardMLDetector
        assert isinstance(det, PrivacyGuardMLDetector)
        pm._detectors.clear()

    def test_detector_cache_is_keyed_by_model_and_threshold(self, monkeypatch):
        import synthelion.privacy_ml as pm
        pm._detectors.clear()
        a = pm.get_ml_detector(model_name="privacyguardml", min_confidence=0.5)
        b = pm.get_ml_detector(model_name="privacyguardml", min_confidence=0.5)
        c = pm.get_ml_detector(model_name="privacyguardml", min_confidence=0.9)
        assert a is b
        assert a is not c
        pm._detectors.clear()
