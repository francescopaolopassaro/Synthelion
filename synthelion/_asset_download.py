# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Shared lazy-download helper for large data/model assets that live on
Hugging Face instead of inside the PyPI wheel, to keep the published package
under PyPI's size limit. Every asset here is Synthelion's own work — no
third-party content — just hosted externally because of size, not authorship:

- `digitalsolutiosai/synthelion-worddata` (dataset) — per-language function
  word / IDF / POS tables, used by every `compress()` call.
- `digitalsolutiosai/synthellion` (model) — SynthelionML compression checkpoint.
- `digitalsolutiosai/privacyguardml` (model) — PrivacyGuardML PII-confirmation
  checkpoint.

Resolution for each asset checks, in order: an env var override, then
`~/.synthelion/<name>`, then the packaged `synthelion/<name>` (present only if
a build chose to bundle it). If nothing local is found, one download populates
`~/.synthelion/<name>` — after that it behaves exactly like a bundled asset.
The download happens at most once per process per asset (a failure isn't
retried within the same run, to avoid hammering the network); callers that get
`None` back degrade exactly as they would for a missing bundled asset.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

WORDDATA_REPO_ID = "digitalsolutiosai/synthelion-worddata"
SYNTHELIONML_REPO_ID = "digitalsolutiosai/synthellion"
PRIVACYGUARDML_REPO_ID = "digitalsolutiosai/privacyguardml"

_download_lock = threading.Lock()
_attempted: set[str] = set()


def _has_content(d: Path) -> bool:
    try:
        return d.is_dir() and any(d.iterdir())
    except OSError:
        return False


def fetch_once(repo_id: str, repo_type: str, dest_dir: Path, what: str) -> Path | None:
    """Download `repo_id` into `dest_dir` if it isn't already populated.

    Returns `dest_dir` on success (including "already had content"), or
    `None` if the download couldn't happen (no `huggingface_hub`, no
    network, repo error) — callers treat that exactly like a missing
    bundled asset, never raise.
    """
    if _has_content(dest_dir):
        return dest_dir

    with _download_lock:
        if _has_content(dest_dir):  # re-check: another thread may have finished
            return dest_dir
        if repo_id in _attempted:
            return None
        _attempted.add(repo_id)

        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            log.warning(
                "%s not found locally and `huggingface_hub` isn't installed — "
                "pip install huggingface_hub to enable automatic download "
                "(one-time, from https://huggingface.co/%s), or fetch it "
                "manually into %s.",
                what, repo_id, dest_dir,
            )
            return None

        try:
            log.info("Downloading %s from %s (one-time, into %s)...", what, repo_id, dest_dir)
            dest_dir.mkdir(parents=True, exist_ok=True)
            snapshot_download(repo_id=repo_id, repo_type=repo_type, local_dir=str(dest_dir))
            log.info("%s ready at %s", what, dest_dir)
            return dest_dir
        except Exception as exc:  # noqa: BLE001 — never let a network hiccup break the caller
            log.warning("Failed to download %s from %s (%s); continuing without it.", what, repo_id, exc)
            return None


def _asset_present(*, subpath: str, env_var: str, env_is_direct: bool) -> bool:
    """Cheap presence check (no download) across the same root order the
    resolvers use — for the startup check, which reports before it acts.

    `env_is_direct`: worddata's env var names the worddata dir itself; the ML
    models' env var (`SYNTHELION_ML_MODELS_DIR`) names a *root* that a model
    short name is joined onto — same distinction the resolvers already make.
    """
    import os
    env = os.environ.get(env_var)
    candidates = []
    if env:
        candidates.append(Path(env) if env_is_direct else Path(env) / Path(subpath).name)
    candidates.append(Path.home() / ".synthelion" / subpath)
    candidates.append(Path(__file__).resolve().parent / subpath)
    return any(_has_content(d) for d in candidates)


def check_and_fetch_startup_assets(download_models: bool = True) -> dict[str, bool]:
    """Startup check: is worddata present, and (if `download_models`) are the
    ML checkpoints present? Anything missing is logged as a warning and then
    downloaded — same one-time-per-process behaviour as the lazy resolvers,
    just run eagerly instead of waiting for the first call that needs it.

    Returns {asset: bool} — True means "present after this call" (already
    there, or freshly downloaded), False means the download also failed.
    Never raises: a fully offline machine just runs in degraded mode, same
    as always.
    """
    results: dict[str, bool] = {}

    worddata_dir = Path.home() / ".synthelion" / "worddata"
    if _asset_present(subpath="worddata", env_var="SYNTHELION_WORDDATA_DIR", env_is_direct=True):
        results["worddata"] = True
    else:
        log.warning("Synthelion worddata not found locally — downloading from %s...", WORDDATA_REPO_ID)
        results["worddata"] = fetch_once(WORDDATA_REPO_ID, "dataset", worddata_dir, "Synthelion worddata") is not None

    if not download_models:
        return results

    for asset_name, repo_id, what in (
        ("synthelionml", SYNTHELIONML_REPO_ID, "SynthelionML checkpoint"),
        ("privacyguardml", PRIVACYGUARDML_REPO_ID, "PrivacyGuardML checkpoint"),
    ):
        dest = Path.home() / ".synthelion" / "ml_models" / asset_name
        if _asset_present(subpath=f"ml_models/{asset_name}", env_var="SYNTHELION_ML_MODELS_DIR", env_is_direct=False):
            results[asset_name] = True
        else:
            log.warning("%s not found locally — downloading from %s...", what, repo_id)
            results[asset_name] = fetch_once(repo_id, "model", dest, what) is not None

    return results
