# Synthelion — Python port of Caveman.PrivacyGuard (https://github.com/francescopaolopassaro/Caveman.PrivacyGuard)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for the optional ML-assisted confirmation tier (privacy.use_ml).

These tests exercise the *integration* between PrivacyAnalyzer and a span-
producing detector using a deterministic fake (no GLiNER download, no network,
no CPU cost). The real GLiNER wrapper (privacy_ml.PrivacyMLDetector) is
covered only for its degradation contract, not for inference quality.
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
        assert defaults["ml_model"] == "gliner_small-v2.1"  # local bundled name
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
    """resolve_ml_model_path is purely local — no network, no gliner import."""

    def _make_model_dir(self, root, name):
        d = root / name
        d.mkdir(parents=True)
        (d / "config.json").write_text('{"name":"x"}')
        (d / "model.safetensors").write_bytes(b"\x00" * 12)
        return d

    def test_resolve_direct_path(self, tmp_path):
        from synthelion.privacy_ml import resolve_ml_model_path
        d = self._make_model_dir(tmp_path, "mymodel")
        assert resolve_ml_model_path(str(d)) == d

    def test_resolve_short_name_under_root(self, tmp_path, monkeypatch):
        from synthelion.privacy_ml import resolve_ml_model_path, user_models_dir
        monkeypatch.setenv("SYNTHELION_ML_MODELS_DIR", str(tmp_path))
        self._make_model_dir(tmp_path, "gliner_small-v2.1")
        assert resolve_ml_model_path("gliner_small-v2.1").parent == tmp_path

    def test_resolve_none_when_absent(self, tmp_path, monkeypatch):
        from synthelion.privacy_ml import resolve_ml_model_path
        monkeypatch.setenv("SYNTHELION_ML_MODELS_DIR", str(tmp_path))
        assert resolve_ml_model_path("does-not-exist") is None

    def test_resolve_ignores_invalid_dir(self, tmp_path, monkeypatch):
        from synthelion.privacy_ml import resolve_ml_model_path
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / "config.json").write_text("x")
        monkeypatch.setenv("SYNTHELION_ML_MODELS_DIR", str(tmp_path))
        assert resolve_ml_model_path("bad") is None  # no weights file

    def test_list_installed_empty(self, tmp_path, monkeypatch):
        from synthelion.privacy_ml import list_installed_models
        monkeypatch.setenv("SYNTHELION_ML_MODELS_DIR", str(tmp_path))
        assert list_installed_models() == []