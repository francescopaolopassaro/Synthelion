# Synthelion — Python port of Caveman.PrivacyGuard (https://github.com/francescopaolopassaro/Caveman.PrivacyGuard)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Optional ML-assisted confirmation layer for the privacy analyzer — fully
offline, models bundled inside Synthelion.

The core PrivacyGuard tier is regex + checksum validators and is deliberately
zero-ML (see `privacy_rules.yaml`). This module is the *opt-in* counterpart:
when `privacy.use_ml = true` it runs a small CPU-friendly zero-shot NER model
(GLiNER) over the text and exposes the detected entity spans to
`PrivacyAnalyzer`. The spans are used only as a **confirmation signal** — a
genuinely sensitive bare value (phone number, national-ID format, ...) that
matches a context-gated rule but has no keyword around it can be confirmed by an
overlapping ML span whose label maps to that rule's category. A failed
algorithmic checksum still vetoes detection no matter what the model says, so ML
never introduces false positives: it only recovers recall that the strict
context gate intentionally trades away.

**Technical requirement: everything is local — zero network dependency at
runtime.** The model never downloads on first use. It must exist on disk inside
Synthelion, i.e. under one of the *model roots*:

1. the `SYNTHELION_ML_MODELS_DIR` environment variable (highest priority),
2. `~/.synthelion/ml_models`,
3. the packaged `synthelion/ml_models/` directory (ship-with-the-wheel).

The one-time download happens only inside the explicit admin command
`python -m synthelion models install` (requires `synthelion[ml]`, needs the
network exactly once); after that the runtime loads purely from disk. If no
model is present, every `detect()` call degrades gracefully to `[]` with a
one-line warning instructing to run that command.
"""
from __future__ import annotations

import importlib.resources
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

# Zero-shot entity labels queried at analysis time. GLiNER is label-driven, so
# this tuple IS the vocabulary of "things the ML tier is allowed to confirm".
DEFAULT_ML_LABELS = (
    "phone number",
    "email address",
    "credit card number",
    "bank account number (IBAN)",
    "national identification number",
    "tax identification number",
    "social security number",
    "passport number",
    "driver's license number",
    "GPS coordinates",
)

# Default bundled model *short name*. The full model id used at install time is
# `urchade/gliner_small-v2.1` — a short name (no slash) is what `ml_model` in
# the config points at, so resolution stays local and unambiguous.
DEFAULT_MODEL_NAME = "gliner_small-v2.1"
DEFAULT_MODEL_ID = "urchade/" + DEFAULT_MODEL_NAME


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
# GLiNER PII models this module manages, and the SynthelionML *compression*
# checkpoint (see synthelionml.py). The latter also ships a config.json plus
# weights, so the layout check below would otherwise claim it as an installed
# privacy model — listing it under `synthelion models list` and, worse,
# letting `privacy.ml_model = synthelionml` resolve, which would hand GLiNER a
# compression model to load as a PII detector. Every Synthelion-trained model
# declares its own `model_type`, so exclude the ones that aren't ours to load.
_NON_PRIVACY_MODEL_TYPES = frozenset({"synthelionml"})


def _declared_model_type(config_path: Path) -> str:
    try:
        import json
        with open(config_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return ""
    return data.get("model_type", "") if isinstance(data, dict) else ""


def _looks_like_model_dir(d: Path) -> bool:
    """Minimal GLiNER layout check so `from_pretrained` on a local dir can never
    fall back to the network: config.json + a weights file must be present,
    and the checkpoint must not be another subsystem's model."""
    if not d.is_dir():
        return False
    config = d / "config.json"
    if not config.is_file():
        return False
    if _declared_model_type(config) in _NON_PRIVACY_MODEL_TYPES:
        return False
    return any(
        (d / w).is_file()
        for w in ("model.safetensors", "pytorch_model.bin", "model.ckpt", "onnx/model.onnx", "model.onnx")
    )


def resolve_ml_model_path(model_name: str, env_dir: str | None = None) -> Path | None:
    """Resolve ``model_name`` to a local directory that contains a GLiNER model.

    Accepts either a direct path to an existing model dir (absolute or relative)
    or a short name looked up under each model root. Always returns None (never
    raises, never downloads) when the model is not already on disk.
    """
    if not model_name or not str(model_name).strip():
        return None
    candidate = Path(model_name).expanduser()
    if candidate.is_dir() and _looks_like_model_dir(candidate):
        return candidate

    # Try the short name (basename strips a bundled "owner/name" style config).
    short = candidate.name or candidate.parts[-1]
    for root in models_root_candidates(env_dir):
        for name in (candidate.name, short):
            p = root / name
            if _looks_like_model_dir(p):
                return p
            # Also allow "owner/name" -> root/name with the owner segment intact.
            p2 = root / model_name
            if _looks_like_model_dir(p2):
                return p2
    return None


def list_installed_models(env_dir: str | None = None) -> list[tuple[str, Path, int]]:
    """Models found on disk under the roots: (short name, path, size in bytes)."""
    found: dict[str, tuple[Path, int]] = {}
    for root in models_root_candidates(env_dir):
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if _looks_like_model_dir(child):
                size = sum(f.stat().st_size for f in child.rglob("*") if f.is_file())
                found.setdefault(child.name, (child, size))
    return [(n, p, s) for n, (p, s) in found.items()]


def install_model(
    model_id: str = DEFAULT_MODEL_ID,
    name: str | None = None,
    dest: str | None = None,
) -> tuple[str, Path, int]:
    """One-time admin step: download ``model_id`` from Hugging Face into a local
    model root (default: the packaged ``synthelion/ml_models/`` dir when writable,
    else ``~/.synthelion/ml_models``). After this, runtime is fully offline.
    Requires the `ml` extra (`synthelion[ml]`) for both `gliner` and
    `huggingface_hub`.
    """
    short = name or Path(model_id.rstrip("/")).name
    if dest:
        dest_dir = Path(dest).expanduser()
    else:
        env = os.environ.get("SYNTHELION_ML_MODELS_DIR")
        if env:
            dest_dir = Path(env)
        else:
            packaged = packaged_models_dir()
            dest_dir = packaged if _writable(packaged) else user_models_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "`synthelion models install` needs the `ml` extra: pip install \"synthelion[ml]\""
        ) from exc

    target = dest_dir / short
    snapshot_download(repo_id=model_id, local_dir=str(target))
    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    log.info("Installed ML model %s -> %s (%d bytes)", model_id, target, size)
    return short, target, size


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False


class PrivacyMLDetector:
    """Lazy, thread-safe, offline wrapper around a local GLiNER model.

    The model is loaded once on the first `detect()` call from disk only (never
    downloaded at runtime), and reused afterwards — threads share the same
    instance via the module-level `get_ml_detector()` cache, with a lock
    serializing inference since one model instance is not safe to run
    concurrently.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        min_confidence: float = 0.6,
        labels: Iterable[str] = DEFAULT_ML_LABELS,
    ) -> None:
        self._model_name = model_name
        self._min_confidence = min_confidence
        self._labels = tuple(labels)
        self._model = None
        self._init_lock = threading.Lock()
        self._infer_lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        with self._init_lock:
            if self._model is not None:
                return self._model
            path = resolve_ml_model_path(self._model_name)
            if path is None:
                log.warning(
                    "privacy.use_ml is enabled but no local ML model named %r is installed — "
                    "run `synthelion models install` (one network call), then everything is "
                    "offline. Analysis falls back to regex-only for now.",
                    self._model_name,
                )
                return None
            try:
                from gliner import GLiNER  # optional dependency (pyproject `ml` extra)

                # path layout is pre-verified, so this load is strictly local.
                model = GLiNER.from_pretrained(str(path))
            except Exception as exc:
                log.warning(
                    "privacy.use_ml is enabled but the local model at %s failed to load (%s); "
                    "falling back to regex-only analysis",
                    path, exc,
                )
                return None
            self._model = model
            return model

    def detect(self, text: str) -> list[MLSpan]:
        model = self._ensure_model()
        if model is None or not text.strip():
            return []
        try:
            with self._infer_lock:
                preds = model.predict_entities(text, self._labels, threshold=self._min_confidence)
        except Exception as exc:
            log.warning(
                "GLiNER inference failed (%s); falling back to regex-only analysis", exc,
            )
            return []

        spans: list[MLSpan] = []
        for p in preds or []:
            start = int(p.get("start", -1))
            end = int(p.get("end", -1))
            value = str(p.get("text") or p.get("value") or "").strip()
            label = str(p.get("label", "")).lower()
            confidence = float(p.get("score") or p.get("confidence") or 0.0)
            if start < 0 or end < 0 or (end - start) <= 0:
                # Older GLiNER versions may not return char offsets; recover them
                # by locating the predicted span value in the source text.
                start = text.find(value)
                end = start + len(value) if start >= 0 else -1
            if 0 <= start < end <= len(text):
                spans.append(MLSpan(start, end, value, label, confidence))
        return spans


def get_ml_detector(
    model_name: str = DEFAULT_MODEL_NAME,
    min_confidence: float = 0.6,
) -> PrivacyMLDetector:
    """Cached detector factory — one detector instance per (model, threshold) is
    shared by all analyzers/threads, so the bundled model is loaded (and held in
    memory) once instead of per call."""
    key = f"{model_name}|{min_confidence}"
    with _detector_lock:
        det = _detectors.get(key)
        if det is None:
            det = PrivacyMLDetector(model_name, min_confidence)
            _detectors[key] = det
        return det


_detectors: dict[str, PrivacyMLDetector] = {}
_detector_lock = threading.Lock()