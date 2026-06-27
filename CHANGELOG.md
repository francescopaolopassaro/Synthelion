# Changelog

All notable changes to Synthelion are documented here.

---

## [1.0.7] — 2026-06-25 → 2026-06-27

### Added

#### AI-agent context tools (3 new MCP tools)
- **`compress_for_context`** — compresses any content to fit within a token budget (`max_tokens`). Chains routing → NLP compression → TextRank summarization until the budget is met. Returns `fits_budget`, `strategy`, and `budget_exceeded_by` so the caller always knows exactly where it stands. Profile options: `light | balanced | agent | aggressive`.
- **`compress_conversation`** — compresses a conversation history (list of `{role, content}` messages). Keeps the last `keep_last_n` messages verbatim (default: 4), compresses older turns with the content router, and collapses everything into a `[system]` summary block when a `max_tokens` budget is provided and still exceeded.
- **`deduplicate`** — removes near-duplicate texts from a list using bag-of-words cosine similarity. Configurable `threshold` (default: 0.8). Preserves order of first occurrence. Useful when multiple retrieval sources return overlapping content.

#### Analytics & savings tracking
- **`cost_usd_saved`** field in every ledger record — estimated dollar savings at Sonnet 4.6 input pricing ($3.00/MTok). Accumulated and shown in `synthelion status` and `synthelion gain`.
- **`synthelion status`** CLI command — shows total calls, tokens before/after, avg efficiency %, cost saved, breakdown by tool and content type.
- **`synthelion gain [--days N] [--all] [--json]`** — savings history with dollar estimate and efficiency rate.
- **`synthelion bench [--json]`** — benchmark compression on a built-in 7-sample corpus (prose EN/IT, JSON array, git diff, Python code, log, HTML).

#### Cross-session memory (MCP tools)
- **`session_record`** — persist a decision or context note across sessions. Stored in ChromaDB (semantic) or lexical fallback when chromadb is not installed.
- **`session_recall`** — retrieve past decisions by semantic similarity or keyword. Supports `limit`, `since_days` filtering.
- **`session_start` / `session_end`** — track session boundaries and return summaries.
- **`synthelion_status`** — return aggregate savings stats as a structured dict (also available via MCP).

#### CLI
- **`synthelion doctor [--json]`** — health check: verifies MCP package, savings ledger, session DB, `synthelion-mcp` in PATH, and Claude Code MCP config registration.
- **`synthelion install [--agent claude|gemini] [--local]`** — registers the Synthelion MCP server in the global or project-local agent config (`~/.claude.json`, `./.claude/settings.json`, `~/.gemini/settings.json`). Idempotent — safe to re-run after upgrades.

#### Agent integrations
- **`ClaudeAdapter`** (`synthelion.integrations.claude_adapter`) — drop-in wrapper around `anthropic.Anthropic` with auto-compression + RAG memory recall on every `chat()` call.
- **`OpenAIAdapter`** (`synthelion.integrations.openai_adapter`) — equivalent wrapper for `openai.OpenAI`.
- **`RagAgent`** (`synthelion.agent.rag_agent`) — provider-agnostic stateful agent: compresses every message, recalls past decisions via SessionDB, maintains a rolling context window, and tracks token savings in the ledger.
- **`SynthelionMemory`** (LangChain plugin) — drop-in `ConversationBufferMemory` replacement that compresses history and injects RAG recall.

#### MCP server
- **`readOnlyHint: true`** annotation on all non-mutating tools — Claude Code and other MCP clients can safely call these in parallel without write-conflict checks.
- **`~$X.XXXXX`** dollar cost estimate appended to every `synthelion_metrics` field — visible in every tool response.
- **13 MCP tools total**: `compress`, `detect_language`, `route_content`, `summarize`, `compress_batch`, `compress_for_context`, `compress_conversation`, `deduplicate`, `compress_file`, `session_record`, `session_recall`, `session_start`, `session_end`, `synthelion_status`.

#### Tests
- **222 tests total** (`test_synthelion.py`: 110, `test_analytics.py`: 112): analytics suite covers SavingsLedger, SessionDB (fallback + ChromaDB mock), RagAgent, ClaudeAdapter, OpenAIAdapter, LangChain memory, and all new MCP tools.

### Fixed
- **`install_claude.ps1` — here-string parsing**: script now saved with CRLF line endings; Windows PowerShell requires CRLF for here-string delimiters (`@'...'@`)
- **`install_claude.ps1` — smoke test**: Python code no longer passed via `-c "..."` (f-string `:.0f` format and `%` operator caused PS parser errors); uses a temp `.py` file instead
- **`install_claude.ps1` — Python version check**: replaced f-string `f'{sys.version_info.major}.{minor}'` with string concatenation to avoid PowerShell `{...}` interpolation issues
- **`install_claude.ps1` — hook path escaping**: removed unnecessary double-backslash escaping; Windows paths in PS double-quoted strings do not require extra escaping
- **`install_claude.ps1` — hook call operator**: added `&` call operator before the quoted executable path
- **`install_claude.ps1` — hook bracket escaping**: escaped `[` and `]` in `additionalContext` with backtick to prevent PowerShell from parsing them as type literals
- **`cli.py` — `compress --json` output**: `energy_mwh` and `co2_mg` fields now included in JSON output

#### MCP tool — compress_file
- **`compress_file`** — read a file by path and return only the compressed content. Avoids loading the full raw file into LLM context. Accepts `path`, `profile`, `max_tokens`, `encoding`. Delegates to `compress_for_context` so routing → NLP → TextRank chain applies automatically.

#### CLI additions
- **`synthelion upgrade [--dry-run]`** — self-upgrade via `pip install --upgrade synthelion`.
- **`synthelion export [--format csv|jsonl] [-o FILE] [--days N]`** — export savings ledger for analysis in Excel / Grafana / pandas.

#### Hook improvement
- Hook now injects the **compressed text** into `additionalContext` (not just a stats label) — Claude receives the actual compressed version and can reason from it directly.
- PowerShell hook: uses string-concatenation pattern (`$ctx = '[Synthelion '+$pct+'% saved] '+$r.compressed`) — avoids PS type-literal parsing of `[...]`.
- Bash hook: uses `json.dumps` for proper escaping of the compressed string in JSON output.

#### LangChain
- `synthelion_compress_file` StructuredTool added (12 tools total in `get_tools()`).

### Changed
- **`install_claude.ps1`** installer options use PowerShell switch syntax (`-Upgrade`, `-NoHook`, `-NoPip`, `-Uninstall`)
- **`synthelion_metrics`** format extended: `before=N after=M saved=K (XX.X%) ~$0.00015` — dollar cost always included
- **Tools table**: 13 MCP tools total (`compress_file` added)

---

## [1.0.6] — 2026-06-24

### Fixed
- `__version__` was stuck at 1.0.0 — now kept in sync with `pyproject.toml`
- `"dagli"` appeared 3× in the Italian curated function-word list (duplicate entries removed)
- `mcp_server.py` docstring incorrectly said `pip install "synthelion[mcp]"` — `mcp` is now a core dependency
- `_CURATED` private symbol no longer imported directly across modules — exposed via `FunctionWordProvider.get_curated_iso3s()`
- `getattr(args, "json", False)` in CLI replaced with direct `args.json`

### Improved
- **ContentRouter cache** now has a hard max of 512 entries with 25% LRU eviction — prevents unbounded memory growth in long-running processes
- **TextRank** sentence cap added (`_MAX_SENTENCES = 200`) — prevents O(n² × 100) blowup on very long documents
- **`compress_batch()`** uses `ThreadPoolExecutor` for batches > 8 items — parallel execution with up to 4 workers
- **Error logging** added to `compress()` — failures emit a `WARNING` via Python logging instead of being fully silent
- **`py.typed` marker** added — mypy and pyright now recognize Synthelion as a fully typed package
- **`plugins/__init__.py`** now exports `get_tool_definitions`, `get_tool_list`, `execute_tool`, `serve_mcp`

### Added
- **`count_tokens(text, mode="approx")`** public function in `synthelion` namespace — GPT-style estimate (`len // 4`) or whitespace word count
- **`FunctionWordProvider.get_curated_iso3s()`** public class method
- **`CHANGELOG.md`** — this file

### Removed
- `synthelion_mcp.py` root-level script — superseded by `synthelion-mcp` console_script entry point

---

## [1.0.5] — 2026-06-24

### Fixed
- Language detector: Italian/Catalan/Portuguese confusion on short texts — curated languages now preferred when score is within 75% of best YAML-derived score
- Duplicate `get_tool_list()` definition in `mcp_server.py` removed
- 35 new tests added (LangChain plugin, CLI, JsonCrusher BM25, HTML/diff/log edge cases, Romance language disambiguation)

---

## [1.0.4] — 2026-06-24

### Added
- Full code examples in README: compress, detect, content router (JSON/HTML/diff/log/code), summarize (TF-IDF + TextRank), agent memory

---

## [1.0.3] — 2026-06-24

### Added
- Benchmark section in README: before/after examples, token savings tables by content type, cost calculator (GPT-4o), energy estimator

---

## [1.0.2] — 2026-06-24

### Added
- LangChain plugin (`synthelion/plugins/langchain_tools.py`) — 5 `StructuredTool` wrappers for LangGraph/LCEL/ReAct agents
- Universal README covering all integrations equally (MCP, OpenAI, LangChain, Python API, CLI)
- `langchain` optional extra: `pip install "synthelion[langchain]"`

---

## [1.0.1] — 2026-06-24

### Fixed
- `pyproject.toml` license field updated to SPDX format (deprecation warning resolved)

### Changed
- README simplified to focus on end-user setup

---

## [1.0.0] — 2026-06-24

### Added
- Initial public release
- Core NLP compression engine: Light / Semantic / Aggressive levels, 50+ languages
- Content router: JSON array, HTML, git diff, build logs, source code, plain text
- Summarization: TF-IDF + MMR, TextRank + MMR, chat-aware mode
- Agent toolkit: ContextWindow, MemoryExtractor, MemoryStore
- MCP server: Claude Code, OpenCode, Cursor, Windsurf, Continue
- OpenAI function tools: GPT-4, GPT-4o, Codex
- CLI: compress / detect / route / summarize / serve-mcp
- Python API: CompressionService, ContentRouter, LanguageDetector
