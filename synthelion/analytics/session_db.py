# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""ChromaDB-backed cross-session memory.

Mirrors tokensave's record_decision / session_recall pattern using ChromaDB
for semantic (vector) recall instead of FTS5.

ChromaDB is an *optional* dependency — install with:
    pip install 'synthelion[chromadb]'

If chromadb is not installed the module falls back to lexical search (cosine
bag-of-words), keeping the same public API.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


_DEFAULT_DIR = Path.home() / ".synthelion" / "sessions"
_COLLECTION_NAME = "synthelion_decisions"


def _now_ts() -> float:
    return time.time()


class SessionDB:
    """Persistent cross-session memory for AI agents.

    Stores decisions / context notes and recalls them by semantic similarity
    (ChromaDB embeddings) or falls back to lexical cosine similarity.

    Parameters
    ----------
    directory:
        Root directory for the ChromaDB on-disk store.
        Defaults to ``~/.synthelion/sessions/``.
    """

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory or _DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._collection: Any = None
        self._fallback_records: list[dict] = []
        self._fallback_file = self._dir / "decisions_fallback.json"
        self._use_chroma = False
        self._session_id = str(uuid.uuid4())
        self._session_start_ts: float = _now_ts()
        self._init_store()

    # ── init ─────────────────────────────────────────────────────────────────

    def _init_store(self) -> None:
        try:
            import chromadb  # type: ignore[import]
            client = chromadb.PersistentClient(path=str(self._dir))
            self._collection = client.get_or_create_collection(
                name=_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            self._use_chroma = True
        except Exception:
            self._use_chroma = False
            self._fallback_records = self._load_fallback()

    # ── public API ───────────────────────────────────────────────────────────

    def record_decision(
        self,
        text: str,
        reason: str = "",
        tags: list[str] | None = None,
        files: list[str] | None = None,
    ) -> str:
        """Save a decision/context note and return its ID."""
        decision_id = str(uuid.uuid4())
        metadata: dict[str, Any] = {
            "reason": reason or "",
            "tags": json.dumps(tags or []),
            "files": json.dumps(files or []),
            "ts": _now_ts(),
            "session_id": self._session_id,
        }
        if self._use_chroma and self._collection is not None:
            self._collection.add(
                documents=[text],
                metadatas=[metadata],
                ids=[decision_id],
            )
        else:
            self._fallback_records.append({"id": decision_id, "text": text, **metadata})
            self._save_fallback()
        return decision_id

    def session_recall(
        self,
        query: str | None = None,
        since: float | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Recall decisions matching *query* (semantic or lexical)."""
        limit = max(1, min(limit, 200))

        if self._use_chroma and self._collection is not None:
            return self._chroma_recall(query, since, limit)
        return self._fallback_recall(query, since, limit)

    def list_decisions(self, limit: int = 50) -> list[dict]:
        """Return the most recent *limit* decisions."""
        if self._use_chroma and self._collection is not None:
            result = self._collection.get(limit=limit, include=["documents", "metadatas"])
            return self._format_chroma_result(result)
        recent = sorted(self._fallback_records, key=lambda r: r.get("ts", 0), reverse=True)
        return recent[:limit]

    def session_start(self) -> dict:
        """Mark the start of a new session and return session info."""
        self._session_id = str(uuid.uuid4())
        self._session_start_ts = _now_ts()
        return {"session_id": self._session_id, "started_at": self._session_start_ts}

    def session_end(self) -> dict:
        """Mark the end of a session and return a brief summary."""
        elapsed = _now_ts() - self._session_start_ts
        count = self._count_session_decisions()
        return {
            "session_id": self._session_id,
            "elapsed_seconds": round(elapsed, 1),
            "decisions_recorded": count,
        }

    def backend(self) -> str:
        return "chromadb" if self._use_chroma else "lexical"

    # ── internal ─────────────────────────────────────────────────────────────

    def _chroma_recall(self, query: str | None, since: float | None, limit: int) -> list[dict]:
        assert self._collection is not None
        try:
            if query:
                result = self._collection.query(
                    query_texts=[query],
                    n_results=min(limit, max(1, self._collection.count())),
                    include=["documents", "metadatas", "distances"],
                )
                items = self._format_chroma_query_result(result)
            else:
                result = self._collection.get(
                    limit=limit,
                    include=["documents", "metadatas"],
                )
                items = self._format_chroma_result(result)
        except Exception:
            return []

        if since is not None:
            items = [i for i in items if i.get("ts", 0) >= since]
        return items[:limit]

    def _fallback_recall(self, query: str | None, since: float | None, limit: int) -> list[dict]:
        from collections import Counter
        import re

        records = self._fallback_records
        if since is not None:
            records = [r for r in records if r.get("ts", 0) >= since]

        if not query:
            recent = sorted(records, key=lambda r: r.get("ts", 0), reverse=True)
            return recent[:limit]

        def _bag(t: str) -> Counter:
            return Counter(re.findall(r"\b\w{3,}\b", t.lower()))

        def _cosine(a: Counter, b: Counter) -> float:
            if not a or not b:
                return 0.0
            dot = sum(a[w] * b[w] for w in a if w in b)
            na = sum(v * v for v in a.values()) ** 0.5
            nb = sum(v * v for v in b.values()) ** 0.5
            return dot / (na * nb) if na and nb else 0.0

        qbag = _bag(query)
        scored = [(r, _cosine(qbag, _bag(r.get("text", "")))) for r in records]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [r for r, s in scored[:limit] if s > 0]

    def _count_session_decisions(self) -> int:
        if self._use_chroma and self._collection is not None:
            try:
                result = self._collection.get(where={"session_id": self._session_id})
                return len(result.get("ids", []))
            except Exception:
                return 0
        return sum(1 for r in self._fallback_records if r.get("session_id") == self._session_id)

    @staticmethod
    def _format_chroma_result(result: dict) -> list[dict]:
        ids = result.get("ids", [])
        docs = result.get("documents", [])
        metas = result.get("metadatas", [])
        out = []
        for i, doc_id in enumerate(ids):
            meta = metas[i] if i < len(metas) else {}
            out.append({
                "id": doc_id,
                "text": docs[i] if i < len(docs) else "",
                **meta,
            })
        return out

    @staticmethod
    def _format_chroma_query_result(result: dict) -> list[dict]:
        out = []
        ids_list = result.get("ids", [[]])[0]
        docs_list = result.get("documents", [[]])[0]
        metas_list = result.get("metadatas", [[]])[0]
        dists_list = result.get("distances", [[]])[0]
        for i, doc_id in enumerate(ids_list):
            meta = metas_list[i] if i < len(metas_list) else {}
            dist = dists_list[i] if i < len(dists_list) else None
            out.append({
                "id": doc_id,
                "text": docs_list[i] if i < len(docs_list) else "",
                "distance": dist,
                **meta,
            })
        return out

    def _load_fallback(self) -> list[dict]:
        if not self._fallback_file.exists():
            return []
        try:
            data = json.loads(self._fallback_file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _save_fallback(self) -> None:
        self._fallback_file.write_text(
            json.dumps(self._fallback_records, ensure_ascii=False),
            encoding="utf-8",
        )


# Module-level singleton
_db: SessionDB | None = None
_db_lock = __import__("threading").Lock()


def get_session_db() -> SessionDB:
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:
                _db = SessionDB()
    return _db
