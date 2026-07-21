# Tests for Synthelion analytics, session DB, RAG agent, and integrations
# (https://github.com/francescopaolopassaro/caveman)
"""
Coverage targets:
  - synthelion/analytics/ledger.py
  - synthelion/analytics/session_db.py
  - synthelion/agent/rag_agent.py
  - synthelion/integrations/claude_adapter.py  (mocked anthropic)
  - synthelion/integrations/openai_adapter.py  (mocked openai)
  - synthelion/plugins/openai_tools.py          (new session / status tools)
  - synthelion/cli.py                            (status, gain, bench commands)
"""
from __future__ import annotations

import json
import sys
import time
import threading
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 16. SavingsLedger
# ---------------------------------------------------------------------------
class TestSavingsLedger:
    """Tests for synthelion.analytics.ledger.SavingsLedger."""

    @pytest.fixture()
    def ledger(self, tmp_path):
        from synthelion.analytics.ledger import SavingsLedger
        return SavingsLedger(directory=tmp_path)

    def test_record_and_all_records(self, ledger):
        ledger.record("compress", 100, 60)
        records = ledger.all_records()
        assert len(records) == 1
        assert records[0]["tool"] == "compress"
        assert records[0]["tokens_before"] == 100
        assert records[0]["tokens_after"] == 60
        assert records[0]["tokens_saved"] == 40

    def test_multiple_records_accumulated(self, ledger):
        ledger.record("compress", 100, 60)
        ledger.record("route_content", 200, 120, content_type="JsonArray")
        ledger.record("summarize", 500, 200)
        assert len(ledger.all_records()) == 3

    def test_content_type_stored(self, ledger):
        ledger.record("route_content", 100, 50, content_type="Code")
        r = ledger.all_records()[0]
        assert r["content_type"] == "Code"

    def test_language_stored(self, ledger):
        ledger.record("compress", 100, 70, language="ita")
        r = ledger.all_records()[0]
        assert r["language"] == "ita"

    def test_summary_empty(self, ledger):
        s = ledger.summary()
        assert s["total_calls"] == 0
        assert s["tokens_saved"] == 0
        assert s["avg_efficiency_pct"] == 0.0

    def test_summary_with_records(self, ledger):
        ledger.record("compress", 100, 60)      # saved 40
        ledger.record("compress", 200, 100)     # saved 100
        s = ledger.summary()
        assert s["total_calls"] == 2
        assert s["tokens_before"] == 300
        assert s["tokens_after"] == 160
        assert s["tokens_saved"] == 140
        assert s["avg_efficiency_pct"] > 0
        assert "compress" in s["by_tool"]

    def test_summary_by_content_type(self, ledger):
        ledger.record("route_content", 100, 50, content_type="Code")
        ledger.record("route_content", 200, 100, content_type="PlainText")
        s = ledger.summary()
        assert "Code" in s["by_content_type"]
        assert "PlainText" in s["by_content_type"]

    def test_summary_with_unknown_content_type(self, ledger):
        ledger.record("compress", 100, 60)
        s = ledger.summary()
        assert "unknown" in s["by_content_type"] or "" in s["by_content_type"]

    def test_records_since_filters_old(self, ledger):
        ledger.record("compress", 100, 60)
        # All records are recent (just created), should be included
        recent = ledger.records_since(1)
        assert len(recent) == 1

    def test_records_since_excludes_future(self, ledger, tmp_path):
        from synthelion.analytics.ledger import SavingsLedger
        import datetime, json
        # Manually write an old record
        old_ts = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=100)).isoformat()
        raw = [{"ts": old_ts, "tool": "compress", "tokens_before": 100, "tokens_after": 60, "tokens_saved": 40, "content_type": "", "language": ""}]
        (tmp_path / "savings.json").write_text(json.dumps(raw), encoding="utf-8")
        ledger2 = SavingsLedger(directory=tmp_path)
        recent = ledger2.records_since(7)
        assert len(recent) == 0

    def test_reset_clears_all(self, ledger):
        ledger.record("compress", 100, 60)
        ledger.record("compress", 100, 60)
        ledger.reset()
        assert ledger.all_records() == []

    def test_prune_older_than_removes_old_records(self, ledger, tmp_path):
        import datetime
        old_ts = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=40)).isoformat()
        ledger._write_all([{
            "ts": old_ts, "tool": "compress", "tokens_before": 100, "tokens_after": 60,
            "tokens_saved": 40, "content_type": "", "language": "", "session_id": "old", "pid": 1,
        }])
        ledger.record("compress", 100, 60)  # fresh record
        removed = ledger.prune_older_than(30)
        assert removed == 1
        remaining = ledger.all_records()
        assert len(remaining) == 1
        assert remaining[0]["session_id"] != "old"

    def test_prune_older_than_keeps_records_without_ts(self, ledger):
        ledger._write_all([{"tool": "compress", "tokens_before": 100, "tokens_after": 60}])
        removed = ledger.prune_older_than(1)
        assert removed == 0
        assert len(ledger.all_records()) == 1

    def test_delete_session_removes_only_that_session(self, ledger):
        ledger.record("compress", 100, 60)
        records = ledger.all_records()
        target_session = records[0]["session_id"]
        ledger._write_all(records + [{
            "ts": records[0]["ts"], "tool": "compress", "tokens_before": 10, "tokens_after": 5,
            "tokens_saved": 5, "content_type": "", "language": "", "session_id": "other-session", "pid": 2,
        }])
        removed = ledger.delete_session(target_session)
        assert removed == 1
        remaining = ledger.all_records()
        assert len(remaining) == 1
        assert remaining[0]["session_id"] == "other-session"

    def test_delete_session_unknown_id_removes_nothing(self, ledger):
        ledger.record("compress", 100, 60)
        removed = ledger.delete_session("does-not-exist")
        assert removed == 0
        assert len(ledger.all_records()) == 1

    def test_persists_to_disk_and_reloads(self, tmp_path):
        from synthelion.analytics.ledger import SavingsLedger
        l1 = SavingsLedger(directory=tmp_path)
        l1.record("compress", 100, 50)
        l2 = SavingsLedger(directory=tmp_path)
        assert len(l2.all_records()) == 1

    def test_thread_safety(self, tmp_path):
        from synthelion.analytics.ledger import SavingsLedger
        ledger = SavingsLedger(directory=tmp_path)
        errors = []

        def worker():
            try:
                for _ in range(5):
                    ledger.record("compress", 100, 60)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(ledger.all_records()) == 20

    def test_corrupted_file_returns_empty(self, tmp_path):
        from synthelion.analytics.ledger import SavingsLedger
        (tmp_path / "savings.json").write_text("NOT JSON {{{", encoding="utf-8")
        ledger = SavingsLedger(directory=tmp_path)
        assert ledger.all_records() == []

    def test_non_list_json_returns_empty(self, tmp_path):
        from synthelion.analytics.ledger import SavingsLedger
        (tmp_path / "savings.json").write_text('{"key": "value"}', encoding="utf-8")
        ledger = SavingsLedger(directory=tmp_path)
        assert ledger.all_records() == []

    def test_records_since_with_invalid_ts(self, tmp_path):
        from synthelion.analytics.ledger import SavingsLedger
        raw = [{"ts": "NOT_A_DATE", "tool": "compress", "tokens_before": 100, "tokens_after": 60, "tokens_saved": 40}]
        (tmp_path / "savings.json").write_text(json.dumps(raw), encoding="utf-8")
        ledger = SavingsLedger(directory=tmp_path)
        # Invalid timestamp records are skipped
        assert ledger.records_since(30) == []

    def test_get_ledger_singleton(self, tmp_path):
        from synthelion.analytics import ledger as ledger_mod
        # Reset singleton to ensure isolation
        orig = ledger_mod._ledger
        ledger_mod._ledger = None
        try:
            l1 = ledger_mod.get_ledger()
            l2 = ledger_mod.get_ledger()
            assert l1 is l2
        finally:
            ledger_mod._ledger = orig

    def test_summary_provided_records(self, ledger):
        records = [
            {"tokens_before": 100, "tokens_after": 50, "tokens_saved": 50, "tool": "compress", "content_type": "Code"},
        ]
        s = ledger.summary(records=records)
        assert s["total_calls"] == 1
        assert s["tokens_saved"] == 50


# ---------------------------------------------------------------------------
# 17. SessionDB (fallback mode — no chromadb)
# ---------------------------------------------------------------------------
class TestSessionDB:
    """Tests for synthelion.analytics.session_db.SessionDB in fallback mode."""

    @pytest.fixture()
    def db(self, tmp_path):
        from synthelion.analytics.session_db import SessionDB
        # Force fallback mode by patching chromadb import
        with patch.dict("sys.modules", {"chromadb": None}):
            db = SessionDB(directory=tmp_path)
        return db

    def test_record_and_recall_lexical(self, db):
        db.record_decision("We use JWT for authentication", reason="stateless")
        results = db.session_recall(query="authentication JWT")
        assert len(results) >= 1
        assert "JWT" in results[0]["text"]

    def test_record_returns_id(self, db):
        decision_id = db.record_decision("Test decision")
        assert isinstance(decision_id, str)
        assert len(decision_id) > 0

    def test_record_with_tags_and_files(self, db):
        db.record_decision("Decision A", reason="r", tags=["t1", "t2"], files=["a.py"])
        results = db.session_recall(query="Decision A")
        assert results[0]["reason"] == "r"

    def test_record_decision_redacts_aws_key(self, db):
        decision_id = db.record_decision("Rotated key: AKIAIOSFODNN7EXAMPLE for the deploy user")
        assert isinstance(decision_id, str)
        stored = db.list_decisions(limit=10)[0]
        assert "AKIAIOSFODNN7EXAMPLE" not in stored["text"]
        assert "REDACTED" in stored["text"]
        assert "aws-access-key" in stored["text"]

    def test_record_decision_redacts_private_key(self, db):
        secret = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
        db.record_decision(secret)
        stored = db.list_decisions(limit=10)[0]
        assert "MIIEow" not in stored["text"]
        assert "REDACTED" in stored["text"]

    def test_record_decision_redaction_not_on_disk(self, db):
        db.record_decision("token: ghp_abcdefghijklmnopqrstuvwxyzABCDEF")
        raw = db._fallback_file.read_text(encoding="utf-8")
        assert "ghp_abcdefghijklmnopqrstuvwxyzABCDEF" not in raw

    def test_record_decision_ordinary_text_not_redacted(self, db):
        db.record_decision("We use JWT for authentication", reason="stateless")
        stored = db.list_decisions(limit=10)[0]
        assert stored["text"] == "We use JWT for authentication"

    def test_record_decision_redaction_still_returns_normal_id(self, db):
        decision_id = db.record_decision("AKIAIOSFODNN7EXAMPLE")
        assert isinstance(decision_id, str) and len(decision_id) > 0
        # metadata (reason/tags/files) is still recorded normally alongside the redaction
        db2_id = db.record_decision("AKIAIOSFODNN7EXAMPLE", reason="leaked key", tags=["security"])
        stored = [d for d in db.list_decisions(limit=10) if d["id"] == db2_id][0]
        assert stored["reason"] == "leaked key"

    def test_recall_no_query_returns_recent(self, db):
        db.record_decision("First decision")
        db.record_decision("Second decision")
        results = db.session_recall(limit=5)
        assert len(results) == 2

    def test_recall_with_since_filters(self, db):
        db.record_decision("Old decision")
        future_ts = time.time() + 10000
        results = db.session_recall(since=future_ts)
        assert len(results) == 0

    def test_recall_limit_respected(self, db):
        for i in range(10):
            db.record_decision(f"Decision {i}")
        results = db.session_recall(limit=3)
        assert len(results) <= 3

    def test_list_decisions(self, db):
        db.record_decision("A")
        db.record_decision("B")
        decisions = db.list_decisions(limit=10)
        assert len(decisions) == 2

    def test_session_start_returns_id(self, db):
        info = db.session_start()
        assert "session_id" in info
        assert "started_at" in info

    def test_session_end_returns_summary(self, db):
        db.session_start()
        db.record_decision("Decision during session")
        info = db.session_end()
        assert "session_id" in info
        assert "elapsed_seconds" in info
        assert "decisions_recorded" in info

    def test_backend_returns_lexical(self, db):
        assert db.backend() == "lexical"

    def test_prune_older_than_removes_old_decisions(self, db):
        db.record_decision("Old decision")
        old_ts = time.time() - 40 * 86400
        decisions = db._load_fallback()
        decisions[0]["ts"] = old_ts
        db._write_fallback(decisions)
        db.record_decision("Fresh decision")

        removed = db.prune_older_than(30)
        assert removed == 1
        remaining = db.list_decisions(limit=10)
        assert len(remaining) == 1
        assert remaining[0]["text"] == "Fresh decision"

    def test_prune_older_than_nothing_to_remove(self, db):
        db.record_decision("Fresh decision")
        removed = db.prune_older_than(30)
        assert removed == 0
        assert len(db.list_decisions(limit=10)) == 1

    def test_fallback_persists_to_disk(self, tmp_path):
        from synthelion.analytics.session_db import SessionDB
        with patch.dict("sys.modules", {"chromadb": None}):
            db1 = SessionDB(directory=tmp_path)
            db1.record_decision("Persistent decision")
            db2 = SessionDB(directory=tmp_path)
        # db2 never saw db1's write at init time — reads must come fresh from disk
        # every call (append-only JSONL, no in-memory cache to go stale).
        assert len(db2.list_decisions()) == 1

    def test_get_session_db_singleton(self):
        from synthelion.analytics import session_db as sdb_mod
        orig = sdb_mod._db
        sdb_mod._db = None
        try:
            db1 = sdb_mod.get_session_db()
            db2 = sdb_mod.get_session_db()
            assert db1 is db2
        finally:
            sdb_mod._db = orig

    def test_recall_zero_score_excluded(self, db):
        db.record_decision("completely unrelated topic xyz abc")
        # Query that shares zero words
        results = db.session_recall(query="999 zzz mmm", limit=5)
        # All zero-score results should be excluded
        assert len(results) == 0

    def test_corrupted_fallback_file(self, tmp_path):
        from synthelion.analytics.session_db import SessionDB
        # Legacy (pre-JSONL) format file with unparseable content.
        (tmp_path / "decisions_fallback.json").write_text("NOT JSON", encoding="utf-8")
        with patch.dict("sys.modules", {"chromadb": None}):
            db = SessionDB(directory=tmp_path)
        assert db.list_decisions() == []


# ---------------------------------------------------------------------------
# 18. SessionDB with ChromaDB mock
# ---------------------------------------------------------------------------
class TestSessionDBChromaMock:
    """Tests that verify the ChromaDB code path using a mock."""

    @pytest.fixture()
    def db(self, tmp_path):
        from synthelion.analytics.session_db import SessionDB

        mock_collection = MagicMock()
        mock_collection.count.return_value = 1
        mock_collection.query.return_value = {
            "ids": [["id1"]],
            "documents": [["some decision text"]],
            "metadatas": [[{"reason": "test", "tags": "[]", "files": "[]", "ts": time.time(), "session_id": "s1"}]],
            "distances": [[0.1]],
        }
        mock_collection.get.return_value = {
            "ids": ["id1"],
            "documents": ["some decision text"],
            "metadatas": [{"reason": "test", "tags": "[]", "files": "[]", "ts": time.time(), "session_id": "s1"}],
        }

        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client

        with patch.dict("sys.modules", {"chromadb": mock_chromadb}):
            db = SessionDB(directory=tmp_path)

        return db, mock_collection

    def test_backend_is_chromadb(self, db):
        db_inst, _ = db
        assert db_inst.backend() == "chromadb"

    def test_record_decision_calls_add(self, db):
        db_inst, coll = db
        doc_id = db_inst.record_decision("Test decision", reason="reason")
        coll.add.assert_called_once()
        assert isinstance(doc_id, str)

    def test_session_recall_with_query(self, db):
        db_inst, coll = db
        results = db_inst.session_recall(query="some decision")
        assert isinstance(results, list)
        coll.query.assert_called()

    def test_session_recall_no_query(self, db):
        db_inst, coll = db
        results = db_inst.session_recall()
        assert isinstance(results, list)

    def test_list_decisions_chroma(self, db):
        db_inst, coll = db
        results = db_inst.list_decisions(limit=5)
        assert isinstance(results, list)

    def test_chroma_recall_exception_returns_empty(self, tmp_path):
        from synthelion.analytics.session_db import SessionDB

        mock_collection = MagicMock()
        mock_collection.count.return_value = 1
        mock_collection.query.side_effect = RuntimeError("DB error")
        mock_collection.get.side_effect = RuntimeError("DB error")

        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client

        with patch.dict("sys.modules", {"chromadb": mock_chromadb}):
            db = SessionDB(directory=tmp_path)

        results = db.session_recall(query="something")
        assert results == []

    def test_chroma_init_failure_falls_back(self, tmp_path):
        from synthelion.analytics.session_db import SessionDB

        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient.side_effect = RuntimeError("init failed")

        with patch.dict("sys.modules", {"chromadb": mock_chromadb}):
            db = SessionDB(directory=tmp_path)

        assert db.backend() == "lexical"


# ---------------------------------------------------------------------------
# 18b. SessionDB with Qdrant mock
# ---------------------------------------------------------------------------
class TestSessionDBQdrantMock:
    """Tests that verify the Qdrant code path using a mock qdrant_client."""

    def _mock_qdrant_module(self):
        mock_point = MagicMock()
        mock_point.id = "id1"
        mock_point.score = 0.9
        mock_point.payload = {
            "text": "some decision text", "reason": "test", "tags": "[]",
            "files": "[]", "ts": time.time(), "session_id": "s1",
        }

        mock_query_result = MagicMock()
        mock_query_result.points = [mock_point]

        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])
        mock_client.query_points.return_value = mock_query_result
        mock_client.scroll.return_value = ([mock_point], None)

        mock_qdrant_client_mod = MagicMock()
        mock_qdrant_client_mod.QdrantClient.return_value = mock_client

        mock_models_mod = MagicMock()

        mock_pkg = MagicMock()
        mock_pkg.QdrantClient = mock_qdrant_client_mod.QdrantClient
        return mock_pkg, mock_models_mod, mock_client

    def _make_db(self, tmp_path):
        from synthelion.analytics.session_db import SessionDB
        mock_pkg, mock_models_mod, mock_client = self._mock_qdrant_module()
        with patch.dict("sys.modules", {
            "qdrant_client": mock_pkg,
            "qdrant_client.models": mock_models_mod,
        }):
            db = SessionDB(directory=tmp_path, backend="qdrant")
        return db, mock_client

    def test_backend_is_qdrant(self, tmp_path):
        db, _ = self._make_db(tmp_path)
        assert db.backend() == "qdrant"

    def test_record_decision_calls_upsert(self, tmp_path):
        db, client = self._make_db(tmp_path)
        with patch.dict("sys.modules", {"qdrant_client.models": MagicMock()}):
            doc_id = db.record_decision("Test decision", reason="reason")
        client.upsert.assert_called_once()
        assert isinstance(doc_id, str)

    def test_session_recall_with_query(self, tmp_path):
        db, client = self._make_db(tmp_path)
        results = db.session_recall(query="some decision")
        assert isinstance(results, list)
        client.query_points.assert_called()

    def test_session_recall_no_query_uses_scroll(self, tmp_path):
        db, client = self._make_db(tmp_path)
        results = db.session_recall()
        assert isinstance(results, list)
        client.scroll.assert_called()

    def test_list_decisions_qdrant(self, tmp_path):
        db, _ = self._make_db(tmp_path)
        results = db.list_decisions(limit=5)
        assert isinstance(results, list)

    def test_qdrant_recall_exception_returns_empty(self, tmp_path):
        db, client = self._make_db(tmp_path)
        client.query_points.side_effect = RuntimeError("qdrant error")
        results = db.session_recall(query="something")
        assert results == []

    def test_qdrant_init_failure_falls_back(self, tmp_path):
        from synthelion.analytics.session_db import SessionDB
        with patch.dict("sys.modules", {"qdrant_client": None}):
            db = SessionDB(directory=tmp_path, backend="qdrant")
        assert db.backend() == "lexical"


# ---------------------------------------------------------------------------
# 19. New OpenAI Tool handlers (session / status)
# ---------------------------------------------------------------------------
class TestNewMcpTools:

    @pytest.fixture(autouse=True)
    def _isolated_session_db(self, tmp_path):
        """Each test gets its own isolated SessionDB to avoid cross-test state."""
        from synthelion.analytics import session_db as sdb_mod
        from synthelion.analytics.session_db import SessionDB
        orig_db = sdb_mod._db
        with patch.dict("sys.modules", {"chromadb": None}):
            sdb_mod._db = SessionDB(directory=tmp_path)
        yield
        sdb_mod._db = orig_db

    @pytest.fixture(autouse=True)
    def _isolated_ledger(self, tmp_path):
        from synthelion.analytics import ledger as led_mod
        from synthelion.analytics.ledger import SavingsLedger
        orig_led = led_mod._ledger
        led_mod._ledger = SavingsLedger(directory=tmp_path)
        yield
        led_mod._ledger = orig_led

    def test_session_record(self):
        from synthelion.plugins.openai_tools import execute_tool
        r = execute_tool("session_record", {"text": "We decided to use JWT"})
        assert r["status"] == "recorded"
        assert "id" in r
        assert "backend" in r

    def test_session_record_with_reason_and_tags(self):
        from synthelion.plugins.openai_tools import execute_tool
        r = execute_tool("session_record", {
            "text": "Use PostgreSQL for storage",
            "reason": "ACID compliance",
            "tags": ["db", "storage"],
        })
        assert r["status"] == "recorded"

    def test_session_record_with_files(self):
        from synthelion.plugins.openai_tools import execute_tool
        r = execute_tool("session_record", {
            "text": "Authentication logic",
            "files": ["auth.py", "middleware.py"],
        })
        assert r["status"] == "recorded"

    def test_session_recall_empty(self):
        from synthelion.plugins.openai_tools import execute_tool
        r = execute_tool("session_recall", {})
        assert "decisions" in r
        assert isinstance(r["decisions"], list)

    def test_session_recall_after_record(self):
        from synthelion.plugins.openai_tools import execute_tool
        execute_tool("session_record", {"text": "JWT authentication decision"})
        r = execute_tool("session_recall", {"query": "JWT authentication"})
        assert len(r["decisions"]) >= 1

    def test_session_recall_with_limit(self):
        from synthelion.plugins.openai_tools import execute_tool
        for i in range(5):
            execute_tool("session_record", {"text": f"Decision {i}"})
        r = execute_tool("session_recall", {"limit": 2})
        assert len(r["decisions"]) <= 2

    def test_session_recall_with_since_days(self):
        from synthelion.plugins.openai_tools import execute_tool
        r = execute_tool("session_recall", {"since_days": 7})
        assert "decisions" in r

    def test_session_start(self):
        from synthelion.plugins.openai_tools import execute_tool
        r = execute_tool("session_start", {})
        assert "session_id" in r
        assert "started_at" in r

    def test_session_end(self):
        from synthelion.plugins.openai_tools import execute_tool
        execute_tool("session_start", {})
        r = execute_tool("session_end", {})
        assert "session_id" in r
        assert "elapsed_seconds" in r

    def test_synthelion_status_empty(self):
        from synthelion.plugins.openai_tools import execute_tool
        r = execute_tool("synthelion_status", {})
        assert r["total_calls"] == 0

    def test_synthelion_status_after_compress(self):
        from synthelion.plugins.openai_tools import execute_tool
        execute_tool("compress", {"text": "I would like to know if it is possible.", "level": "light"})
        r = execute_tool("synthelion_status", {})
        assert r["total_calls"] >= 1

    def test_synthelion_status_with_days(self):
        from synthelion.plugins.openai_tools import execute_tool
        execute_tool("compress", {"text": "Hello world", "level": "light"})
        r = execute_tool("synthelion_status", {"days": 30})
        assert "total_calls" in r

    def test_compress_returns_metrics(self):
        from synthelion.plugins.openai_tools import execute_tool
        r = execute_tool("compress", {"text": "I would like to know if it is possible.", "level": "light"})
        assert "synthelion_metrics" in r
        assert "before=" in r["synthelion_metrics"]
        assert "after=" in r["synthelion_metrics"]

    def test_route_content_returns_metrics(self):
        from synthelion.plugins.openai_tools import execute_tool
        r = execute_tool("route_content", {"content": "I would like to know if it is possible."})
        assert "synthelion_metrics" in r

    def test_route_content_success_collapse_via_command_and_exit_code(self):
        from synthelion.plugins.openai_tools import execute_tool
        r = execute_tool("route_content", {
            "content": "added 42 packages in 3s\n2 vulnerabilities (1 moderate, 1 high)\n" + "noise\n" * 30,
            "command": "npm install",
            "exit_code": 0,
        })
        assert r["strategy_used"] == "SuccessCollapse"
        assert "added 42 packages in 3s" in r["compressed"]

    def test_summarize_returns_metrics(self):
        from synthelion.plugins.openai_tools import execute_tool
        text = "Rome is the capital of Italy. It is very old. Many tourists visit."
        r = execute_tool("summarize", {"text": text})
        assert "synthelion_metrics" in r

    def test_compress_batch_returns_metrics(self):
        from synthelion.plugins.openai_tools import execute_tool
        r = execute_tool("compress_batch", {"texts": ["Hello world", "Ciao mondo"]})
        assert "synthelion_metrics" in r

    def test_fmt_metrics_helper(self):
        from synthelion.plugins.openai_tools import _fmt_metrics
        s = _fmt_metrics(100, 60)
        assert "before=100" in s
        assert "after=60" in s
        assert "saved=40" in s
        assert "40.0%" in s

    def test_fmt_metrics_zero_before(self):
        from synthelion.plugins.openai_tools import _fmt_metrics
        s = _fmt_metrics(0, 0)
        assert "0.0%" in s

    def test_check_sensitive_content_flags_secret(self):
        from synthelion.plugins.openai_tools import execute_tool, get_tool_definitions
        names = {td["function"]["name"] for td in get_tool_definitions()}
        assert "check_sensitive_content" in names
        r = execute_tool("check_sensitive_content", {"text": "AKIAIOSFODNN7EXAMPLE"})
        assert r == {"sensitive": True, "class": "aws-access-key"}

    def test_check_sensitive_content_clean_text(self):
        from synthelion.plugins.openai_tools import execute_tool
        r = execute_tool("check_sensitive_content", {"text": "Hello world"})
        assert r == {"sensitive": False, "class": None}

    def test_record_ledger_ignores_exceptions(self):
        from synthelion.plugins.openai_tools import _record_ledger
        # Should not raise even if ledger fails
        with patch("synthelion.analytics.ledger.get_ledger", side_effect=RuntimeError("fail")):
            _record_ledger("compress", 100, 60)  # must not raise


# ---------------------------------------------------------------------------
# 20. CLI new commands: status, gain, bench
# ---------------------------------------------------------------------------
class TestCliNewCommands:

    def _run(self, args: list[str]) -> str:
        from synthelion.cli import main
        with patch("sys.argv", ["synthelion"] + args):
            with patch("sys.stdout", new_callable=StringIO) as mock_out:
                with patch("sys.stderr", new_callable=StringIO):
                    try:
                        main()
                    except SystemExit:
                        pass
                    return mock_out.getvalue()

    @pytest.fixture(autouse=True)
    def _isolated_ledger(self, tmp_path):
        from synthelion.analytics import ledger as led_mod
        from synthelion.analytics.ledger import SavingsLedger
        orig = led_mod._ledger
        led_mod._ledger = SavingsLedger(directory=tmp_path)
        yield
        led_mod._ledger = orig

    def test_status_no_records(self):
        out = self._run(["status"])
        assert "Calls" in out or "calls" in out.lower() or "0" in out

    def test_status_json_output(self):
        out = self._run(["status", "--json"])
        data = json.loads(out.strip())
        assert "total_calls" in data

    def test_status_with_days(self):
        out = self._run(["status", "--days", "7"])
        assert out.strip()  # must not crash

    def test_status_with_days_json(self):
        out = self._run(["status", "--days", "7", "--json"])
        data = json.loads(out.strip())
        assert "total_calls" in data

    def test_gain_default(self):
        out = self._run(["gain"])
        assert out.strip()

    def test_gain_all(self):
        out = self._run(["gain", "--all"])
        assert "all time" in out

    def test_gain_json(self):
        out = self._run(["gain", "--json"])
        data = json.loads(out.strip())
        assert "total_calls" in data

    def test_gain_with_days(self):
        out = self._run(["gain", "--days", "7"])
        assert out.strip()

    def test_gain_all_json(self):
        out = self._run(["gain", "--all", "--json"])
        data = json.loads(out.strip())
        assert "range" in data
        assert data["range"] == "all time"

    def test_bench_default(self):
        out = self._run(["bench"])
        assert "Synthelion bench" in out
        assert "TOTAL" in out

    def test_bench_json_output(self):
        out = self._run(["bench", "--json"])
        data = json.loads(out.strip())
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "label" in data[0]
        assert "savings_pct" in data[0]

    def test_bench_all_labels_present(self):
        out = self._run(["bench", "--json"])
        data = json.loads(out.strip())
        labels = {item["label"] for item in data}
        assert "plain_text_eng" in labels
        assert "git_diff" in labels
        assert "json_array" in labels
        assert "html_content" in labels
        assert "code_python" in labels
        assert "log_stacktrace" in labels

    def test_bench_savings_are_non_negative(self):
        out = self._run(["bench", "--json"])
        data = json.loads(out.strip())
        for item in data:
            assert item["savings_pct"] >= 0


# ---------------------------------------------------------------------------
# 21. RagAgent
# ---------------------------------------------------------------------------
class TestRagAgent:

    @pytest.fixture(autouse=True)
    def _isolated_db(self, tmp_path):
        from synthelion.analytics import session_db as sdb_mod, ledger as led_mod
        from synthelion.analytics.session_db import SessionDB
        from synthelion.analytics.ledger import SavingsLedger
        orig_db = sdb_mod._db
        orig_led = led_mod._ledger
        with patch.dict("sys.modules", {"chromadb": None}):
            sdb_mod._db = SessionDB(directory=tmp_path)
        led_mod._ledger = SavingsLedger(directory=tmp_path)
        yield
        sdb_mod._db = orig_db
        led_mod._ledger = orig_led

    @pytest.fixture()
    def agent(self):
        from synthelion.agent.rag_agent import RagAgent
        return RagAgent(max_context_tokens=2000)

    def test_prepare_message_returns_prepared(self, agent):
        from synthelion.agent.rag_agent import PreparedMessage
        result = agent.prepare_message("Tell me about JWT authentication")
        assert isinstance(result, PreparedMessage)
        assert result.original == "Tell me about JWT authentication"
        assert result.compressed  # must not be empty

    def test_prepare_message_token_counts(self, agent):
        result = agent.prepare_message("I would like to know if it is possible to receive information.")
        assert result.tokens_before >= 0
        assert result.tokens_after >= 0

    def test_prepared_message_savings_pct(self, agent):
        result = agent.prepare_message("I would like to know if it is possible to receive information.")
        assert 0.0 <= result.savings_pct <= 100.0

    def test_prepare_message_with_recall_query(self, agent):
        agent.store("JWT used for authentication", reason="stateless")
        result = agent.prepare_message("Tell me about auth", recall_query="JWT")
        assert isinstance(result.recalled_context, list)

    def test_store_and_recall(self, agent):
        agent.store("We use PostgreSQL", reason="ACID", tags=["db"])
        hits = agent.recall("PostgreSQL database")
        assert len(hits) >= 1

    def test_add_turn_appends_to_window(self, agent):
        agent.add_turn("user", "Hello there")
        ctx = agent.render_context()
        assert "Hello there" in ctx

    def test_add_turn_auto_store(self, agent):
        agent.add_turn("assistant", "We decided to use Redis for caching because of speed", auto_store=True)
        hits = agent.recall("Redis cache")
        assert isinstance(hits, list)

    def test_to_messages_returns_list(self, agent):
        agent.add_turn("user", "Hello")
        agent.add_turn("assistant", "Hi")
        msgs = agent.to_messages()
        assert isinstance(msgs, list)
        assert len(msgs) == 2

    def test_session_start(self, agent):
        info = agent.session_start()
        assert "session_id" in info

    def test_session_end(self, agent):
        agent.session_start()
        info = agent.session_end()
        assert "elapsed_seconds" in info

    def test_status_returns_dict(self, agent):
        agent.prepare_message("Hello")
        s = agent.status()
        assert "total_calls" in s

    def test_clear_resets_window(self, agent):
        agent.add_turn("user", "Some message")
        agent.clear()
        assert agent.render_context() == ""

    def test_tokens_saved_property(self):
        from synthelion.agent.rag_agent import PreparedMessage
        pm = PreparedMessage(original="x", compressed="x", tokens_before=100, tokens_after=60)
        assert pm.tokens_saved == 40
        assert pm.savings_pct == pytest.approx(40.0)

    def test_tokens_saved_zero_before(self):
        from synthelion.agent.rag_agent import PreparedMessage
        pm = PreparedMessage(original="x", compressed="x", tokens_before=0, tokens_after=0)
        assert pm.savings_pct == 0.0


# ---------------------------------------------------------------------------
# 22. ClaudeAdapter (mocked anthropic)
# ---------------------------------------------------------------------------
class TestClaudeAdapter:

    @pytest.fixture()
    def mock_anthropic(self):
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="Mocked Claude response")]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_mod = MagicMock()
        mock_mod.Anthropic.return_value = mock_client
        return mock_mod, mock_client

    @pytest.fixture(autouse=True)
    def _isolated(self, tmp_path):
        from synthelion.analytics import session_db as sdb_mod, ledger as led_mod
        from synthelion.analytics.session_db import SessionDB
        from synthelion.analytics.ledger import SavingsLedger
        orig_db = sdb_mod._db
        orig_led = led_mod._ledger
        with patch.dict("sys.modules", {"chromadb": None}):
            sdb_mod._db = SessionDB(directory=tmp_path)
        led_mod._ledger = SavingsLedger(directory=tmp_path)
        yield
        sdb_mod._db = orig_db
        led_mod._ledger = orig_led

    def test_chat_returns_response(self, mock_anthropic):
        mock_mod, mock_client = mock_anthropic
        with patch.dict("sys.modules", {"anthropic": mock_mod}):
            from synthelion.integrations.claude_adapter import ClaudeAdapter
            adapter = ClaudeAdapter(model="claude-sonnet-4-6")
            r = adapter.chat("What is JWT?")
        assert r.content == "Mocked Claude response"
        assert r.tokens_saved >= 0

    def test_chat_with_system_prompt(self, mock_anthropic):
        mock_mod, _ = mock_anthropic
        with patch.dict("sys.modules", {"anthropic": mock_mod}):
            from synthelion.integrations.claude_adapter import ClaudeAdapter
            adapter = ClaudeAdapter()
            r = adapter.chat("Hello", system="You are a helpful assistant.")
        assert r.content

    def test_chat_with_recall_context(self, mock_anthropic):
        mock_mod, _ = mock_anthropic
        with patch.dict("sys.modules", {"anthropic": mock_mod}):
            from synthelion.integrations.claude_adapter import ClaudeAdapter
            adapter = ClaudeAdapter()
            adapter.store("JWT used for authentication")
            r = adapter.chat("Explain auth", inject_recall=True)
        assert isinstance(r.recalled_context, list)

    def test_chat_no_inject_recall(self, mock_anthropic):
        mock_mod, _ = mock_anthropic
        with patch.dict("sys.modules", {"anthropic": mock_mod}):
            from synthelion.integrations.claude_adapter import ClaudeAdapter
            adapter = ClaudeAdapter()
            r = adapter.chat("Hello", inject_recall=False)
        assert r.content

    def test_store_and_recall(self, mock_anthropic):
        mock_mod, _ = mock_anthropic
        with patch.dict("sys.modules", {"anthropic": mock_mod}):
            from synthelion.integrations.claude_adapter import ClaudeAdapter
            adapter = ClaudeAdapter()
            adapter.store("Use Redis for caching")
            hits = adapter.recall("Redis")
        assert isinstance(hits, list)

    def test_status(self, mock_anthropic):
        mock_mod, _ = mock_anthropic
        with patch.dict("sys.modules", {"anthropic": mock_mod}):
            from synthelion.integrations.claude_adapter import ClaudeAdapter
            adapter = ClaudeAdapter()
            s = adapter.status()
        assert "total_calls" in s

    def test_reset(self, mock_anthropic):
        mock_mod, _ = mock_anthropic
        with patch.dict("sys.modules", {"anthropic": mock_mod}):
            from synthelion.integrations.claude_adapter import ClaudeAdapter
            adapter = ClaudeAdapter()
            adapter.chat("Hello")
            adapter.reset()
        assert True  # must not raise

    def test_import_error_without_anthropic(self):
        with patch.dict("sys.modules", {"anthropic": None}):
            with pytest.raises(ImportError, match="anthropic"):
                from synthelion.integrations.claude_adapter import ClaudeAdapter
                ClaudeAdapter()

    def test_chat_with_empty_content(self, mock_anthropic):
        mock_mod, mock_client = mock_anthropic
        mock_msg = MagicMock()
        mock_msg.content = []
        mock_client.messages.create.return_value = mock_msg
        with patch.dict("sys.modules", {"anthropic": mock_mod}):
            from synthelion.integrations.claude_adapter import ClaudeAdapter
            adapter = ClaudeAdapter()
            r = adapter.chat("Hello")
        assert r.content == ""


# ---------------------------------------------------------------------------
# 23. OpenAIAdapter (mocked openai)
# ---------------------------------------------------------------------------
class TestOpenAIAdapter:

    @pytest.fixture()
    def mock_openai(self):
        mock_choice = MagicMock()
        mock_choice.message.content = "Mocked OpenAI response"
        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_completion
        mock_mod = MagicMock()
        mock_mod.OpenAI.return_value = mock_client
        return mock_mod, mock_client

    @pytest.fixture(autouse=True)
    def _isolated(self, tmp_path):
        from synthelion.analytics import session_db as sdb_mod, ledger as led_mod
        from synthelion.analytics.session_db import SessionDB
        from synthelion.analytics.ledger import SavingsLedger
        orig_db = sdb_mod._db
        orig_led = led_mod._ledger
        with patch.dict("sys.modules", {"chromadb": None}):
            sdb_mod._db = SessionDB(directory=tmp_path)
        led_mod._ledger = SavingsLedger(directory=tmp_path)
        yield
        sdb_mod._db = orig_db
        led_mod._ledger = orig_led

    def test_chat_returns_response(self, mock_openai):
        mock_mod, _ = mock_openai
        with patch.dict("sys.modules", {"openai": mock_mod}):
            from synthelion.integrations.openai_adapter import OpenAIAdapter
            adapter = OpenAIAdapter(model="gpt-4o-mini")
            r = adapter.chat("What is JWT?")
        assert r.content == "Mocked OpenAI response"
        assert r.tokens_saved >= 0

    def test_chat_with_system_prompt(self, mock_openai):
        mock_mod, _ = mock_openai
        with patch.dict("sys.modules", {"openai": mock_mod}):
            from synthelion.integrations.openai_adapter import OpenAIAdapter
            adapter = OpenAIAdapter()
            r = adapter.chat("Hello", system="You are a helpful assistant.")
        assert r.content

    def test_chat_with_recall_inject(self, mock_openai):
        mock_mod, _ = mock_openai
        with patch.dict("sys.modules", {"openai": mock_mod}):
            from synthelion.integrations.openai_adapter import OpenAIAdapter
            adapter = OpenAIAdapter()
            adapter.store("Use PostgreSQL for ACID compliance")
            r = adapter.chat("Explain database choices", inject_recall=True)
        assert isinstance(r.recalled_context, list)

    def test_chat_no_inject_recall(self, mock_openai):
        mock_mod, _ = mock_openai
        with patch.dict("sys.modules", {"openai": mock_mod}):
            from synthelion.integrations.openai_adapter import OpenAIAdapter
            adapter = OpenAIAdapter()
            r = adapter.chat("Hello", inject_recall=False)
        assert r.content

    def test_store_and_recall(self, mock_openai):
        mock_mod, _ = mock_openai
        with patch.dict("sys.modules", {"openai": mock_mod}):
            from synthelion.integrations.openai_adapter import OpenAIAdapter
            adapter = OpenAIAdapter()
            adapter.store("Redis for caching")
            hits = adapter.recall("Redis")
        assert isinstance(hits, list)

    def test_status(self, mock_openai):
        mock_mod, _ = mock_openai
        with patch.dict("sys.modules", {"openai": mock_mod}):
            from synthelion.integrations.openai_adapter import OpenAIAdapter
            adapter = OpenAIAdapter()
            s = adapter.status()
        assert "total_calls" in s

    def test_reset(self, mock_openai):
        mock_mod, _ = mock_openai
        with patch.dict("sys.modules", {"openai": mock_mod}):
            from synthelion.integrations.openai_adapter import OpenAIAdapter
            adapter = OpenAIAdapter()
            adapter.chat("Hello")
            adapter.reset()
        assert True  # must not raise

    def test_import_error_without_openai(self):
        with patch.dict("sys.modules", {"openai": None}):
            with pytest.raises(ImportError, match="openai"):
                from synthelion.integrations.openai_adapter import OpenAIAdapter
                OpenAIAdapter()

    def test_chat_empty_choices(self, mock_openai):
        mock_mod, mock_client = mock_openai
        mock_completion = MagicMock()
        mock_completion.choices = []
        mock_client.chat.completions.create.return_value = mock_completion
        with patch.dict("sys.modules", {"openai": mock_mod}):
            from synthelion.integrations.openai_adapter import OpenAIAdapter
            adapter = OpenAIAdapter()
            r = adapter.chat("Hello")
        assert r.content == ""


# ---------------------------------------------------------------------------
# 24. LangChain new tools (session / status / SynthelionMemory)
# ---------------------------------------------------------------------------
try:
    from synthelion.plugins.langchain_tools import get_tools as _lc_get_tools
    HAS_LANGCHAIN = True
except ImportError:
    HAS_LANGCHAIN = False


@pytest.mark.skipif(not HAS_LANGCHAIN, reason="langchain-core not installed")
class TestLangChainNewTools:

    @pytest.fixture(autouse=True)
    def _isolated(self, tmp_path):
        from synthelion.analytics import session_db as sdb_mod, ledger as led_mod
        from synthelion.analytics.session_db import SessionDB
        from synthelion.analytics.ledger import SavingsLedger
        orig_db = sdb_mod._db
        orig_led = led_mod._ledger
        with patch.dict("sys.modules", {"chromadb": None}):
            sdb_mod._db = SessionDB(directory=tmp_path)
        led_mod._ledger = SavingsLedger(directory=tmp_path)
        yield
        sdb_mod._db = orig_db
        led_mod._ledger = orig_led

    def test_session_record_tool_runs(self):
        tools = {t.name: t for t in _lc_get_tools()}
        result = tools["synthelion_session_record"].invoke({"text": "Use JWT for auth"})
        assert "Recorded" in result
        assert "backend" in result

    def test_session_recall_tool_runs(self):
        tools = {t.name: t for t in _lc_get_tools()}
        tools["synthelion_session_record"].invoke({"text": "JWT authentication decision"})
        result = tools["synthelion_session_recall"].invoke({"query": "JWT"})
        assert isinstance(result, str)

    def test_session_recall_no_results(self):
        tools = {t.name: t for t in _lc_get_tools()}
        result = tools["synthelion_session_recall"].invoke({"query": ""})
        assert isinstance(result, str)

    def test_synthelion_status_tool(self):
        tools = {t.name: t for t in _lc_get_tools()}
        result = tools["synthelion_status"].invoke({})
        assert "Calls" in result or "calls" in result.lower()

    def test_synthelion_memory_load_save(self):
        from synthelion.plugins.langchain_tools import SynthelionMemory
        mem = SynthelionMemory(memory_key="history")
        mem.save_context({"input": "Hello"}, {"output": "Hi"})
        variables = mem.load_memory_variables({"input": "Hello"})
        assert "history" in variables

    def test_synthelion_memory_variables(self):
        from synthelion.plugins.langchain_tools import SynthelionMemory
        mem = SynthelionMemory()
        assert "history" in mem.memory_variables

    def test_synthelion_memory_clear(self):
        from synthelion.plugins.langchain_tools import SynthelionMemory
        mem = SynthelionMemory()
        mem.save_context({"input": "Hi"}, {"output": "Hello"})
        mem.clear()
        variables = mem.load_memory_variables({})
        assert variables["history"] == ""

    def test_synthelion_memory_custom_key(self):
        from synthelion.plugins.langchain_tools import SynthelionMemory
        mem = SynthelionMemory(memory_key="chat_history")
        assert "chat_history" in mem.memory_variables

    def test_synthelion_memory_recall_injects(self):
        from synthelion.plugins.langchain_tools import SynthelionMemory
        from synthelion.analytics.session_db import get_session_db
        # Pre-populate memory
        db = get_session_db()
        db.record_decision("We use Redis for session caching")
        mem = SynthelionMemory()
        variables = mem.load_memory_variables({"input": "Redis caching"})
        assert isinstance(variables["history"], str)
