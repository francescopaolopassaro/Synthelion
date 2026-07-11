# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""OpenAI-compatible function tool definitions for Synthelion.

Usage:
    from synthelion.plugins.openai_tools import get_tool_definitions, execute_tool

    tools = get_tool_definitions()
    # Pass to: client.chat.completions.create(tools=tools, ...)

    result = execute_tool("compress", {"text": "...", "level": "semantic"})
"""
from __future__ import annotations

import threading
import time

from synthelion.core import CompressionService
from synthelion.detector import LanguageDetector
from synthelion.models import CompressionLevel, CompressionProfile
from synthelion.nlp.text_rank import TextRankSummarizer

_svc = CompressionService()
_det = LanguageDetector()
_tr = TextRankSummarizer()

# Per-thread call timer: execute_tool() starts it, _record_ledger() reads the
# elapsed time. Thread-local because execute_tool runs in a thread pool
# (asyncio.to_thread in mcp_server.py) — each concurrent call gets its own.
_call_timer = threading.local()

_LEVEL_MAP = {
    "none": CompressionLevel.NONE,
    "light": CompressionLevel.LIGHT,
    "semantic": CompressionLevel.SEMANTIC,
    "aggressive": CompressionLevel.AGGRESSIVE,
}


def get_tool_definitions() -> list[dict]:
    """Return the list of tool definitions in OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": "compress",
                "description": (
                    "Compress a text prompt to reduce LLM token usage. "
                    "Removes stop words and lemmatizes content words. "
                    "Supports 50+ languages with zero ML model dependency."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The text to compress."},
                        "level": {
                            "type": "string",
                            "enum": ["light", "semantic", "aggressive"],
                            "description": "Compression level. Default: semantic.",
                        },
                        "language": {
                            "type": "string",
                            "description": "ISO 639-3 code (e.g. 'eng', 'ita'). Auto-detected when omitted.",
                        },
                    },
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "detect_language",
                "description": "Detect the language of a text and return the ISO 639-3 code.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The text to analyse."},
                        "with_scores": {
                            "type": "boolean",
                            "description": "Return per-language confidence scores.",
                        },
                    },
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "route_content",
                "description": (
                    "Auto-detect content type (JSON, HTML, diff, log, code, prose) "
                    "and apply the best compression strategy."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "The content to compress."},
                        "profile": {
                            "type": "string",
                            "enum": ["light", "balanced", "agent", "aggressive"],
                            "description": "Compression profile. Default: balanced.",
                        },
                        "query": {
                            "type": "string",
                            "description": "Optional relevance query for JSON BM25 row selection.",
                        },
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "summarize",
                "description": "Extractive summarization of a text block.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The text to summarize."},
                        "sentence_count": {
                            "type": "integer",
                            "description": "Number of sentences to keep.",
                        },
                        "ratio": {
                            "type": "number",
                            "description": "Fraction of sentences to keep (0.0–1.0). Used when sentence_count is omitted.",
                        },
                        "algorithm": {
                            "type": "string",
                            "enum": ["tfidf", "textrank"],
                            "description": "Summarization algorithm. Default: textrank.",
                        },
                    },
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "compress_batch",
                "description": "Compress a list of texts in one call.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "texts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of texts to compress.",
                        },
                        "level": {
                            "type": "string",
                            "enum": ["light", "semantic", "aggressive"],
                            "description": "Compression level. Default: semantic.",
                        },
                    },
                    "required": ["texts"],
                },
            },
        },
        # ── AI-agent context tools (Claude-first design) ─────────────────────
        {
            "type": "function",
            "function": {
                "name": "compress_for_context",
                "description": (
                    "Compress content to fit within a token budget before inserting it into "
                    "an LLM context window. Automatically chains routing → NLP compression → "
                    "summarization until the content fits. Token counts are word-count estimates. "
                    "Returns fits_budget=true when the result is within max_tokens."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Content to compress."},
                        "max_tokens": {
                            "type": "integer",
                            "description": "Target token budget. Omit to compress without a limit.",
                        },
                        "profile": {
                            "type": "string",
                            "enum": ["light", "balanced", "agent", "aggressive"],
                            "description": "Compression profile. Default: agent.",
                        },
                        "prefer": {
                            "type": "string",
                            "enum": ["compress", "summarize", "auto"],
                            "description": "Prefer compression or summarization when budget is tight. Default: auto.",
                        },
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "compress_conversation",
                "description": (
                    "Compress a conversation history (list of {role, content} messages) to reduce "
                    "token usage. Keeps the last keep_last_n messages verbatim and compresses/summarizes "
                    "older turns. Returns a compressed messages array compatible with the OpenAI/Anthropic format."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "messages": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "role": {"type": "string"},
                                    "content": {"type": "string"},
                                },
                                "required": ["role", "content"],
                            },
                            "description": "Conversation history in OpenAI/Anthropic format.",
                        },
                        "max_tokens": {
                            "type": "integer",
                            "description": "Target token budget for the entire conversation. Omit to compress without a limit.",
                        },
                        "keep_last_n": {
                            "type": "integer",
                            "description": "Number of recent messages to keep verbatim. Default: 4.",
                        },
                    },
                    "required": ["messages"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "deduplicate",
                "description": (
                    "Remove near-duplicate texts from a list using cosine bag-of-words similarity. "
                    "Useful when multiple sources return overlapping content. Returns the deduplicated list "
                    "and the number of items removed."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "texts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of text blocks to deduplicate.",
                        },
                        "threshold": {
                            "type": "number",
                            "description": "Similarity threshold (0.0–1.0). Texts with similarity >= threshold are considered duplicates. Default: 0.8.",
                        },
                    },
                    "required": ["texts"],
                },
            },
        },
        # ── file-level tool ───────────────────────────────────────────────────
        {
            "type": "function",
            "function": {
                "name": "compress_file",
                "description": (
                    "Read a file by path and compress it using the best algorithm for its content type. "
                    "Avoids loading the full raw file into context — returns only the compressed version. "
                    "Supports JSON, HTML, git diff, logs, source code, and plain text. "
                    "Optionally applies a max_tokens budget (chains routing + summarization)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute or relative path to the file."},
                        "profile": {
                            "type": "string",
                            "enum": ["light", "balanced", "agent", "aggressive"],
                            "description": "Compression profile. Default: agent.",
                        },
                        "max_tokens": {
                            "type": "integer",
                            "description": "Optional token budget. Triggers summarization when routing alone is insufficient.",
                        },
                        "encoding": {
                            "type": "string",
                            "description": "File encoding. Default: utf-8.",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        # ── session / memory tools (mirrors tokensave pattern) ────────────────
        {
            "type": "function",
            "function": {
                "name": "session_record",
                "description": (
                    "Save a design/architecture decision or context note that persists "
                    "across sessions. Stored in ChromaDB (semantic recall) or lexical "
                    "fallback when chromadb is not installed."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The decision or context note to save."},
                        "reason": {"type": "string", "description": "Optional reason or rationale."},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of tags for filtering.",
                        },
                        "files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional file paths related to this decision.",
                        },
                    },
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "session_recall",
                "description": (
                    "Recall previously saved decisions by semantic similarity (ChromaDB) "
                    "or lexical cosine search (fallback). Use to avoid re-explaining "
                    "architecture choices across sessions."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Natural-language search query."},
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results. Default: 10.",
                        },
                        "since_days": {
                            "type": "number",
                            "description": "Only return decisions from the last N days.",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "session_start",
                "description": "Mark the start of a new agent session. Returns a session ID.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "session_end",
                "description": "Mark the end of the current session and return a summary.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "synthelion_status",
                "description": "Return aggregate token savings statistics from the savings ledger.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "days": {
                            "type": "integer",
                            "description": "Restrict to last N days. Omit for all-time.",
                        },
                    },
                    "required": [],
                },
            },
        },
    ]


def get_tool_list() -> list[str]:
    return [t["function"]["name"] for t in get_tool_definitions()]


def execute_tool(name: str, arguments: dict) -> dict:
    """Execute a Synthelion tool by name and return a JSON-serializable result."""
    _call_timer.start = time.perf_counter()
    if name == "compress":
        level = _LEVEL_MAP.get((arguments.get("level") or "semantic").lower(), CompressionLevel.SEMANTIC)
        r = _svc.compress(arguments["text"], level, iso3=arguments.get("language"))
        _record_ledger("compress", r.original_tokens, r.compressed_tokens)
        return {
            "compressed_text": r.compressed_text,
            "original_tokens": r.original_tokens,
            "compressed_tokens": r.compressed_tokens,
            "efficiency_pct": round(r.efficiency_pct, 2),
            "error": r.error_message,
            "synthelion_metrics": _fmt_metrics(r.original_tokens, r.compressed_tokens),
        }

    if name == "detect_language":
        text = arguments["text"]
        if arguments.get("with_scores"):
            return {"scores": _det.detect_with_scores(text)}
        return {"language": _det.detect(text)}

    if name == "route_content":
        from synthelion.content_router import ContentRouter
        profile_map = {
            "light": CompressionProfile.LIGHT,
            "balanced": CompressionProfile.BALANCED,
            "agent": CompressionProfile.AGENT,
            "aggressive": CompressionProfile.AGGRESSIVE,
        }
        profile = profile_map.get((arguments.get("profile") or "balanced").lower(), CompressionProfile.BALANCED)
        router = ContentRouter.from_profile(profile)
        r = router.route(arguments["content"], arguments.get("query"))
        _record_ledger("route_content", r.tokens_before, r.tokens_after, r.detected_type.value)
        return {
            "compressed": r.compressed,
            "detected_type": r.detected_type.value,
            "strategy_used": r.strategy_used,
            "tokens_before": r.tokens_before,
            "tokens_after": r.tokens_after,
            "savings_pct": round(r.savings_pct, 2),
            "ccr_hash": r.ccr_hash,
            "synthelion_metrics": _fmt_metrics(r.tokens_before, r.tokens_after),
        }

    if name == "summarize":
        algo = arguments.get("algorithm", "textrank")
        text = arguments["text"]
        sc = arguments.get("sentence_count")
        ratio = arguments.get("ratio")
        if algo == "tfidf":
            from synthelion.nlp.summarizer import TfIdfSummarizer
            summ = TfIdfSummarizer()
        else:
            summ = _tr
        summary = summ.summarize(text, sentence_count=sc, ratio=ratio)
        before = len(text.split())
        after = len(summary.split())
        _record_ledger("summarize", before, after)
        return {
            "summary": summary,
            "synthelion_metrics": _fmt_metrics(before, after),
        }

    if name == "compress_batch":
        level = _LEVEL_MAP.get((arguments.get("level") or "semantic").lower(), CompressionLevel.SEMANTIC)
        results = _svc.compress_batch(arguments["texts"], level)
        total_before = sum(r.original_tokens for r in results)
        total_after = sum(r.compressed_tokens for r in results)
        _record_ledger("compress_batch", total_before, total_after)
        return {
            "results": [
                {
                    "compressed_text": r.compressed_text,
                    "efficiency_pct": round(r.efficiency_pct, 2),
                    "error": r.error_message,
                }
                for r in results
            ],
            "synthelion_metrics": _fmt_metrics(total_before, total_after),
        }

    if name == "compress_file":
        return _exec_compress_file(arguments)

    if name == "compress_for_context":
        return _exec_compress_for_context(arguments)

    if name == "compress_conversation":
        return _exec_compress_conversation(arguments)

    if name == "deduplicate":
        return _exec_deduplicate(arguments)

    # ── session tools ─────────────────────────────────────────────────────────

    if name == "session_record":
        from synthelion.analytics.session_db import get_session_db
        db = get_session_db()
        decision_id = db.record_decision(
            text=arguments["text"],
            reason=arguments.get("reason", ""),
            tags=arguments.get("tags"),
            files=arguments.get("files"),
        )
        return {"id": decision_id, "status": "recorded", "backend": db.backend()}

    if name == "session_recall":
        from synthelion.analytics.session_db import get_session_db
        import time as _time
        db = get_session_db()
        since_days = arguments.get("since_days")
        since_ts = _time.time() - since_days * 86400 if since_days else None
        decisions = db.session_recall(
            query=arguments.get("query"),
            since=since_ts,
            limit=int(arguments.get("limit", 10)),
        )
        return {"decisions": decisions, "backend": db.backend()}

    if name == "session_start":
        from synthelion.analytics.session_db import get_session_db
        return get_session_db().session_start()

    if name == "session_end":
        from synthelion.analytics.session_db import get_session_db
        return get_session_db().session_end()

    if name == "synthelion_status":
        from synthelion.analytics.ledger import get_ledger
        ledger = get_ledger()
        days = arguments.get("days")
        records = ledger.records_since(int(days)) if days else ledger.all_records()
        return ledger.summary(records)

    return {"error": f"Unknown tool: {name}"}


# ── helpers ───────────────────────────────────────────────────────────────────

_SONNET_PRICE_PER_TOKEN: float = 3e-6  # $3.00/MTok (Sonnet 4.6 input)


def _fmt_metrics(before: int, after: int) -> str:
    saved = max(0, before - after)
    pct = (saved / before * 100) if before > 0 else 0.0
    cost = saved * _SONNET_PRICE_PER_TOKEN
    return f"before={before} after={after} saved={saved} ({pct:.1f}%) ~${cost:.5f}"


def _record_ledger(tool: str, before: int, after: int, content_type: str = "") -> None:
    try:
        from synthelion.analytics.ledger import get_ledger
        start = getattr(_call_timer, "start", None)
        duration_ms = (time.perf_counter() - start) * 1000 if start is not None else 0.0
        get_ledger().record(tool, before, after, content_type=content_type, duration_ms=duration_ms)
    except Exception:
        pass


# ── new AI-agent context tools ────────────────────────────────────────────────

def _exec_compress_file(arguments: dict) -> dict:
    import os
    path = arguments["path"]
    if not os.path.isfile(path):
        return {"error": f"File not found: {path}"}
    encoding = arguments.get("encoding", "utf-8")
    try:
        with open(path, encoding=encoding, errors="replace") as fh:
            content = fh.read()
    except Exception as exc:
        return {"error": f"Could not read file: {exc}"}
    ctx_args: dict = {"content": content, "profile": arguments.get("profile", "agent")}
    if "max_tokens" in arguments:
        ctx_args["max_tokens"] = arguments["max_tokens"]
    result = _exec_compress_for_context(ctx_args)
    result["path"] = path
    result["file_size_chars"] = len(content)
    return result


def _exec_compress_for_context(arguments: dict) -> dict:
    from synthelion.content_router import ContentRouter
    from synthelion.models import CompressionProfile
    from synthelion.nlp.text_rank import TextRankSummarizer

    profile_map = {
        "light": CompressionProfile.LIGHT,
        "balanced": CompressionProfile.BALANCED,
        "agent": CompressionProfile.AGENT,
        "aggressive": CompressionProfile.AGGRESSIVE,
    }
    content = arguments["content"]
    max_tokens: int | None = arguments.get("max_tokens")
    prefer = (arguments.get("prefer") or "auto").lower()
    profile = profile_map.get((arguments.get("profile") or "agent").lower(), CompressionProfile.AGENT)

    router = ContentRouter.from_profile(profile)
    routed = router.route(content)
    result_text = routed.compressed or content
    result_tokens = routed.tokens_after

    fits = max_tokens is None or result_tokens <= max_tokens
    strategy = "route"

    if not fits and prefer in ("summarize", "auto"):
        # Try summarization to hit the budget
        ratio = max(0.05, min(0.9, (max_tokens or result_tokens) / max(result_tokens, 1)))
        try:
            summary = TextRankSummarizer().summarize(result_text, ratio=ratio)
            summary_tokens = len(summary.split())
            if summary and summary_tokens < result_tokens:
                result_text = summary
                result_tokens = summary_tokens
                strategy = "route+summarize"
                fits = max_tokens is None or result_tokens <= max_tokens
        except Exception:
            pass

    _record_ledger("compress_for_context", routed.tokens_before, result_tokens, routed.detected_type.value)
    out: dict = {
        "compressed": result_text,
        "detected_type": routed.detected_type.value,
        "tokens_before": routed.tokens_before,
        "tokens_after": result_tokens,
        "strategy": strategy,
        "fits_budget": fits,
        "synthelion_metrics": _fmt_metrics(routed.tokens_before, result_tokens),
    }
    if max_tokens is not None and not fits:
        out["budget_exceeded_by"] = result_tokens - max_tokens
    return out


def _exec_compress_conversation(arguments: dict) -> dict:
    from synthelion.content_router import ContentRouter
    from synthelion.models import CompressionProfile
    from synthelion.nlp.text_rank import TextRankSummarizer

    messages: list[dict] = arguments.get("messages") or []
    max_tokens: int | None = arguments.get("max_tokens")
    keep_last_n: int = max(0, int(arguments.get("keep_last_n") or 4))

    def _words(msg: dict) -> int:
        return len(str(msg.get("content", "")).split())

    total_before = sum(_words(m) for m in messages)

    kept_tail = messages[-keep_last_n:] if keep_last_n > 0 and len(messages) > keep_last_n else []
    to_compress = messages[: len(messages) - len(kept_tail)]

    if not to_compress:
        return {
            "messages": messages,
            "tokens_before": total_before,
            "tokens_after": total_before,
            "messages_before": len(messages),
            "messages_after": len(messages),
            "strategy": "none",
            "synthelion_metrics": _fmt_metrics(total_before, total_before),
        }

    router = ContentRouter.from_profile(CompressionProfile.AGENT)
    compressed_msgs: list[dict] = []
    for msg in to_compress:
        content = str(msg.get("content", ""))
        if len(content.split()) > 15:
            r = router.route(content)
            compressed_msgs.append({**msg, "content": r.compressed or content})
        else:
            compressed_msgs.append(msg)

    result_messages = compressed_msgs + kept_tail
    total_after = sum(_words(m) for m in result_messages)

    strategy = "route"

    # If still over budget, collapse older messages into a summary
    if max_tokens and total_after > max_tokens:
        tail_tokens = sum(_words(m) for m in kept_tail)
        budget_for_history = max(20, (max_tokens or total_after) - tail_tokens)
        history_text = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in compressed_msgs
        )
        ratio = max(0.05, min(0.8, budget_for_history / max(len(history_text.split()), 1)))
        try:
            summary = TextRankSummarizer().summarize(history_text, ratio=ratio)
            if summary:
                result_messages = [
                    {"role": "system", "content": f"[Compressed conversation history]\n{summary}"}
                ] + kept_tail
                total_after = sum(_words(m) for m in result_messages)
                strategy = "route+summarize"
        except Exception:
            pass

    _record_ledger("compress_conversation", total_before, total_after)
    return {
        "messages": result_messages,
        "tokens_before": total_before,
        "tokens_after": total_after,
        "messages_before": len(messages),
        "messages_after": len(result_messages),
        "strategy": strategy,
        "synthelion_metrics": _fmt_metrics(total_before, total_after),
    }


def _exec_deduplicate(arguments: dict) -> dict:
    import re
    from collections import Counter

    texts: list[str] = arguments.get("texts") or []
    threshold: float = float(arguments.get("threshold") or 0.8)

    def _bag(t: str) -> Counter:
        return Counter(re.findall(r"\b\w{3,}\b", t.lower()))

    def _cosine(a: Counter, b: Counter) -> float:
        if not a or not b:
            return 0.0
        dot = sum(a[w] * b[w] for w in a if w in b)
        na = sum(v * v for v in a.values()) ** 0.5
        nb = sum(v * v for v in b.values()) ** 0.5
        return dot / (na * nb) if na and nb else 0.0

    bags = [_bag(t) for t in texts]
    kept_indices: list[int] = []
    removed = 0

    for i in range(len(texts)):
        is_dup = any(_cosine(bags[i], bags[j]) >= threshold for j in kept_indices)
        if is_dup:
            removed += 1
        else:
            kept_indices.append(i)

    result = [texts[i] for i in kept_indices]
    tokens_before = sum(len(t.split()) for t in texts)
    tokens_after = sum(len(t.split()) for t in result)
    _record_ledger("deduplicate", tokens_before, tokens_after)
    return {
        "texts": result,
        "original_count": len(texts),
        "deduplicated_count": len(result),
        "removed_count": removed,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "synthelion_metrics": _fmt_metrics(tokens_before, tokens_after),
    }
