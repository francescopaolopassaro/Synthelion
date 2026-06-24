#!/usr/bin/env bash
# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
#
# Synthelion installer for Claude Code — Linux / macOS
#
# Usage:
#   chmod +x install_claude.sh
#   ./install_claude.sh              # install
#   ./install_claude.sh --upgrade    # update to latest version
#   ./install_claude.sh --no-hook    # install without auto-compression hook
#   ./install_claude.sh --uninstall  # remove everything

set -euo pipefail

# ── colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[0;33m'; RED='\033[0;31m'
BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✓ ${RESET}$*"; }
info() { echo -e "${CYAN}  → ${RESET}$*"; }
warn() { echo -e "${YELLOW}  ! ${RESET}$*"; }
err()  { echo -e "${RED}  ✗ ${RESET}$*"; }
h1()   { echo -e "\n${BOLD}${CYAN}$*${RESET}"; }
h2()   { echo -e "\n${BOLD}$*${RESET}"; }

# ── argument parsing ─────────────────────────────────────────────────────────
UPGRADE=false; NO_HOOK=false; UNINSTALL=false; NO_PIP=false
for arg in "$@"; do
  case "$arg" in
    --upgrade)   UPGRADE=true ;;
    --no-hook)   NO_HOOK=true ;;
    --uninstall) UNINSTALL=true ;;
    --no-pip)    NO_PIP=true ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

# ── detect python ─────────────────────────────────────────────────────────────
PY=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then PY="$cmd"; break; fi
done
if [ -z "$PY" ]; then
  err "Python not found. Install Python 3.11+ from https://www.python.org/"
  exit 1
fi

# ── settings.json ─────────────────────────────────────────────────────────────
SETTINGS="$HOME/.claude/settings.json"

load_settings() {
  if [ -f "$SETTINGS" ]; then
    cat "$SETTINGS"
  else
    echo '{}'
  fi
}

save_settings() {
  local data="$1"
  mkdir -p "$(dirname "$SETTINGS")"
  echo "$data" > "$SETTINGS"
  ok "Saved → $SETTINGS"
}

# ── find synthelion binaries ──────────────────────────────────────────────────
find_mcp_binary() {
  # 1. Same bin as the running Python
  local py_bin; py_bin=$(command -v "$PY")
  local py_dir; py_dir=$(dirname "$py_bin")
  if [ -x "$py_dir/synthelion-mcp" ]; then
    echo "$py_dir/synthelion-mcp"; return
  fi
  # 2. PATH
  if command -v synthelion-mcp &>/dev/null; then
    command -v synthelion-mcp; return
  fi
  # 3. ~/.local/bin (pip --user install)
  if [ -x "$HOME/.local/bin/synthelion-mcp" ]; then
    echo "$HOME/.local/bin/synthelion-mcp"; return
  fi
  echo ""
}

find_cli_binary() {
  if command -v synthelion &>/dev/null; then
    command -v synthelion; return
  fi
  if [ -x "$HOME/.local/bin/synthelion" ]; then
    echo "$HOME/.local/bin/synthelion"; return
  fi
  echo "synthelion"
}

# ── build hook command (bash) ─────────────────────────────────────────────────
build_hook_command() {
  local cli="$1"
  # Single-line bash command for the hook
  cat <<EOF
prompt=\$(cat | $PY -c "import sys,json; print(json.load(sys.stdin).get('prompt',''))"); if [ \${#prompt} -gt 200 ]; then r=\$(printf '%s' "\$prompt" | "$cli" compress --json 2>/dev/null); eff=\$(printf '%s' "\$r" | $PY -c "import sys,json; d=json.load(sys.stdin); print(int(d.get('efficiency_pct',0)))"); comp=\$(printf '%s' "\$r" | $PY -c "import sys,json; print(json.load(sys.stdin).get('compressed',''))"); if [ "\$eff" -gt 15 ]; then $PY -c "import json; print(json.dumps({'hookSpecificOutput':{'hookEventName':'UserPromptSubmit','additionalContext':'[Synthelion {}% saved] {}'.format(\$eff,'\$comp')}}))"; fi; fi
EOF
}

# ── configure Claude Code ─────────────────────────────────────────────────────
configure_claude() {
  local mcp_bin="$1"
  local add_hook="$2"

  h2 "Configuring Claude Code…"
  info "Settings: $SETTINGS"

  local current; current=$(load_settings)

  # Build MCP config using Python for safe JSON manipulation
  current=$($PY - <<PYEOF
import json, sys
data = json.loads('''$current''')
data.setdefault('mcpServers', {})

mcp_bin = '''$mcp_bin'''
if mcp_bin:
    data['mcpServers']['synthelion'] = {'command': mcp_bin}
else:
    data['mcpServers']['synthelion'] = {
        'command': '$PY',
        'args': ['-m', 'synthelion.plugins.mcp_server']
    }

print(json.dumps(data, indent=2, ensure_ascii=False))
PYEOF
)
  ok "MCP server configured"

  if [ "$add_hook" = "true" ]; then
    local cli; cli=$(find_cli_binary)
    local hook_cmd; hook_cmd=$(build_hook_command "$cli" | tr -d '\n')

    current=$($PY - <<PYEOF
import json
data = json.loads(r"""$current""")
hook_entry = {
    "type": "command",
    "shell": "bash",
    "command": """$hook_cmd""",
    "statusMessage": "Compressing prompt...",
    "timeout": 15,
}
hooks = data.setdefault("hooks", {})
existing = [g for g in hooks.get("UserPromptSubmit", [])
            if not any("synthelion" in h.get("command","") for h in g.get("hooks",[]))]
existing.append({"hooks": [hook_entry]})
hooks["UserPromptSubmit"] = existing
print(json.dumps(data, indent=2, ensure_ascii=False))
PYEOF
)
    ok "UserPromptSubmit hook configured"
  fi

  save_settings "$current"
}

# ── remove configuration ──────────────────────────────────────────────────────
remove_claude_config() {
  h2 "Removing Synthelion from Claude Code…"
  if [ ! -f "$SETTINGS" ]; then
    warn "settings.json not found — nothing to remove."
    return
  fi

  local current; current=$(load_settings)
  current=$($PY - <<PYEOF
import json
data = json.loads(r"""$current""")
# Remove MCP
mcp = data.get("mcpServers", {})
if "synthelion" in mcp:
    del mcp["synthelion"]
    print("  ✓ MCP server removed", flush=True)

# Remove hook
hooks = data.get("hooks", {})
before = len(hooks.get("UserPromptSubmit", []))
hooks["UserPromptSubmit"] = [
    g for g in hooks.get("UserPromptSubmit", [])
    if not any("synthelion" in h.get("command","") for h in g.get("hooks",[]))
]
if before != len(hooks["UserPromptSubmit"]):
    print("  ✓ Hook removed", flush=True)
if not hooks.get("UserPromptSubmit"):
    hooks.pop("UserPromptSubmit", None)
if not hooks:
    data.pop("hooks", None)

import sys
print(json.dumps(data, indent=2, ensure_ascii=False))
PYEOF
)
  save_settings "$current"
}

# ── smoke test ────────────────────────────────────────────────────────────────
smoke_test() {
  h2 "Running smoke test…"
  local result
  result=$($PY - <<PYEOF
from synthelion import CompressionService, CompressionLevel
svc = CompressionService()
r = svc.compress(
    "I would like to know if it is possible to receive information.",
    CompressionLevel.SEMANTIC,
)
assert r.compressed_text, "empty output"
print(f"{r.original_tokens}to{r.compressed_tokens} tokens ({r.efficiency_pct:.0f}% saved): {r.compressed_text}")
PYEOF
)
  ok "compress OK — $result"
}

# ── main ─────────────────────────────────────────────────────────────────────
h1 "Synthelion Installer for Claude Code (Linux / macOS)"
echo "  Platform : $(uname -s) $(uname -m)"
echo "  Python   : $($PY --version)"

if [ "$UNINSTALL" = "true" ]; then
  remove_claude_config
  if [ "$NO_PIP" = "false" ]; then
    h2 "Uninstalling Synthelion…"
    $PY -m pip uninstall -y synthelion && ok "Synthelion uninstalled" || warn "Not installed via pip"
  fi
  h1 "Uninstall complete."
  exit 0
fi

# Check Python version
h2 "Checking Python version…"
PY_VER=$($PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PY -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PY -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
  err "Python $PY_VER found — Synthelion needs 3.11+."
  err "Download from https://www.python.org/downloads/"
  exit 1
fi
ok "Python $PY_VER"

# pip install
if [ "$NO_PIP" = "false" ]; then
  h2 "Installing Synthelion…"
  if [ "$UPGRADE" = "true" ]; then
    $PY -m pip install --upgrade synthelion
  else
    $PY -m pip install synthelion
  fi
  ok "pip install synthelion succeeded"
fi

MCP_BIN=$(find_mcp_binary)
if [ -n "$MCP_BIN" ]; then
  info "synthelion-mcp found: $MCP_BIN"
else
  warn "synthelion-mcp not in PATH — will use Python module form"
fi

smoke_test

ADD_HOOK="true"
[ "$NO_HOOK" = "true" ] && ADD_HOOK="false"
configure_claude "$MCP_BIN" "$ADD_HOOK"

h1 "Installation complete!"
echo ""
echo "  Next steps:"
echo "  1. Restart Claude Code (or open /hooks to reload)"
echo "  2. Ask Claude: 'Use Synthelion to compress this text'"
echo "  3. Prompts > 200 chars are auto-compressed"
echo ""
echo "  To update:"
echo "    ./install_claude.sh --upgrade"
echo ""
echo "  To uninstall:"
echo "    ./install_claude.sh --uninstall"
echo ""
