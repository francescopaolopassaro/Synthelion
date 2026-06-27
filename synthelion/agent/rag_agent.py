# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Provider-agnostic RAG agent wrapper.

Combines three Synthelion subsystems to maximise LLM efficiency:
  1. ContentRouter  — compresses every message before it enters the context
  2. SessionDB      — persists important facts in ChromaDB for cross-session recall
  3. ContextWindow  — keeps a rolling token-budgeted conversation buffer
  4. SavingsLedger  — tracks tokens saved per call

Usage::

    from synthelion.agent.rag_agent import RagAgent

    agent = RagAgent()
    # Compress + recall context before your LLM call
    compressed_msg, recalled = agent.prepare_message("Tell me about authentication")
    # After the LLM response, store what matters
    agent.store("We decided to use JWT for authentication", reason="stateless")
    # Recall on next session
    hits = agent.recall("authentication JWT")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from synthelion.agent.context_window import ContextWindow
from synthelion.agent.memory_extractor import MemoryExtractor
from synthelion.analytics.ledger import get_ledger
from synthelion.analytics.session_db import get_session_db
from synthelion.content_router import ContentRouter
from synthelion.models import CompressionProfile


@dataclass
class PreparedMessage:
    """Result of ``RagAgent.prepare_message``."""
    original: str
    compressed: str
    recalled_context: list[dict] = field(default_factory=list)
    tokens_before: int = 0
    tokens_after: int = 0

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)

    @property
    def savings_pct(self) -> float:
        return (self.tokens_saved / self.tokens_before * 100) if self.tokens_before else 0.0


class RagAgent:
    """Stateful RAG agent that compresses, recalls, and learns.

    Parameters
    ----------
    profile:
        Compression profile used for content routing.
    max_context_tokens:
        Rolling token budget for the conversation window.
    recall_limit:
        Max past decisions to inject before each LLM call.
    auto_store:
        If True, every assistant reply is automatically extracted and stored.
    """

    def __init__(
        self,
        profile: CompressionProfile = CompressionProfile.BALANCED,
        max_context_tokens: int = 4000,
        recall_limit: int = 5,
        auto_store: bool = False,
    ) -> None:
        self._router = ContentRouter.from_profile(profile)
        self._window = ContextWindow(max_tokens=max_context_tokens)
        self._extractor = MemoryExtractor()
        self._recall_limit = recall_limit
        self._auto_store = auto_store
        self._db = get_session_db()
        self._ledger = get_ledger()

    # ── main API ─────────────────────────────────────────────────────────────

    def prepare_message(
        self,
        message: str,
        role: str = "user",
        recall_query: str | None = None,
    ) -> PreparedMessage:
        """Compress *message* and recall relevant past context.

        Returns a :class:`PreparedMessage` with the compressed text and any
        recalled decisions that should be injected into the prompt.
        """
        routed = self._router.route(message)
        compressed = routed.compressed or message
        self._ledger.record(
            "rag_prepare",
            routed.tokens_before,
            routed.tokens_after,
            content_type=routed.detected_type.value,
        )
        self._window.append(role, compressed)

        query = recall_query or message
        recalled = self._db.session_recall(query=query, limit=self._recall_limit)

        return PreparedMessage(
            original=message,
            compressed=compressed,
            recalled_context=recalled,
            tokens_before=routed.tokens_before,
            tokens_after=routed.tokens_after,
        )

    def store(
        self,
        text: str,
        reason: str = "",
        tags: list[str] | None = None,
        files: list[str] | None = None,
    ) -> str:
        """Persist a decision/fact in the session DB and return its ID."""
        return self._db.record_decision(text=text, reason=reason, tags=tags, files=files)

    def recall(self, query: str, limit: int | None = None) -> list[dict]:
        """Semantic/lexical recall from the persistent session DB."""
        return self._db.session_recall(query=query, limit=limit or self._recall_limit)

    def add_turn(self, role: str, content: str, auto_store: bool | None = None) -> None:
        """Add a conversation turn to the rolling context window.

        If *auto_store* is True (or ``self.auto_store`` is True and the arg
        is None), the turn is also extracted and persisted in the session DB.
        """
        self._window.append(role, content)
        should_store = auto_store if auto_store is not None else self._auto_store
        if should_store and content.strip():
            note = self._extractor.extract(content)
            if note.get("summary"):
                self._db.record_decision(
                    text=note["summary"],
                    tags=note.get("keywords", [])[:5],
                )

    def render_context(self) -> str:
        """Return the current compressed conversation buffer as a string."""
        return self._window.render()

    def to_messages(self) -> list[dict[str, str]]:
        """Return the conversation as an OpenAI-compatible messages list."""
        return self._window.to_messages()

    def session_start(self) -> dict[str, Any]:
        return self._db.session_start()

    def session_end(self) -> dict[str, Any]:
        return self._db.session_end()

    def status(self) -> dict[str, Any]:
        """Return aggregate savings statistics for this session."""
        return self._ledger.summary()

    def clear(self) -> None:
        self._window.clear()
