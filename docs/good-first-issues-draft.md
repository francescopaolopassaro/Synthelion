# Bozze "Good First Issue" / "Help Wanted"

Contenuti pronti da incollare manualmente su GitHub (Issues → New issue), dato
che `gh` CLI non è disponibile in questo ambiente per crearli via script.

Prima di incollarli, crea le due etichette (se non esistono già) in
**Settings → Labels**:
- `good first issue` (colore standard GitHub: `#7057ff`)
- `help wanted` (colore standard GitHub: `#008672`)

---

## 1. Add SQL query auto-formatter/compressor to ContentRouter

**Labels:** `good first issue`, `enhancement`

Synthelion's `ContentRouter` (`synthelion/content_router.py`) auto-detects
content type (JSON, HTML, git diff, logs, code, prose) and picks the best
compression strategy for each — see `synthelion/compressors/` for the
individual compressor implementations (one file per content type).

SQL queries/results aren't handled specially today — they fall through to
generic NLP compression, which doesn't understand SQL syntax (keywords,
whitespace formatting, repeated column lists).

**What to build:** a new `synthelion/compressors/sql_compressor.py` that:
- Detects SQL-shaped content (a new `ContentType.SQL` in `synthelion/models.py`
  + detection heuristic in `synthelion/content_detector.py` — keyword density
  of `SELECT`/`FROM`/`WHERE`/`INSERT`/`UPDATE`, similar to how
  `content_detector.py` already detects git diffs/logs).
- Compresses whitespace/formatting without changing query semantics (collapse
  multi-line queries, normalize indentation) — see `log_compressor.py` or
  `diff_compressor.py` for the existing pattern of a `compress(text) -> tuple[str, bool]`
  method.
- Wire it into `ContentRouter._route_inner()` following the existing branches
  for `ContentType.CODE`/`ContentType.GIT_DIFF`.

**Tests:** add to `tests/test_synthelion.py`, following the existing compressor
test classes (e.g. `TestDiffCompressor`) as a template.

---

## 2. Add support for CrewAI agent integration

**Status:** Done — shipped as `synthelion/integrations/crewai_adapter.py`
(`CrewAIAdapter` + `get_tools()`).

**Labels:** `help wanted`, `integration`

Synthelion already ships integrations for LangChain (`synthelion/plugins/langchain_tools.py`),
OpenAI (`synthelion/integrations/openai_adapter.py`), and Claude
(`synthelion/integrations/claude_adapter.py`) — each wraps the underlying
client with auto-compression + RAG memory recall on every call (see
`ClaudeAdapter`/`OpenAIAdapter` for the pattern: compress the outgoing
message, optionally inject recalled context, call the real client, record the
decision).

**What to build:** a `synthelion/integrations/crewai_adapter.py` (or a CrewAI
tool wrapper, depending on CrewAI's actual extension points) that lets a
CrewAI agent/crew automatically compress messages/tool output through
Synthelion — mirroring `ClaudeAdapter`'s `chat()`/`store()`/`recall()`/`status()`
shape as closely as CrewAI's API allows.

**Tests:** follow `tests/test_analytics.py`'s `TestClaudeAdapter`/`TestOpenAIAdapter`
classes (mocked client, no real API calls) as a template.

---

## 3. Add support for a new language's stopword/function-word list

**Labels:** `good first issue`, `help wanted`

Synthelion supports 50+ languages via curated word-data files in
`synthelion/worddata/` (compressed `.yaml.br` files — stopwords, lemma maps,
POS tags per ISO 639-3 language code). If your language isn't well-supported
yet (check `FunctionWordProvider.get_all_supported_iso3()`), this is a
self-contained, low-risk way to contribute: add or refine a curated function
word list for one language, with a couple of before/after compression
examples in the PR description to show it working.

**Tests:** see `tests/test_synthelion.py`'s `TestWordProvider`/`TestLanguageDetector`
classes for the expected shape (detect the language, confirm function words
load correctly).

---

## Note on "All Contributors" bot

Optional per the original growth-hack list — it's a GitHub Marketplace App
install (`https://allcontributors.org/`), not something scriptable via `gh`
CLI or from this environment. Install it manually from the repo's
Settings → Integrations if you want it.
