# Synthelion — Universal Token Compressor for AI Agents

Synthelion compresses prompts before they reach any AI model — cutting token usage by up to 70%, reducing API costs, and speeding up responses. It works with **any agent or framework**: Claude Code, OpenAI, LangChain, OpenCode, Cursor, and more.

Supports 50+ languages out of the box. No AI model required. No configuration.

> "Why use many tokens when few tokens do trick?" — A caveman (and your wallet).

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
| Claude Code | `~/.claude/settings.json` |
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
