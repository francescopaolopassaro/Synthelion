#!/usr/bin/env bash
# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
#
# Developer environment setup — Linux / macOS
#
# `git clone` alone does NOT give you a working dev checkout: worddata
# (per-language function-word/IDF/POS tables) and the ML checkpoints
# (SynthelionML, PrivacyGuardML) are excluded from git and from the PyPI
# wheel (see .gitignore, pyproject.toml package-data) — both ship from
# Hugging Face instead and are normally auto-downloaded on first use into
# ~/.synthelion/. This script does the same downloads but places the files
# directly INTO the repo tree (synthelion/worddata/, synthelion/ml_models/),
# which is what a from-source dev checkout needs to actually run and test.
#
# Usage:
#   chmod +x install_devenv.sh
#   ./install_devenv.sh

set -euo pipefail

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[0;33m'; RED='\033[0;31m'
BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✓ ${RESET}$*"; }
info() { echo -e "${CYAN}  → ${RESET}$*"; }
warn() { echo -e "${YELLOW}  ! ${RESET}$*"; }
err()  { echo -e "${RED}  ✗ ${RESET}$*"; }
h1()   { echo -e "\n${BOLD}${CYAN}$*${RESET}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

h1 "Synthelion — developer environment setup"

if [ ! -f "pyproject.toml" ] || ! grep -q '^name = "synthelion"' pyproject.toml 2>/dev/null; then
  err "Run this from the root of a Synthelion checkout (pyproject.toml not found here)."
  exit 1
fi

# `command -v` alone isn't enough on Windows/Git Bash: a Microsoft Store
# "python3"/"python" App Execution Alias can sit on PATH and satisfy
# command -v while actually failing (with a redirect-to-Store message) the
# moment it runs — so each candidate is also exit-code-checked before use.
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" --version >/dev/null 2>&1; then
      PYTHON="$candidate"
      break
    fi
  done
fi
[ -n "$PYTHON" ] || { err "Python not found on PATH (or only a Microsoft Store alias stub is present — install Python from python.org and re-run)."; exit 1; }
ok "Using $($PYTHON --version 2>&1)"

info "Ensuring huggingface_hub is installed..."
"$PYTHON" -m pip install --quiet --upgrade huggingface_hub >/dev/null
ok "huggingface_hub ready"

info "Downloading worddata (56+ languages, ~143MB)..."
"$PYTHON" - <<'PYEOF'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="digitalsolutiosai/synthelion-worddata", repo_type="dataset",
    local_dir="synthelion/worddata",
)
PYEOF
ok "worddata ready at synthelion/worddata/"

info "Downloading SynthelionML checkpoint (~40MB)..."
"$PYTHON" - <<'PYEOF'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="digitalsolutiosai/synthellion", repo_type="model",
    local_dir="synthelion/ml_models/synthelionml",
)
PYEOF
ok "SynthelionML ready at synthelion/ml_models/synthelionml/"

info "Downloading PrivacyGuardML checkpoint (~25MB)..."
"$PYTHON" - <<'PYEOF'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="digitalsolutiosai/privacyguardml", repo_type="model",
    local_dir="synthelion/ml_models/privacyguardml",
)
PYEOF
ok "PrivacyGuardML ready at synthelion/ml_models/privacyguardml/"

info "Installing Synthelion in editable mode with dev dependencies..."
if ! "$PYTHON" -m pip install --quiet -e ".[dev]"; then
  err "Editable install failed. If a synthelion/synthelion-mcp process is currently running, stop it first (a locked .exe/entry-point file is the most common cause), then re-run this script."
  exit 1
fi
ok "synthelion installed (editable)"

h1 "Done — dev environment ready"
echo "  Run the test suite with:  pytest tests/ -q"
