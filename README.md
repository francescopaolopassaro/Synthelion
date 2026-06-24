# Synthelion — Universal Token Compressor and Prompt Manager for AI Agents
![Synthelion Logo](Synthelion.png)
Synthelion compresses prompts before they reach any AI model — cutting token usage by up to 70%, reducing API costs, and speeding up responses. It works with **any agent or framework**: Claude Code, OpenAI, LangChain, OpenCode, Cursor, and more.

Supports 50+ languages out of the box. No AI model required. No configuration.

> "Why use many tokens when few tokens do trick?" — A caveman (and your wallet).

---

## Why Synthelion?

Every token sent to a model costs money and time. Synthelion removes the words that carry no meaning — articles, prepositions, conjunctions, auxiliary verbs — and reduces inflected words to their base form. The model receives exactly the same information, just without the grammatical packaging.

### Before / After

**English prose** — 20 tokens → 7 tokens (−65%)
```
Before: I would like to know if it is possible to receive information about
        cheap restaurants in Rome.

After:  know possible receive information cheap restaurant Rome
```

**Italian prose** — 17 tokens → 8 tokens (−52%)
```
Before: Vorrei sapere se è possibile ricevere informazioni sui ristoranti
        economici a Roma, per favore.

After:  sapere possibile ricevere informazione ristorante economico Roma
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

Measured on GPT-4 token counts with real inputs.

#### NLP compression

| Content | Original tokens | Light | Semantic | Aggressive |
|:---|---:|:---:|:---:|:---:|
| Prose EN | 92 | −35.9% | −34.8% | −34.8% |
| Prose IT | 93 | −23.7% | −28.0% | **−51.6%** |
| Prose DE | 81 | −25.9% | −28.4% | −35.8% |
| Prose FR | 65 | −33.8% | −32.3% | −38.5% |
| Prose ES | 51 | −27.5% | −19.6% | −27.5% |
| JSON array | 256 | −66.8% | **−68.8%** | **−68.8%** |
| Git diff | 196 | −51.0% | −58.2% | −58.2% |
| Build log | 207 | −32.4% | **−62.3%** | **−62.3%** |
| Markdown table | 158 | −60.8% | **−64.6%** | **−64.6%** |
| HTML page | 192 | −45.3% | −49.0% | −50.0% |
| Source code | 249 | −41.0% | −41.0% | −41.0% |

#### Content router (Balanced profile — auto-selects the best strategy)

| Content | Original | After | Saved | Strategy |
|:---|---:|---:|:---:|:---|
| Prose EN | 92 | 60 | −34.8% | NlpCompression |
| JSON array | 256 | 134 | **−47.7%** | JsonCrush:MarkdownTable |
| Git diff | 196 | 137 | −30.1% | DiffCompression |
| HTML page | 192 | 58 | **−69.8%** | HtmlExtract+NlpCompression |
| Source code | 249 | 184 | −26.1% | CodeCompression |

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

## Install

```bash
pip install synthelion
```

---

## Integrations

### MCP — Claude Code, Claude Desktop, OpenCode, Cursor, Windsurf, Continue…

Any agent that supports the [Model Context Protocol](https://modelcontextprotocol.io) can use Synthelion as a tool server.

**1.** Open your agent's MCP settings file:

| Agent | Settings file |
|---|---|
| Claude Code | `~/.claude/settings.json` on Windows (%USERPROFILE%\.claude\settings.json) |
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` |
| OpenCode | `~/.config/opencode/config.json` |
| Cursor / Windsurf | MCP settings in the app |

**2.** Add this block:

```json
{
  "mcpServers": {
    "synthelion": {
      "command": "synthelion-mcp"
    }
  }
}
```
best way --> claude mcp add synthelion -- synthelion-mcp

**3.** Restart the agent. Done.

**Zero-install with uvx** (no `pip install` needed if you have [uv](https://docs.astral.sh/uv/)):

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

Once connected, just ask naturally:
> *"Compress this text to save tokens"*  
> *"Summarize this article in 3 sentences"*  
> *"Detect the language of this message"*  
> *"Compress this JSON / HTML / diff / log"*

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
tools = get_tools()

agent = create_react_agent(llm, tools)
result = agent.invoke({"messages": [{"role": "user", "content": "Compress this prompt: ..."}]})
```

Works with any LangChain-compatible LLM (OpenAI, Anthropic, Groq, Ollama, …).

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
```

Pipe-friendly — reads from stdin if no `--text` or `--file` is given:

```bash
cat big_prompt.txt | synthelion compress --level aggressive
```

---

## Tools

| Tool | What it does |
|---|---|
| **compress** | Removes stop words, lemmatizes content words. Up to 70% token reduction. |
| **detect_language** | Identifies language of any text. Returns ISO 639-3 code. |
| **route_content** | Auto-detects JSON, HTML, diff, log, code or prose and applies the best algorithm. |
| **summarize** | Extractive summarization — keeps the most important sentences (TF-IDF or TextRank). |
| **compress_batch** | Compresses a list of texts in one call. |

---

## Code examples

### Text compression

```python
from synthelion import CompressionService, CompressionLevel

svc = CompressionService()

# Semantic (default) — removes stop words and lemmatizes
r = svc.compress(
    "I would like to know if it is possible to receive information about cheap restaurants in Rome.",
    CompressionLevel.SEMANTIC,
)
print(r.compressed_text)      # know possible receive information cheap restaurant Rome
print(f"{r.efficiency_pct:.1f}% saved")   # 65.0% saved
print(f"{r.original_tokens} → {r.compressed_tokens} tokens")

# Aggressive — also removes generic verbs and adjectives
r = svc.compress("The important thing is to find a good and reliable solution.", CompressionLevel.AGGRESSIVE)
print(r.compressed_text)      # important find reliable solution

# Explicit language (skip auto-detection)
r = svc.apply_compression(
    "Ich hätte gerne einen Kaffee, bitte.",
    iso3="deu",
    level=CompressionLevel.SEMANTIC,
)
print(r.compressed_text)      # Kaffee

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

## Compression levels

| Level | What it removes | Typical savings |
|---|---|---|
| `light` | Stop words (articles, prepositions, conjunctions…) | 25–35% |
| `semantic` | Stop words + lemmatization to base form | 30–69% |
| `aggressive` | Everything above + generic verbs and descriptive adjectives | 35–70% |

Default: `semantic`.

---

## Supported languages (50+)

Afrikaans · Arabic · Armenian · Basque · Belarusian · Bengali · Bulgarian · Catalan · Chinese · Croatian · Czech · Danish · Dutch · English · Estonian · Finnish · French · Galician · German · Greek · Hebrew · Hindi · Hungarian · Icelandic · Indonesian · Irish · Italian · Japanese · Kannada · Kazakh · Korean · Latin · Latvian · Lithuanian · Macedonian · Malay · Marathi · Norwegian · Persian · Polish · Portuguese · Romanian · Russian · Serbian · Slovak · Slovenian · Spanish · Swedish · Tamil · Telugu · Thai · Turkish · Ukrainian · Urdu · Vietnamese

Language is detected automatically from the text. Pass an explicit ISO 639-3 code to override.

---

## Troubleshooting

**`synthelion-mcp: command not found`**

Use the module form instead:

```json
{
  "mcpServers": {
    "synthelion": {
      "command": "python",
      "args": ["-m", "synthelion.plugins.mcp_server"]
    }
  }
}
```

Or use `uvx` — it always works without PATH issues.

---

## Links

- **PyPI:** https://pypi.org/project/synthelion/
- **Source:** https://github.com/francescopaolopassaro/synthelion
- **Original C# project (Caveman):** https://github.com/francescopaolopassaro/caveman

© 2026 Passaro Francesco Paolo — Digitalsolutions.it
