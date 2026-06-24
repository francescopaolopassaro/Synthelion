# Changelog

All notable changes to Synthelion are documented here.

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
