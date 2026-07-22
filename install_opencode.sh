#!/usr/bin/env bash
# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
#
# Synthelion installer for OpenCode — Linux / macOS
#
# Usage:
#   chmod +x install_opencode.sh
#   ./install_opencode.sh              # install (global config)
#   ./install_opencode.sh --local      # install into project-local .opencode/
#   ./install_opencode.sh --upgrade    # update to latest version
#   ./install_opencode.sh --no-plugin  # install without the auto-compression plugin
#   ./install_opencode.sh --uninstall  # remove everything

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
LOCAL=false; UPGRADE=false; NO_PLUGIN=false; NO_RULES=false; UNINSTALL=false; NO_PIP=false; CHROMADB=false
for arg in "$@"; do
  case "$arg" in
    --local)     LOCAL=true ;;
    --upgrade)   UPGRADE=true ;;
    --no-plugin) NO_PLUGIN=true ;;
    --no-rules)  NO_RULES=true ;;
    --uninstall) UNINSTALL=true ;;
    --no-pip)    NO_PIP=true ;;
    --chromadb)  CHROMADB=true ;;
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

# ── config paths ───────────────────────────────────────────────────────────────
RULES_REL="rules/privacy.md"

opencode_config_dir() {
  if [ "$LOCAL" = "true" ]; then
    pwd
  else
    local dir="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
    mkdir -p "$dir"
    echo "$dir"
  fi
}

OPENCODE_JSON="$(opencode_config_dir)/opencode.json"

plugin_dir() {
  if [ "$LOCAL" = "true" ]; then
    echo "$(pwd)/.opencode/plugins"
  else
    echo "$(opencode_config_dir)/plugins"
  fi
}

load_config() {
  if [ -f "$OPENCODE_JSON" ]; then
    cat "$OPENCODE_JSON"
  else
    echo '{"$schema": "https://opencode.ai/config.json"}'
  fi
}

save_config() {
  local data="$1"
  mkdir -p "$(dirname "$OPENCODE_JSON")"
  echo "$data" > "$OPENCODE_JSON"
  ok "Saved → $OPENCODE_JSON"
}

# ── find synthelion binaries ──────────────────────────────────────────────────
find_mcp_binary() {
  local py_bin; py_bin=$(command -v "$PY")
  local py_dir; py_dir=$(dirname "$py_bin")
  if [ -x "$py_dir/synthelion-mcp" ]; then
    echo "$py_dir/synthelion-mcp"; return
  fi
  if command -v synthelion-mcp &>/dev/null; then
    command -v synthelion-mcp; return
  fi
  if [ -x "$HOME/.local/bin/synthelion-mcp" ]; then
    echo "$HOME/.local/bin/synthelion-mcp"; return
  fi
  echo ""
}

# ── configure OpenCode ────────────────────────────────────────────────────────
configure_opencode() {
  local mcp_bin="$1"
  local add_plugin="$2"
  local add_rules="$3"

  h2 "Configuring OpenCode…"
  info "Config: $OPENCODE_JSON"

  local tmp; tmp=$(mktemp)
  load_config > "$tmp"

  $PY - "$tmp" "$mcp_bin" "$PY" <<'PYEOF'
import json, sys
path, mcp_bin, py_exe = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    data = json.load(f)
data.setdefault('mcp', {})
if mcp_bin:
    data['mcp']['synthelion'] = {'type': 'local', 'command': [mcp_bin], 'enabled': True}
else:
    data['mcp']['synthelion'] = {
        'type': 'local',
        'command': [py_exe, '-m', 'synthelion.plugins.mcp_server'],
        'enabled': True,
    }
with open(path, 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write('\n')
PYEOF
  ok "MCP server configured"

  if [ "$add_rules" = "true" ]; then
    local rules_path="$(opencode_config_dir)/$RULES_REL"
    mkdir -p "$(dirname "$rules_path")"
    cat > "$rules_path" <<'RULEEOF'
# Privacy Filter — Mandatory (Synthelion)

BEFORE responding to any user message, you MUST follow this procedure.

## 1. Analyze every message
Call `synthelion_analyze_privacy` with:
- `text`: the full user message
- `auto_masking`: `true`
- `language`: auto-detect or `"it"` for Italian, `"en"` otherwise

## 2. Honour the block decision
- If `result.blocked` is **true**:
  → Do NOT process the message. Respond ONLY with `result.warning_message`.
  → Do NOT reference, repeat, or reason about the original text.
- If `result.blocked` is **false**:
  → Use `result.masked_text` as the effective user input from this point on.
  → Treat the original message as if you never saw it — all subsequent
     reasoning MUST use only the masked version.

## 3. Why this exists
This rule protects sensitive data (PII, financial info, credentials) from
being processed by the LLM. The Synthelion privacy engine scores every
message and blocks or masks content based on your configured threshold.
RULEEOF
    ok "Privacy rules written → $rules_path"

    $PY - "$tmp" "$RULES_REL" <<'PYEOF'
import json, sys
path, entry = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)
instructions = data.get('instructions', [])
if entry not in instructions:
    instructions.append(entry)
data['instructions'] = instructions
with open(path, 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write('\n')
PYEOF
    ok "Privacy rules instruction registered"
  else
    info "Skipping privacy rules (--no-rules)"
  fi

  mkdir -p "$(dirname "$OPENCODE_JSON")"
  cp "$tmp" "$OPENCODE_JSON"
  rm -f "$tmp"
  ok "Saved → $OPENCODE_JSON"

  if [ "$add_plugin" = "true" ]; then
    local pdir; pdir=$(plugin_dir)
    mkdir -p "$pdir"
    cat > "$pdir/synthelion.ts" <<'PLUGINEOF'
import { type Plugin } from "@opencode-ai/plugin"

const MIN_LEN = 10
const MIN_EFF = 15

async function syn($: any, subcmd: string, flags: Record<string, any> = {}): Promise<any> {
  const args: string[] = [subcmd, "--json"]
  for (const [k, v] of Object.entries(flags)) {
    if (v === undefined || v === null) continue
    const flag = k.length === 1 ? `-${k}` : `--${k.replace(/_/g, "-")}`
    args.push(flag)
    if (v !== true) args.push(typeof v === "string" ? v : JSON.stringify(v))
  }
  for (const bin of ["synthelion", "python -m synthelion.cli"]) {
    try {
      const out = await $`${bin} ${args}`.text()
      const parsed = JSON.parse(out.trim())
      if (parsed.error) continue
      return parsed
    } catch {}
  }
  return { error: "synthelion not available" }
}

export const SynthelionPlugin: Plugin = async (ctx) => {
  const { $ } = ctx

  return {
    "chat.message": async (_input, output) => {
      const textParts = output.parts.filter(
        (p): p is { type: "text"; text: string } =>
          "text" in p && typeof (p as any).text === "string",
      )
      if (textParts.length === 0) return
      const fullText = textParts.map((p) => p.text).join("\n").trim()
      if (fullText.length < MIN_LEN) return
      try {
        const r = await syn($, "compress", { text: fullText })
        if (r.error || !r.compressed_text || r.efficiency_pct <= MIN_EFF) return
        for (const p of textParts) p.text = r.compressed_text
        output.parts.push({
          type: "text",
          text: `\n\n[⚡ Synthelion: ${r.original_tokens}→${r.compressed_tokens} tok, ${r.efficiency_pct}% saved]`,
        })
      } catch {}
    },

    "experimental.chat.system.transform": async (_input, output) => {
      const text = output.system.join("\n")
      if (text.length < 50) return
      try {
        const r = await syn($, "shape_output", { system_prompt: text, level: "no_restatement" })
        if (r.system_prompt) output.system = [r.system_prompt]
      } catch {}
    },

    "experimental.chat.messages.transform": async (_input, output) => {
      const msgs = output.messages
      if (msgs.length === 0) return

      const last = msgs[msgs.length - 1]
      if (last.info.role === "user") {
        const text = last.parts
          .filter((p): p is { type: "text"; text: string } => "text" in p && typeof (p as any).text === "string")
          .map((p) => p.text)
          .join("\n")
          .trim()
        if (text.length >= MIN_LEN) {
          try {
            const r = await syn($, "compress", { text })
            if (!r.error && r.blocked) {
              last.parts = [{ type: "text", text: r.notice || "[Blocked by Synthelion: PII detected]" }]
              return
            }
            if (!r.error && r.privacy_masked && r.compressed_text) {
              for (const p of last.parts) {
                if ("text" in p && typeof (p as any).text === "string") (p as any).text = r.compressed_text
              }
            }
          } catch {}
        }
      }

      if (msgs.length < 6) return
      const keep = Math.max(2, Math.floor(msgs.length / 2))
      const old = msgs.slice(0, -keep)
      if (old.length === 0) return
      const oldText = old.map((m) => `${m.info.role}: ${m.parts.filter((p) => "text" in p).map((p: any) => p.text).join(" ")}`).join("\n")
      if (oldText.length < 100) return
      try {
        const r = await syn($, "compress", { text: oldText, level: "aggressive" })
        if (r.compressed_text && r.efficiency_pct > 20) {
          const tail = msgs.slice(-keep)
          output.messages = [{
            info: { role: "system" } as any,
            parts: [{ type: "text", text: `[Compressed conversation — ${r.original_tokens}→${r.compressed_tokens} tok, ${r.efficiency_pct}% saved]\n${r.compressed_text}` }],
          }, ...tail]
        }
      } catch {}
    },

    "experimental.session.compacting": async (_input, output) => {
      output.context.push("## Synthelion Plugin\nActive Synthelion MCP tools: compression, PII masking, summarization, and more.")
    },
  }
}
PLUGINEOF
    ok "Plugin installed → $pdir/synthelion.ts"
  else
    info "Skipping plugin (--no-plugin)"
  fi
}

# ── remove configuration ──────────────────────────────────────────────────────
remove_opencode_config() {
  h2 "Removing Synthelion from OpenCode…"
  if [ ! -f "$OPENCODE_JSON" ]; then
    warn "$OPENCODE_JSON not found — nothing to remove."
    return
  fi

  local tmp; tmp=$(mktemp)
  cp "$OPENCODE_JSON" "$tmp"

  $PY - "$tmp" "$RULES_REL" <<'PYEOF'
import json, sys
path, entry = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)
mcp = data.get('mcp', {})
if 'synthelion' in mcp:
    del mcp['synthelion']
    print('  ✓ MCP server removed', flush=True)
instructions = data.get('instructions', [])
if entry in instructions:
    instructions.remove(entry)
    data['instructions'] = instructions
    print('  ✓ Privacy rules instruction removed', flush=True)
with open(path, 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write('\n')
PYEOF

  cp "$tmp" "$OPENCODE_JSON"
  rm -f "$tmp"
  ok "Saved → $OPENCODE_JSON"

  local pfile; pfile="$(plugin_dir)/synthelion.ts"
  if [ -f "$pfile" ]; then
    rm -f "$pfile"
    ok "Plugin removed → $pfile"
  fi
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
h1 "Synthelion Installer for OpenCode (Linux / macOS)"
echo "  Platform : $(uname -s) $(uname -m)"
echo "  Python   : $($PY --version)"

if [ "$UNINSTALL" = "true" ]; then
  remove_opencode_config
  if [ "$NO_PIP" = "false" ]; then
    h2 "Uninstalling Synthelion…"
    $PY -m pip uninstall -y synthelion && ok "Synthelion uninstalled" || warn "Not installed via pip"
  fi
  h1 "Uninstall complete."
  exit 0
fi

if ! command -v opencode &>/dev/null; then
  warn "'opencode' not found in PATH — continuing anyway (config is written either way)."
fi

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

if [ "$NO_PIP" = "false" ]; then
  h2 "Installing Synthelion…"
  PKG="synthelion"
  [ "$CHROMADB" = "true" ] && PKG="synthelion[chromadb]"
  if [ "$UPGRADE" = "true" ]; then
    $PY -m pip install --upgrade "$PKG"
  else
    $PY -m pip install "$PKG"
  fi
  ok "pip install $PKG succeeded"
fi

MCP_BIN=$(find_mcp_binary)
if [ -n "$MCP_BIN" ]; then
  info "synthelion-mcp found: $MCP_BIN"
else
  warn "synthelion-mcp not in PATH — will use Python module form"
fi

smoke_test

ADD_PLUGIN="true"
[ "$NO_PLUGIN" = "true" ] && ADD_PLUGIN="false"
ADD_RULES="true"
[ "$NO_RULES" = "true" ] && ADD_RULES="false"
configure_opencode "$MCP_BIN" "$ADD_PLUGIN" "$ADD_RULES"

h1 "Installation complete!"
echo ""
echo "  Next steps:"
echo "  1. Restart OpenCode (or run 'opencode mcp list') to activate MCP tools."
echo "  2. The plugin auto-compresses every chat message and masks PII."
echo "  3. Run 'opencode doctor' to verify everything loaded."
echo ""
echo "  Savings tracker:"
echo "    synthelion status         # show all-time token savings"
echo "    synthelion gain --days 7  # last 7 days"
echo "    synthelion bench          # benchmark on sample corpus"
echo ""
echo "  Optional: install into the current project instead of globally:"
echo "    ./install_opencode.sh --local"
echo ""
echo "  To update:"
echo "    ./install_opencode.sh --upgrade"
echo ""
echo "  To uninstall:"
echo "    ./install_opencode.sh --uninstall"
echo ""
