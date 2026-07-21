# Synthelion — Universal Token Compressor and Prompt Manager for AI Agents
![Synthelion Logo](Synthelion.png)

[![PyPI version](https://badge.fury.io/py/synthelion.svg)](https://pypi.org/project/synthelion/)
[![Python Versions](https://img.shields.io/pypi/pyversions/synthelion.svg)](https://pypi.org/project/synthelion/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub stars](https://img.shields.io/github/stars/francescopaolopassaro/synthelion)](https://github.com/francescopaolopassaro/synthelion/stargazers)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-blue)](https://modelcontextprotocol.io)

Synthelion compresses prompts before they reach any AI model — cutting token usage by up to 70%, reducing API costs, and speeding up responses. It works with **any agent or framework**: Claude Code, OpenAI, LangChain, OpenCode, Cursor, and more.

Supports 50+ languages out of the box. No AI model required. No configuration.

> "Why use many tokens when few tokens do trick?" — A caveman (and your wallet).

<!--
  Demo GIF goes here — record ~5-10s of a terminal running Claude Code: a long
  prompt goes in, the Synthelion hook fires, and "[Synthelion NN% saved]" shows
  up in the systemMessage. Save it as docs/demo.gif and uncomment the line below.
  ![Synthelion in action](docs/demo.gif)
-->

---

## Table of contents

- [Why Synthelion?](#why-synthelion)
- [Synthelion vs other prompt/context-compression tools](#synthelion-vs-other-promptcontext-compression-tools)
- [Quick install — one command](#quick-install--one-command)
- [Install (manual)](#install-manual)
- [Update](#update)
- [Set up on Claude Code](#set-up-on-claude-code)
- [Automatic prompt compression — Claude Code hook](#automatic-prompt-compression--claude-code-hook)
- [Using Synthelion with all agents](#using-synthelion-with-all-agents--automatic-compression)
- [Integrations](#integrations) (OpenAI, LangChain, Claude/OpenAI adapters, Python API, CLI)
- [Web dashboard](#web-dashboard)
- [Cluster deployment](#cluster-deployment)
- [Tools](#tools) (37 MCP tools)
- [Code examples](#code-examples)
- [Compression levels](#compression-levels)
- [Supported languages](#supported-languages-50)
- [Troubleshooting](#troubleshooting)
- [Optional extras](#optional-extras)
- [Contributing](#contributing)
- [Sponsors](#sponsors)
- [Links](#links)

---

## Why Synthelion?

Every token sent to a model costs money and time. Synthelion removes the words that carry no meaning — articles, prepositions, conjunctions, auxiliary verbs — and reduces inflected words to their base form. The model receives exactly the same information, just without the grammatical packaging.

**Strengths:**
- **Zero ML models, zero network calls** — every technique is a deterministic heuristic (curated word lists, BM25, TF-IDF, regex/structural detection). No embedding model to download, nothing phones home.
- **50+ languages out of the box**, no per-language configuration.
- **Content-aware routing** — JSON, HTML, git diffs, logs, code, and prose each get a dedicated compression strategy instead of one generic pass; a universal anti-expansion guard means you never get back something bigger than what you sent in.
- **Adaptive by design** — compression escalates automatically for larger inputs, results are cached by content hash, and repeated tool calls get diffed instead of resent in full.
- **Safety-conscious by default** — credential-shaped text (API keys, tokens, PEM blocks) is redacted before it's ever persisted to disk; destructive-command text is flagged before compression could obscure it.
- **MCP-native** — 37 tools, `readOnlyHint`-annotated where safe for parallel calls, plus first-class OpenAI/LangChain/Claude adapters and a plain Python API.
- **Ops-ready** — a local multi-page dashboard, cluster/master-slave deployment, Docker/Kubernetes manifests, all included, none required.

### Before / After

**English prose** — 20 tokens → 9 tokens (−55%)
```
Before: I would like to know if it is possible to receive information about
        cheap restaurants in Rome, please.

After:  like know possible receive information about cheap restaurant Rome
```

**Italian prose** — 16 tokens → 9 tokens (−44%)
```
Before: Vorrei sapere se è possibile ricevere informazioni sui ristoranti
        economici a Roma, per favore.

After:  sapere è possibile ricevere informazione ristorante economico Roma favore
```

**JSON array** — 256 tokens → 80 tokens (−69%)
```json
// Before: full JSON with repeated keys on every object
[{"name":"Alice","age":30,"city":"Rome"},{"name":"Bob","age":25,"city":"Milan"},…]

// After: lossless markdown table
| name  | age | city  |
| ----- | --- | ----- |
| Alice | 30  | Rome  |
| Bob   | 25  | Milan |
```

**HTML page** — 192 tokens → 58 tokens (−70%)
```
// Before: full HTML with tags, attributes, scripts
<html><head>…</head><body><div class="…"><p>Visit Rome today…</p></div></body></html>

// After: clean extracted text, then NLP-compressed
Visit Rome today enjoy ancient history food culture
```

---

### Benchmark — token savings by content type

Measured with `synthelion`'s own token counter against real inputs — reproduce
with `synthelion bench --json` (content router) or `CompressionService.compress`
directly (NLP-only, per-level).

#### NLP compression (prose, per level)

| Content | Original tokens | Light | Semantic | Aggressive |
|:---|---:|:---:|:---:|:---:|
| Prose EN | 20 | −55.0% | −55.0% | **−75.0%** |
| Prose IT | 16 | −43.8% | −43.8% | **−62.5%** |
| Prose DE | 19 | −47.4% | −47.4% | **−63.2%** |
| Prose FR | 18 | −38.9% | −38.9% | **−55.6%** |
| Prose ES | 17 | −47.1% | −47.1% | −52.9% |

#### Content router (`synthelion bench --json`, auto-selects the best strategy)

| Content | Original | After | Saved |
|:---|---:|---:|:---:|
| Plain text EN | 196 | 105 | −46.4% |
| Plain text IT | 200 | 131 | −34.5% |
| JSON array (20 rows) | 609 | 326 | −46.5% |
| Git diff (2 files) | 328 | 198 | −39.6% |
| Python code | 273 | 151 | −44.7% |
| Log / stacktrace (retry burst) | 1,666 | 102 | **−93.9%** |
| HTML page | 242 | 61 | **−74.8%** |
| Tool-schema JSON (new in 1.2.2 — `ToolSignature`) | 315 | 106 | **−66.3%** |
| Nested JSON object (new in 1.2.2 — `ChainCollapse`) | 32 | 24 | −25.0% |

Larger, more realistic payloads compress further than tiny samples — the log
benchmark above is a 20-repeat retry burst (a real flaky-dependency scenario),
where `LogCompressor`'s dedup collapses near-identical stack traces down to
one occurrence plus a counter.

---

### Synthelion vs other prompt/context-compression tools

A capability comparison, not a performance benchmark — we don't publish
head-to-head token-savings numbers against other projects because we haven't
run their code in a controlled, reproducible setup; this table is based on
reading each project's public source. If you've measured a real head-to-head,
open an issue with your methodology and we'll link it here.

| Capability | Synthelion | headroom | kompact | tokenless | squeez | bu-ketao |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| Zero ML models, zero network calls | ✅ | ❌ (torch/transformers/SigLIP, fine-tuned classifiers) | ✅ | ⚠️ optional ONNX embedding | ✅ | n/a (prompt rules, no code) |
| NLP compression, 50+ languages | ✅ | — (ML feature extraction instead) | ✅ (TF-IDF) | — | — | n/a |
| Content-type auto-routing (JSON/HTML/diff/log/code) | ✅ | ✅ | ✅ | ✅ (shape-based) | — | n/a |
| Tool-schema → compact signature | ✅ | — | ✅ (TF-IDF selection) | ✅ | — | n/a |
| Credential-shape detection before persisting | ✅ | — | — | — | ✅ (origin) | n/a |
| Terminal ANSI/noise cleanup + success collapse | ✅ | — | — | — | ✅ (origin) | n/a |
| Masking old tool output + retrieval (Artifact Index) | ✅ | — | ✅ (origin) | — | — | n/a |
| Diff-on-repeat for identical tool calls | ✅ | — | — | — | — | n/a |
| Adaptive compression scaling by content size | ✅ | — | ✅ (origin) | — | — | n/a |
| JSON chain-depth / dot-path collapsing | ✅ | — | — | ✅ (origin) | — | n/a |
| Advisory command-rewrite (never executes) | ✅ | — | — | ⚠️ executes it (rtk wrapper) | — | n/a |
| Local multi-page web dashboard | ✅ | ✅ | ✅ (simpler) | — | — | n/a |
| Cluster / master-slave deployment | ✅ | — | — | — | — | n/a |
| MCP protocol (Claude Code, etc.) | ✅ 37 tools | ✅ (CLI plugins: Claude/Codex/Gemini) | — (HTTP proxy instead) | ✅ (hooks) | — | n/a |
| Vision/image token optimization | — (text-only) | ✅ (tile-aligned resize + trained router) | — | — | — | n/a |
| Provider cache-breakpoint-aware read staleness | ✅ | ✅ (origin, `read_maturation.py`) | — | — | — | n/a |
| Response-style compression (output-side, CJK-aware) | ✅ | — | — | — | — | ✅ (origin) |

**Not in this table:** `tokensave` — a Rust code-intelligence tool (Tree-sitter knowledge graph, dead-code/cycle detection, code-health scoring) that solves a genuinely different problem (structural understanding of a codebase) rather than context/token compression, so it isn't a like-for-like comparison here.

**On headroom specifically:** the broadest-scope alternative we looked at — proxy architecture, persistent memory, vision-token optimization, and ML-based response-length prediction (fine-tuned MiniLM/SigLIP classifiers hosted on HuggingFace). That breadth comes at the cost of the zero-ML-models guarantee Synthelion makes: several of headroom's key decisions (image routing, response-length prediction) depend on downloaded, trained models rather than deterministic heuristics.

---

### What this means for your costs

Token pricing varies by model. As a rough example with GPT-4o ($2.50 / 1M input tokens):

| Daily input volume | Without Synthelion | With Synthelion (40% avg savings) | Annual saving |
|:---|---:|---:|---:|
| 500K tokens/day | $456/year | $274/year | **$182/year** |
| 2M tokens/day | $1,825/year | $1,095/year | **$730/year** |
| 10M tokens/day | $9,125/year | $5,475/year | **$3,650/year** |

Savings scale with volume. For agent loops that send the same context on every call, real savings are often higher than the 40% average.

### Energy & sustainability

Synthelion includes a built-in energy estimator. Every saved token avoids approximately **0.005 mWh** of compute energy and **0.002 mg CO₂**. At scale, that adds up.

```python
result = svc.compress(long_prompt, CompressionLevel.SEMANTIC)
print(f"Energy saved: {result.estimated_energy_saved_mwh:.3f} mWh")
print(f"CO₂ avoided:  {result.estimated_co2_saved_mg:.3f} mg")
```

---

## Quick install — one command

> The fastest way: download one script and run it. It installs Synthelion, detects your Python path, configures Claude Code MCP, and sets up the auto-compression hook automatically.

### Windows (PowerShell)

```powershell
# Download and run
Invoke-WebRequest https://raw.githubusercontent.com/francescopaolopassaro/synthelion/main/install_claude.ps1 -OutFile install_claude.ps1
powershell -ExecutionPolicy Bypass -File install_claude.ps1
```

Or, if you already cloned the repo:
```powershell
powershell -ExecutionPolicy Bypass -File install_claude.ps1
```

### Linux / macOS (bash)

```bash
curl -fsSL https://raw.githubusercontent.com/francescopaolopassaro/synthelion/main/install_claude.sh | bash
# or, after cloning the repo:
chmod +x install_claude.sh && ./install_claude.sh
```

### All platforms (Python — works everywhere)

```bash
python install_claude.py
```

### Installer options

**Windows PowerShell (`install_claude.ps1`)**

| Flag | Description |
|---|---|
| `-Upgrade` | Update Synthelion to the latest version |
| `-NoHook` | Skip the auto-compression hook |
| `-NoPip` | Skip pip install (Synthelion already installed) |
| `-Uninstall` | Remove Synthelion and all Claude Code config |

```powershell
powershell -ExecutionPolicy Bypass -File install_claude.ps1 -Upgrade     # update
powershell -ExecutionPolicy Bypass -File install_claude.ps1 -Uninstall   # remove everything
powershell -ExecutionPolicy Bypass -File install_claude.ps1 -NoPip -NoHook  # only update settings.json
```

**Linux / macOS (`install_claude.sh`) and Python (`install_claude.py`)**

| Flag | Description |
|---|---|
| `--upgrade` | Update Synthelion to the latest version |
| `--no-hook` | Skip the auto-compression hook |
| `--no-pip` | Skip pip install (Synthelion already installed) |
| `--uninstall` | Remove Synthelion and all Claude Code config |

```bash
python install_claude.py --upgrade          # update
python install_claude.py --uninstall        # remove everything
python install_claude.py --no-pip --no-hook # only update settings.json
```

---

## Install (manual)

**Requirements:** Python 3.11+ — download from [python.org](https://www.python.org/downloads/) and tick "Add to PATH" during setup.

```powershell
# 1. Install Synthelion
pip install synthelion

# 2. Verify the CLI works
synthelion compress --text "Hello world, how are you today?" --json

# 3. Verify the MCP server starts (Ctrl+C to stop)
synthelion-mcp
```

If `synthelion` is not recognised after install, close and reopen the terminal (PATH refresh needed).

---

### Linux

```bash
# 1. Install Synthelion
pip install synthelion
# or, in a virtualenv:
python3 -m venv ~/.venvs/synthelion
source ~/.venvs/synthelion/bin/activate
pip install synthelion

# 2. Verify
synthelion compress --text "Hello world, how are you today?" --json

# 3. If synthelion-mcp is not in PATH (virtualenv scenario), add it:
# Add the venv's bin directory to ~/.bashrc or use the absolute path in MCP config
echo 'export PATH="$HOME/.venvs/synthelion/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

---

### macOS

```bash
# 1. Install with pip (system Python or Homebrew Python)
pip3 install synthelion
# or with uv (recommended — no PATH issues):
pip install uv
uvx synthelion-mcp   # runs the MCP server without a permanent install

# 2. Verify
synthelion compress --text "Hello world, how are you today?" --json
```

---

### Zero-install with uvx (all platforms)

[uv](https://docs.astral.sh/uv/) installs and runs Synthelion in an isolated environment — no `pip install` needed:

```bash
pip install uv       # one-time
uvx synthelion-mcp   # starts the MCP server directly
```

---

## Update

### Windows

```powershell
pip install --upgrade synthelion

# Verify new version
synthelion --version
```

### Linux / macOS

```bash
pip install --upgrade synthelion
# or, if installed in a virtualenv:
source ~/.venvs/synthelion/bin/activate
pip install --upgrade synthelion
```

### With uv / uvx

uvx always fetches the latest version automatically — nothing to do.

---

## Set up on Claude Code

Claude Code uses the MCP protocol to talk to Synthelion.

### Step 1 — Install Synthelion (see above)

### Step 2 — Register with one command (new in 1.0.7)

```bash
synthelion install           # writes to ~/.claude.json (global)
synthelion install --local   # writes to .claude/settings.json (project-only)
```

Or manually:

### Step 2 (manual) — Add to `~/.claude/settings.json`

Open the file (`%USERPROFILE%\.claude\settings.json` on Windows, `~/.claude/settings.json` on Linux/macOS) and add:

```json
{
  "mcpServers": {
    "synthelion": {
      "command": "synthelion-mcp"
    }
  }
}
```

If `synthelion-mcp` is not in PATH (virtualenv, macOS Homebrew Python), use the absolute path:

```json
{
  "mcpServers": {
    "synthelion": {
      "command": "/home/user/.venvs/synthelion/bin/synthelion-mcp"
    }
  }
}
```

Or use uvx — it always works without PATH issues:

```json
{
  "mcpServers": {
    "synthelion": {
      "command": "uvx",
      "args": ["synthelion-mcp"]
    }
  }
}
```

### Step 3 — Restart Claude Code

Close and reopen the Claude Code window (or run `claude` again in the terminal). Synthelion is now available as an MCP tool.

### Step 4 — Verify

Type in Claude Code:
> *"Use Synthelion to compress this: I would like to know if it is possible to receive information about cheap restaurants in Rome."*

Claude will call the MCP tool and return the compressed version.

---

## Automatic prompt compression — Claude Code hook

> **How it works:** every prompt longer than 200 characters is automatically compressed by Synthelion. The compressed text is injected as `additionalContext` for Claude (invisible in the terminal — that's the part that actually does the token-saving work), while a short `systemMessage` — `[Synthelion N% saved - X mWh - Y mg CO2 saved]` — is shown visibly so you can confirm it fired.

### Automatic setup (recommended)

```bash
synthelion install          # writes hook + MCP to ~/.claude.json
synthelion install --local  # project-local .claude/settings.json
```

### Manual — Windows (`~/.claude/settings.json`)

```json
{
  "mcpServers": {
    "synthelion": { "command": "synthelion-mcp" }
  },
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "shell": "powershell",
            "command": "$j=[Console]::In.ReadToEnd()|ConvertFrom-Json;$p=$j.prompt;if($p -and $p.Length -gt 200){$r=($p| & \"synthelion\" compress --json 2>$null)|ConvertFrom-Json;if($r -and $r.efficiency_pct -gt 15){$pct=[Math]::Round($r.efficiency_pct);$label='[Synthelion '+$pct+'% saved - '+$r.energy_mwh+' mWh - '+$r.co2_mg+' mg CO2 saved]';@{systemMessage=$label;hookSpecificOutput=@{hookEventName='UserPromptSubmit';additionalContext=$r.compressed}}|ConvertTo-Json -Compress}}",
            "statusMessage": "Compressing prompt...",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

### Manual — Linux / macOS (`~/.claude/settings.json`)

```json
{
  "mcpServers": {
    "synthelion": { "command": "synthelion-mcp" }
  },
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "shell": "bash",
            "command": "prompt=$(cat | python3 -c \"import sys,json; print(json.load(sys.stdin).get('prompt',''))\"); if [ ${#prompt} -gt 200 ]; then r=$(printf '%s' \"$prompt\" | \"synthelion\" compress --json 2>/dev/null); if [ -n \"$r\" ]; then out=$(printf '%s' \"$r\" | python3 -c \"import sys,json; d=json.load(sys.stdin); eff=int(d.get('efficiency_pct',0)); label='[Synthelion '+str(eff)+'% saved - '+str(d.get('energy_mwh',0))+' mWh - '+str(d.get('co2_mg',0))+' mg CO2 saved]'; print(json.dumps({'systemMessage':label,'hookSpecificOutput':{'hookEventName':'UserPromptSubmit','additionalContext':d.get('compressed','')}})) if eff>15 else None\"); [ -n \"$out\" ] && printf '%s' \"$out\"; fi; fi",
            "statusMessage": "Compressing prompt...",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

### How to disable the hook

Remove the `"hooks"` block from `~/.claude/settings.json`, or open `/hooks` in Claude Code to toggle it.

---

## Using Synthelion with all agents — automatic compression

Synthelion can compress inputs automatically for **any agent** that supports the MCP protocol (Claude Code, Claude Desktop, OpenCode, Cursor, Windsurf, Continue…).

### Configure all MCP-compatible agents

Add Synthelion to each agent's config file:

| Agent | Config file |
|---|---|
| Claude Code | `~/.claude/settings.json` |
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` |
| OpenCode | `~/.config/opencode/opencode.json` (global) or `opencode.json` (project) |
| Cursor | `~/.cursor/mcp.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| Continue | `.continue/config.json` |

Claude / Claude Desktop / Cursor / Windsurf / Continue all use the same JSON block:
```json
{
  "mcpServers": {
    "synthelion": {
      "command": "synthelion-mcp"
    }
  }
}
```

**OpenCode** uses its own MCP schema (`mcp` key, explicit `type`, `command` as an array):
```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "synthelion": {
      "type": "local",
      "command": ["synthelion-mcp"],
      "enabled": true
    }
  }
}
```
Or register it automatically:
```bash
synthelion install --agent opencode           # global: ~/.config/opencode/opencode.json
synthelion install --agent opencode --local    # project: ./opencode.json
```
Once registered, all 13 Synthelion tools (`compress`, `route_content`, `compress_for_context`, `deduplicate`, …) show up as callable tools in OpenCode — ask it to *"use the synthelion tool to compress this text"* or let it call them automatically per your agent instructions (see below).

**Cursor** and **Windsurf** read the same `mcpServers` shape as Claude, just at their own config path — register with:
```bash
synthelion install --agent cursor
synthelion install --agent windsurf
```

### Instruct agents to compress automatically

Add this to your agent's system prompt or CLAUDE.md:

```
When processing long texts, files, or documents (>200 tokens), use Synthelion:
- mcp__synthelion__compress_for_context  — fit any content in your token budget
- mcp__synthelion__compress_conversation — compress older turns before sending history
- mcp__synthelion__deduplicate           — remove overlapping retrieved chunks
- mcp__synthelion__route_content         — auto-detect content type and compress
- mcp__synthelion__session_record        — save decisions for cross-session recall
- mcp__synthelion__session_recall        — retrieve past decisions by query
Report the token reduction achieved (synthelion_metrics field).
```

### Use the CLI in shell pipelines

```bash
# Compress a file before sending to any LLM API
cat long_context.txt | synthelion compress --level semantic > compressed.txt

# Pipe directly into any tool
synthelion route --file document.html | llm-cli --model gpt-4o

# Batch compress a directory
for f in docs/*.md; do
  synthelion compress --text "$(cat $f)" --json >> compressed_batch.jsonl
done
```

---

## Integrations

---

### OpenAI — GPT-4, GPT-4o, Codex, and any OpenAI-compatible API

```python
from openai import OpenAI
from synthelion.plugins.openai_tools import get_tool_definitions, execute_tool

client = OpenAI()
tools = get_tool_definitions()

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Compress this text: I would like to know if it is possible..."}],
    tools=tools,
    tool_choice="auto",
)

# Handle tool calls returned by the model
for tool_call in response.choices[0].message.tool_calls or []:
    result = execute_tool(tool_call.function.name, tool_call.function.arguments)
    print(result)
```

---

### LangChain — LangGraph, LCEL, ReAct agents

```bash
pip install "synthelion[langchain]"
```

```python
from synthelion.plugins.langchain_tools import get_tools
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

llm = ChatOpenAI(model="gpt-4o")
tools = get_tools()   # 11 StructuredTools, including all new context tools

agent = create_react_agent(llm, tools)
result = agent.invoke({"messages": [{"role": "user", "content": "Compress this prompt: ..."}]})
```

Works with any LangChain-compatible LLM (OpenAI, Anthropic, Groq, Ollama, …).

#### SynthelionMemory — drop-in compressing memory

```python
from langchain.chains import ConversationChain
from synthelion.plugins.langchain_tools import SynthelionMemory

# Compresses history turns and injects relevant past decisions via RAG
memory = SynthelionMemory(max_context_tokens=4000, recall_limit=5)
chain = ConversationChain(llm=llm, memory=memory)

chain.predict(input="Tell me about Rome.")
chain.predict(input="What are the best restaurants there?")
# Older turns are automatically compressed; RAG recalls relevant notes from past sessions
```

---

### Claude & OpenAI Adapters — auto-compression with one import

```bash
pip install "synthelion[claude]"    # for ClaudeAdapter
pip install "synthelion[openai]"    # for OpenAIAdapter
```

```python
from synthelion.integrations.claude_adapter import ClaudeAdapter

# Replaces anthropic.Anthropic — same interface, auto-compresses every message
client = ClaudeAdapter()
reply = client.chat("claude-sonnet-4-6", [
    {"role": "user", "content": "Explain how the Renaissance shaped modern science in detail..."}
])
print(reply)                  # model answer
print(client.total_saved)     # tokens saved so far
```

```python
from synthelion.integrations.openai_adapter import OpenAIAdapter

client = OpenAIAdapter()
reply = client.chat("gpt-4o", [
    {"role": "user", "content": "Explain how the Renaissance shaped modern science in detail..."}
])
```

---

### RagAgent — stateful agent with memory, RAG, and cost tracking

```python
from synthelion.agent.rag_agent import RagAgent

agent = RagAgent(max_context_tokens=8000, recall_limit=5)

# Each add_turn compresses the message, recalls past decisions, and updates the rolling window
agent.add_turn("user", "I decided to use PostgreSQL for the user database.")
agent.add_turn("assistant", "Good choice. PostgreSQL handles JSONB fields well for config data.")

agent.add_turn("user", "What did we decide about the database?")
# The agent automatically recalls past decisions about PostgreSQL
recalled = agent.recall("database")
for d in recalled:
    print(d["text"])    # "I decided to use PostgreSQL for the user database."

# Get compressed message list ready for any LLM API
messages = agent.get_context_messages()
print(agent.total_saved, "tokens saved")
```

---

### Python API — any custom agent or pipeline

```python
from synthelion import CompressionService, CompressionLevel, ContentRouter, CompressionProfile

# Compress text
svc = CompressionService()
result = svc.compress(
    "I would like to know if it is possible to receive information about cheap restaurants in Rome.",
    CompressionLevel.SEMANTIC,
)
print(result.compressed_text)   # "know possible receive information cheap restaurant Rome"
print(f"{result.efficiency_pct:.1f}% saved")

# Auto-route any content type (JSON, HTML, diff, log, code, prose)
router = ContentRouter.from_profile(CompressionProfile.BALANCED)
routed = router.route(my_content)
print(routed.strategy_used, f"{routed.savings_pct:.1f}% saved")
```

---

### CLI — shell scripts, pipelines, any language

```bash
# Compress text
synthelion compress --text "I would like to know if it is possible..." --level semantic

# Detect language
synthelion detect --text "Guten Morgen, wie geht es Ihnen?"

# Auto-route a file
synthelion route --file context.json

# Summarize
synthelion summarize --text "..." --sentences 3

# Start MCP server manually
synthelion serve-mcp

# Start the local read-only web dashboard
synthelion serve-dashboard
```

Pipe-friendly — reads from stdin if no `--text` or `--file` is given:

```bash
cat big_prompt.txt | synthelion compress --level aggressive
```

#### Diagnostics & setup

```bash
# Health check — verifies MCP package, ledger, session DB, PATH, Claude config
synthelion doctor
synthelion doctor --json      # machine-readable output

# Register the MCP server automatically (global Claude Code config)
synthelion install
synthelion install --agent gemini            # Gemini CLI
synthelion install --agent opencode          # OpenCode (global: ~/.config/opencode/opencode.json)
synthelion install --agent opencode --local  # OpenCode (project: ./opencode.json)
synthelion install --agent claude --local    # project-local .claude/settings.json
synthelion install --agent cursor            # Cursor (~/.cursor/mcp.json)
synthelion install --agent windsurf          # Windsurf (~/.codeium/windsurf/mcp_config.json)
```

#### Analytics & savings tracking

```bash
# Show total tokens saved, cost estimate, and tool breakdown
synthelion status

# Show savings history (last 7 days)
synthelion gain --days 7
synthelion gain --all --json   # full history, machine-readable

# Benchmark on a built-in corpus (prose, JSON, diff, code, logs, HTML)
synthelion bench
synthelion bench --json

# Export ledger to CSV or JSONL for analysis in Excel / Grafana / pandas
synthelion export                          # CSV to stdout
synthelion export --format jsonl -o savings.jsonl
synthelion export --days 30 -o last_month.csv
```

#### Self-upgrade

```bash
synthelion upgrade            # pip install --upgrade synthelion
synthelion upgrade --dry-run  # show what would run, don't run it
```

---

## Web dashboard

A local web dashboard over everything Synthelion has compressed — no external calls, no CDN, works offline. Built for a multi-session setup: every `synthelion-mcp` process (one per agent session) and every CLI/hook invocation writes to the same lock-free ledger, and the dashboard aggregates them live. Since 1.2.1 it's a full multi-page admin panel (separate URLs, not one long scroll) rather than a single read-only report.

```bash
synthelion serve-dashboard                    # http://127.0.0.1:8787
synthelion serve-dashboard --port 9000        # custom port
synthelion serve-dashboard --host 0.0.0.0     # explicit opt-in to expose it on the network
```

Protected by a login page — default credentials are **admin / admin**, change them before exposing the dashboard beyond your own machine:

```bash
synthelion dashboard-passwd                   # prompts for a new password (keeps current username)
synthelion dashboard-passwd -u alice -p ...   # change username and password non-interactively
```

Changing the password immediately invalidates every session already logged in on that running dashboard process. The dashboard's own **Notifications** page also flags it for you if the default password is still active — see below.

UI built with [Material Dashboard Free](https://www.creative-tim.com/product/material-dashboard) by [Creative Tim](https://www.creative-tim.com) (MIT License, vendored locally — no CDN, see `synthelion/plugins/dashboard_assets/vendor/material-dashboard/ATTRIBUTION.md`).

![Synthelion dashboard — login](docs/dashboard-login.png)

![Synthelion dashboard — overview](docs/dashboard-overview.png)

**Overview**: calls, tokens saved, avg efficiency, CO₂ saved, active sessions, avg calls per session, tools used, best single call, and latency (avg / p95 / max) — plus a version badge showing exactly which Synthelion build is running. **Charts**: tokens saved over time, by tool, and by content type.

![Synthelion dashboard — sessions](docs/dashboard-sessions.png)

**Sessions**: one row per `synthelion-mcp`/CLI process (PID, calls, tools used, first/last activity), with per-row delete and a one-click cleanup (10/20/30 days) for old records. **Recent requests**: every individual call with before/after tokens, efficiency, and latency. **Decisions**: recorded session-memory notes, with the same age-based cleanup.

![Synthelion dashboard — settings](docs/dashboard-settings.png)

**Settings**: default compression level, default project-wiki depth (1-4, see below), session-store/vector-store backend selection, live storage counts, a **Doctor** panel (same checks as `synthelion doctor`, one click), and **Version** (checks PyPI only when you click "Check for updates" — never automatically — and can trigger `pip install --upgrade synthelion` from the button next to it).

![Synthelion dashboard — profile](docs/dashboard-profile.png)

**Profile**: change the dashboard's own username/password (requires the current password), account info (version, active backends), and a feed of the same real health notifications shown in the bell icon up top — never fabricated demo content, only things actually true about this install (default password still set, a configured backend's Python package isn't installed, etc.).

![Synthelion dashboard — cluster](docs/dashboard-cluster.png)

**Cluster** — a lightweight master/slave fleet layer, separate from (and on top of) the shared-backend replica model described in [Cluster deployment](#cluster-deployment) below: "Become master" generates a node ID and a shared token; other nodes join with that token (from their own dashboard's "Join a master" form, or `synthelion cluster join <url> --token ...`) and appear in the master's node table with live calls/tokens-saved/version. The master and every slave authenticate to each other with that shared token (`Authorization: Bearer ...`), never with the browser session cookie — one node's dashboard login has no bearing on another node's. A joining slave copies the master's compression/wiki defaults; storage backends are deliberately **not** copied, since those often differ per node/region. The page also has one-click downloads for a `docker-compose.yml` and a Kubernetes manifest pre-wired for this master/N-slave topology (env-var based — `SYNTHELION_ROLE`, `SYNTHELION_NODE_TOKEN`, `SYNTHELION_MASTER_URL` — no secret baked into the downloaded file). See `synthelion cluster --help`.

**Auto-start with Claude Code** — add a `SessionStart` hook so the dashboard is already running whenever you open a session:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "shell": "powershell",
            "command": "try{$c=Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue;if(-not $c){Start-Process -FilePath \"synthelion\" -ArgumentList 'serve-dashboard' -WindowStyle Hidden}}catch{}",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

The check is non-blocking and idempotent — if the dashboard is already listening on the port, the hook does nothing.

---

## Cluster deployment

For an AI-provider-scale deployment (many nodes, thousands of concurrent agent
sessions), point every node at a shared session/vector store instead of each
one keeping its own local ledger — then any dashboard replica shows the
whole cluster's activity, not just its own.

This is about *storage* — identical, interchangeable replicas behind a load
balancer. For *node identity and fleet visibility* (master/slave roles, a
shared cluster token, "which nodes have joined and are they healthy", one-click
deploy file downloads), see the dashboard's **Cluster** page and `synthelion
cluster --help` in the [Web dashboard](#web-dashboard) section above — the two
are independent and commonly used together (identical nodes, still individually
tracked).

### 1. Configure

```bash
synthelion configure --session-store redis --redis-url redis://redis-host:6379/0 \
                      --vector-store qdrant --qdrant-url http://qdrant-host:6333 \
                      --dashboard-host 0.0.0.0
synthelion configure --show   # print the effective config without writing
```
Writes `~/.synthelion/config.json` (or `--output <path>` / `SYNTHELION_CONFIG` env
var for a per-node/ConfigMap-mounted file). See `synthelion.config.example.json`
in the repo root for the full key reference — every key has a built-in
default, so a partial file only needs to override what changes.

Backends:
| | Options |
|---|---|
| **Session store** (active sessions, savings ledger) | `local` (single-node file), `redis`, `postgres` |
| **Vector store** (cross-session RAG memory) | `chromadb` (bundled embedding), `qdrant` (deterministic hashed vectors — no ML model, see below), `lexical` (no external service) |
| **Dashboard realtime** | `websocket` (push updates), `polling` |

Qdrant support keeps Synthelion's "zero ML models" design: rather than pulling
in an embedding model just for Qdrant, it indexes a deterministic FNV-1a
hashed bag-of-words vector — the same lexical scoring the fallback path
already does, just queryable through Qdrant's ANN index across a cluster.

### 2. Docker

```bash
docker build -t synthelion:latest .
docker compose up -d                       # single node, local-file storage
docker compose --profile cluster up -d     # + redis + postgres + qdrant containers
```
See the `Dockerfile` and `docker-compose.yml` at the repo root — the image runs
`synthelion serve-dashboard --host 0.0.0.0` by default and exposes `8787`
(dashboard) and `8788` (WebSocket realtime updates).

For Docker Swarm, the same compose file works with `docker stack deploy -c
docker-compose.yml synthelion`; scale with `docker service scale
synthelion_dashboard=3` (Swarm's routing mesh load-balances the published
port across replicas — unlike plain `docker compose up`, where each replica
binds the host port directly, so scale there via multiple named services or a
reverse proxy instead).

### 3. Kubernetes

Manifests in `k8s/`: `namespace.yaml`, `configmap.yaml` (holds
`synthelion.config.json` — edit the Redis/Qdrant URLs to match your cluster),
`deployment.yaml` (3 replicas + `HorizontalPodAutoscaler`, readiness/liveness
probes on `/api/summary`, non-root), `service.yaml` (ClusterIP — front it with
your own Ingress/auth layer), and `backing-services.yaml` (minimal in-cluster
Redis + Qdrant StatefulSets for evaluation; swap for managed services in
production).

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/backing-services.yaml   # or point configmap.yaml at managed Redis/Qdrant instead
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

### 4. Load balancer (no orchestrator)

Run `synthelion serve-dashboard --host 0.0.0.0` on N plain nodes (systemd
service, `synthelion install`-style), all pointed at the same
`SYNTHELION_CONFIG`, and put any standard load balancer (nginx, HAProxy,
a cloud LB) in front on port 8787. Every node reads/writes the same shared
Redis/Postgres/Qdrant backend, so it doesn't matter which node a request
lands on.

---

## Tools

37 MCP tools — the compression/read tools are marked `readOnlyHint: true` so Claude Code and other MCP clients can call them safely in parallel; the handful that mutate state (session recording, the loop guard, output masking) are not.

| Tool | What it does |
|---|---|
| **compress** | Removes stop words, lemmatizes content words. Up to 70% token reduction. |
| **detect_language** | Identifies language of any text. Returns ISO 639-3 code. |
| **route_content** | Auto-detects JSON, HTML, diff, log, code or prose and applies the best algorithm — also collapses low-signal command output to 1-3 facts when `command`/`exit_code` are passed. |
| **summarize** | Extractive summarization — keeps the most important sentences (TF-IDF or TextRank). |
| **compress_batch** | Compresses a list of texts in one call. |
| **compress_for_context** | Compresses content to fit a token budget. Chains routing → NLP → TextRank until budget met. |
| **compress_conversation** | Compresses a messages list. Keeps last N verbatim, summarizes/collapses older turns. |
| **deduplicate** | Removes near-duplicate texts using cosine bag-of-words similarity. Configurable threshold. |
| **session_record** | Persists a decision or context note across sessions (ChromaDB or lexical fallback) — credential-shaped text (AWS/GitHub/Slack tokens, PEM blocks, `.env` dumps) is redacted before it ever touches disk. |
| **session_recall** | Retrieves past decisions by semantic or keyword similarity. |
| **session_start / session_end** | Track session boundaries and emit summaries. |
| **compress_file** | Read a file by path and return only the compressed content. Avoids loading raw files into context. |
| **synthelion_status** | Returns aggregate token savings and estimated cost as structured JSON. |
| **safety_check** | Flags security-critical or destructive-command text before it gets compressed away. |
| **check_sensitive_content** | Scans text for credential-shaped content (AWS/GitHub/Slack tokens, PEM blocks, Bearer headers, `.env` dumps) before persisting it. |
| **analyze_waste** | Detects HTML noise, base64 blobs, excess whitespace, inline JSON bloat — read-only. |
| **check_cache_alignment** | Scans a system prompt for volatile tokens (UUIDs, timestamps, JWTs, hashes) that break provider KV-cache prefix reuse. |
| **align_cache_prompt** | Rewrites a system prompt so volatile blocks sink to the end, keeping the cacheable prefix stable call-to-call. |
| **shape_output** | Appends verbosity-steering instructions to a system prompt to cut the model's *output* tokens. |
| **focus_relevant** | Query-focused context shaping: keeps only the top-K most relevant blocks of a text. |
| **list_relevant_tools** | Filters the full tool list down to the ones most relevant to a task/query, for orchestrators building their own per-turn `tools=[...]` array. |
| **estimate_cost** | Estimates the USD/EUR value of a token count for a given model. |
| **generate_commit_message** | Generates a conventional commit message from a git diff. |
| **review_diff** | Generates single-line PR review comments from a git diff (bugs, security, perf, TODOs). |
| **generate_project_wiki** | Scans a project folder into an AI-synthesized Markdown wiki — `depth` 1-4 controls detail (see [Web dashboard](#web-dashboard) Settings for the default). |
| **check_tool_loop** | Pre-tool guardrail: blocks a tool call that would repeat an identical prior call too many times in a row (agent stuck retrying). |
| **reset_tool_loop** | Clears the loop-guard history for a session after a genuine change of approach. |
| **mask_old_tool_output** | Replaces all but the most recent N entries in a chronological tool-output list with a placeholder, storing originals for later retrieval. Returns an Artifact Index alongside the masked list. |
| **expand_masked_output** | Retrieves the original text behind a `mask_old_tool_output` placeholder, by its hash. |
| **get_artifact_index** | Returns the catalog of everything masked so far, grouped by tool — meant to be re-injected into context so the model knows what was hidden. |
| **rewrite_command** | Suggests a less verbose variant of a known shell command (same semantics/exit code) — advisory only, never executed. Refuses composite commands. |
| **diff_tool_output** | For a tool called again with identical arguments, returns a unified diff against the previous call's output instead of the full text again, when that's actually shorter. |
| **get_response_style_guidance** | Returns verbosity-reduction instructions to inject into an agent's own system prompt (no filler openings, structured bug-fix format, CJK-aware) — shapes the model's *output*, not its input context. |
| **track_file_read** | Records a file read for freshness tracking within a session — returns whether it's fresh or already stale. |
| **track_file_write** | Records a file write — any earlier tracked reads of that path become stale. |
| **check_read_maturity** | Checks whether a tracked file read is stale/superseded and has been quiet long enough to safely collapse into a compact marker. |

Two more ship as CLI-only, meant for shell hooks rather than an agent calling them directly: `synthelion loop-check` / `synthelion loop-reset` — same loop guard, but persisted across process invocations (`~/.synthelion/loop_guard.jsonl`) for use as an external `PreToolUse`-style hook, since a hook script is a fresh process every call and can't keep the MCP tools' in-memory history.

---

## Code examples

### Text compression

```python
from synthelion import CompressionService, CompressionLevel

svc = CompressionService()

# Semantic (default) — removes stop words and lemmatizes
r = svc.compress(
    "I would like to know if it is possible to receive information about cheap restaurants in Rome, please.",
    CompressionLevel.SEMANTIC,
)
print(r.compressed_text)      # like know possible receive information about cheap restaurant Rome
print(f"{r.efficiency_pct:.1f}% saved")   # 55.0% saved
print(f"{r.original_tokens} → {r.compressed_tokens} tokens")

# Aggressive — also removes generic verbs and adjectives
r = svc.compress("The important thing is to find a good and reliable solution.", CompressionLevel.AGGRESSIVE)
print(r.compressed_text)      # solution

# Statistical — TF-IDF word scoring instead of curated dictionaries
r = svc.compress(
    "I would like to know if it is possible to receive information about cheap "
    "restaurants in Rome, please. The city has many wonderful places to eat.",
    CompressionLevel.STATISTICAL,
)
print(r.compressed_text)      # like possible receive information about cheap restaurant Rome city wonderful eat

# Explicit language (skip auto-detection)
r = svc.apply_compression(
    "Ich hätte gerne einen Kaffee, bitte.",
    iso3="deu",
    level=CompressionLevel.SEMANTIC,
)
print(r.compressed_text)      # gerne kaffee bitten

# Batch — compress many prompts at once
results = svc.compress_batch(
    ["Tell me about Rome.", "What is the capital of France?", "Explain neural networks."],
    CompressionLevel.SEMANTIC,
)
for r in results:
    print(r.compressed_text, f"({r.efficiency_pct:.0f}% saved)")
```

---

### Language detection

```python
from synthelion import LanguageDetector

det = LanguageDetector()

print(det.detect("Wo ist der nächste Bahnhof?"))        # deu
print(det.detect("Je voudrais une table pour deux."))   # fra
print(det.detect("Quiero información sobre Madrid."))   # spa

# Confidence scores for all matched languages
scores = det.detect_with_scores("Where is the nearest train station?")
# → {"eng": 0.42, "afr": 0.05, ...}
top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
print(top)   # [("eng", 0.42), ...]
```

---

### Content router — auto-detects and picks the best algorithm

```python
from synthelion import ContentRouter, CompressionProfile

router = ContentRouter.from_profile(CompressionProfile.BALANCED)

# JSON array → lossless markdown table or BM25 row-drop
json_data = '[{"name":"Alice","age":30,"city":"Rome"},{"name":"Bob","age":25,"city":"Milan"}]'
r = router.route(json_data)
print(r.strategy_used)   # JsonCrush:MarkdownTable
print(r.compressed)
# | name  | age | city  |
# | Alice | 30  | Rome  |
# | Bob   | 25  | Milan |
print(f"{r.savings_pct:.1f}% saved")

# HTML → extract text, then NLP-compress
html = "<html><body><h1>Visit Rome</h1><p>Rome is a beautiful city with ancient history.</p></body></html>"
r = router.route(html)
print(r.strategy_used)   # HtmlExtract+NlpCompression
print(r.compressed)      # Visit Rome Rome beautiful city ancient history

# Git diff → keeps +/- lines, trims context
diff = """--- a/main.py\n+++ b/main.py\n@@ -10,7 +10,7 @@\n def hello():\n-    print("Hello world")\n+    print("Hello Synthelion")\n     return True"""
r = router.route(diff)
print(r.strategy_used)   # DiffCompression

# Build log → deduplicates repeated lines
log = """ERROR: connection refused\nERROR: connection refused\nERROR: connection refused\nINFO: retrying..."""
r = router.route(log)
print(r.compressed)      # ERROR: connection refused  [×3]\nINFO: retrying...

# Source code → strips comments and blank lines
code = """
def greet(name):
    # This function greets the user
    # It prints a greeting message
    print(f"Hello, {name}!")  # say hello
"""
r = router.route(code)
print(r.compressed)      # def greet(name):\n    print(f"Hello, {name}!")
```

---

### Summarization

```python
from synthelion.nlp import TfIdfSummarizer, TextRankSummarizer

long_text = """
Rome is the capital of Italy and one of the most visited cities in the world.
It was founded in 753 BC and served as the center of the Roman Empire for centuries.
The city contains numerous ancient monuments including the Colosseum, the Pantheon,
and the Roman Forum. Vatican City, an independent state within Rome, is the seat of
the Catholic Church. Today Rome is a major European capital with a population of
nearly three million people. Its economy is driven by tourism, culture, and public
administration. Every year millions of tourists visit from every corner of the globe.
"""

# TF-IDF — best for factual/report text, picks sentences with rare distinctive words
tfidf = TfIdfSummarizer()
print(tfidf.summarize(long_text, sentence_count=3))

# TextRank — best for narrative text, picks sentences central to the storyline
tr = TextRankSummarizer()
print(tr.summarize(long_text, ratio=0.4))   # keep 40% of sentences

# Chain: summarize first, then compress — maximum token savings
summary = tr.summarize(long_text, sentence_count=3)
from synthelion import CompressionService, CompressionLevel
compressed = CompressionService().compress(summary, CompressionLevel.SEMANTIC)
print(compressed.compressed_text)
print(f"Final size: {compressed.compressed_tokens} tokens (was {len(long_text.split())})")
```

---

### Agent memory & context window

```python
from synthelion.agent import ContextWindow, MemoryStore, MemoryExtractor

# Rolling context window — auto-compacts when it exceeds the token budget
window = ContextWindow(max_tokens=2000, keep_last_turns=4)

for i in range(20):
    window.append("user", f"Message {i}: tell me about topic {i} in great detail...")
    window.append("assistant", f"Response {i}: here is a detailed explanation of topic {i}...")

print(f"Messages in window: {window.message_count}")   # stays bounded
print(window.to_messages_json(indent=2))               # ready for any LLM API

# Long-term memory across sessions
extractor = MemoryExtractor()
note = extractor.extract("The user lives in Rome and works in tech. They prefer Python over C#.", max_sentences=2)
# → {"summary": "User lives Rome works tech.", "keywords": ["Rome", "Python", "tech"]}

store = MemoryStore()
store.remember(note)
store.remember({"summary": "User prefers dark mode and short answers.", "keywords": ["dark mode", "concise"]})

# Save to disk, restore next session
json_blob = store.save()
store2 = MemoryStore()
store2.load(json_blob)

# Recall what's relevant for the current query
hits = store2.recall("What does the user prefer for coding?", top_k=2)
print(hits[0]["summary"])   # User lives Rome works tech.
```

---

### AI-agent context tools

#### compress_file — read and compress a file by path

```python
# Instead of: content = open("big_log.txt").read()  → 8000 tokens sent to LLM
# Do this:
r = execute_tool("compress_file", {"path": "big_log.txt", "profile": "agent"})
print(r["compressed"])          # deduplicated log, ~1200 tokens
print(r["synthelion_metrics"])  # "before=8000 after=1200 saved=6800 (85.0%) ~$0.02040"
print(r["detected_type"])       # "log"

# With a token budget
r2 = execute_tool("compress_file", {
    "path": "src/big_module.py",
    "max_tokens": 500,
    "profile": "agent",
})
print(r2["fits_budget"])        # True if ≤ 500 tokens
```

#### compress_for_context — fit content into a token budget

```python
from synthelion.plugins.openai_tools import execute_tool

long_article = """Artificial intelligence is a branch of computer science that aims to create
intelligent machines... [1000+ token document]"""

# Compress without a budget — route + NLP, agent profile
r = execute_tool("compress_for_context", {"content": long_article, "profile": "agent"})
print(r["compressed"])           # compressed text
print(r["synthelion_metrics"])   # "before=213 after=82 saved=131 (61.5%) ~$0.00039"
print(r["detected_type"])        # "prose"
print(r["strategy"])             # "NlpCompression"

# Compress to fit in a 200-token context window
r2 = execute_tool("compress_for_context", {
    "content": long_article,
    "max_tokens": 200,
    "prefer": "auto",    # "compress" | "summarize" | "auto"
})
print(r2["fits_budget"])         # True or False
print(r2["budget_exceeded_by"])  # 0 if fits, else delta
```

#### compress_conversation — shrink a message history

```python
conversation = [
    {"role": "user",      "content": "Tell me about machine learning in detail."},
    {"role": "assistant", "content": "Machine learning is a subset of AI that enables..."},
    {"role": "user",      "content": "Can you explain supervised vs unsupervised learning?"},
    {"role": "assistant", "content": "Supervised learning uses labeled data, like spam detection..."},
    {"role": "user",      "content": "What Python libraries should I use?"},   # ← kept verbatim
]

r = execute_tool("compress_conversation", {
    "messages": conversation,
    "keep_last_n": 2,    # last 2 messages verbatim
    "max_tokens": 150,   # collapse older turns if still over budget
})
print(r["messages_before"], "→", r["messages_after"])
print(r["strategy"])     # "nlp_compress" or "summarize_collapse"
for m in r["messages"]:
    print(f"[{m['role']}] {m['content'][:80]}")
```

#### deduplicate — remove overlapping retrieved chunks

```python
# Classic RAG problem: multiple retrieval sources return similar chunks
chunks = [
    "Python is a high-level programming language used for web development and data science.",
    "Python programming language high-level web development data science applications.",  # near-dup
    "Rome is the capital city of Italy and a center of civilization for thousands of years.",
    "JavaScript is primarily used for web front-end development in browsers.",
    "Rome, Italy capital, civilization center, history monuments.",   # near-dup of Rome
]

r = execute_tool("deduplicate", {"texts": chunks, "threshold": 0.75})
print(f"Kept {r['deduplicated_count']}/{r['original_count']} chunks")
# Kept 3/5 chunks
for t in r["texts"]:
    print("-", t[:70])
```

#### Analytics — track cumulative savings

```python
from synthelion.analytics.ledger import get_ledger

ledger = get_ledger()
summary = ledger.summary()
print(f"Total calls:  {summary['total_calls']}")
print(f"Tokens saved: {summary['tokens_saved']:,}")
print(f"Cost saved:   ${summary['cost_usd_saved']:.4f}")
print(f"Note:         {summary['pricing_note']}")
# Cost saved:   $0.0234
# Note:         Estimated at Sonnet 4.6 input price ($3.00/MTok)
```

---

## Compression levels

| Level | What it removes | Typical savings |
|---|---|---|
| `light` | Stop words (articles, prepositions, conjunctions…) | 25–55% |
| `semantic` | Stop words + lemmatization to base form | 30–55% |
| `aggressive` | Everything above + generic verbs and descriptive adjectives | 35–75% |
| `statistical` | TF-IDF word scoring instead of curated dictionaries — keeps words that score above the prompt's own median relevance | 40–65% |
| `syntactic` | Rule-based pruning: keeps grammatical glue only where it touches a surviving word, plus (when POS data is available) elides a leading hedging/matrix clause in favour of the sentence's last verb | 45–70% |

Negation particles ("non"/"not"/"ne...pas"/"no"/"nicht"/"não"/"不") are always
protected and never dropped, at every level, in every supported language they
apply to — dropping a negation doesn't just cost fluency, it inverts the
sentence's meaning.

Default: `semantic`. All levels are additive — earlier levels are never
removed or replaced when a new one ships.

---

## Supported languages (50+)

Afrikaans · Arabic · Armenian · Basque · Belarusian · Bengali · Bulgarian · Catalan · Chinese · Croatian · Czech · Danish · Dutch · English · Estonian · Finnish · French · Galician · German · Greek · Hebrew · Hindi · Hungarian · Icelandic · Indonesian · Irish · Italian · Japanese · Kannada · Kazakh · Korean · Latin · Latvian · Lithuanian · Macedonian · Malay · Marathi · Norwegian · Persian · Polish · Portuguese · Romanian · Russian · Serbian · Slovak · Slovenian · Spanish · Swedish · Tamil · Telugu · Thai · Turkish · Ukrainian · Urdu · Vietnamese

Language is detected automatically from the text. Pass an explicit ISO 639-3 code to override.

---

## Troubleshooting

**`synthelion-mcp: command not found`**

The CLI entry point is not in your PATH. Fixes (choose one):

```json
// Option A — use the Python module form
{
  "mcpServers": {
    "synthelion": {
      "command": "python",
      "args": ["-m", "synthelion.plugins.mcp_server"]
    }
  }
}
```

```json
// Option B — use uvx (always works, no PATH needed)
{
  "mcpServers": {
    "synthelion": {
      "command": "uvx",
      "args": ["synthelion-mcp"]
    }
  }
}
```

```json
// Option C — absolute path to the installed binary
// Windows: find it with: where synthelion-mcp
// Linux/macOS: which synthelion-mcp
{
  "mcpServers": {
    "synthelion": {
      "command": "C:\\Users\\you\\AppData\\Local\\Programs\\Python\\Python312\\Scripts\\synthelion-mcp.exe"
    }
  }
}
```

**Hook not firing (Windows)**

Run `where synthelion` in PowerShell to verify the CLI is in PATH. If not, add the Scripts folder to PATH:
```powershell
$env:PATH += ";$env:APPDATA\Python\Python312\Scripts"
```

**Hook not firing (Linux/macOS)**

Verify with `which synthelion`. If using a virtualenv, activate it before starting Claude Code or use the absolute path in the hook command.

**Detection errors (wrong language detected)**

Pass the language explicitly:
```bash
synthelion compress --text "..." --language ita
```

Or in Python:
```python
result = svc.compress(text, iso3="ita")
```

**Something not working? Run the health check first:**

```bash
synthelion doctor
```

Output:
```
[✓] mcp package installed (mcp 1.9.4)
[✓] synthelion 1.1.0
[✓] savings ledger: ~/.synthelion/savings.jsonl (42 entries)
[!] session DB: chromadb not installed — lexical fallback active
[✓] synthelion-mcp in PATH
[✓] Claude MCP config: ~/.claude.json → synthelion registered
```

Install chromadb for semantic (vector) session recall:
```bash
pip install "synthelion[chromadb]"
```

---

## Optional extras

| Extra | Installs | Enables |
|---|---|---|
| `synthelion[langchain]` | `langchain-core` | `get_tools()`, `SynthelionMemory` |
| `synthelion[openai]` | `openai` | `OpenAIAdapter` |
| `synthelion[claude]` | `anthropic` | `ClaudeAdapter` |
| `synthelion[chromadb]` | `chromadb` | Vector session recall in `session_record` / `session_recall` |
| `synthelion[all]` | everything above | Full stack |

---

## Contributing

Contributions are welcome — new language data, new content-router strategies,
framework adapters, bug reports, or a good first issue. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the local dev setup and PR guidelines.

If Synthelion is saving you tokens, a ⭐ on the repo helps other people find it:
[github.com/francescopaolopassaro/synthelion](https://github.com/francescopaolopassaro/synthelion)

---

## Sponsors

<img src="https://www.digitalsolutions.it/img/partners/novaroutelogo.png" alt="NovaRouteAI" height="180" style="max-width: 100%; height: auto; min-height: 180px; max-height: 190px;">

**[NovaRouteAI](https://novarouteai.com/?ref=synthelion)** — Build with Chinese AI models through one simple API.

NovaRouteAI helps developers and AI SaaS teams test, compare, and run models like DeepSeek, Qwen, Doubao, Kimi, and GLM without managing multiple provider accounts. Start with test credits and optimize your cost per successful task.

[Click here to know NovaRouteAI](https://novarouteai.com/?ref=synthelion)

---

## Links

- **PyPI:** https://pypi.org/project/synthelion/
- **Source:** https://github.com/francescopaolopassaro/synthelion
- **Original C# project (Caveman):** https://github.com/francescopaolopassaro/caveman

© 2026 Passaro Francesco Paolo — Digitalsolutions.it
