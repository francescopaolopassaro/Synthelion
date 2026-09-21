# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# (c) 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Shared test fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest


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
