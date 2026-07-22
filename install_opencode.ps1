# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
#
# Synthelion installer for OpenCode — Windows PowerShell
#
# Usage:
#   .\install_opencode.ps1              # install (global config)
#   .\install_opencode.ps1 -Local       # install into project-local .opencode\
#   .\install_opencode.ps1 -Upgrade     # update to latest version
#   .\install_opencode.ps1 -NoPlugin    # install without the auto-compression plugin
#   .\install_opencode.ps1 -Uninstall   # remove everything
#
# Run with: powershell -ExecutionPolicy Bypass -File install_opencode.ps1

param(
    [switch]$Local,
    [switch]$Upgrade,
    [switch]$NoPlugin,
    [switch]$NoRules,
    [switch]$Uninstall,
    [switch]$NoPip,
    [switch]$Chromadb
)

$ErrorActionPreference = "Stop"

# ── colours ──────────────────────────────────────────────────────────────────
function Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Info($msg) { Write-Host "   --> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "   !   $msg" -ForegroundColor Yellow }
function Err($msg)  { Write-Host "  [X] $msg" -ForegroundColor Red }
function H1($msg)   { Write-Host "`n$msg" -ForegroundColor Cyan }
function H2($msg)   { Write-Host "`n$msg" -ForegroundColor White }

$RulesRelPath = "rules/privacy.md"

$RuleContent = @'
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
'@

$PluginCode = @'
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
'@

# ── config paths ───────────────────────────────────────────────────────────────
function Get-OpenCodeConfigDir {
    if ($Local) { return (Get-Location).Path }
    $dir = Join-Path $env:APPDATA "opencode"
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    return $dir
}

function Get-OpenCodeJsonPath {
    Join-Path (Get-OpenCodeConfigDir) "opencode.json"
}

function Get-PluginDir {
    if ($Local) { return (Join-Path (Get-Location).Path ".opencode\plugins") }
    return (Join-Path (Get-OpenCodeConfigDir) "plugins")
}

function Load-OpenCodeJson($path) {
    if (Test-Path $path) {
        try {
            return Get-Content $path -Raw | ConvertFrom-Json
        } catch {
            Warn "$path has invalid JSON — backing up and recreating."
            Move-Item $path "$path.bak" -Force
        }
    }
    return [PSCustomObject]@{ '$schema' = "https://opencode.ai/config.json" }
}

function Save-OpenCodeJson($path, $data) {
    $dir = Split-Path $path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $data | ConvertTo-Json -Depth 10 | Set-Content $path -Encoding UTF8
    Ok "Saved → $path"
}

# ── find synthelion-mcp ───────────────────────────────────────────────────────
function Find-McpBinary {
    $pythonDir = Split-Path (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($pythonDir) {
        $candidate = Join-Path $pythonDir "synthelion-mcp.exe"
        if (Test-Path $candidate) { return $candidate }
        $candidate = Join-Path $pythonDir "Scripts\synthelion-mcp.exe"
        if (Test-Path $candidate) { return $candidate }
    }
    $found = Get-Command synthelion-mcp -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    $appdata = $env:APPDATA
    foreach ($ver in @("Python313","Python312","Python311")) {
        $candidate = "$appdata\Python\$ver\Scripts\synthelion-mcp.exe"
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

# ── configure OpenCode ────────────────────────────────────────────────────────
function Configure-OpenCode($mcpBin, $addPlugin, $addRules) {
    H2 "Configuring OpenCode…"
    $configPath = Get-OpenCodeJsonPath
    Info "Config: $configPath"

    $cfg = Load-OpenCodeJson $configPath

    if (-not (Get-Member -InputObject $cfg -Name "mcp" -MemberType NoteProperty)) {
        $cfg | Add-Member -MemberType NoteProperty -Name "mcp" -Value ([PSCustomObject]@{})
    }
    if ($mcpBin) {
        $mcpCfg = [PSCustomObject]@{ type = "local"; command = @($mcpBin); enabled = $true }
    } else {
        $py = (Get-Command python -ErrorAction SilentlyContinue).Source
        if (-not $py) { $py = "python" }
        $mcpCfg = [PSCustomObject]@{ type = "local"; command = @($py, "-m", "synthelion.plugins.mcp_server"); enabled = $true }
    }
    $cfg.mcp | Add-Member -MemberType NoteProperty -Name "synthelion" -Value $mcpCfg -Force
    Ok "MCP server configured"

    if ($addRules) {
        $rulesPath = Join-Path (Get-OpenCodeConfigDir) $RulesRelPath
        $rulesDir = Split-Path $rulesPath
        if (-not (Test-Path $rulesDir)) { New-Item -ItemType Directory -Path $rulesDir -Force | Out-Null }
        Set-Content -Path $rulesPath -Value $RuleContent -Encoding UTF8
        $entry = $RulesRelPath
        $instructions = @()
        if (Get-Member -InputObject $cfg -Name "instructions" -MemberType NoteProperty) {
            $instructions = @($cfg.instructions)
        }
        if ($instructions -notcontains $entry) { $instructions += $entry }
        $cfg | Add-Member -MemberType NoteProperty -Name "instructions" -Value $instructions -Force
        Ok "Privacy rules written → $rulesPath"
    } else {
        Info "Skipping privacy rules (-NoRules)"
    }

    Save-OpenCodeJson $configPath $cfg

    if ($addPlugin) {
        $pluginDir = Get-PluginDir
        if (-not (Test-Path $pluginDir)) { New-Item -ItemType Directory -Path $pluginDir -Force | Out-Null }
        $pluginFile = Join-Path $pluginDir "synthelion.ts"
        Set-Content -Path $pluginFile -Value $PluginCode -Encoding UTF8
        Ok "Plugin installed → $pluginFile"
    } else {
        Info "Skipping plugin (-NoPlugin)"
    }
}

# ── remove configuration ──────────────────────────────────────────────────────
function Remove-OpenCodeConfig {
    H2 "Removing Synthelion from OpenCode…"
    $configPath = Get-OpenCodeJsonPath
    if (-not (Test-Path $configPath)) {
        Warn "$configPath not found — nothing to remove."
        return
    }
    $cfg = Load-OpenCodeJson $configPath

    if ((Get-Member -InputObject $cfg -Name "mcp" -MemberType NoteProperty) -and
        (Get-Member -InputObject $cfg.mcp -Name "synthelion" -MemberType NoteProperty)) {
        $cfg.mcp.PSObject.Properties.Remove("synthelion")
        Ok "MCP server removed"
    }

    if (Get-Member -InputObject $cfg -Name "instructions" -MemberType NoteProperty) {
        $filtered = @($cfg.instructions | Where-Object { $_ -ne $RulesRelPath })
        $cfg | Add-Member -MemberType NoteProperty -Name "instructions" -Value $filtered -Force
        Ok "Privacy rules instruction removed"
    }

    Save-OpenCodeJson $configPath $cfg

    $pluginFile = Join-Path (Get-PluginDir) "synthelion.ts"
    if (Test-Path $pluginFile) {
        Remove-Item $pluginFile -Force
        Ok "Plugin removed → $pluginFile"
    }
}

# ── smoke test ────────────────────────────────────────────────────────────────
function Invoke-SmokeTest {
    H2 "Running smoke test…"
    $tmpPy = [System.IO.Path]::GetTempFileName() -replace '\.tmp$', '.py'
    Set-Content -Path $tmpPy -Encoding UTF8 -Value @'
from synthelion import CompressionService, CompressionLevel
svc = CompressionService()
r = svc.compress("I would like to know if it is possible to receive information.", CompressionLevel.SEMANTIC)
assert r.compressed_text
print(f"{r.original_tokens}to{r.compressed_tokens} tokens ({r.efficiency_pct:.0f}% saved): {r.compressed_text}")
'@
    $result = python $tmpPy 2>&1
    Remove-Item $tmpPy -Force -ErrorAction SilentlyContinue
    if ($LASTEXITCODE -ne 0) {
        Err "Smoke test failed: $result"
        exit 1
    }
    Ok "compress OK — $result"
}

# ── main ─────────────────────────────────────────────────────────────────────
H1 "Synthelion Installer for OpenCode (Windows)"
Write-Host "  Platform : Windows $([System.Environment]::OSVersion.Version)"
$pyVer = python --version 2>&1
Write-Host "  Python   : $pyVer"

if ($Uninstall) {
    Remove-OpenCodeConfig
    if (-not $NoPip) {
        H2 "Uninstalling Synthelion…"
        python -m pip uninstall -y synthelion
        Ok "Synthelion uninstalled"
    }
    H1 "Uninstall complete."
    exit 0
}

if (-not (Get-Command opencode -ErrorAction SilentlyContinue)) {
    Warn "'opencode' not found in PATH — continuing anyway (config is written either way)."
}

H2 "Checking Python version…"
$pyVerNum = python -c "import sys; v=sys.version_info; print(str(v.major)+'.'+str(v.minor))"
if ([version]$pyVerNum -lt [version]"3.11") {
    Err "Python $pyVerNum found — Synthelion needs 3.11+."
    Err "Download from https://www.python.org/downloads/"
    exit 1
}
Ok "Python $pyVerNum"

if (-not $NoPip) {
    H2 "Installing Synthelion…"
    $pkg = if ($Chromadb) { "synthelion[chromadb]" } else { "synthelion" }
    if ($Upgrade) {
        python -m pip install --upgrade $pkg
    } else {
        python -m pip install $pkg
    }
    if ($LASTEXITCODE -ne 0) { Err "pip install failed"; exit 1 }
    Ok "pip install $pkg succeeded"
}

$mcpBin = Find-McpBinary
if ($mcpBin) { Info "synthelion-mcp found: $mcpBin" }
else          { Warn "synthelion-mcp not in PATH — will use Python module form" }

Invoke-SmokeTest
Configure-OpenCode $mcpBin (-not $NoPlugin) (-not $NoRules)

H1 "Installation complete!"
Write-Host ""
Write-Host "  Next steps:"
Write-Host "  1. Restart OpenCode (or run 'opencode mcp list') to activate MCP tools."
Write-Host "  2. The plugin auto-compresses every chat message and masks PII."
Write-Host "  3. Run 'opencode doctor' to verify everything loaded."
Write-Host ""
Write-Host "  Savings tracker:"
Write-Host "    synthelion status         # show all-time token savings"
Write-Host "    synthelion gain --days 7  # last 7 days"
Write-Host "    synthelion bench          # benchmark on sample corpus"
Write-Host ""
Write-Host "  Optional: install into the current project instead of globally:"
Write-Host "    powershell -ExecutionPolicy Bypass -File install_opencode.ps1 -Local"
Write-Host ""
Write-Host "  To update:"
Write-Host "    powershell -ExecutionPolicy Bypass -File install_opencode.ps1 -Upgrade"
Write-Host ""
Write-Host "  To uninstall:"
Write-Host "    powershell -ExecutionPolicy Bypass -File install_opencode.ps1 -Uninstall"
Write-Host ""
