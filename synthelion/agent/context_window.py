# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import hashlib
import json

from synthelion.nlp.text_rank import TextRankSummarizer
from synthelion.word_provider import FunctionWordProvider


def _count_tokens(text: str) -> int:
    return len(text) // 4


class ContextWindow:
    """Rolling token-budget conversation buffer for AI agents.

    Ported from C# CavemanContextWindow. Auto-compacts older turns with
    TextRank when the total token count exceeds max_tokens.
    """

    def __init__(
        self,
        max_tokens: int = 4000,
        keep_last_turns: int = 4,
        deduplicate: bool = False,
        summarizer: TextRankSummarizer | None = None,
    ) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self.max_tokens = max_tokens
        self.keep_last_turns = keep_last_turns
        self.deduplicate = deduplicate
        self._messages: list[dict] = []
        self._seen_hashes: set[str] = set()
        self._summarizer = summarizer or TextRankSummarizer()

    @property
    def message_count(self) -> int:
        return len(self._messages)

    @property
    def token_count(self) -> int:
        return _count_tokens(self.render())

    def append(self, role: str, content: str) -> None:
        if not content or not content.strip():
            return
        h = hashlib.md5(content.encode()).hexdigest()
        if self.deduplicate and h in self._seen_hashes:
            return
        self._seen_hashes.add(h)
        self._messages.append({"role": role, "content": content})
        if self.token_count > self.max_tokens:
            self._compact()

    def render(self) -> str:
        return "\n".join(f"{m['role']}: {m['content']}" for m in self._messages)

    def to_messages_json(self, indent: int | None = None) -> str:
        return json.dumps(self._messages, ensure_ascii=False, indent=indent)

    def to_messages(self) -> list[dict]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()
        self._seen_hashes.clear()

    def _compact(self) -> None:
        """Summarize older turns to fit within the token budget."""
        if len(self._messages) <= self.keep_last_turns:
            return

        system_msgs = [m for m in self._messages if m["role"] == "system"]
        recent = self._messages[-self.keep_last_turns :]
        old = self._messages[len(system_msgs) : len(self._messages) - self.keep_last_turns]

        if not old:
            return

        old_text = "\n".join(f"{m['role']}: {m['content']}" for m in old)
        summary = self._summarizer.summarize(old_text, ratio=0.3)

        compacted = {"role": "assistant", "content": f"[Summary of earlier context: {summary}]"}
        self._messages = system_msgs + [compacted] + recent
