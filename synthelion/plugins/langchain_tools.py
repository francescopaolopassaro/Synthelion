# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""LangChain tool wrappers and RAG memory for Synthelion.

Requires: pip install "synthelion[langchain]"

Usage::

    from synthelion.plugins.langchain_tools import get_tools, SynthelionMemory

    # Standalone tools
    tools = get_tools()
    agent = initialize_agent(tools, llm, agent=AgentType.OPENAI_FUNCTIONS)

    # Or with LangGraph / LCEL:
    from langgraph.prebuilt import create_react_agent
    app = create_react_agent(llm, get_tools())

    # RAG memory — compresses and recalls context automatically
    memory = SynthelionMemory()
    chain = ConversationChain(llm=llm, memory=memory)
"""
from __future__ import annotations

from typing import Any, Optional, Type

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

    class SessionRecordInput(BaseModel):
        text: str = Field(description="The decision or context note to save.")
        reason: str = Field(default="", description="Optional reason or rationale.")
        tags: list[str] = Field(default_factory=list, description="Optional tags for filtering.")

    class SessionRecallInput(BaseModel):
        query: str = Field(default="", description="Search query (empty = most recent).")
        limit: int = Field(default=10, description="Max results.")
        since_days: Optional[float] = Field(default=None, description="Restrict to last N days.")

    class StatusInput(BaseModel):
        days: Optional[int] = Field(default=None, description="Restrict to last N days. Omit for all-time.")

    class CompressForContextInput(BaseModel):
        content: str = Field(description="Content to compress.")
        max_tokens: Optional[int] = Field(default=None, description="Target token budget. Omit to compress without a limit.")
        profile: str = Field(default="agent", description="Profile: light, balanced, agent, or aggressive.")
        prefer: str = Field(default="auto", description="compress, summarize, or auto.")

    class CompressConversationInput(BaseModel):
        messages: list[dict] = Field(description="Conversation history in OpenAI/Anthropic format.")
        max_tokens: Optional[int] = Field(default=None, description="Target token budget for the entire conversation.")
        keep_last_n: int = Field(default=4, description="Number of recent messages to keep verbatim.")

    class DeduplicateInput(BaseModel):
        texts: list[str] = Field(description="List of text blocks to deduplicate.")
        threshold: float = Field(default=0.8, description="Similarity threshold (0.0-1.0).")

    class CompressFileInput(BaseModel):
        path: str = Field(description="Absolute or relative path to the file.")
        profile: str = Field(default="agent", description="Profile: light, balanced, agent, or aggressive.")
        max_tokens: Optional[int] = Field(default=None, description="Optional token budget.")
        encoding: str = Field(default="utf-8", description="File encoding.")

    # --- Tool factories ---

    def _compress(text: str, level: str = "semantic", language: Optional[str] = None) -> str:
        args: dict[str, Any] = {"text": text, "level": level}
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
        args: dict[str, Any] = {"content": content, "profile": profile}
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

    def _session_record(text: str, reason: str = "", tags: list[str] | None = None) -> str:
        args: dict[str, Any] = {"text": text, "reason": reason}
        if tags:
            args["tags"] = tags
        r = execute_tool("session_record", args)
        return f"Recorded: id={r.get('id')} backend={r.get('backend')}"

    def _session_recall(query: str = "", limit: int = 10, since_days: Optional[float] = None) -> str:
        args: dict[str, Any] = {"query": query, "limit": limit}
        if since_days is not None:
            args["since_days"] = since_days
        r = execute_tool("session_recall", args)
        decisions = r.get("decisions", [])
        if not decisions:
            return "No matching decisions found."
        lines = [f"[{d.get('id', '?')}] {d.get('text', '')}" for d in decisions]
        return "\n".join(lines)

    def _compress_for_context(
        content: str,
        max_tokens: Optional[int] = None,
        profile: str = "agent",
        prefer: str = "auto",
    ) -> str:
        args: dict[str, Any] = {"content": content, "profile": profile, "prefer": prefer}
        if max_tokens is not None:
            args["max_tokens"] = max_tokens
        r = execute_tool("compress_for_context", args)
        fits = r.get("fits_budget", True)
        budget_str = f" (fits_budget={fits})" if max_tokens else ""
        return (
            f"Type: {r.get('detected_type', '?')} | Strategy: {r.get('strategy', '?')}{budget_str}\n"
            f"Savings: {r.get('synthelion_metrics', '')}\n{r.get('compressed', '')}"
        )

    def _compress_conversation(
        messages: list[dict],
        max_tokens: Optional[int] = None,
        keep_last_n: int = 4,
    ) -> str:
        args: dict[str, Any] = {"messages": messages, "keep_last_n": keep_last_n}
        if max_tokens is not None:
            args["max_tokens"] = max_tokens
        r = execute_tool("compress_conversation", args)
        return (
            f"Messages: {r.get('messages_before', '?')} → {r.get('messages_after', '?')} | "
            f"Strategy: {r.get('strategy', '?')} | "
            f"Savings: {r.get('synthelion_metrics', '')}"
        )

    def _deduplicate(texts: list[str], threshold: float = 0.8) -> str:
        r = execute_tool("deduplicate", {"texts": texts, "threshold": threshold})
        return (
            f"Kept {r.get('deduplicated_count', '?')}/{r.get('original_count', '?')} texts "
            f"(removed {r.get('removed_count', 0)}) | "
            f"Savings: {r.get('synthelion_metrics', '')}"
        )

    def _compress_file(
        path: str,
        profile: str = "agent",
        max_tokens: Optional[int] = None,
        encoding: str = "utf-8",
    ) -> str:
        args: dict[str, Any] = {"path": path, "profile": profile, "encoding": encoding}
        if max_tokens is not None:
            args["max_tokens"] = max_tokens
        r = execute_tool("compress_file", args)
        if "error" in r:
            return f"Error: {r['error']}"
        fits = r.get("fits_budget", True)
        budget_str = f" fits_budget={fits}" if max_tokens else ""
        return (
            f"Path: {r.get('path', '?')} | Type: {r.get('detected_type', '?')}{budget_str}\n"
            f"Savings: {r.get('synthelion_metrics', '')}\n{r.get('compressed', '')}"
        )

    def _synthelion_status(days: Optional[int] = None) -> str:
        args: dict[str, Any] = {}
        if days:
            args["days"] = days
        r = execute_tool("synthelion_status", args)
        return (
            f"Calls: {r.get('total_calls', 0)} | "
            f"Tokens saved: {r.get('tokens_saved', 0):,} | "
            f"Efficiency: {r.get('avg_efficiency_pct', 0):.1f}%"
        )

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
        StructuredTool.from_function(
            func=_session_record,
            name="synthelion_session_record",
            description="Save a decision or context note that persists across sessions (ChromaDB RAG).",
            args_schema=SessionRecordInput,
        ),
        StructuredTool.from_function(
            func=_session_recall,
            name="synthelion_session_recall",
            description="Recall relevant past decisions by semantic or lexical similarity.",
            args_schema=SessionRecallInput,
        ),
        StructuredTool.from_function(
            func=_synthelion_status,
            name="synthelion_status",
            description="Return aggregate token savings statistics.",
            args_schema=StatusInput,
        ),
        StructuredTool.from_function(
            func=_compress_file,
            name="synthelion_compress_file",
            description=(
                "Read a file by path and return the compressed content. "
                "Avoids loading raw file content into context — returns only the useful part."
            ),
            args_schema=CompressFileInput,
        ),
        StructuredTool.from_function(
            func=_compress_for_context,
            name="synthelion_compress_for_context",
            description=(
                "Compress content to fit within a token budget before inserting it into an LLM context. "
                "Chains routing + NLP compression + summarization until the budget is met."
            ),
            args_schema=CompressForContextInput,
        ),
        StructuredTool.from_function(
            func=_compress_conversation,
            name="synthelion_compress_conversation",
            description=(
                "Compress a conversation history (messages list) to reduce token usage. "
                "Keeps recent messages verbatim and compresses/summarizes older turns."
            ),
            args_schema=CompressConversationInput,
        ),
        StructuredTool.from_function(
            func=_deduplicate,
            name="synthelion_deduplicate",
            description="Remove near-duplicate text blocks from a list using cosine similarity.",
            args_schema=DeduplicateInput,
        ),
    ]


class SynthelionMemory:
    """LangChain-compatible memory that compresses history and recalls via RAG.

    Drop-in replacement for ``ConversationBufferMemory``.  Each turn is
    compressed before storage; a semantic recall step injects relevant past
    decisions at the top of the prompt.

    Requires: langchain-core >= 0.1

    Usage::

        from langchain.chains import ConversationChain
        from synthelion.plugins.langchain_tools import SynthelionMemory

        memory = SynthelionMemory(memory_key="history")
        chain = ConversationChain(llm=llm, memory=memory)
    """

    def __init__(
        self,
        memory_key: str = "history",
        human_prefix: str = "Human",
        ai_prefix: str = "AI",
        max_context_tokens: int = 4000,
        recall_limit: int = 5,
    ) -> None:
        try:
            import langchain_core  # noqa: F401 — just validate install
        except ImportError as exc:
            raise ImportError(
                "LangChain is not installed. Run: pip install 'synthelion[langchain]'"
            ) from exc

        from synthelion.agent.rag_agent import RagAgent
        self.memory_key = memory_key
        self.human_prefix = human_prefix
        self.ai_prefix = ai_prefix
        self._agent = RagAgent(max_context_tokens=max_context_tokens, recall_limit=recall_limit)

    # LangChain Memory interface

    @property
    def memory_variables(self) -> list[str]:
        return [self.memory_key]

    def load_memory_variables(self, inputs: dict[str, Any]) -> dict[str, Any]:
        query = next(iter(inputs.values()), "") if inputs else ""
        recalled = self._agent.recall(str(query))
        history = self._agent.render_context()
        if recalled:
            recall_block = "\n".join(f"[memory] {d.get('text', '')}" for d in recalled)
            history = recall_block + "\n" + history if history else recall_block
        return {self.memory_key: history}

    def save_context(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        human_msg = next(iter(inputs.values()), "")
        ai_msg = next(iter(outputs.values()), "")
        self._agent.add_turn(self.human_prefix, str(human_msg))
        self._agent.add_turn(self.ai_prefix, str(ai_msg))

    def clear(self) -> None:
        self._agent.clear()
