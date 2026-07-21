# Contributing to Synthelion

First off, thank you for considering contributing to Synthelion! 🎉

Synthelion aims to be the universal, ultra-fast prompt compressor and context manager for AI agents. Every contribution — whether it's adding support for a new language, optimizing a compression algorithm, building a new agent plugin, or fixing a typo — helps the open-source AI community save tokens and reduce LLM costs.

---

## How Can I Contribute?

### 1. Adding Support for New Languages
Synthelion operates on fast, deterministic NLP rules — no ML models. You can help expand our 50+ language support by adding or refining:
- Stopword/function-word lists for unsupported languages (`synthelion/worddata/`).
- Language-specific summarization or tokenization helpers in `synthelion/nlp/`.

### 2. New Content Router Strategies
Got a great algorithm for compressing YAML, SQL, GraphQL, or a specific log format?
- Individual compressors live in `synthelion/compressors/` (JSON, HTML, diff, log, code, tabular), dispatched by `synthelion/content_router.py`. Propose a new one there, following the existing pattern (a `compress()`/`crush()` method returning the compressed text plus whether anything actually changed).

### 3. Framework Integrations
We want Synthelion to work seamlessly everywhere. Feel free to contribute adapters for:
- LlamaIndex
- CrewAI / AutoGen / Semantic Kernel
- Custom MCP clients or IDE extensions

MCP/OpenAI-style tool definitions live in `synthelion/plugins/openai_tools.py`; the LangChain wrappers are in `synthelion/plugins/langchain_tools.py` — new integrations typically follow one of these two shapes.

### 4. Reporting Bugs & Requesting Features
- **Bug Reports:** Search existing issues before opening a new one. Include your Python version, OS, and a minimal reproducible example (or the output of `synthelion doctor`).
- **Feature Requests:** Open an issue explaining the use case and expected behavior.

---

## Local Development Setup

### Prerequisites
- Python 3.11 or higher
- `git`
- `uv` (recommended) or standard `pip`

### Step-by-Step Setup

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/synthelion.git
   cd synthelion
   ```

2. **Create a virtual environment and install in editable mode:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -e ".[all]"
   ```

3. **Verify your setup with `synthelion doctor`:**
   ```bash
   synthelion doctor
   ```

4. **Run tests:**
   ```bash
   pytest
   ```

---

## Pull Request Guidelines

**Branch Naming:** Create a topic branch from `main`:
```bash
git checkout -b feature/add-sql-compressor
# or
git checkout -b fix/mcp-timeout-windows
```

**Code Style:** Match the existing style in the file you're editing — type hints on public functions, no unused imports, no unnecessary comments (this codebase favors self-explanatory code over comment-explained code; comments are reserved for non-obvious *why*, not *what*).

**Include Tests:** If you add a new feature or fix a bug, add corresponding tests in `tests/` — the project keeps its whole test suite green (`pytest -q`) on every change.

**Keep PRs Focused:** Try to keep PRs small and focused on a single feature or bug fix.

**Run Diagnostics & Benchmarks:**
```bash
pytest
synthelion bench
```

---

## Community & Recognition

Contributors are credited in release notes. If you find Synthelion useful, don't forget to ⭐ star the repository and spread the word!

Thank you for making AI agents faster and more cost-effective! 🚀
