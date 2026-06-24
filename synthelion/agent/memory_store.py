# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import json
import re
from collections import Counter


def _bag(text: str) -> Counter:
    words = re.findall(r"\b\w{3,}\b", text.lower())
    return Counter(words)


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[w] * b[w] for w in a if w in b)
    norm_a = sum(v * v for v in a.values()) ** 0.5
    norm_b = sum(v * v for v in b.values()) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class MemoryStore:
    """Append-only long-term memory with embedding-free relevance recall.

    Ported from C# CavemanMemoryStore. Stores {summary, keywords} notes
    and scores them by lexical TF-IDF cosine similarity for recall.
    """

    def __init__(self) -> None:
        self._notes: list[dict] = []

    def remember(self, note: dict) -> None:
        """Add a memory note. Expected keys: summary (str), keywords (list[str])."""
        self._notes.append(note)

    def recall(self, query: str, top_k: int = 3) -> list[dict]:
        """Return top_k most relevant notes for the query."""
        if not self._notes or not query.strip():
            return []
        qbag = _bag(query)
        scored = []
        for note in self._notes:
            text = note.get("summary", "") + " " + " ".join(note.get("keywords", []))
            score = _cosine(qbag, _bag(text))
            if score > 0:
                scored.append((score, note))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [n for _, n in scored[:top_k]]

    def clear(self) -> None:
        self._notes.clear()

    def save(self) -> str:
        return json.dumps(self._notes, ensure_ascii=False)

    def load(self, json_str: str) -> None:
        self._notes = json.loads(json_str)

    def __len__(self) -> int:
        return len(self._notes)
