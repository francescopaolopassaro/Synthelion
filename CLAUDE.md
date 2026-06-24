# Synthelion — Project Guide for Claude Agents

**Synthelion** is a Python port of [Caveman](https://github.com/francescopaolopassaro/caveman) (C#) by Passaro Francesco Paolo.  
It is both a **Claude Code MCP plugin** and a standalone Python library for LLM token compression.

---

## What this project does

Synthelion reduces token count in LLM prompts by:
- Removing grammatical "noise" (stop words: articles, prepositions, conjunctions, auxiliaries)
- Lemmatizing inflected words to their base form (e.g. `studying → study`, `gatti → gatto`)
- Routing content to the best algorithm (JSON, HTML, git diff, log, code, plain text)
- Summarizing long texts with TF-IDF or TextRank

**No ML models, no API calls, no downloads at runtime.** All language data (50+ languages) ships as brotli-compressed YAML files inside the package.

---

## Project structure

```
synthelion/
├── __init__.py          Public API: CompressionService, LanguageDetector, ContentRouter
├── models.py            Dataclasses: CompressionResult, RoutedCompressionResult, enums
├── word_provider.py     Loads worddata/*.br (brotli YAML), curated function-word lists
├── detector.py          Language detection by stop-word frequency scoring
├── core.py              NLP compression: Light / Semantic / Aggressive levels
├── content_detector.py  Heuristic content-type classification
├── content_router.py    Routes to best compressor, in-process cache (30 min TTL)
├── compressors/
│   ├── json_crusher.py     JSON array → CSV / markdown table / BM25 row-drop
│   ├── html_extractor.py   HTML → plain text (stdlib html.parser)
│   ├── diff_compressor.py  Unified diff → keep +/- lines, trim context
│   ├── log_compressor.py   Logs/stacktraces → deduplicate repeated lines
│   ├── code_compressor.py  Strip // # /* */ comments and blank lines
│   └── tabular.py          Markdown table column pruning
├── nlp/
│   ├── text_splitter.py     Unicode tokenizer
│   ├── sentence_detector.py Sentence splitting with abbreviation lists
│   ├── summarizer.py        TF-IDF + MMR + position bias
│   └── text_rank.py         TextRank (PageRank damping=0.85, 100 iter) + MMR
├── agent/
│   ├── context_window.py   Rolling token-budget buffer, auto-compact with TextRank
│   ├── memory_extractor.py Distil salient sentences + key terms
│   └── memory_store.py     JSON-persisted long-term memory, lexical recall
├── plugins/
│   ├── mcp_server.py    MCP stdio server (tools: compress, detect_language, route_content, summarize, compress_batch)
│   └── openai_tools.py  OpenAI function tool definitions + executor
├── cli.py               CLI: compress / detect / route / summarize / serve-mcp
└── worddata/            _index.br + *.yaml.br  (56 files, one per language)
```

---

## Running tests

```bash
python -m pytest tests/ -v
```

All 52 tests must pass. Python 3.11+ required. Dependencies: `brotli`, `regex`, `mcp`.

---

## Key design rules (follow when modifying)

1. **Package name is `synthelion`** everywhere — directories, imports, CLI commands, PyPI.
2. **Attribution required**: every source file header must reference Caveman C# with URL `https://github.com/francescopaolopassaro/caveman`.
3. **`.claude/` excluded from git** — always keep this rule in `.gitignore`.
4. **No ML models**: the library must stay dependency-free (only `brotli`, `regex`, `mcp`).
5. **worddata files are binary blobs** — never edit `synthelion/worddata/*.br` manually; they come from the C# project's compile-worddata script.

---

## Common tasks

### Add a new compressor
1. Create `synthelion/compressors/my_compressor.py`
2. Export from `synthelion/compressors/__init__.py`
3. Add detection in `content_detector.py` and routing branch in `content_router.py`
4. Add a test in `tests/test_synthelion.py`

### Add a new MCP tool
1. Add the tool definition to `get_tool_definitions()` in `synthelion/plugins/openai_tools.py`
2. Add the execution branch to `execute_tool()` in the same file
3. The MCP server picks it up automatically (it reads `get_tool_definitions()`)

### Publish to PyPI
```bash
python -m pip install build twine
python -m build
twine upload dist/*
```

---

## Attribution

Python port of **Caveman** — © 2026 Passaro Francesco Paolo, Digitalsolutions.it.  
Original: https://github.com/francescopaolopassaro/caveman  
Language data: Universal Dependencies (CC BY-SA / CC BY).
