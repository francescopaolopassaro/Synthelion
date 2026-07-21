# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""CrewAI adapter and tool wrappers with automatic compression and RAG memory.

Requires: pip install 'synthelion[crewai]'  (adds crewai>=1.15)

Two entry points:

``CrewAIAdapter`` — a drop-in helper that mirrors ``ClaudeAdapter``/``OpenAIAdapter``
(``chat``/``store``/``recall``/``status``/``reset``). Each ``chat`` call compresses
the outgoing message, optionally injects recalled context, runs a one-shot CrewAI
Agent + Task + Crew, and records the exchange::

    from synthelion.integrations.crewai_adapter import CrewAIAdapter

    adapter = CrewAIAdapter(model="gpt-4o")
    response = adapter.chat("Explain JWT authentication")
    print(response.content)
    print(f"Tokens saved: {response.tokens_saved}")

``get_tools()`` — CrewAI-native ``BaseTool`` instances (compress, route_content,
session_record, ...) an agent/crew can call directly to compress messages or
tool output::

    from crewai import Agent
    from synthelion.integrations.crewai_adapter import get_tools

    agent = Agent(role="Researcher", goal="...", backstory="...", tools=get_tools())
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Type

from synthelion.agent.rag_agent import RagAgent
from synthelion.models import CompressionProfile

_IMPORT_ERROR = "crewai is not installed. Run: pip install 'synthelion[crewai]'"


@dataclass
class CrewAIResponse:
    """Wrapper around a CrewAI kickoff result with added savings metadata."""
    content: str
    tokens_saved: int
    savings_pct: float
    recalled_context: list[dict] = field(default_factory=list)
    raw: Any = None


class CrewAIAdapter:
    """CrewAI helper with auto-compression + RAG, mirroring the Claude/OpenAI adapters.

    Each :meth:`chat` call is compressed and enriched with recalled context, then
    executed as a single-agent, single-task CrewAI crew.

    Parameters
    ----------
    model:
        Model ID used for the CrewAI agent when *llm* is not given (e.g. ``"gpt-4o"``).
    profile:
        Synthelion compression profile applied to every user message.
    max_context_tokens:
        Rolling token budget for the conversation buffer.
    recall_limit:
        Max past decisions injected into each prompt.
    auto_store:
        Automatically persist assistant replies in the session DB.
    role / goal / backstory:
        CrewAI agent persona used for every ``chat`` call.
    llm:
        Optional pre-built CrewAI LLM (or provider string). Falls back to *model*.
    **crew_kwargs:
        Extra keyword arguments forwarded to ``crewai.Crew()``.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        profile: CompressionProfile = CompressionProfile.BALANCED,
        max_context_tokens: int = 4000,
        recall_limit: int = 5,
        auto_store: bool = False,
        role: str = "Assistant",
        goal: str = "Answer the user accurately and concisely",
        backstory: str = "A helpful AI assistant.",
        llm: Any = None,
        **crew_kwargs: Any,
    ) -> None:
        try:
            import crewai  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(_IMPORT_ERROR) from exc
        self._crewai = crewai
        self._llm = llm if llm is not None else model
        self._role = role
        self._goal = goal
        self._backstory = backstory
        self._crew_kwargs = crew_kwargs
        self._agent = RagAgent(
            profile=profile,
            max_context_tokens=max_context_tokens,
            recall_limit=recall_limit,
            auto_store=auto_store,
        )

    def chat(
        self,
        message: str,
        system: str = "",
        inject_recall: bool = True,
        expected_output: str = "A helpful, accurate answer.",
        **kwargs: Any,
    ) -> CrewAIResponse:
        """Run *message* through a CrewAI crew with compression + memory recall.

        Parameters
        ----------
        message:
            User message (compressed before being sent to the agent).
        system:
            Optional extra instruction prepended to the task description.
        inject_recall:
            If True, prepend recalled context to the task description.
        expected_output:
            CrewAI ``Task.expected_output`` describing the desired result.
        **kwargs:
            Extra keyword args forwarded to ``Crew.kickoff()``.
        """
        prepared = self._agent.prepare_message(message)

        parts: list[str] = []
        if inject_recall and prepared.recalled_context:
            recall_block = "\n".join(
                f"- {d.get('text', '')}" for d in prepared.recalled_context
            )
            parts.append(f"[Recalled context]\n{recall_block}")
        if system:
            parts.append(system)
        parts.append(prepared.compressed)
        description = "\n\n".join(parts)

        agent = self._crewai.Agent(
            role=self._role,
            goal=self._goal,
            backstory=self._backstory,
            llm=self._llm,
        )
        task = self._crewai.Task(
            description=description,
            expected_output=expected_output,
            agent=agent,
        )
        crew = self._crewai.Crew(
            agents=[agent],
            tasks=[task],
            **self._crew_kwargs,
        )
        raw = crew.kickoff(**kwargs)
        if raw is None:
            reply = ""
        elif hasattr(raw, "raw"):
            reply = raw.raw or ""
        else:
            reply = str(raw)

        self._agent.add_turn("assistant", reply)

        return CrewAIResponse(
            content=reply,
            tokens_saved=prepared.tokens_saved,
            savings_pct=round(prepared.savings_pct, 2),
            recalled_context=prepared.recalled_context,
            raw=raw,
        )

    def store(self, text: str, reason: str = "", tags: list[str] | None = None) -> str:
        """Persist a decision in the RAG memory and return its ID."""
        return self._agent.store(text, reason=reason, tags=tags)

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        """Recall relevant past decisions from the RAG memory."""
        return self._agent.recall(query, limit=limit)

    def status(self) -> dict[str, Any]:
        return self._agent.status()

    def reset(self) -> None:
        self._agent.clear()


def get_tools() -> list:
    """Return a list of CrewAI ``BaseTool`` instances for Synthelion.

    Requires crewai >= 1.15. Install with:
        pip install 'synthelion[crewai]'
    """
    try:
        from crewai.tools import BaseTool
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise ImportError(_IMPORT_ERROR) from exc

    from synthelion.plugins.openai_tools import execute_tool

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
        ratio: Optional[float] = Field(default=None, description="Fraction of sentences to keep (0.0-1.0).")
        algorithm: str = Field(default="textrank", description="Algorithm: tfidf or textrank.")

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

    class DeduplicateInput(BaseModel):
        texts: list[str] = Field(description="List of text blocks to deduplicate.")
        threshold: float = Field(default=0.8, description="Similarity threshold (0.0-1.0).")

    class CompressFileInput(BaseModel):
        path: str = Field(description="Absolute or relative path to the file.")
        profile: str = Field(default="agent", description="Profile: light, balanced, agent, or aggressive.")
        max_tokens: Optional[int] = Field(default=None, description="Optional token budget.")
        encoding: str = Field(default="utf-8", description="File encoding.")

    class SynthelionCompressTool(BaseTool):
        name: str = "synthelion_compress"
        description: str = (
            "Compress a text prompt to reduce LLM token usage. "
            "Removes stop words and lemmatizes content words. "
            "Supports 50+ languages automatically."
        )
        args_schema: Type[BaseModel] = CompressInput

        def _run(self, text: str, level: str = "semantic", language: Optional[str] = None) -> str:
            args: dict[str, Any] = {"text": text, "level": level}
            if language:
                args["language"] = language
            r = execute_tool("compress", args)
            return (
                f"Compressed: {r['compressed_text']}\n"
                f"Savings: {r.get('efficiency_pct', 0):.1f}% "
                f"({r.get('original_tokens', '?')} -> {r.get('compressed_tokens', '?')} tokens)"
            )

    class SynthelionDetectLanguageTool(BaseTool):
        name: str = "synthelion_detect_language"
        description: str = "Detect the language of a text and return the ISO 639-3 code (e.g. 'eng', 'ita', 'deu')."
        args_schema: Type[BaseModel] = DetectLanguageInput

        def _run(self, text: str, with_scores: bool = False) -> str:
            r = execute_tool("detect_language", {"text": text, "with_scores": with_scores})
            if with_scores:
                scores = r.get("scores", {})
                top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
                return "\n".join(f"{k}: {v:.3f}" for k, v in top)
            return r.get("language", "unknown")

    class SynthelionRouteContentTool(BaseTool):
        name: str = "synthelion_route_content"
        description: str = (
            "Auto-detect content type (JSON array, HTML, git diff, logs, code, or plain text) "
            "and apply the best compression strategy for each."
        )
        args_schema: Type[BaseModel] = RouteContentInput

        def _run(self, content: str, profile: str = "balanced", query: Optional[str] = None) -> str:
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

    class SynthelionSummarizeTool(BaseTool):
        name: str = "synthelion_summarize"
        description: str = "Extractive summarization — keeps the most important sentences from a text."
        args_schema: Type[BaseModel] = SummarizeInput

        def _run(
            self,
            text: str,
            sentence_count: Optional[int] = None,
            ratio: Optional[float] = None,
            algorithm: str = "textrank",
        ) -> str:
            r = execute_tool(
                "summarize",
                {"text": text, "sentence_count": sentence_count, "ratio": ratio, "algorithm": algorithm},
            )
            return r.get("summary", "")

    class SynthelionSessionRecordTool(BaseTool):
        name: str = "synthelion_session_record"
        description: str = "Save a decision or context note that persists across sessions (ChromaDB RAG)."
        args_schema: Type[BaseModel] = SessionRecordInput

        def _run(self, text: str, reason: str = "", tags: list[str] | None = None) -> str:
            args: dict[str, Any] = {"text": text, "reason": reason}
            if tags:
                args["tags"] = tags
            r = execute_tool("session_record", args)
            return f"Recorded: id={r.get('id')} backend={r.get('backend')}"

    class SynthelionSessionRecallTool(BaseTool):
        name: str = "synthelion_session_recall"
        description: str = "Recall relevant past decisions by semantic or lexical similarity."
        args_schema: Type[BaseModel] = SessionRecallInput

        def _run(self, query: str = "", limit: int = 10, since_days: Optional[float] = None) -> str:
            args: dict[str, Any] = {"query": query, "limit": limit}
            if since_days is not None:
                args["since_days"] = since_days
            r = execute_tool("session_recall", args)
            decisions = r.get("decisions", [])
            if not decisions:
                return "No matching decisions found."
            return "\n".join(f"[{d.get('id', '?')}] {d.get('text', '')}" for d in decisions)

    class SynthelionStatusTool(BaseTool):
        name: str = "synthelion_status"
        description: str = "Return aggregate token savings statistics."
        args_schema: Type[BaseModel] = StatusInput

        def _run(self, days: Optional[int] = None) -> str:
            args: dict[str, Any] = {}
            if days:
                args["days"] = days
            r = execute_tool("synthelion_status", args)
            return (
                f"Calls: {r.get('total_calls', 0)} | "
                f"Tokens saved: {r.get('tokens_saved', 0):,} | "
                f"Efficiency: {r.get('avg_efficiency_pct', 0):.1f}%"
            )

    class SynthelionCompressForContextTool(BaseTool):
        name: str = "synthelion_compress_for_context"
        description: str = (
            "Compress content to fit within a token budget before inserting it into an LLM context. "
            "Chains routing + NLP compression + summarization until the budget is met."
        )
        args_schema: Type[BaseModel] = CompressForContextInput

        def _run(
            self,
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

    class SynthelionDeduplicateTool(BaseTool):
        name: str = "synthelion_deduplicate"
        description: str = "Remove near-duplicate text blocks from a list using cosine similarity."
        args_schema: Type[BaseModel] = DeduplicateInput

        def _run(self, texts: list[str], threshold: float = 0.8) -> str:
            r = execute_tool("deduplicate", {"texts": texts, "threshold": threshold})
            return (
                f"Kept {r.get('deduplicated_count', '?')}/{r.get('original_count', '?')} texts "
                f"(removed {r.get('removed_count', 0)}) | "
                f"Savings: {r.get('synthelion_metrics', '')}"
            )

    class SynthelionCompressFileTool(BaseTool):
        name: str = "synthelion_compress_file"
        description: str = (
            "Read a file by path and return the compressed content. "
            "Avoids loading raw file content into context — returns only the useful part."
        )
        args_schema: Type[BaseModel] = CompressFileInput

        def _run(
            self,
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

    return [
        SynthelionCompressTool(),
        SynthelionDetectLanguageTool(),
        SynthelionRouteContentTool(),
        SynthelionSummarizeTool(),
        SynthelionSessionRecordTool(),
        SynthelionSessionRecallTool(),
        SynthelionStatusTool(),
        SynthelionCompressForContextTool(),
        SynthelionDeduplicateTool(),
        SynthelionCompressFileTool(),
    ]
