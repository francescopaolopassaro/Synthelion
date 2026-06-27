# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Anthropic Claude SDK adapter with automatic compression and RAG memory.

Requires: pip install 'synthelion[claude]'  (adds anthropic>=0.25)

Usage::

    from synthelion.integrations.claude_adapter import ClaudeAdapter

    adapter = ClaudeAdapter(model="claude-sonnet-4-6")
    response = adapter.chat("Explain authentication in JWT")
    print(response.content)
    print(f"Tokens saved: {response.tokens_saved}")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from synthelion.agent.rag_agent import RagAgent
from synthelion.models import CompressionProfile


@dataclass
class ClaudeResponse:
    """Wrapper around the Anthropic response with added savings metadata."""
    content: str
    tokens_saved: int
    savings_pct: float
    recalled_context: list[dict] = field(default_factory=list)
    raw: Any = None


class ClaudeAdapter:
    """Drop-in wrapper around ``anthropic.Anthropic`` with auto-compression + RAG.

    Parameters
    ----------
    model:
        Claude model ID (e.g. ``"claude-sonnet-4-6"``).
    profile:
        Synthelion compression profile applied to every user message.
    max_context_tokens:
        Rolling token budget for the conversation buffer.
    recall_limit:
        Max past decisions injected into each prompt.
    auto_store:
        Automatically persist assistant replies in the session DB.
    **anthropic_kwargs:
        Extra keyword arguments forwarded to ``anthropic.Anthropic()``.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        profile: CompressionProfile = CompressionProfile.BALANCED,
        max_context_tokens: int = 4000,
        recall_limit: int = 5,
        auto_store: bool = False,
        **anthropic_kwargs: Any,
    ) -> None:
        try:
            import anthropic  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "anthropic is not installed. Run: pip install 'synthelion[claude]'"
            ) from exc
        self._client = anthropic.Anthropic(**anthropic_kwargs)
        self._model = model
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
        max_tokens: int = 2048,
        inject_recall: bool = True,
        **kwargs: Any,
    ) -> ClaudeResponse:
        """Send *message* to Claude with automatic compression + memory recall.

        Parameters
        ----------
        message:
            User message (will be compressed before sending).
        system:
            Optional system prompt.
        max_tokens:
            Max tokens in the response.
        inject_recall:
            If True, prepend recalled context to the system prompt.
        **kwargs:
            Extra keyword args forwarded to ``messages.create()``.
        """
        prepared = self._agent.prepare_message(message)

        sys_parts: list[str] = []
        if inject_recall and prepared.recalled_context:
            recall_block = "\n".join(
                f"- {d.get('text', '')}" for d in prepared.recalled_context
            )
            sys_parts.append(f"[Recalled context]\n{recall_block}")
        if system:
            sys_parts.append(system)
        final_system = "\n\n".join(sys_parts)

        messages = self._agent.to_messages()
        if not messages:
            messages = [{"role": "user", "content": prepared.compressed}]

        create_kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": messages,
            **kwargs,
        }
        if final_system:
            create_kwargs["system"] = final_system

        raw = self._client.messages.create(**create_kwargs)
        reply = raw.content[0].text if raw.content else ""

        self._agent.add_turn("assistant", reply)

        return ClaudeResponse(
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
