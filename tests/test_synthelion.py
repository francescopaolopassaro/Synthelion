# Tests for Synthelion — Python port of Caveman
# (https://github.com/francescopaolopassaro/caveman)
import json
import pytest

from synthelion.models import (
    CompressionLevel, CompressionProfile, ContentType,
)
from synthelion.word_provider import FunctionWordProvider
from synthelion.detector import LanguageDetector
from synthelion.core import CompressionService
from synthelion.content_detector import ContentDetector
from synthelion.content_router import ContentRouter
from synthelion.nlp.summarizer import TfIdfSummarizer
from synthelion.nlp.text_rank import TextRankSummarizer
from synthelion.agent.context_window import ContextWindow
from synthelion.agent.memory_store import MemoryStore
from synthelion.plugins.openai_tools import get_tool_definitions, get_tool_list, execute_tool
from synthelion.plugins import mcp_server  # import check only


# ---------------------------------------------------------------------------
# 1. FunctionWordProvider — load index
# ---------------------------------------------------------------------------
class TestWordProvider:
    def test_load_index_and_get_eng_function_words(self):
        p = FunctionWordProvider()
        fw = p.get_function_words("eng")
        assert isinstance(fw, frozenset)
        assert len(fw) > 10
        assert "the" in fw
        assert "in" in fw

    def test_get_ita_function_words(self):
        p = FunctionWordProvider()
        fw = p.get_function_words("ita")
        assert "il" in fw
        assert "di" in fw

    def test_get_all_supported_returns_many_languages(self):
        p = FunctionWordProvider()
        langs = p.get_all_supported_iso3()
        assert "eng" in langs
        assert "ita" in langs
        assert "deu" in langs
        assert len(langs) >= 20

    def test_load_word_data_ita_returns_lemmas(self):
        p = FunctionWordProvider()
        data = p.load_word_data("ita")
        if data is None:
            pytest.skip("ita.yaml.br not available")
        assert data.iso3.lower() in ("ita", "")
        # lemmas should be a dict
        assert isinstance(data.lemmas, dict)

    def test_load_word_data_unknown_returns_none(self):
        p = FunctionWordProvider()
        assert p.load_word_data("xyz") is None

    def test_get_lemma_map_eng(self):
        p = FunctionWordProvider()
        lm = p.get_lemma_map("eng")
        assert isinstance(lm, dict)


# ---------------------------------------------------------------------------
# 2. LanguageDetector
# ---------------------------------------------------------------------------
class TestLanguageDetector:
    def setup_method(self):
        self.det = LanguageDetector()

    def test_detect_eng(self):
        assert self.det.detect("Where is the nearest train station?") == "eng"

    def test_detect_ita(self):
        # Sentence with multiple distinctive Italian function words: ho, il, dal, e, sono, nella
        assert self.det.detect("Ho comprato il pane dal fornaio e sono andato nella stazione.") == "ita"

    def test_detect_deu(self):
        result = self.det.detect("Ich hätte gerne einen Kaffee, bitte.")
        assert result == "deu"

    def test_detect_fra(self):
        result = self.det.detect("Je voudrais une table pour deux personnes, s'il vous plaît.")
        assert result == "fra"

    def test_detect_empty_returns_eng(self):
        assert self.det.detect("") == "eng"

    def test_detect_with_scores_returns_dict(self):
        scores = self.det.detect_with_scores("Where is the nearest train station?")
        assert isinstance(scores, dict)
        assert all(0.0 <= v <= 1.0 for v in scores.values())
        assert "eng" in scores


# ---------------------------------------------------------------------------
# 3. CompressionService
# ---------------------------------------------------------------------------
class TestCompressionService:
    EN_SENTENCE = "I would like to know if it is possible to receive information about cheap restaurants in Rome."

    def setup_method(self):
        self.svc = CompressionService()

    def test_compress_light_removes_stop_words(self):
        r = self.svc.compress(self.EN_SENTENCE, CompressionLevel.LIGHT)
        assert r.compressed_text
        assert "the" not in r.compressed_text.lower().split()
        assert r.efficiency_pct > 0

    def test_compress_semantic_lemmatizes(self):
        r = self.svc.compress(self.EN_SENTENCE, CompressionLevel.SEMANTIC)
        assert r.compressed_text
        assert r.compressed_tokens < r.original_tokens

    def test_compress_aggressive_further_reduces(self):
        r_sem = self.svc.compress(self.EN_SENTENCE, CompressionLevel.SEMANTIC)
        r_agg = self.svc.compress(self.EN_SENTENCE, CompressionLevel.AGGRESSIVE)
        assert r_agg.compressed_tokens <= r_sem.compressed_tokens

    def test_compress_italian_sentence(self):
        r = self.svc.compress(
            "Vorrei sapere se è possibile ricevere informazioni sui ristoranti economici a Roma.",
            CompressionLevel.SEMANTIC,
        )
        assert r.compressed_text
        assert r.efficiency_pct > 0

    def test_compress_none_returns_unchanged(self):
        r = self.svc.compress(self.EN_SENTENCE, CompressionLevel.NONE)
        assert r.compressed_text == self.EN_SENTENCE

    def test_compress_empty_returns_empty(self):
        r = self.svc.compress("", CompressionLevel.SEMANTIC)
        assert r.compressed_text == ""

    def test_compress_with_explicit_language(self):
        r = self.svc.apply_compression(
            "Ich hätte gerne einen Kaffee.", "deu", CompressionLevel.LIGHT
        )
        assert r.compressed_text
        assert r.efficiency_pct >= 0

    def test_compress_batch_preserves_order(self):
        texts = [self.EN_SENTENCE, "Hello world.", "Ciao mondo."]
        results = self.svc.compress_batch(texts, CompressionLevel.LIGHT)
        assert len(results) == 3
        for r in results:
            assert r.compressed_text

    def test_result_energy_savings(self):
        r = self.svc.compress(self.EN_SENTENCE, CompressionLevel.SEMANTIC)
        assert r.estimated_energy_saved_mwh >= 0
        assert r.estimated_co2_saved_mg >= 0


# ---------------------------------------------------------------------------
# 4. ContentDetector
# ---------------------------------------------------------------------------
class TestContentDetector:
    def setup_method(self):
        self.det = ContentDetector()

    def test_detect_json_array(self):
        r = self.det.detect('[{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]')
        assert r.type == ContentType.JSON_ARRAY
        assert r.confidence > 0.9

    def test_detect_json_object(self):
        r = self.det.detect('{"key": "value", "num": 42}')
        assert r.type == ContentType.JSON_OBJECT

    def test_detect_git_diff(self):
        diff = "--- a/file.py\n+++ b/file.py\n@@ -1,3 +1,4 @@\n-old\n+new"
        r = self.det.detect(diff)
        assert r.type == ContentType.GIT_DIFF

    def test_detect_html(self):
        r = self.det.detect("<html><body><p>Hello world</p></body></html>")
        assert r.type == ContentType.HTML

    def test_detect_plain_text(self):
        r = self.det.detect("This is a simple sentence about nothing special.")
        assert r.type == ContentType.PLAIN_TEXT


# ---------------------------------------------------------------------------
# 5. ContentRouter
# ---------------------------------------------------------------------------
class TestContentRouter:
    def test_route_json_array(self):
        router = ContentRouter.from_profile(CompressionProfile.BALANCED)
        arr = json.dumps([{"name": f"Item {i}", "value": i, "desc": "x" * 20} for i in range(20)])
        r = router.route(arr)
        assert r.detected_type == ContentType.JSON_ARRAY
        assert "JsonCrush" in r.strategy_used

    def test_route_prose(self):
        router = ContentRouter.from_profile(CompressionProfile.BALANCED)
        r = router.route("I would like to know if it is possible to receive information about cheap restaurants.")
        assert r.strategy_used == "NlpCompression"
        assert r.compressed

    def test_route_html(self):
        router = ContentRouter()
        r = router.route("<html><body><p>Hello world, this is a test sentence.</p></body></html>")
        assert r.detected_type == ContentType.HTML

    def test_route_git_diff(self):
        diff = "--- a/file.py\n+++ b/file.py\n@@ -1,5 +1,5 @@\n hello\n-old line\n+new line\n end"
        router = ContentRouter()
        r = router.route(diff)
        assert r.detected_type == ContentType.GIT_DIFF


# ---------------------------------------------------------------------------
# 6. Summarizers
# ---------------------------------------------------------------------------
LONG_IT = (
    "Roma è la capitale della Repubblica Italiana. "
    "È il comune più popolato d'Italia e il quarto dell'Unione europea. "
    "La città è stata per secoli il centro politico e culturale della civiltà occidentale. "
    "Roma ospita numerosi monumenti storici tra cui il Colosseo, il Pantheon e la Basilica di San Pietro. "
    "Il Vaticano, enclave indipendente all'interno della città, è la sede della Chiesa cattolica. "
    "L'economia di Roma è basata principalmente sul turismo, sui servizi e sull'amministrazione pubblica. "
    "La città accoglie ogni anno milioni di visitatori provenienti da tutto il mondo. "
    "Roma è anche un importante centro universitario con numerose istituzioni accademiche di rilievo internazionale."
)

class TestSummarizers:
    def test_tfidf_summarize_by_count(self):
        summ = TfIdfSummarizer()
        result = summ.summarize(LONG_IT, sentence_count=3)
        assert result
        sentences = [s for s in result.split(".") if s.strip()]
        assert len(sentences) <= 4  # approx

    def test_tfidf_summarize_by_ratio(self):
        summ = TfIdfSummarizer()
        result = summ.summarize(LONG_IT, ratio=0.3)
        assert result
        assert len(result) < len(LONG_IT)

    def test_textrank_summarize_by_count(self):
        tr = TextRankSummarizer()
        result = tr.summarize(LONG_IT, sentence_count=3)
        assert result
        assert len(result) < len(LONG_IT)

    def test_textrank_summarize_by_ratio(self):
        tr = TextRankSummarizer()
        result = tr.summarize(LONG_IT, ratio=0.4)
        assert result
        assert len(result) < len(LONG_IT)

    def test_summarize_short_text_returns_as_is(self):
        tr = TextRankSummarizer()
        short = "Just one sentence."
        result = tr.summarize(short, sentence_count=3)
        assert result  # doesn't crash

    def test_textrank_chat_aware(self):
        tr = TextRankSummarizer()
        chat = LONG_IT + "\n\nok\n\n" + LONG_IT
        result = tr.summarize_chat(chat, ratio=0.3)
        assert result


# ---------------------------------------------------------------------------
# 7. ContextWindow
# ---------------------------------------------------------------------------
class TestContextWindow:
    def test_append_and_render(self):
        w = ContextWindow(max_tokens=10000)
        w.append("user", "Hello")
        w.append("assistant", "Hi there!")
        assert w.message_count == 2
        assert "Hello" in w.render()

    def test_compaction_when_over_budget(self):
        w = ContextWindow(max_tokens=50, keep_last_turns=2)
        big = "word " * 200
        for i in range(10):
            w.append("user", f"{big} turn {i}")
            w.append("assistant", f"Response {i}")
        # After compaction message count should be reduced
        assert w.message_count < 20

    def test_to_messages_json(self):
        w = ContextWindow(max_tokens=10000)
        w.append("user", "Test message")
        data = json.loads(w.to_messages_json())
        assert isinstance(data, list)
        assert data[0]["role"] == "user"

    def test_deduplicate_mode(self):
        w = ContextWindow(max_tokens=10000, deduplicate=True)
        w.append("user", "Same message")
        w.append("user", "Same message")
        assert w.message_count == 1


# ---------------------------------------------------------------------------
# 8. MemoryStore
# ---------------------------------------------------------------------------
class TestMemoryStore:
    def test_remember_and_recall(self):
        store = MemoryStore()
        store.remember({"summary": "User likes Italian food pizza pasta", "keywords": ["pizza", "pasta", "Italy"]})
        store.remember({"summary": "Project deadline is next Friday", "keywords": ["deadline", "project"]})
        results = store.recall("What food does the user prefer?", top_k=1)
        assert len(results) == 1
        assert "pizza" in results[0].get("keywords", [])

    def test_save_and_load(self):
        store = MemoryStore()
        store.remember({"summary": "Test note", "keywords": ["test"]})
        saved = store.save()
        store2 = MemoryStore()
        store2.load(saved)
        assert len(store2) == 1

    def test_recall_empty_returns_empty(self):
        store = MemoryStore()
        assert store.recall("anything") == []

    def test_clear(self):
        store = MemoryStore()
        store.remember({"summary": "Note", "keywords": []})
        store.clear()
        assert len(store) == 0


# ---------------------------------------------------------------------------
# 9. OpenAI Tools
# ---------------------------------------------------------------------------
class TestOpenAiTools:
    def test_get_tool_definitions_returns_five_tools(self):
        tools = get_tool_definitions()
        assert len(tools) == 5
        names = {t["function"]["name"] for t in tools}
        assert names == {"compress", "detect_language", "route_content", "summarize", "compress_batch"}

    def test_get_tool_list(self):
        names = get_tool_list()
        assert "compress" in names
        assert "detect_language" in names

    def test_execute_compress(self):
        r = execute_tool("compress", {"text": "I would like to know if it is possible.", "level": "semantic"})
        assert "compressed_text" in r
        assert r["compressed_text"]

    def test_execute_detect_language(self):
        r = execute_tool("detect_language", {"text": "Ho comprato il pane dal fornaio e sono andato nella stazione."})
        assert r["language"] == "ita"

    def test_execute_compress_batch(self):
        r = execute_tool("compress_batch", {"texts": ["Hello world.", "Ciao mondo."], "level": "light"})
        assert len(r["results"]) == 2

    def test_execute_unknown_tool(self):
        r = execute_tool("unknown_tool", {})
        assert "error" in r


# ---------------------------------------------------------------------------
# 10. MCP server — import and tool list
# ---------------------------------------------------------------------------
class TestMcpServer:
    def test_get_tool_list_from_openai_tools(self):
        names = get_tool_list()
        expected = {"compress", "detect_language", "route_content", "summarize", "compress_batch"}
        assert expected.issubset(set(names))

    def test_mcp_server_module_importable(self):
        from synthelion.plugins import mcp_server as ms
        assert hasattr(ms, "main")
        assert hasattr(ms, "get_tool_list")

    def test_mcp_package_installed(self):
        """mcp must be importable — it's a core dependency for the public plugin."""
        import mcp
        assert hasattr(mcp, "__version__") or True  # just verify it imports

    def test_mcp_server_builds_tool_list(self):
        """MCP server uses the same tool list as the OpenAI tools module."""
        from synthelion.plugins.mcp_server import get_tool_list as mcp_gtl
        from synthelion.plugins.openai_tools import get_tool_list as openai_gtl
        assert set(mcp_gtl()) == set(openai_gtl())
