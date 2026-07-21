# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Returns a block of style-guidance instructions to inject into an agent's own
system prompt, to reduce the verbosity of its *generated* responses.

Different axis from the rest of Synthelion: every other module compresses text
*entering* the model's context (tool output, files, JSON). This one has no text to
transform — there's no response yet at the point a caller would use it — so it's a
guidance-text generator, not a compressor: same shape as `align_cache_prompt`
(rewrites/returns text for the caller to inject), not `compress`/`route_content`.

Three escalating levels (lite/full/ultra): general verbosity-reduction principles
apply to every language, but token-per-character cost varies a lot by language —
CJK scripts commonly run 2.5-5x more tokens per character than English in common
tokenizers — so a CJK-aware note is appended when the caller identifies the
response language as one of those.
"""
from __future__ import annotations

_CJK_LANGUAGES = frozenset({"zho", "jpn", "kor"})

_GUIDANCE_LITE = """\
Response style: answer directly, no opening pleasantries or filler ("Sure, I'd be happy to help!", "Great question!"). \
Don't restate what the user just said back to them. Don't hedge with phrases that add no information ("it's worth noting that", "as an AI, I should mention"). \
Skip a summary at the end unless it adds new information."""

_GUIDANCE_FULL = _GUIDANCE_LITE + """

For bug-fix / debugging responses, use this structure instead of a narrative: \
1) the diff or exact change, 2) root cause in one sentence, 3) the fix in two sentences or fewer, \
4) a short verification checklist. Avoid restating the stack trace or error message the user already pasted."""

_GUIDANCE_ULTRA = _GUIDANCE_FULL + """

When a shorter synonym or loanword is unambiguous and equally clear, prefer it over a longer native phrase \
purely to reduce output length (this trades a small amount of stylistic purity for token savings — use judgment, \
don't sacrifice clarity)."""

_LEVELS = {"lite": _GUIDANCE_LITE, "full": _GUIDANCE_FULL, "ultra": _GUIDANCE_ULTRA}

_CJK_NOTE = (
    "\n\nThis conversation is in a CJK language, where common tokenizers spend "
    "meaningfully more tokens per character than for English — prioritize trimming "
    "verbosity here specifically."
)


def get_style_guidance(level: str = "lite", language: str | None = None) -> str:
    """Returns the guidance block for *level* (invalid values fall back to "lite"),
    with a CJK-specific note appended if *language* (an ISO 639-3 code) is
    zho/jpn/kor."""
    guidance = _LEVELS.get((level or "lite").lower(), _GUIDANCE_LITE)
    if (language or "").lower() in _CJK_LANGUAGES:
        guidance += _CJK_NOTE
    return guidance
