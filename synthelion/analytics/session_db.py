# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""ChromaDB/Qdrant-backed cross-session memory (RAG).

Mirrors tokensave's record_decision / session_recall pattern using a vector
store for semantic-ish recall instead of FTS5.

Backend is selected by `backend` ("chromadb" | "qdrant" | "lexical", default
"chromadb" — see synthelion.config for the JSON config knob). Both vector
backends are *optional* dependencies:
    pip install 'synthelion[chromadb]'
    pip install 'synthelion[qdrant]'
If the selected backend's package is not installed, or "lexical" is chosen
explicitly, the module falls back to lexical search (cosine bag-of-words over
the same JSONL log every backend appends to), keeping the same public API.

Note on Qdrant vectors: Synthelion ships with zero ML models (see the package
description) — ChromaDB's default collection embeds text with its own bundled
sentence-transformer, but pulling in an embedding model here just for Qdrant
would mean a multi-hundred-MB PyTorch dependency for a "zero ML" library. The
Qdrant backend instead stores a deterministic hashed bag-of-words vector (see
_hash_vector) — the same lexical scoring the fallback already does, just
indexed in Qdrant for fast, distributed, remote-capable similarity search
across a cluster. It is not semantic embedding search; if you need that,
point ChromaDB's collection at your own embedding function, or use Qdrant
with vectors you compute yourself upstream.

Concurrency model (fallback / lexical backend): built for many concurrent MCP
server processes — one per agent session, as happens behind an AI provider
serving lots of parallel requests. Each decision is appended to a JSONL file
with a single atomic os.write() (O_APPEND) — no read-modify-write, no
cross-process lock. Reads (recall/list) always re-scan the file from disk
instead of trusting an in-memory cache, so a session immediately sees
decisions written by other concurrent sessions. ChromaDB/Qdrant themselves
already handle concurrent writers internally when that backend is active.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from synthelion.analytics._atomic_append import append_line

_COLLECTION_NAME = "synthelion_decisions"
_FALLBACK_FILE = "decisions_fallback.jsonl"
_LEGACY_FALLBACK_FILE = "decisions_fallback.json"
_HASH_VECTOR_DIM = 256


def _hash_vector(text: str, dim: int = _HASH_VECTOR_DIM) -> list[float]:
    """Deterministic hashed bag-of-words vector (feature hashing) — no ML model,
    no external embedding call. Uses the same stable FNV-1a hash as
    synthelion.simhash: Python's built-in hash() is randomised per *process*
    (PYTHONHASHSEED) for strings, which would make the same word land in a
    different bucket on every node — breaking cross-node similarity search
    before it even starts. Words that hash to the same bucket collide (a
    known, accepted trade-off of feature hashing at this dimensionality), but
    two texts sharing vocabulary still land close in cosine distance, which is
    all Qdrant's ANN index needs for "find similar decisions" recall."""
    import math
    import re

    from synthelion.simhash import _fnv1a64

    vec = [0.0] * dim
    for word in re.findall(r"\w+", text.lower()):
        vec[_fnv1a64(word) % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm > 0 else vec


def _now_ts() -> float:
    return time.time()


def _append_json_line(path: Path, obj: dict) -> None:
    append_line(path, (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))


def _migrate_legacy(path: Path) -> None:
    legacy = path.with_name(_LEGACY_FALLBACK_FILE)
    if path.exists() or not legacy.exists():
        return
    try:
        records = json.loads(legacy.read_text(encoding="utf-8"))
        if isinstance(records, list):
            with open(path, "a", encoding="utf-8") as fh:
                for r in records:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        legacy.rename(legacy.with_suffix(".json.migrated"))
    except (OSError, json.JSONDecodeError):
        pass


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

    def __init__(self, directory: Path | None = None, backend: str | None = None) -> None:
        """`backend`: "chromadb" | "qdrant" | "lexical". Defaults to reading
        `vector_store.backend` from synthelion.config (itself defaulting to
        "chromadb") when not given explicitly."""
        # Path.home() re-read here, not cached at module import time — see the
        # equivalent comment/incident in synthelion/analytics/ledger.py.
        self._dir = directory or (Path.home() / ".synthelion" / "sessions")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._collection: Any = None
        self._qdrant: Any = None
        self._qdrant_collection_name = _COLLECTION_NAME
        self._fallback_file = self._dir / _FALLBACK_FILE
        self._backend = "lexical"
        self._requested_backend = backend
        self._session_id = str(uuid.uuid4())
        self._session_start_ts: float = _now_ts()
        self._session_decision_count = 0
        self._init_store()

    # ── init ─────────────────────────────────────────────────────────────────

    def _init_store(self) -> None:
        requested = self._requested_backend
        if requested is None:
            try:
                from synthelion.config import load_config
                requested = load_config().get("vector_store", {}).get("backend", "chromadb")
            except Exception:
                requested = "chromadb"

        if requested == "lexical":
            self._backend = "lexical"
            _migrate_legacy(self._fallback_file)
            return

        if requested == "qdrant":
            if self._init_qdrant():
                self._backend = "qdrant"
                return
            _migrate_legacy(self._fallback_file)
            return

        # default / "chromadb"
        if self._init_chromadb():
            self._backend = "chromadb"
            return
        self._backend = "lexical"
        _migrate_legacy(self._fallback_file)

    def _init_chromadb(self) -> bool:
        try:
            import chromadb  # type: ignore[import]
            client = chromadb.PersistentClient(path=str(self._dir))
            self._collection = client.get_or_create_collection(
                name=_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            return True
        except Exception:
            return False

    def _init_qdrant(self) -> bool:
        try:
            from qdrant_client import QdrantClient  # type: ignore[import]
            from qdrant_client.models import Distance, VectorParams  # type: ignore[import]

            cfg = {}
            try:
                from synthelion.config import load_config
                cfg = load_config().get("vector_store", {}).get("qdrant", {})
            except Exception:
                pass

            url = cfg.get("url", "http://localhost:6333")
            api_key = cfg.get("api_key")
            self._qdrant_collection_name = cfg.get("collection", _COLLECTION_NAME)
            self._qdrant = QdrantClient(url=url, api_key=api_key)

            existing = {c.name for c in self._qdrant.get_collections().collections}
            if self._qdrant_collection_name not in existing:
                self._qdrant.create_collection(
                    collection_name=self._qdrant_collection_name,
                    vectors_config=VectorParams(size=_HASH_VECTOR_DIM, distance=Distance.COSINE),
                )
            return True
        except Exception:
            return False

    # ── public API ───────────────────────────────────────────────────────────

    def record_decision(
        self,
        text: str,
        reason: str = "",
        tags: list[str] | None = None,
        files: list[str] | None = None,
    ) -> str:
        """Save a decision/context note and return its ID.

        `text` is scanned for credential-shaped content (`sensitive_guard`) before
        it touches any backend — a decision an agent asks to persist could easily
        be "we set AWS_SECRET_ACCESS_KEY=..." pasted from a terminal, and this is
        the only path in Synthelion that writes arbitrary agent-supplied text to
        disk indefinitely (unlike `CcrStore`, which is in-memory with a 5-minute
        TTL). A hit redacts `text` to a placeholder rather than raising — the
        calling tool still gets a normal decision_id back, degrading gracefully
        the same way a backend error already does below.
        """
        from synthelion.sensitive_guard import find_sensitive
        sensitive_class = find_sensitive(text)
        if sensitive_class is not None:
            text = f"[REDACTED: possible {sensitive_class} detected — not persisted verbatim]"

        decision_id = str(uuid.uuid4())
        metadata: dict[str, Any] = {
            "reason": reason or "",
            "tags": json.dumps(tags or []),
            "files": json.dumps(files or []),
            "ts": _now_ts(),
            "session_id": self._session_id,
        }
        if self._backend == "chromadb" and self._collection is not None:
            try:
                self._collection.add(documents=[text], metadatas=[metadata], ids=[decision_id])
            except Exception:
                return decision_id  # degrade gracefully rather than crash the calling tool
        elif self._backend == "qdrant" and self._qdrant is not None:
            try:
                from qdrant_client.models import PointStruct  # type: ignore[import]
                self._qdrant.upsert(
                    collection_name=self._qdrant_collection_name,
                    points=[PointStruct(id=decision_id, vector=_hash_vector(text), payload={"text": text, **metadata})],
                )
            except Exception:
                return decision_id
        else:
            _append_json_line(self._fallback_file, {"id": decision_id, "text": text, **metadata})
        self._session_decision_count += 1
        return decision_id

    def session_recall(
        self,
        query: str | None = None,
        since: float | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Recall decisions matching *query* (vector or lexical similarity)."""
        limit = max(1, min(limit, 200))

        if self._backend == "chromadb" and self._collection is not None:
            return self._chroma_recall(query, since, limit)
        if self._backend == "qdrant" and self._qdrant is not None:
            return self._qdrant_recall(query, since, limit)
        return self._fallback_recall(query, since, limit)

    def list_decisions(self, limit: int = 50) -> list[dict]:
        """Return the most recent *limit* decisions."""
        if self._backend == "chromadb" and self._collection is not None:
            try:
                result = self._collection.get(limit=limit, include=["documents", "metadatas"])
                return self._format_chroma_result(result)
            except Exception:
                return []
        if self._backend == "qdrant" and self._qdrant is not None:
            return self._qdrant_recall(None, None, limit)
        recent = sorted(self._load_fallback(), key=lambda r: r.get("ts", 0), reverse=True)
        return recent[:limit]

    def session_start(self) -> dict:
        """Mark the start of a new session and return session info."""
        self._session_id = str(uuid.uuid4())
        self._session_start_ts = _now_ts()
        self._session_decision_count = 0
        return {"session_id": self._session_id, "started_at": self._session_start_ts}

    def session_end(self) -> dict:
        """Mark the end of a session and return a brief summary."""
        elapsed = _now_ts() - self._session_start_ts
        return {
            "session_id": self._session_id,
            "elapsed_seconds": round(elapsed, 1),
            "decisions_recorded": self._session_decision_count,
        }

    def backend(self) -> str:
        return self._backend

    def prune_older_than(self, days: int) -> int:
        """Deletes decisions older than *days*. Returns the number removed.

        Fully supported for the lexical/fallback JSONL store (read-all/rewrite-all,
        same trade-off as SavingsLedger.prune_older_than — not safe to run
        concurrently with writers, fine for a manual/scheduled cleanup action).
        For chromadb/qdrant, delegates to that backend's own filtered delete; if it
        raises, the caller sees a clear error instead of a silent no-op.
        """
        cutoff = _now_ts() - days * 86400
        if self._backend == "chromadb" and self._collection is not None:
            existing = self._collection.get(include=["metadatas"])
            ids = existing.get("ids", []) or []
            metas = existing.get("metadatas", []) or []
            stale = [i for i, m in zip(ids, metas) if (m or {}).get("ts", 0) < cutoff]
            if stale:
                self._collection.delete(ids=stale)
            return len(stale)
        if self._backend == "qdrant" and self._qdrant is not None:
            from qdrant_client.models import FieldCondition, Filter, Range
            before = self._qdrant.count(collection_name=self._qdrant_collection_name).count
            self._qdrant.delete(
                collection_name=self._qdrant_collection_name,
                points_selector=Filter(must=[FieldCondition(key="ts", range=Range(lt=cutoff))]),
            )
            after = self._qdrant.count(collection_name=self._qdrant_collection_name).count
            return before - after
        kept, removed = [], 0
        for d in self._load_fallback():
            if (d.get("ts", 0) or 0) < cutoff:
                removed += 1
            else:
                kept.append(d)
        self._write_fallback(kept)
        return removed

    def _write_fallback(self, decisions: list[dict]) -> None:
        tmp = self._fallback_file.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for d in decisions:
                fh.write(json.dumps(d, ensure_ascii=False) + "\n")
        import os
        os.replace(tmp, self._fallback_file)

    # ── internal ─────────────────────────────────────────────────────────────

    def _qdrant_recall(self, query: str | None, since: float | None, limit: int) -> list[dict]:
        assert self._qdrant is not None
        try:
            if query:
                result = self._qdrant.query_points(
                    collection_name=self._qdrant_collection_name,
                    query=_hash_vector(query),
                    limit=limit,
                    with_payload=True,
                )
                points = result.points
                items = []
                for p in points:
                    payload = dict(p.payload or {})
                    text = payload.pop("text", "")
                    items.append({"id": str(p.id), "text": text, "distance": 1.0 - p.score, **payload})
            else:
                points, _ = self._qdrant.scroll(
                    collection_name=self._qdrant_collection_name,
                    limit=limit,
                    with_payload=True,
                )
                items = []
                for p in points:
                    payload = dict(p.payload or {})
                    text = payload.pop("text", "")
                    items.append({"id": str(p.id), "text": text, **payload})
        except Exception:
            return []

        if since is not None:
            items = [i for i in items if i.get("ts", 0) >= since]
        return items[:limit]

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

        records = self._load_fallback()
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
        records: list[dict] = []
        try:
            with open(self._fallback_file, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []
        return records


# Module-level singleton. The lock only guards this process's first-init race
# (e.g. two threads from the same asyncio.to_thread pool) — it never touches
# other processes or files, so it does not limit cross-session concurrency.
_db: SessionDB | None = None
_db_lock = __import__("threading").Lock()


def get_session_db() -> SessionDB:
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:
                _db = SessionDB()
    return _db
