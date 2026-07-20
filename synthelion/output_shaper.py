# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

from synthelion.models import VerbosityLevel

_SENTINEL_OPEN = "<!-- synthelion-verbosity-"
_SENTINEL_CLOSE = " -->"

_L1_TEXT = (
    'Skip preamble and postamble. Do not say things like "Sure!", "Of course!", '
    '"Great question!", "Certainly!", "I\'d be happy to...", "Let me...", or similar. '
    "Start with substance immediately."
)

_L2_TEXT = (
    "Never restate or echo back code, file contents, diffs, or tool output shown in context. "
    "Do not repeat what was provided. If you need to refer to it, use filename:line references."
)

_L3_TEXT = "Give conclusions and results only. Do not explain your reasoning unless explicitly asked."

_L4_TEXT = (
    "Minimum token response. Sentence fragments are fine. "
    "No preamble. No postamble. No restatement. No reasoning."
)


def _build_steering(level: VerbosityLevel) -> str:
    if level == VerbosityLevel.SKIP_CEREMONY:
        return _L1_TEXT
    if level == VerbosityLevel.NO_RESTATEMENT:
        return _L1_TEXT + "\n" + _L2_TEXT
    if level == VerbosityLevel.CONCLUSIONS_ONLY:
        return _L1_TEXT + "\n" + _L2_TEXT + "\n" + _L3_TEXT
    if level == VerbosityLevel.MINIMUM_TOKENS:
        return _L4_TEXT
    return ""


class OutputShaper:
    """Reduces LLM output tokens by injecting verbosity-steering instructions into a system prompt.

    Ported from C# CavemanOutputShaper. Idempotent: a sentinel comment tags the
    steering block per level, so calling `shape_system_prompt` twice at the same
    level does not double-inject.
    """

    def shape_system_prompt(self, system_prompt: str, level: VerbosityLevel = VerbosityLevel.NO_RESTATEMENT) -> str:
        if level == VerbosityLevel.OFF:
            return system_prompt

        prompt = system_prompt or ""
        sentinel = f"{_SENTINEL_OPEN}{level.value}{_SENTINEL_CLOSE}"
        if sentinel in prompt:
            return prompt  # already shaped at this level

        clean = self.remove_verbosity_steering(prompt)
        steering = _build_steering(level)
        return clean.rstrip() + "\n\n" + sentinel + "\n" + steering

    def has_verbosity_steering(self, system_prompt: str) -> bool:
        return _SENTINEL_OPEN in (system_prompt or "")

    def remove_verbosity_steering(self, system_prompt: str) -> str:
        if not system_prompt or _SENTINEL_OPEN not in system_prompt:
            return system_prompt

        start = system_prompt.index(_SENTINEL_OPEN)
        trim_start = start
        while trim_start > 0 and system_prompt[trim_start - 1] in "\n\r ":
            trim_start -= 1

        return system_prompt[:trim_start]
