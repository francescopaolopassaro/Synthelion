# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""OpenAI / Codex SDK adapter with automatic compression and RAG memory.

Requires: pip install 'synthelion[openai]'  (adds openai>=1.0)

Usage::

    from synthelion.integrations.openai_adapter import OpenAIAdapter

    adapter = OpenAIAdapter(model="gpt-4o")
    response = adapter.chat("Explain JWT authentication")
    print(response.content)
    print(f"Tokens saved: {response.tokens_saved}")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from synthelion.agent.rag_agent import RagAgent
from synthelion.models import CompressionProfile


@dataclass
class OpenAIResponse:
    """Wrapper around an OpenAI response with added savings metadata."""
    content: str
    tokens_saved: int
    savings_pct: float
    recalled_context: list[dict] = field(default_factory=list)
    raw: Any = None


class OpenAIAdapter:
    """Drop-in wrapper around ``openai.OpenAI`` with auto-compression + RAG.

    Parameters
    ----------
    model:
        OpenAI model ID (e.g. ``"gpt-4o"``, ``"gpt-4o-mini"``).
    profile:
        Synthelion compression profile applied to every user message.
    max_context_tokens:
        Rolling token budget for the conversation buffer.
    recall_limit:
        Max past decisions injected into each prompt.
    auto_store:
        Automatically persist assistant replies in the session DB.
    **openai_kwargs:
        Extra keyword arguments forwarded to ``openai.OpenAI()``.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        profile: CompressionProfile = CompressionProfile.BALANCED,
        max_context_tokens: int = 4000,
        recall_limit: int = 5,
        auto_store: bool = False,
        **openai_kwargs: Any,
    ) -> None:
        try:
            import openai  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "openai is not installed. Run: pip install 'synthelion[openai]'"
            ) from exc
        self._client = openai.OpenAI(**openai_kwargs)
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
    ) -> OpenAIResponse:
        """Send *message* to OpenAI with automatic compression + memory recall.

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
            Extra keyword args forwarded to ``chat.completions.create()``.
        """
        prepared = self._agent.prepare_message(message)

        messages: list[dict[str, str]] = []

        sys_parts: list[str] = []
        if inject_recall and prepared.recalled_context:
            recall_block = "\n".join(
                f"- {d.get('text', '')}" for d in prepared.recalled_context
            )
            sys_parts.append(f"[Recalled context]\n{recall_block}")
        if system:
            sys_parts.append(system)
        if sys_parts:
            messages.append({"role": "system", "content": "\n\n".join(sys_parts)})

        messages.extend(self._agent.to_messages())
        if not any(m["role"] == "user" for m in messages):
            messages.append({"role": "user", "content": prepared.compressed})

        raw = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            **kwargs,
        )
        reply = raw.choices[0].message.content or "" if raw.choices else ""
        self._agent.add_turn("assistant", reply)

        return OpenAIResponse(
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
