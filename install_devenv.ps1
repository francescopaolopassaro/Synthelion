# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
#
# Developer environment setup — Windows
#
# `git clone` alone does NOT give you a working dev checkout: worddata
# (per-language function-word/IDF/POS tables) and the ML checkpoints
# (SynthelionML, PrivacyGuardML) are excluded from git and from the PyPI
# wheel (see .gitignore, pyproject.toml package-data) — both ship from
# Hugging Face instead and are normally auto-downloaded on first use into
# ~/.synthelion/. This script does the same downloads but places the files
# directly INTO the repo tree (synthelion\worddata\, synthelion\ml_models\),
# which is what a from-source dev checkout needs to actually run and test.
#
# Usage:
#   .\install_devenv.ps1

$ErrorActionPreference = "Stop"

function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Info($msg) { Write-Host "  ->   $msg" -ForegroundColor Cyan }
function Write-Err($msg)  { Write-Host "  [X]  $msg" -ForegroundColor Red }
function Write-H1($msg)   { Write-Host "`n$msg" -ForegroundColor Cyan }

# Native (non-cmdlet) commands don't throw on failure — $ErrorActionPreference
# doesn't cover them, only $LASTEXITCODE does. Every call below is checked
# explicitly so a failed download or install is reported, not silently
# followed by a false "[OK]".
function Invoke-Checked($what) {
    if ($LASTEXITCODE -ne 0) {
        Write-Err "$what failed (exit code $LASTEXITCODE)."
        exit 1
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-H1 "Synthelion - developer environment setup"

if (-not (Test-Path "pyproject.toml") -or -not (Select-String -Path "pyproject.toml" -Pattern '^name = "synthelion"' -Quiet)) {
    Write-Err "Run this from the root of a Synthelion checkout (pyproject.toml not found here)."
    exit 1
}

$python = "python"
try { & $python --version *>$null } catch { $python = "py" }
try { & $python --version *>$null } catch { Write-Err "Python not found on PATH."; exit 1 }
Write-Ok "Using $(& $python --version 2>&1)"

Write-Info "Ensuring huggingface_hub is installed..."
& $python -m pip install --quiet --upgrade huggingface_hub
Invoke-Checked "huggingface_hub install"
Write-Ok "huggingface_hub ready"

# Python string literals below use single quotes on purpose: PowerShell's
# argv marshalling to a native exe can strip embedded double-quote characters
# from a here-string argument, which silently turns "digitalsolutionsai/..."
# into a bare (and syntactically broken) expression on the Python side.
Write-Info "Downloading worddata (56+ languages, ~143MB)..."
& $python -c @'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='digitalsolutionsai/synthelion-worddata', repo_type='dataset',
    local_dir='synthelion/worddata',
)
'@
Invoke-Checked "worddata download"
Write-Ok "worddata ready at synthelion\worddata\"

Write-Info "Downloading SynthelionML checkpoint (~40MB)..."
& $python -c @'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='digitalsolutionsai/synthellion', repo_type='model',
    local_dir='synthelion/ml_models/synthelionml',
)
'@
Invoke-Checked "SynthelionML download"
Write-Ok "SynthelionML ready at synthelion\ml_models\synthelionml\"

Write-Info "Downloading PrivacyGuardML checkpoint (~25MB)..."
& $python -c @'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='digitalsolutionsai/privacyguardml', repo_type='model',
    local_dir='synthelion/ml_models/privacyguardml',
)
'@
Invoke-Checked "PrivacyGuardML download"
Write-Ok "PrivacyGuardML ready at synthelion\ml_models\privacyguardml\"

Write-Info "Installing Synthelion in editable mode with dev dependencies..."
& $python -m pip install --quiet -e ".[dev]"
if ($LASTEXITCODE -ne 0) {
    Write-Err "Editable install failed (exit code $LASTEXITCODE). If a synthelion*.exe is 'in use', stop any running synthelion/synthelion-mcp process first, then re-run this script."
    exit 1
}
Write-Ok "synthelion installed (editable)"

Write-H1 "Done - dev environment ready"
Write-Host "  Run the test suite with:  pytest tests/ -q"
