# Feature: Synthelion integration with GitHub Copilot, VS Code, Visual Studio 2022/2023

## Goal

Allow developers to use Synthelion as an MCP server inside GitHub Copilot Chat
(Agent Mode) in both VS Code and Visual Studio 2022/2023, without manual
configuration.

---

## Context

Synthelion already runs as an MCP stdio server (`synthelion serve-mcp`) and is
installable in Claude Code via `synthelion install --agent claude`. The same
server can be registered in any MCP-compatible host by pointing to the right
config file.

The existing `install_claude.ps1` / `install_claude.py` / `install_claude.sh`
installers are the reference pattern for new agent targets.

---

## Integration targets

### 1. VS Code + GitHub Copilot Chat (Agent Mode)

**Status:** Ready — VS Code supports MCP since Copilot Chat Agent Mode GA.

**Config file:** `.vscode/mcp.json` (workspace) or user settings
(`settings.json` → `github.copilot.chat.mcp.servers`).

**Approach:**
- Extend `synthelion install --agent vscode [--local]`
  - `--local` → writes `.vscode/mcp.json` in the current workspace
  - default (global) → writes to VS Code user `settings.json`
- Idempotent, same pattern as `--agent claude`

**VS Code extension (Marketplace) — Phase 2:**
- Lightweight VSIX that calls `synthelion install --agent vscode` on activation
- Published via `vsce` (npm `@vscode/vsce`) with a PAT from dev.azure.com
  (scope: Marketplace Publish)
- Publisher: `DigitalsolutionsIt`
- Review time: 1–3 business days
- No logic in the extension itself — just shell-out to the CLI

---

### 2. Visual Studio 2022 / 2023 + GitHub Copilot

**Status:** MCP supported from VS 17.14+ (Preview). Chat participant API
(`@synthelion` in Copilot Chat) is **blocked** — `Microsoft.VisualStudio.Extensibility.Chat`
is not yet a public NuGet package.

**Config file:** `%APPDATA%\GitHub Copilot\mcp.json`

**Approach — Phase 1 (immediate):**
- Extend `synthelion install --agent copilot`
  - Writes/updates `%APPDATA%\GitHub Copilot\mcp.json` with the Synthelion
    MCP server entry
  - Works for both VS 2022 17.14+ and any other host that reads that file
  - PowerShell installer (`install_claude.ps1`) updated with a `-Agent Copilot`
    switch

**VS 2022 VSIX — Phase 2 (future):**
- Separate package `Synthelion.VisualStudio` — does not touch `synthelion` core
- On install: runs `synthelion install --agent copilot` via shell
- Published on VS Marketplace (`marketplace.visualstudio.com/manage`)
- VSIX must be built from Visual Studio (requires VSSDK build tools), not from
  `dotnet build` CLI

---

## Implementation plan

### Phase 1 — CLI installer extensions (no new packages)

| Task | File | Notes |
|---|---|---|
| Add `vscode` target to `install` command | `synthelion/cli.py` | writes `.vscode/mcp.json` or user settings |
| Add `copilot` target to `install` command | `synthelion/cli.py` | writes `%APPDATA%\GitHub Copilot\mcp.json` |
| Update `install_claude.ps1` with `-Agent` switch | `install_claude.ps1` | values: `claude`, `vscode`, `copilot` |
| Update `install_claude.py` cross-platform | `install_claude.py` | same logic, portable paths |
| Add tests for new install targets | `tests/test_synthelion.py` | mock file writes |

### Phase 2 — VS Code Extension

| Task | Notes |
|---|---|
| Init VS Code extension project | `extensions/vscode/` — separate from Python package |
| Activation: call `synthelion install --agent vscode` | Shell-out on first activation |
| Package with `vsce` | `npm install -g @vscode/vsce && vsce package` |
| Publish to Marketplace | Publisher: `DigitalsolutionsIt`, PAT from dev.azure.com |

### Phase 3 — Visual Studio 2022 VSIX (blocked on Microsoft API)

| Task | Notes |
|---|---|
| Create `Synthelion.VisualStudio` VSIX project | Separate repo/package, references synthelion via pip |
| On install: run `synthelion install --agent copilot` | Shell-out |
| Build from VS 2022 | Requires VSSDK build tools |
| Publish to VS Marketplace | Same publisher, same PAT scope |
| Chat participant `@synthelion` | **Planned — blocked** on `Microsoft.VisualStudio.Extensibility.Chat` becoming public |

---

## Priority

1. **Phase 1** — extend the CLI installer. Zero new dependencies, works today,
   covers both VS Code and VS 2022 17.14+.
2. **Phase 2** — VS Code extension on Marketplace for discoverability.
3. **Phase 3** — VS 2022 VSIX after Microsoft publishes the chat participant API.
