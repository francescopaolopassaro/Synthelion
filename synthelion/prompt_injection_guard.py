# Synthelion — Python port of Caveman.PrivacyGuard (https://github.com/francescopaolopassaro/Caveman.PrivacyGuard)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Heuristic, regex-based scanner for prompt-injection attempts in untrusted text
before it reaches an LLM (user messages, tool outputs, retrieved documents, etc.).

Complements `PrivacyAnalyzer`: that class protects data flowing OUT to the model,
this class screens instructions trying to sneak IN and hijack the model's behavior.
Also a different concern from `synthelion.safety_guard.SafetyGuard` (which flags
text about security *topics* to decide whether to skip compressing it) — this
module targets jailbreak/injection technique patterns specifically.

Detection is heuristic and cannot catch every technique — treat it as one layer of
defense, not a guarantee.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_RISK_LEVELS = ("Safe", "Low", "Medium", "High", "Critical")


@dataclass
class PromptInjectionResult:
    score: int = 0
    risk_level: str = "Safe"
    detected_categories: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return len(self.detected_categories) == 0


def _to_risk_level(score: int) -> str:
    if score == 0:
        return "Safe"
    if score <= 20:
        return "Low"
    if score <= 45:
        return "Medium"
    if score <= 70:
        return "High"
    return "Critical"


_BUILTIN_PATTERNS: tuple[tuple[str, str, int], ...] = (
    # Instruction override: attempts to discard the system prompt or prior instructions.
    ("Instruction Override", r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|earlier|all)\b.{0,30}\b(instructions?|prompts?|rules?)\b", 30),
    ("Instruction Override", r"\b(ignora|dimentica)\b.{0,30}\b(le istruzioni|il prompt|le regole)\b", 30),
    ("Instruction Override", r"\bnew instructions?\s*:", 20),
    # System prompt exfiltration: trying to get the model to reveal its hidden configuration.
    ("System Prompt Exfiltration", r"\b(repeat|reveal|show|print|output)\b.{0,20}\b(your|the)\b.{0,20}\b(system prompt|instructions|initial prompt)\b", 30),
    ("System Prompt Exfiltration", r"\bwhat (are|were) your (instructions|rules|guidelines)\b", 25),
    # Role hijack / jailbreak framing: asking the model to assume an unrestricted persona.
    ("Role Hijack", r"\byou are now\b.{0,30}\b(dan|jailbroken|unrestricted|uncensored)\b", 35),
    ("Role Hijack", r"\b(developer mode|dan mode|jailbreak)\b", 30),
    ("Role Hijack", r"\bpretend (you are|to be)\b.{0,30}\bno (restrictions|rules|filters)\b", 30),
    ("Role Hijack", r"\bact as if\b.{0,30}\b(no|without)\b.{0,20}\b(restrictions|filters|guidelines|rules)\b", 25),
    # Delimiter/role-marker injection: fake system/assistant turns smuggled inside user content.
    ("Delimiter Injection", r"<\|im_start\|>\s*(system|assistant)", 35),
    ("Delimiter Injection", r"\[\s*(system|SYSTEM)\s*\]\s*:", 25),
    ("Delimiter Injection", r"```\s*system\b", 20),
    # Encoded payload: unusually long base64-looking blob that may hide instructions from a naive filter.
    ("Encoded Payload", r"\b[A-Za-z0-9+/]{80,}={0,2}\b", 15),
    # Exfiltration coercion: asking the model to leak secrets/config to an external channel.
    ("Data Exfiltration Coercion", r"\bsend\b.{0,30}\b(api key|password|secret|credentials)\b.{0,30}\bto\b", 30),
)


class PromptInjectionGuard:
    def __init__(self) -> None:
        self._patterns: list[tuple[str, re.Pattern, int]] = []
        self.load_builtin_patterns()

    def add_pattern(self, category: str, regex_pattern: str, weight: int) -> None:
        self._patterns.append((category, re.compile(regex_pattern, re.IGNORECASE), weight))

    def remove_category(self, category: str) -> int:
        before = len(self._patterns)
        self._patterns = [p for p in self._patterns if p[0].lower() != category.lower()]
        return before - len(self._patterns)

    def clear_patterns(self) -> None:
        self._patterns = []

    def load_builtin_patterns(self) -> None:
        for category, pattern, weight in _BUILTIN_PATTERNS:
            self.add_pattern(category, pattern, weight)

    def analyze(self, text: str) -> PromptInjectionResult:
        if not text or not text.strip():
            return PromptInjectionResult(score=0, risk_level="Safe")

        matched_categories: set[str] = set()
        score = 0
        for category, pattern, weight in self._patterns:
            if pattern.search(text):
                matched_categories.add(category)
                score += weight

        score = min(score, 100)
        return PromptInjectionResult(
            score=score,
            risk_level=_to_risk_level(score),
            detected_categories=sorted(matched_categories),
        )
