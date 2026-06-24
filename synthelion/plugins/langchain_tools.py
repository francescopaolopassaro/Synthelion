# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""LangChain tool wrappers for Synthelion.

Requires: pip install "synthelion[langchain]"

Usage:
    from synthelion.plugins.langchain_tools import get_tools

    tools = get_tools()
    agent = initialize_agent(tools, llm, agent=AgentType.OPENAI_FUNCTIONS)

    # Or with LangGraph / LCEL:
    from langgraph.prebuilt import create_react_agent
    app = create_react_agent(llm, get_tools())
"""
from __future__ import annotations

from typing import Optional, Type

from synthelion.plugins.openai_tools import execute_tool


def get_tools() -> list:
    """Return a list of LangChain StructuredTool instances for Synthelion.

    Requires langchain-core >= 0.1. Install with:
        pip install "synthelion[langchain]"
    """
    try:
        from langchain_core.tools import StructuredTool
        from pydantic import BaseModel, Field
    except ImportError as e:
        raise ImportError(
            "LangChain is not installed. Run: pip install 'synthelion[langchain]'"
        ) from e

    # --- Input schemas ---

    class CompressInput(BaseModel):
        text: str = Field(description="Text to compress.")
        level: str = Field(default="semantic", description="Compression level: light, semantic, or aggressive.")
        language: Optional[str] = Field(default=None, description="ISO 639-3 language code (auto-detected if omitted).")

    class DetectLanguageInput(BaseModel):
        text: str = Field(description="Text to analyse.")
        with_scores: bool = Field(default=False, description="Return per-language confidence scores.")

    class RouteContentInput(BaseModel):
        content: str = Field(description="Content to compress (JSON, HTML, diff, log, code, or prose).")
        profile: str = Field(default="balanced", description="Profile: light, balanced, agent, or aggressive.")
        query: Optional[str] = Field(default=None, description="Optional relevance hint for JSON row selection.")

    class SummarizeInput(BaseModel):
        text: str = Field(description="Text to summarize.")
        sentence_count: Optional[int] = Field(default=None, description="Number of sentences to keep.")
        ratio: Optional[float] = Field(default=None, description="Fraction of sentences to keep (0.0–1.0).")
        algorithm: str = Field(default="textrank", description="Algorithm: tfidf or textrank.")

    class CompressBatchInput(BaseModel):
        texts: list[str] = Field(description="List of texts to compress.")
        level: str = Field(default="semantic", description="Compression level: light, semantic, or aggressive.")

    # --- Tool factories ---

    def _compress(text: str, level: str = "semantic", language: Optional[str] = None) -> str:
        args = {"text": text, "level": level}
        if language:
            args["language"] = language
        r = execute_tool("compress", args)
        return (
            f"Compressed: {r['compressed_text']}\n"
            f"Savings: {r.get('efficiency_pct', 0):.1f}% "
            f"({r.get('original_tokens', '?')} → {r.get('compressed_tokens', '?')} tokens)"
        )

    def _detect_language(text: str, with_scores: bool = False) -> str:
        r = execute_tool("detect_language", {"text": text, "with_scores": with_scores})
        if with_scores:
            scores = r.get("scores", {})
            top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
            return "\n".join(f"{k}: {v:.3f}" for k, v in top)
        return r.get("language", "unknown")

    def _route_content(content: str, profile: str = "balanced", query: Optional[str] = None) -> str:
        args: dict = {"content": content, "profile": profile}
        if query:
            args["query"] = query
        r = execute_tool("route_content", args)
        return (
            f"Type: {r.get('detected_type', '?')}\n"
            f"Strategy: {r.get('strategy_used', '?')}\n"
            f"Savings: {r.get('savings_pct', 0):.1f}%\n"
            f"Result:\n{r.get('compressed', '')}"
        )

    def _summarize(
        text: str,
        sentence_count: Optional[int] = None,
        ratio: Optional[float] = None,
        algorithm: str = "textrank",
    ) -> str:
        r = execute_tool("summarize", {"text": text, "sentence_count": sentence_count, "ratio": ratio, "algorithm": algorithm})
        return r.get("summary", "")

    def _compress_batch(texts: list[str], level: str = "semantic") -> str:
        r = execute_tool("compress_batch", {"texts": texts, "level": level})
        lines = []
        for i, item in enumerate(r.get("results", [])):
            lines.append(f"[{i}] {item.get('compressed_text', '')} ({item.get('efficiency_pct', 0):.1f}% saved)")
        return "\n".join(lines)

    return [
        StructuredTool.from_function(
            func=_compress,
            name="synthelion_compress",
            description=(
                "Compress a text prompt to reduce LLM token usage. "
                "Removes stop words and lemmatizes content words. "
                "Supports 50+ languages automatically."
            ),
            args_schema=CompressInput,
        ),
        StructuredTool.from_function(
            func=_detect_language,
            name="synthelion_detect_language",
            description="Detect the language of a text and return the ISO 639-3 code (e.g. 'eng', 'ita', 'deu').",
            args_schema=DetectLanguageInput,
        ),
        StructuredTool.from_function(
            func=_route_content,
            name="synthelion_route_content",
            description=(
                "Auto-detect content type (JSON array, HTML, git diff, logs, code, or plain text) "
                "and apply the best compression strategy for each."
            ),
            args_schema=RouteContentInput,
        ),
        StructuredTool.from_function(
            func=_summarize,
            name="synthelion_summarize",
            description="Extractive summarization — keeps the most important sentences from a text.",
            args_schema=SummarizeInput,
        ),
        StructuredTool.from_function(
            func=_compress_batch,
            name="synthelion_compress_batch",
            description="Compress a list of texts in a single call.",
            args_schema=CompressBatchInput,
        ),
    ]
