# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re
import unicodedata

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")


class TextSplitter:
    """Unicode-aware tokenizer that splits text by character category.

    Ported from C# CavemanTextSplitter. Handles Latin, CJK, Arabic,
    Devanagari, Emoji, and more without regex dependency on Unicode property escapes.
    """

    def extract_words(self, text: str) -> list[str]:
        return _WORD_RE.findall(text)

    def parse_text(self, text: str) -> list[dict]:
        """Return list of {text, type} tokens with type classification."""
        tokens = []
        i = 0
        while i < len(text):
            ch = text[i]

            # URL
            m = _URL_RE.match(text, i)
            if m:
                tokens.append({"text": m.group(), "type": "URL"})
                i = m.end()
                continue

            # Email
            m = _EMAIL_RE.match(text, i)
            if m:
                tokens.append({"text": m.group(), "type": "Email"})
                i = m.end()
                continue

            # Number
            m = _NUMBER_RE.match(text, i)
            if m:
                tokens.append({"text": m.group(), "type": "Number"})
                i = m.end()
                continue

            cat = unicodedata.category(ch)

            if cat.startswith("L") or cat.startswith("M"):
                # Collect full word
                j = i + 1
                while j < len(text):
                    c2 = text[j]
                    cat2 = unicodedata.category(c2)
                    if cat2.startswith("L") or cat2.startswith("M") or c2 == "'":
                        j += 1
                    else:
                        break
                tokens.append({"text": text[i:j], "type": "Word"})
                i = j
                continue

            if cat == "Zs" or ch in (" ", "\t"):
                tokens.append({"text": ch, "type": "Whitespace"})
                i += 1
                continue

            if ch == "\n":
                tokens.append({"text": ch, "type": "Newline"})
                i += 1
                continue

            if cat.startswith("P") or cat.startswith("S"):
                tokens.append({"text": ch, "type": "Punctuation"})
                i += 1
                continue

            if cat.startswith("So") or ord(ch) > 0x1F600:
                tokens.append({"text": ch, "type": "Emoji"})
                i += 1
                continue

            tokens.append({"text": ch, "type": "Other"})
            i += 1

        return tokens
