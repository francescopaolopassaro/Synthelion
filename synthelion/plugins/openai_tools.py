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

from dataclasses import asdict

from synthelion.core import CompressionService
from synthelion.detector import LanguageDetector
from synthelion.models import CompressionLevel, CompressionProfile
from synthelion.nlp.text_rank import TextRankSummarizer

_svc = CompressionService()
_det = LanguageDetector()
_tr = TextRankSummarizer()

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
    ]


def get_tool_list() -> list[str]:
    return [t["function"]["name"] for t in get_tool_definitions()]


def execute_tool(name: str, arguments: dict) -> dict:
    """Execute a Synthelion tool by name and return a JSON-serializable result."""
    if name == "compress":
        level = _LEVEL_MAP.get((arguments.get("level") or "semantic").lower(), CompressionLevel.SEMANTIC)
        r = _svc.compress(arguments["text"], level, iso3=arguments.get("language"))
        return {
            "compressed_text": r.compressed_text,
            "original_tokens": r.original_tokens,
            "compressed_tokens": r.compressed_tokens,
            "efficiency_pct": round(r.efficiency_pct, 2),
            "error": r.error_message,
        }

    if name == "detect_language":
        text = arguments["text"]
        if arguments.get("with_scores"):
            return {"scores": _det.detect_with_scores(text)}
        return {"language": _det.detect(text)}

    if name == "route_content":
        from synthelion.content_router import ContentRouter
        from synthelion.models import CompressionProfile
        profile_map = {
            "light": CompressionProfile.LIGHT,
            "balanced": CompressionProfile.BALANCED,
            "agent": CompressionProfile.AGENT,
            "aggressive": CompressionProfile.AGGRESSIVE,
        }
        profile = profile_map.get((arguments.get("profile") or "balanced").lower(), CompressionProfile.BALANCED)
        router = ContentRouter.from_profile(profile)
        r = router.route(arguments["content"], arguments.get("query"))
        return {
            "compressed": r.compressed,
            "detected_type": r.detected_type.value,
            "strategy_used": r.strategy_used,
            "tokens_before": r.tokens_before,
            "tokens_after": r.tokens_after,
            "savings_pct": round(r.savings_pct, 2),
            "ccr_hash": r.ccr_hash,
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
        return {"summary": summary}

    if name == "compress_batch":
        level = _LEVEL_MAP.get((arguments.get("level") or "semantic").lower(), CompressionLevel.SEMANTIC)
        results = _svc.compress_batch(arguments["texts"], level)
        return {
            "results": [
                {
                    "compressed_text": r.compressed_text,
                    "efficiency_pct": round(r.efficiency_pct, 2),
                    "error": r.error_message,
                }
                for r in results
            ]
        }

    return {"error": f"Unknown tool: {name}"}
