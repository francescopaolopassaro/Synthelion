# Changelog

All notable changes to Synthelion are documented here.

---

## [1.2.0] — 2026-07-18

### Fixed (found while refreshing the installed Claude Code hook)
- **`install_claude.py`'s Windows `UserPromptSubmit` hook was broken** —
  `_hook_command_windows` called the compress binary as `$p|"C:\...\synthelion.exe" compress --json`,
  which PowerShell rejects (`ExpressionsMustBeFirstInPipeline` — a quoted
  path followed by arguments needs the `&` call operator). The hook had
  silently regressed at some point after being manually patched directly in
  a live `settings.json`; re-running the installer overwrote that working
  fix with the broken generator output. Fixed by adding `& ` before the
  quoted path, matching `install_claude.ps1` (which already had it).
- Also brought `_hook_command_windows`/`_hook_command_unix` back in line with
  `install_claude.ps1`/`install_claude.sh`: they had drifted to injecting only
  an efficiency/energy/CO2 *label*, dropping the actual compressed prompt
  text from `additionalContext` — the whole point of the hook. Restored the
  `'[Synthelion N% saved] ' + compressed_text` format all three installers
  now share.
- **`install_claude.sh`** read the wrong JSON field (`compressed_text`,
  which `synthelion compress --json` has never emitted — the real field is
  `compressed`), so the Unix hook always injected an empty string. Fixed.
- Verified end-to-end: ran `install_claude.py --no-pip`, extracted the
  written hook command from `~/.claude/settings.json`, and executed it
  through real `powershell.exe` with JSON piped over stdin exactly as Claude
  Code invokes it — confirmed valid `hookSpecificOutput` JSON with the
  compressed text for a >200-char prompt, and silent no-op for a short one.

### Changed
- **The `UserPromptSubmit` hook now also returns a top-level `systemMessage`**
  in all three installers (`install_claude.py`, `.ps1`, `.sh`). Previously the
  savings note was injected only into `hookSpecificOutput.additionalContext`,
  which Claude reads but Claude Code never displays — the hook was working
  but invisible. `systemMessage` is shown directly in the terminal, so the
  compression is now visibly confirmed on every prompt it fires for.
- **`systemMessage` and `additionalContext` now carry different content**,
  each tuned for its actual audience: `systemMessage` (user-visible) is a
  short label — `'[Synthelion N% saved - X mWh - Y mg CO2 saved]'` — with no
  compressed text, so the terminal doesn't get cluttered with keyword-bag
  output; `additionalContext` (Claude-only, never rendered) still carries the
  full compressed text, since that's what actually does the token-saving
  work. Re-verified end-to-end via real `powershell.exe` with JSON piped over
  stdin: `systemMessage` and `additionalContext` now differ as intended.

Incremental update porting the algorithmic/correctness work from **Caveman 1.4.1** (the
original C# project — https://github.com/francescopaolopassaro/caveman) to Python. All
new capabilities are additive: existing levels, methods and return signatures keep
working exactly as before unless noted.

### Fixed
- **Critical: `CompressionLevel.AGGRESSIVE` crashed on every non-trivial sentence** —
  `_filter_aggressive` referenced an undefined `group` name (the `_lang_group(iso3)`
  call was missing). `compress()` silently swallowed the exception into
  `error_message`; direct `apply_compression()` calls (e.g. from the MCP server)
  raised outright. Fixed; added regression tests (the existing test for this path
  only checked token counts, which happened to pass even with the exception
  swallowed — now also asserts `error_message is None`).
- **Tokenizer fragmented words in scripts using combining marks** (Kannada, Hindi,
  Tamil, Thai, …): both `core._tokenize` and `detector._WORD_RE` excluded Unicode
  combining marks (category M*), splitting e.g. "दिन" into "द" and "न". Switched
  to the `regex` package (already a declared dependency) with `\p{L}\p{M}` Unicode
  property escapes — a compiled matcher, not a per-character loop, so no
  performance regression.
- **Silent content loss from two overly-broad descriptive-word suffixes**, found via
  a new comprehensibility test suite: the Romance `"are"` suffix matched every
  Italian first-conjugation infinitive verb ("analizzare") in addition to its
  intended "-are" adjectives, silently deleting sentences' main verbs; the English
  `"al"`/`"ical"` suffixes matched domain-specifying adjectives ("financial") as
  often as decorative ones. Both removed from their suffix lists.
- **Historical-treebank contamination in the bundled word data** (Italian, Swedish,
  Romanian, Icelandic): an archaic sense of a word (e.g. Italian "torta" — modern
  "cake" — annotated as a form of "torcere", "to twist", throughout Dante's Divine
  Comedy) could outvote the modern meaning in the lemma map. Word data files
  regenerated from Caveman's corrected pipeline, which now excludes treebanks that
  silently share a modern language's name (`-Old`, `PaHC`, and
  `UD_Romanian-Nonstandard`, found by reading treebank READMEs rather than by
  naming pattern alone).

### Added
- **`CompressionLevel.STATISTICAL`** — TF-IDF word scoring as an alternative to
  curated dictionaries: scores each word by frequency in the prompt vs. how many of
  the prompt's own sentences contain it, grounding "common" words against the
  language's curated function/generic-word lists as the standard-corpus reference.
- **`CompressionLevel.SYNTACTIC`** — rule-based pruning: same content-word filtering
  as `AGGRESSIVE`, but a function word survives when it is grammatical glue directly
  touching a surviving word, so the result reads as a terse but grammatical sentence
  rather than a keyword bag. When POS data is available for the language (see
  below), also elides a leading hedging/matrix clause ("I kindly ask you to…") in
  favour of the sentence's last verb — gated on real POS evidence and restricted to
  never fire when a genuine content noun sits between two candidate verbs, so
  coordinated clauses ("I bought bread and ate cake") are never mistaken for a
  hedge clause and gutted.
- **`FunctionWordProvider.get_pos_tags(iso3)` / `get_pos_tag(word, iso3)`** — a
  Universal POS lookup (NOUN, VERB, ADJ, ADP, DET, …), the most frequent tag
  Universal Dependencies treebanks observed per word form. A frequency-baseline
  tagger, not a model — covers 54 of 55 mappable languages.
- **`FunctionWordProvider.get_generic_words(iso3)`** now derives a generic-word set
  algorithmically for every language without a curated `{iso3}.generic.yaml.br`
  file, instead of falling back to nothing: the most richly inflected verb lemmas
  in that language's own worddata are ranked as the generic set (validated against
  Polish, where the top-ranked lemmas are "być"/be, "mieć"/have, "mówić"/say —
  exactly the target category, derived from data instead of a translated list).
- **`synthelion.simhash`** — a 64-bit Charikar SimHash fingerprint (FNV-1a feature
  hashing, stdlib only) for near-duplicate text detection.
  `LogCompressor.compress(..., fuzzy=True)` uses it to group near-duplicate lines
  (not just exact matches after normalisation) — e.g. templated lines that
  substitute a username or IP address. Off by default.
- **`CodeCompressor.compress(code, skeletonize=True)`** — an additional pass that
  replaces function/method bodies with a placeholder, keeping only signatures. Real
  brace-depth counting (not regex) handles arbitrary nesting and braces inside
  string/char literals correctly; Python bodies are found by indentation. Only leaf
  `def`/method bodies are collapsed, never a `class`/type container. Lossy by
  design, so off by default; the return signature gained a 4th element
  (`functions_skeletonized`).
- **`_bm25_select(..., delta=1.0)`** in the JSON crusher — BM25+ instead of plain
  BM25: a lower-bound term is added to every non-zero term match, so a genuinely
  relevant row that only mentions the query term once no longer scores near zero
  just because it's a long row.
- **`synthelion.nlp.TopicSegmenter`** — TextTiling-style topic segmentation
  (Hearst, 1997): groups sentences into blocks, scores vocabulary similarity
  between adjacent blocks, and cuts where similarity dips sharply relative to the
  surrounding peaks.
  **`TfIdfSummarizer.summarize_topic_aware(...)`** is a new, separate method
  (existing `summarize` is unchanged) that segments first and allocates the
  sentence budget proportionally across topics (largest-remainder rounding), so a
  summary can't let one statistically dense topic dominate and starve the others —
  falls back to `summarize()` when segmentation finds no real topic structure.
- **`synthelion.retriever.Retriever`** — BM25+ ranking over arbitrary text chunks
  (sentences, conversation turns, log lines, …), with `retrieve_with_feedback`
  adding an RM3 pseudo-relevance-feedback pass: an initial BM25 ranking builds a
  relevance model from its own top results' vocabulary, expands the query with
  that model's top terms, and re-ranks — surfacing genuinely relevant chunks that
  don't literally contain the query's words.
- **A comprehensibility test suite** treating "would a reader — human or AI — still
  get the point from the compressed text alone?" as a directly testable property.

#### Cluster / multi-node / AI-provider-scale deployment
- **`synthelion.config`** — JSON configuration with a fixed resolution order
  (`SYNTHELION_CONFIG` env var → `./synthelion.config.json` → `~/.synthelion/config.json`
  → built-in defaults), deep-merged so a partial file only needs to override the keys
  it cares about. Covers `session_store` (local/redis/postgres), `vector_store`
  (chromadb/qdrant/lexical), and `dashboard` (host/port/realtime mechanism) — the
  shape a Kubernetes ConfigMap-mounted file or a per-node override needs.
- **`synthelion configure`** CLI command — writes/updates `~/.synthelion/config.json`
  from flags (`--session-store`, `--redis-url`, `--postgres-dsn`, `--vector-store`,
  `--qdrant-url`, `--dashboard-host/--dashboard-port`, `--realtime`), or `--show` to
  print the effective config without writing anything.
- **`synthelion.analytics.session_store`** — a `SessionStore` abstraction with three
  interchangeable backends behind `create_session_store(config)`:
  `LocalFileSessionStore` (wraps the existing lock-free ledger, single-node),
  `RedisSessionStore` (pipelined hash/set/counter writes, lazy `import redis`),
  and `PostgresSessionStore` (auto-creates its schema on first connect, lazy
  `import psycopg`) — so active-session visibility can span every node behind a
  load balancer instead of being per-process.
- **Qdrant as a third `session_db` vector-store backend** (alongside the existing
  ChromaDB and lexical-fallback paths), selected via `vector_store.backend` in
  config or `SessionDB(backend="qdrant")`. Consistent with Synthelion's "zero ML
  models" design: rather than pulling in an embedding model just for Qdrant, it
  indexes a deterministic hashed bag-of-words vector (`_hash_vector`, FNV-1a
  feature hashing — the same stable hash `simhash` uses, not Python's
  per-process-randomised `hash()`) — enough for Qdrant's ANN index to support
  "find similar decisions" recall across a cluster without adding a heavyweight
  dependency. Falls back to lexical search if the `qdrant-client` package isn't
  installed or the server is unreachable, exactly as the ChromaDB path already did.
- New optional dependency groups in `pyproject.toml`: `qdrant`, `redis`, `postgres`,
  and a `cluster` bundle of all three — none required for the single-node default.

#### Docker / Kubernetes / Docker Swarm deployment
- **`Dockerfile`** — multi-stage build (`pip install ".[cluster]"` in a builder
  stage, non-root runtime user), runs `synthelion serve-dashboard --host
  0.0.0.0` by default, `HEALTHCHECK` against `/api/summary`. Verified
  end-to-end: image builds, container boots, dashboard responds, and a
  session-store write succeeds through a mounted named volume.
- Fixed a **root-owned volume-mount permission bug** found while verifying the
  image: the local session/vector store directory
  (`~/.synthelion`, incl. the ChromaDB `sessions` subdir) didn't exist in the
  image before `USER synthelion` took effect, so Docker seeded any volume
  mounted there as `root:root` — every write then failed with `[Errno 13]
  Permission denied`. Fixed by pre-creating the directory tree with the
  correct ownership as root, before switching to the non-root user and
  declaring the `VOLUME`.
- **`docker-compose.yml`** — single-node quick start (`docker compose up -d`)
  plus a `cluster` profile (`--profile cluster`) that also starts Redis,
  Postgres, and Qdrant containers. Same file deploys to Docker Swarm via
  `docker stack deploy`. Fixed a **replica/port-binding conflict**: `deploy.replicas:
  2` broke plain `docker compose up` (newer Compose honours `deploy.replicas`
  outside Swarm too, and two replicas can't both bind host port 8787) —
  reverted to `replicas: 1` for local use, documented `docker service scale`
  for Swarm's routing-mesh-backed scaling instead. Verified with a live
  `docker compose up -d` run.
- **`synthelion.config.example.json`** — a ready-to-copy config showing the
  Redis + Qdrant cluster-profile wiring, validated against `synthelion.config.load_config`.
- **`k8s/`** — `namespace.yaml`, `configmap.yaml` (mounts
  `synthelion.config.json`), `deployment.yaml` (3 replicas +
  `HorizontalPodAutoscaler`, readiness/liveness probes, non-root
  `securityContext`), `service.yaml` (ClusterIP), `backing-services.yaml`
  (evaluation-grade in-cluster Redis + Qdrant `StatefulSet`s). All manifests
  YAML-parse-validated.
- New "Cluster deployment" section in README.md covering `synthelion
  configure`, Docker/Compose/Swarm, Kubernetes, and the plain-load-balancer
  path.

#### More agents wired into `synthelion install`
- **`synthelion install --agent cursor`** — registers Synthelion in
  `~/.cursor/mcp.json` (same `mcpServers` shape as Claude).
- **`synthelion install --agent windsurf`** — registers Synthelion in
  `~/.codeium/windsurf/mcp_config.json` (same `mcpServers` shape as Claude).
  Both were previously listed in the README as "configure via the app UI" only;
  they're now scriptable like every other supported agent.

## [1.1.0] — 2026-07-11

### Added

#### Web dashboard
- **`synthelion serve-dashboard [--host] [--port]`** — local, read-only web dashboard (stdlib `http.server`, no extra dependencies). Binds to `127.0.0.1:8787` by default.
- Bootstrap 5 and Chart.js **vendored locally** (`synthelion/plugins/dashboard_assets/vendor/`) — no CDN, works fully offline.
- KPIs: calls, tokens saved, avg efficiency, estimated cost saved, active sessions, avg calls/session, tools used, best single call, avg/p95/max latency.
- Charts: tokens saved over time, tokens saved by tool.
- Tables: by content type, recent session-memory decisions, **Sessions** (one row per `synthelion-mcp`/CLI process), **Recent requests** (full per-call feed with latency).
- Auto-start on Claude Code startup via a `SessionStart` hook — checks if the port is already listening (non-blocking) before launching.

#### Concurrency — built for high-volume AI-provider traffic
- **Lock-free append-only ledger** (`analytics/ledger.py`): `savings.json` → `savings.jsonl`, one atomic append per record instead of read-modify-write. Old array-format ledgers are migrated automatically on first read.
- **`analytics/_atomic_append.py`** — new cross-platform atomic line-append primitive. On Windows, Python's `os.open(..., O_APPEND)` is *not* atomic across processes (the CRT does a separate seek-to-EOF + write); an 8-process/1600-write stress test lost ~28% of records with the naive approach. Fixed by opening the file handle with **only** `FILE_APPEND_DATA` access via `CreateFileW` (ctypes) — verified 1600/1600 records with zero loss under concurrent writers.
- **`analytics/session_db.py`** fallback store also converted to lock-free append-only JSONL; reads always re-scan from disk instead of trusting an in-memory cache that could go stale across processes.
- **Non-blocking auto-update claim** (`mcp_server.py`): when many `synthelion-mcp` processes notice a new PyPI release at once, only one may run `pip install --upgrade` — enforced with an atomic `O_CREAT|O_EXCL` claim file (self-expiring after 5 minutes) instead of a blocking lock. Losing processes skip immediately.
- **`asyncio.to_thread`** wraps tool execution in the MCP server's `call_tool` handler — concurrent tool calls no longer serialize on the event loop.
- Every ledger record now carries **`session_id`**, **`pid`**, and **`duration_ms`** — enables per-session and per-request breakdowns without any extra plumbing at call sites.

#### CLI ledger integration
- `synthelion compress`, `synthelion route`, and `synthelion summarize` now write to the same ledger the MCP server and dashboard read (`cli_compress`, `cli_route`, `cli_summarize` tool names) — the Claude Code `UserPromptSubmit` hook's compressions are now visible in `synthelion status` and the dashboard, not just MCP tool calls.
- **`synthelion install --agent opencode [--local]`** — registers Synthelion as an MCP server in OpenCode's config (`~/.config/opencode/opencode.json` global, or `./opencode.json` project-local), using OpenCode's `mcp` schema (`type: "local"`, `command` as an array).

#### Ledger
- **`sessions_summary()`** — groups ledger records by writer process (session_id), returning calls/tokens/tools/first-last-activity per session.
- **`avg_latency_ms` / `p95_latency_ms` / `max_latency_ms`** added to `summary()`.

### Fixed
- README: OpenCode config path corrected from the non-existent `~/.config/opencode/config.json` to the real `~/.config/opencode/opencode.json`, and the MCP block corrected to OpenCode's actual schema (it previously showed the Claude/Gemini `mcpServers` shape, which OpenCode does not use).

---

## [1.0.8] — 2026-06-27

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
