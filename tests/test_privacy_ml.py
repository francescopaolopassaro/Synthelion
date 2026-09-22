# Synthelion — Python port of Caveman.PrivacyGuard (https://github.com/francescopaolopassaro/Caveman.PrivacyGuard)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for the optional ML-assisted confirmation tier (privacy.use_ml).

These tests exercise the *integration* between PrivacyAnalyzer and a span-
producing detector using a deterministic fake (no real inference, no CPU
cost). The real backend (privacyguardml.PrivacyGuardMLDetector, Synthelion's
own model — no third-party model is used or supported) is covered in
tests/test_privacyguardml.py.
"""
from __future__ import annotations

import pytest

from synthelion.privacy_ml import MLSpan


class FakeMLDetector:
    """Deterministic stand-in for PrivacyMLDetector: flags `sensitive_values`
    (substrings) present in the analyzed text as `label`, with a fixed
    confidence."""

    def __init__(self, sensitive_values, label="phone number", confidence=0.9):
        self._values = sensitive_values
        self._label = label
        self._confidence = confidence
        self.calls = 0

    def detect(self, text: str) -> list[MLSpan]:
        self.calls += 1
        spans = []
        for v in self._values:
            start = text.find(v)
            if start >= 0:
                spans.append(MLSpan(start, start + len(v), v, self._label, self._confidence))
        return spans


def _analyzer(use_ml: bool, detector=None):
    from synthelion.privacy_analyzer import PrivacyAnalyzer
    return PrivacyAnalyzer(use_ml=use_ml, ml_detector=detector)


class TestPrivacyMLIntegration:
    def test_default_is_zero_ml(self):
        # The flag defaults to False and no detector is ever resolved.
        a = _analyzer(use_ml=False)
        assert a._use_ml is False

    def test_bare_phone_confirmed_by_ml(self):
        # A local-format phone with no context keyword is *not* PII for the pure
        # regex tier (needs "telefono" etc.) — with ML on, an overlapping span
        # confirms it.
        detector = FakeMLDetector(["39123456"])
        a = _analyzer(use_ml=True, detector=detector)
        text = "Chiamami al 39123456 domani"

        r_off = _analyzer(use_ml=False).analyze(text, auto_masking=True)
        assert "Phone E.164" not in r_off.detected_categories
        assert "39123456" in r_off.masked_text

        r = a.analyze(text, auto_masking=True)
        assert "Phone E.164" in r.detected_categories
        assert "39123456" not in r.masked_text
        assert r.ml_assisted_count == 1

    def test_ml_never_overrides_a_failed_checksum(self):
        # The algorithmic validator is ground truth: even a span the model
        # confidently flags as a national ID must NOT confirm a number whose
        # checksums all fail (99887766554 is valid PESEL *length* but fails the
        # PESEL/BSN/OIB/... modulo-11 checks, and it is not E.164-gated by the
        # "national identification number" label either).
        detector = FakeMLDetector(["99887766554"], label="national identification number")
        a = _analyzer(use_ml=True, detector=detector)
        r = a.analyze("Record 99887766554 allegato", auto_masking=True)
        assert r.detected_categories == []
        assert "99887766554" in r.masked_text
        assert r.ml_assisted_count == 0

    def test_ml_keeps_context_and_checksum_paths(self):
        # With keywords and/or valid checksums present, ML is irrelevant: the
        # same results come back whether it is on or off.
        text = "telefono 39123456 e PESEL: 44051401359"
        detector = FakeMLDetector(["39123456"], label="phone number")
        r_on = _analyzer(use_ml=True, detector=detector).analyze(text)
        r_off = _analyzer(use_ml=False).analyze(text)
        assert r_on.detected_categories == r_off.detected_categories
        assert "Phone E.164" in r_on.detected_categories
        assert "Polish PESEL" in r_on.detected_categories

    def test_ml_confirms_without_masking_harm(self):
        # ML-assisted detection must flow through masking exactly like a
        # keyword-assisted one: the value is replaced, near-text is untouched.
        detector = FakeMLDetector(["39123456"])
        a = _analyzer(use_ml=True, detector=detector)
        r = a.analyze("Chiamami al 39123456 domani", auto_masking=True)
        assert r.masked_text == "Chiamami al [PHONE E.164] domani"
        assert r.ml_assisted_count == 1

    def test_ml_span_before_match_also_confirms(self):
        # Overlap (not containment) is the rule: a span containing a tiny part
        # of the match range is enough.
        detector = FakeMLDetector(["39123456"], label="phone number")
        a = _analyzer(use_ml=True, detector=detector)
        r = a.analyze("+39 39123456 senza keyword", auto_masking=True)
        assert "Phone E.164" in r.detected_categories

    def test_ml_label_national_id_does_not_confirm_phone(self):
        # A "national identification number" span must not create a *phone*
        # detection on the same bare run (and the national-ID rules it could
        # confirm all fail their checksums here, so nothing is detected).
        detector = FakeMLDetector(["39123456789"], label="national identification number")
        a = _analyzer(use_ml=True, detector=detector)
        r = a.analyze("Valore 39123456789 nel file", auto_masking=True)
        assert "Phone E.164" not in r.detected_categories
        assert r.detected_categories == []
        assert r.ml_assisted_count == 0

    def test_ml_label_phone_confirms_phone(self):
        detector = FakeMLDetector(["39123456789"], label="phone number")
        a = _analyzer(use_ml=True, detector=detector)
        r = a.analyze("Valore 39123456789 nel file", auto_masking=True)
        assert "Phone E.164" in r.detected_categories


class TestPrivacyMLDegradation:
    def test_detector_resolution_failure_is_graceful(self, monkeypatch):
        # If the detector factory itself raises (e.g. import error surface),
        # analysis must fall back silently to the regex-only result.
        import synthelion.privacy_analyzer as pa

        def boom(*_a, **_k):
            raise RuntimeError("gliner unavailable")

        monkeypatch.setattr(pa, "get_ml_detector", boom)
        a = pa.PrivacyAnalyzer(use_ml=True)
        text = "telefono 39123456"
        r = a.analyze(text, auto_masking=True)
        assert "Phone E.164" in r.detected_categories  # regular keyword path still works
        assert r.ml_assisted_count == 0


class TestPrivacyMLConfig:
    def test_config_defaults(self):
        from synthelion.config import default_config, privacy_config
        defaults = privacy_config(default_config())
        assert defaults["use_ml"] is False  # CPU cost is opt-in
        assert defaults["ml_model"] == "privacyguardml"  # our own in-house model
        assert defaults["ml_min_confidence"] == 0.6

    def test_from_config_builds_ml_analyzer(self):
        from synthelion.privacy_analyzer import PrivacyAnalyzer
        a = PrivacyAnalyzer.from_config({
            "use_ml": True,
            "ml_model": "custom/model",
            "ml_min_confidence": 0.7,
            "whitelist": ["privacy@example.com"],
        })
        assert a._use_ml is True
        assert a._ml_model == "custom/model"
        assert a._ml_min_confidence == 0.7
        assert a.is_whitelisted("privacy@example.com")


class TestPrivacyMLPathResolution:
    """list_installed_models is purely local — no network, no third-party
    import — and only ever lists a checkpoint that declares itself
    `model_type: "privacyguardml"`, since that is the only backend supported."""

    def _isolate_roots(self, tmp_path, monkeypatch):
        """A real PrivacyGuardML checkpoint ships in synthelion/ml_models/ —
        list_installed_models() merges every root, so an env override alone
        doesn't hide it; the packaged (and user) roots must be pointed
        elsewhere for these tests to see a clean "nothing installed" state."""
        import synthelion.privacy_ml as pm
        monkeypatch.setattr(pm, "packaged_models_dir", lambda: tmp_path / "no_packaged")
        monkeypatch.setattr(pm, "user_models_dir", lambda: tmp_path / "no_user")

    def _write_model_dir(self, root, name, model_type=None, weight_file="model.bin"):
        import json
        d = root / name
        d.mkdir(parents=True)
        config = {"model_type": model_type} if model_type else {}
        (d / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (d / weight_file).write_text("weights", encoding="utf-8")
        return d

    def test_list_installed_empty(self, tmp_path, monkeypatch):
        from synthelion.privacy_ml import list_installed_models
        self._isolate_roots(tmp_path, monkeypatch)
        monkeypatch.setenv("SYNTHELION_ML_MODELS_DIR", str(tmp_path / "env"))
        assert list_installed_models() == []

    def test_privacyguardml_checkpoint_is_listed(self, tmp_path, monkeypatch):
        from synthelion.privacy_ml import list_installed_models
        self._isolate_roots(tmp_path, monkeypatch)
        env_root = tmp_path / "env"
        self._write_model_dir(env_root, "privacyguardml", model_type="privacyguardml")
        monkeypatch.setenv("SYNTHELION_ML_MODELS_DIR", str(env_root))
        assert [n for n, _, _ in list_installed_models()] == ["privacyguardml"]

    def test_synthelionml_checkpoint_is_not_a_privacy_model(self, tmp_path, monkeypatch):
        """The compression checkpoint shares the ml_models/ root and has the
        same config.json + weights shape, but it is a different subsystem's
        model — it must never be offered as a PII model."""
        from synthelion.privacy_ml import list_installed_models
        self._isolate_roots(tmp_path, monkeypatch)
        env_root = tmp_path / "env"
        self._write_model_dir(env_root, "synthelionml", model_type="synthelionml")
        monkeypatch.setenv("SYNTHELION_ML_MODELS_DIR", str(env_root))
        assert list_installed_models() == []

    def test_model_without_declared_type_is_not_listed(self, tmp_path, monkeypatch):
        """Unlike the old GLiNER-era exclusion-list check, only an explicit
        `model_type: "privacyguardml"` counts — absence is not "ours"."""
        from synthelion.privacy_ml import list_installed_models
        self._isolate_roots(tmp_path, monkeypatch)
        env_root = tmp_path / "env"
        self._write_model_dir(env_root, "plain-model")
        monkeypatch.setenv("SYNTHELION_ML_MODELS_DIR", str(env_root))
        assert list_installed_models() == []

    def test_unreadable_config_does_not_crash_the_scan(self, tmp_path, monkeypatch):
        """A corrupt config.json must not take down `models status`."""
        from synthelion.privacy_ml import list_installed_models
        self._isolate_roots(tmp_path, monkeypatch)
        env_root = tmp_path / "env"
        d = env_root / "broken"
        d.mkdir(parents=True)
        (d / "config.json").write_text("{not json", encoding="utf-8")
        (d / "model.bin").write_text("weights", encoding="utf-8")
        monkeypatch.setenv("SYNTHELION_ML_MODELS_DIR", str(env_root))
        assert list_installed_models() == []