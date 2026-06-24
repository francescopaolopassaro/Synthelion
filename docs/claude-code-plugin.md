# Synthelion — Claude Code Plugin Guide

**Synthelion** is a Python port of [Caveman](https://github.com/francescopaolopassaro/caveman) (C#) by Passaro Francesco Paolo.  
It exposes a **Model Context Protocol (MCP) server** that Claude Code and any other MCP-compatible agent can use to compress prompts and reduce token usage — 50+ languages, zero ML models.

---

## Quick setup (3 steps)

### Step 1 — Install

```bash
pip install synthelion
```

### Step 2 — Add to Claude Code

Open your Claude Code settings file:

| OS | Path |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

Add this block inside `"mcpServers"`:

```json
{
  "mcpServers": {
    "synthelion": {
      "command": "synthelion-mcp"
    }
  }
}
```

### Step 3 — Restart Claude Code

Close and reopen Claude Code. The Synthelion tools will appear automatically.

---

## Zero-install setup with `uvx`

If you have [uv](https://docs.astral.sh/uv/) installed, no `pip install` is needed:

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

`uvx` downloads and runs `synthelion-mcp` in an isolated environment on first launch.

---

## Available tools

Once connected, Claude Code can call these tools:

| Tool | Description |
|---|---|
| `compress` | Compress a text prompt. Remove stop words and lemmatize content words. |
| `detect_language` | Detect the language of a text (returns ISO 639-3 code). |
| `route_content` | Auto-detect content type (JSON, HTML, diff, log, code, prose) and apply the best algorithm. |
| `summarize` | Extractive summarization with TF-IDF or TextRank. |
| `compress_batch` | Compress a list of texts in one call. |

---

## Tool parameters

### `compress`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `text` | string | yes | Text to compress |
| `level` | `light` \| `semantic` \| `aggressive` | no | Default: `semantic` |
| `language` | string | no | ISO 639-3 code (e.g. `ita`, `deu`). Auto-detected when omitted. |

**Example prompt to Claude:**
> "Use synthelion to compress this text at semantic level: `I would like to know if it is possible to receive information about cheap restaurants in Rome.`"

**Expected output:**
```json
{
  "compressed_text": "know possible receive information cheap restaurant Rome",
  "original_tokens": 20,
  "compressed_tokens": 7,
  "efficiency_pct": 65.0
}
```

---

### `detect_language`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `text` | string | yes | Text to analyse |
| `with_scores` | boolean | no | Return per-language confidence scores |

**Example:**
> "Detect the language of: `Ich hätte gerne einen Kaffee, bitte.`"

---

### `route_content`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `content` | string | yes | Any content: JSON, HTML, diff, log, code, or prose |
| `profile` | `light` \| `balanced` \| `agent` \| `aggressive` | no | Default: `balanced` |
| `query` | string | no | Relevance hint for JSON BM25 row selection |

**Example:**
> "Use synthelion to route and compress this JSON array: `[{...}, ...]`"

---

### `summarize`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `text` | string | yes | Text to summarize |
| `sentence_count` | integer | no | Number of sentences to keep |
| `ratio` | number | no | Fraction to keep (0.0–1.0) |
| `algorithm` | `tfidf` \| `textrank` | no | Default: `textrank` |

---

### `compress_batch`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `texts` | string[] | yes | List of texts |
| `level` | `light` \| `semantic` \| `aggressive` | no | Default: `semantic` |

---

## Compression levels explained

| Level | What it removes | Token savings |
|---|---|---|
| `light` | Stop words (articles, prepositions, conjunctions…) | ~25–35% |
| `semantic` | Stop words + lemmatizes content words to base form | ~30–69% |
| `aggressive` | Semantic + strips generic verbs and descriptive adjectives | ~35–70% |

---

## Content router profiles

| Profile | NLP level | Best for |
|---|---|---|
| `light` | Light | Minimal intervention, human-readable output |
| `balanced` | Semantic | General use (default) |
| `agent` | Semantic | Agent loops, tool calls, structured output |
| `aggressive` | Aggressive | Maximum token reduction |

---

## Supported languages (50+)

`afr` `ara` `bel` `ben` `bul` `cat` `ces` `dan` `deu` `ell` `eng` `est` `eus` `fas` `fin` `fra` `gle` `glg` `heb` `hin` `hrv` `hun` `hye` `ind` `isl` `ita` `jpn` `kan` `kaz` `kor` `lat` `lav` `lit` `mar` `mkd` `msa` `nld` `nor` `pol` `por` `ron` `rus` `slk` `slv` `spa` `sqi` `srp` `swe` `tam` `tel` `tha` `tur` `ukr` `urd` `vie` `zho`

Language is detected automatically from the text. Pass an explicit ISO 639-3 code to override.

---

## Tips for use inside Claude Code

**Compress a long context file before feeding it to a model:**
> "Compress this file content with synthelion at aggressive level before including it in the prompt."

**Summarize a conversation to save tokens:**
> "Use synthelion to summarize this conversation to 5 sentences."

**Auto-route mixed content:**
> "Route this content through synthelion — it might be JSON or HTML, detect automatically."

**Detect the language before translating:**
> "Use synthelion to detect the language of this user message, then reply in the same language."

---

## Troubleshooting

**"synthelion-mcp not found"**  
Add Python's Scripts directory to PATH, or use the full path:
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

**"No module named synthelion"**  
Run `pip install synthelion` in the same Python environment that Claude Code uses, or use the `uvx` setup above.

**Tools not appearing after restart**  
Check that the JSON in your config file is valid (no trailing commas, correct quotes).

---

## Attribution

Synthelion is a Python port of **Caveman** — © 2026 Passaro Francesco Paolo, Digitalsolutions.it.  
Original C# source: https://github.com/francescopaolopassaro/caveman  
Language data: [Universal Dependencies](https://universaldependencies.org/) (CC BY-SA / CC BY).
