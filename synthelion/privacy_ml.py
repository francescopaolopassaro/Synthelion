# Synthelion — Python port of Caveman.PrivacyGuard (https://github.com/francescopaolopassaro/Caveman.PrivacyGuard)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Optional ML-assisted confirmation layer for the privacy analyzer — fully
offline, model bundled inside Synthelion (no third-party download, ever).

The core PrivacyGuard tier is regex + checksum validators and is deliberately
zero-ML (see `privacy_rules.yaml`). This module is the *opt-in* counterpart:
when `privacy.use_ml = true` it runs Synthelion's own PrivacyGuardML model
(`privacyguardml.py`) over the text and exposes the detected entity spans to
`PrivacyAnalyzer`. The spans are used only as a **confirmation signal** — a
genuinely sensitive bare value (phone number, national-ID format, ...) that
matches a context-gated rule but has no keyword around it can be confirmed by an
overlapping ML span whose label maps to that rule's category. A failed
algorithmic checksum still vetoes detection no matter what the model says, so ML
never introduces false positives: it only recovers recall that the strict
context gate intentionally trades away.

**Everything is local — zero network dependency, ever.** PrivacyGuardML ships
inside the wheel at `synthelion/ml_models/privacyguardml/`; there is no
download step and no third-party model (the earlier `urchade/gliner_small-v2.1`
wrapper was removed once PrivacyGuardML matched it end to end on real masking
tests — see devtools/train_privacyguardml.py). If the checkpoint is somehow
missing, `detect()` degrades gracefully to `[]` with a one-line warning.
"""
from __future__ import annotations

import importlib.resources
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "privacyguardml"


@dataclass(frozen=True)
class MLSpan:
    """One entity the ML model detected, with character offsets into the
    original text (relative to the string that was scanned)."""

    start: int
    end: int
    value: str
    label: str
    confidence: float


# ── model roots / resolution (all local, no network) ────────────────────────


def user_models_dir() -> Path:
    return Path.home() / ".synthelion" / "ml_models"


def packaged_models_dir() -> Path:
    return Path(str(importlib.resources.files("synthelion").joinpath("ml_models")))


def models_root_candidates(env_dir: str | None = None) -> list[Path]:
    """The model roots in priority order."""
    roots: list[Path] = []
    env = env_dir or os.environ.get("SYNTHELION_ML_MODELS_DIR")
    if env:
        roots.append(Path(env))
    roots.append(user_models_dir())
    roots.append(packaged_models_dir())
    return roots


# `ml_models/` is a root shared by more than one Synthelion subsystem: the
# PrivacyGuardML checkpoint this module manages, and the SynthelionML
# *compression* checkpoint (see synthelionml.py). Both ship a config.json plus
# a weights file, so the layout check below would otherwise claim the wrong
# one — each declares its own `model_type`, so anything that isn't
# "privacyguardml" is excluded rather than assumed to be ours.
_PRIVACY_MODEL_TYPE = "privacyguardml"


def _declared_model_type(config_path: Path) -> str:
    try:
        import json
        with open(config_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return ""
    return data.get("model_type", "") if isinstance(data, dict) else ""


def _looks_like_privacy_model_dir(d: Path) -> bool:
    if not d.is_dir():
        return False
    config = d / "config.json"
    if not config.is_file():
        return False
    if _declared_model_type(config) != _PRIVACY_MODEL_TYPE:
        return False
    return any((d / w).is_file() for w in ("model.bin", "model.safetensors"))


def list_installed_models(env_dir: str | None = None) -> list[tuple[str, Path, int]]:
    """Models found on disk under the roots: (short name, path, size in bytes)."""
    found: dict[str, tuple[Path, int]] = {}
    for root in models_root_candidates(env_dir):
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if _looks_like_privacy_model_dir(child):
                size = sum(f.stat().st_size for f in child.rglob("*") if f.is_file())
                found.setdefault(child.name, (child, size))
    return [(n, p, s) for n, (p, s) in found.items()]


def get_ml_detector(
    model_name: str = DEFAULT_MODEL_NAME,
    min_confidence: float = 0.6,
):
    """Cached detector factory — one detector instance per (model, threshold) is
    shared by all analyzers/threads, so the bundled model is loaded (and held in
    memory) once instead of per call. Always returns a
    `privacyguardml.PrivacyGuardMLDetector` — PrivacyGuardML is the only ML
    backend PrivacyGuard supports.
    """
    key = f"{model_name}|{min_confidence}"
    with _detector_lock:
        det = _detectors.get(key)
        if det is None:
            det = _build_detector(model_name, min_confidence)
            _detectors[key] = det
        return det


def _build_detector(model_name: str, min_confidence: float):
    from synthelion import privacyguardml as _pg

    if not model_name or model_name == _pg._MODEL_DIR_NAME:
        return _pg.PrivacyGuardMLDetector(_pg.resolve_model_path(), min_confidence)

    candidate = Path(model_name).expanduser()
    search_dirs = [candidate] if candidate.is_dir() else []
    for root in models_root_candidates():
        search_dirs.append(root / candidate.name)
        if model_name != candidate.name:
            search_dirs.append(root / model_name)
    for d in search_dirs:
        if _looks_like_privacy_model_dir(d):
            return _pg.PrivacyGuardMLDetector(d, min_confidence)

    return _pg.PrivacyGuardMLDetector(None, min_confidence)


_detectors: dict[str, "_pg.PrivacyGuardMLDetector"] = {}
_detector_lock = threading.Lock()