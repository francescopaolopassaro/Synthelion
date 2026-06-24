# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re

from synthelion.word_provider import FunctionWordProvider

# Common abbreviations that should not trigger sentence splits
_DEFAULT_ABBREVS: frozenset[str] = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "vs", "etc", "fig",
    "vol", "no", "pp", "ed", "rev", "est", "approx", "dept", "gov",
    "inc", "corp", "ltd", "co", "st", "ave", "blvd", "rd",
    # Italian
    "sig", "dott", "ing", "avv", "geom", "arch", "prof",
    # German
    "bzw", "usw", "ggf", "ggfs", "ca", "nr",
    # French
    "env", "ex", "cf",
})

_SENTENCE_END = re.compile(r"([.!?…]+)(\s+)")


class SentenceDetector:
    """Splits text into sentences using punctuation + abbreviation lists.

    Ported from C# CavemanSentenceDetector. Uses worddata abbreviation hints
    when available, preventing false splits on "Dr. Rossi" or "e.g.".
    """

    def __init__(self, word_provider: FunctionWordProvider | None = None) -> None:
        self._provider = word_provider or FunctionWordProvider()

    def split_text(self, text: str, iso3: str = "eng") -> list[str]:
        if not text or not text.strip():
            return []

        abbrevs = set(_DEFAULT_ABBREVS)
        # Load language-specific abbreviations from worddata if available
        data = self._provider.load_word_data(iso3)
        if data and data.function_words:
            # Short function words can be abbreviation stems
            abbrevs.update(w.rstrip(".") for w in data.function_words if len(w) <= 4)

        return _split(text, abbrevs)


def _split(text: str, abbrevs: set[str]) -> list[str]:
    sentences: list[str] = []
    start = 0

    for m in _SENTENCE_END.finditer(text):
        punct_end = m.end(1)
        before = text[start : m.start()].rstrip()
        last_word = re.split(r"\s+", before)[-1].rstrip(".").lower() if before else ""

        if last_word in abbrevs:
            continue

        # Avoid splitting on "..." mid-word or ellipsis
        if m.group(1) == "…" and not m.group(2).strip():
            continue

        candidate = text[start : punct_end].strip()
        if candidate:
            sentences.append(candidate)
        start = m.end()

    tail = text[start:].strip()
    if tail:
        sentences.append(tail)

    return sentences if sentences else [text.strip()]
