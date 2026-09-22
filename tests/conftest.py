# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# (c) 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Shared test fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def no_network_asset_download(monkeypatch):
    """Every worddata/model resolution path falls back to a Hugging Face
    download when nothing is found locally (see `synthelion._asset_download`).
    Without this, a test environment with no local checkpoint would trigger a
    real network call on every run — slow, non-deterministic, and broken
    offline. Tests get the same "nothing available" degradation a real
    offline install would see; opt out per-test by monkeypatching
    `fetch_once` again if a test specifically needs to exercise the download
    path (see tests/test_word_provider.py / test_privacyguardml.py)."""
    import synthelion._asset_download as ad
    monkeypatch.setattr(ad, "fetch_once", lambda *a, **k: None)


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Redirect ``Path.home()`` so a test writes no state into the real
    ``~/.synthelion/``.

    Several guards append to cross-process JSONL logs on every match
    (EnterpriseGuard's block log, the agent-policy decision log, the
    compliance audit trail). Tests feed those guards deliberately malicious
    samples by the dozen, so without isolation the operator's real security
    log fills with incidents that never happened — the dashboard's "Recent
    blocks" table and the notification counters then report them as fact, and
    a genuine block is buried among hundreds of test artefacts.

    On Windows ``Path.home()`` reads USERPROFILE rather than $HOME, so the
    method itself is patched instead of the environment variable.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home
