# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re
from enum import Enum

_WORD_SPLIT_RE = re.compile(r"[a-zA-Z0-9_]+|[^\s]")

_SHORT_TOKENS = frozenset({
    "a", "an", "the", "in", "on", "at", "to", "of", "is", "it",
    "as", "by", "or", "be", "if", "do", "no", "up", "we", "he",
    "she", "me", "my", "i", "u", "x", "y", "z", "&", "|",
})


class LlmModel(Enum):
    GPT4 = "gpt-4"
    GPT3_5_TURBO = "gpt-3.5"
    LLAMA3 = "llama-3"
    GEMMA3 = "gemma-3"
    CLAUDE3 = "claude-3"


def _count_whitespace_tokens(text: str) -> int:
    count = 0
    run = 0
    for c in text:
        if c.isspace():
            run += 1
        else:
            if run >= 4:
                count += run // 4
            run = 0
    if run >= 4:
        count += run // 4
    return count


def _count_bpe_approx(text: str) -> int:
    token_count = 0
    for m in _WORD_SPLIT_RE.finditer(text):
        word = m.group()
        if word.lower() in _SHORT_TOKENS:
            token_count += 1
            continue
        length = len(word)
        if length <= 4:
            token_count += 1
        elif length <= 8:
            token_count += 2
        else:
            token_count += 2 + (length - 8 + 3) // 4

    token_count += _count_whitespace_tokens(text)
    return max(1, token_count)


class ModelTokenizer:
    """Approximate token counting for common LLM models.

    Ported from C# ModelTokenizer. Pure heuristic (no BPE vocab) — plug in a real
    tiktoken/BPE counter for exact counts if you need them.
    """

    def count_tokens(self, text: str, model: LlmModel = LlmModel.GPT4) -> int:
        if not text or not text.strip():
            return 0

        base = _count_bpe_approx(text)

        if model == LlmModel.LLAMA3:
            return int(base * 1.05)
        if model == LlmModel.GEMMA3:
            return int(base * 1.02)
        if model == LlmModel.CLAUDE3:
            return int(base * 0.98)
        return base

    def count_all_models(self, text: str) -> dict[str, int]:
        b = _count_bpe_approx(text) if text and text.strip() else 0
        return {
            "gpt4": b,
            "gpt35": b,
            "llama3": int(b * 1.05),
            "gemma3": int(b * 1.02),
            "claude3": int(b * 0.98),
        }

    def model_name(self, model: LlmModel) -> str:
        return model.value
