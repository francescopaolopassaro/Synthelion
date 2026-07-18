# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for the retrieval/structure-aware additions ported from Caveman C# 1.4.1:
SimHash, fuzzy log folding, code skeletonization, and BM25+/RM3 retrieval."""
from __future__ import annotations

import pytest

from synthelion import simhash
from synthelion.compressors.code_compressor import CodeCompressor
from synthelion.compressors.log_compressor import LogCompressor
from synthelion.retriever import Retriever


class TestSimHash:
    def test_identical_text_zero_distance(self):
        text = "the quick brown fox jumps over the lazy dog"
        assert simhash.hamming_distance(simhash.compute(text), simhash.compute(text)) == 0

    def test_near_duplicate_closer_than_unrelated(self):
        a = "User alice logged in from 192.168.1.5 at session start"
        b = "User bob logged in from 10.0.0.9 at session start"
        c = "The quarterly financial report was uploaded successfully"
        near = simhash.hamming_distance(simhash.compute(a), simhash.compute(b))
        far = simhash.hamming_distance(simhash.compute(a), simhash.compute(c))
        assert near < far

    def test_empty_or_whitespace_returns_zero(self):
        assert simhash.compute("") == 0
        assert simhash.compute("   ") == 0

    def test_are_near_duplicates_respects_max_distance(self):
        a = "User alice logged in from 192.168.1.5 at session start"
        c = "The quarterly financial report was uploaded successfully"
        assert simhash.are_near_duplicates(a, c, max_distance=3) is False


class TestFuzzyLogFold:
    LOG = "\n".join([
        "User alice logged in from 192.168.1.5 at session start",
        "User bob logged in from 10.0.0.9 at session start",
        "User carol logged in from 172.16.0.3 at session start",
        "ERROR database connection refused",
    ])

    def test_strict_mode_leaves_templated_variation_unfolded(self):
        compressed, was_compressed = LogCompressor().compress(self.LOG)
        assert was_compressed is False

    def test_fuzzy_mode_folds_near_duplicate_templated_lines(self):
        compressed, was_compressed = LogCompressor().compress(self.LOG, fuzzy=True)
        assert was_compressed is True
        assert "[×3]" in compressed
        assert "ERROR database connection refused" in compressed

    def test_fuzzy_mode_never_folds_unrelated_lines(self):
        log = "\n".join([
            "User alice logged in from 192.168.1.5 at session start",
            "Payment of $42.50 processed for order #1183",
            "Disk usage at 87 percent on volume /var/log",
        ])
        _, was_compressed = LogCompressor().compress(log, fuzzy=True)
        assert was_compressed is False


class TestCodeSkeletonization:
    def test_default_off_matches_no_skeletonize(self):
        code = "public class C { public void M() { var x = 1; var y = 2; return; } }"
        r1 = CodeCompressor().compress(code)
        r2 = CodeCompressor().compress(code, skeletonize=False)
        assert r1[0] == r2[0]
        assert r1[3] == 0

    def test_csharp_replaces_large_body_keeps_signature(self):
        code = """
public class AuthService
{
    public async Task<bool> AuthenticateAsync(string username, string password)
    {
        var user = await _repo.FindByUsernameAsync(username);
        if (user == null) { return false; }
        return user.VerifyPassword(password);
    }
}"""
        compressed, _, _, skeletonized = CodeCompressor().compress(code, skeletonize=True)
        assert skeletonized == 1
        assert "AuthenticateAsync(string username, string password)" in compressed
        assert "FindByUsernameAsync" not in compressed

    def test_csharp_nested_braces_and_strings_stay_balanced(self):
        code = """
public class P
{
    public void Weird()
    {
        var s = "unbalanced { brace in string";
        var c = '{';
        if (s.Length > 0)
        {
            for (int i = 0; i < 10; i++) { Console.WriteLine(i); }
        }
        return;
    }
}"""
        compressed, _, _, _ = CodeCompressor().compress(code, skeletonize=True)
        assert compressed.count("{") == compressed.count("}")

    def test_python_collapses_method_body_keeps_class_and_other_methods(self):
        code = (
            "class Auth:\n"
            "    def __init__(self, repo):\n"
            "        self.repo = repo\n"
            "\n"
            "    def authenticate(self, username, password):\n"
            "        user = self.repo.find(username)\n"
            "        if user is None:\n"
            "            return False\n"
            "        return user.verify(password)\n"
            "\n"
            "    def add(self, a, b):\n"
            "        return a + b\n"
        )
        compressed, _, _, _ = CodeCompressor().compress(code, skeletonize=True)
        assert "class Auth:" in compressed
        assert "def __init__(self, repo):" in compressed
        assert "def authenticate(self, username, password):" in compressed
        assert "def add(self, a, b):" in compressed
        assert "self.repo.find" not in compressed  # collapsed
        assert "self.repo = repo" in compressed    # trivial body untouched
        assert "return a + b" in compressed         # trivial body untouched


class TestRetriever:
    DOCUMENTS = [
        "Electric car battery range improved significantly this year for most manufacturers",
        "Battery technology advances are extending electric car range across the industry",
        "Tesla and Rivian both improved battery range in their latest vehicle models",
        "The weather today is sunny with mild temperatures across the region",
        "Local bakery introduces a new sourdough recipe for the weekend market",
    ]

    def test_plain_bm25_only_finds_literal_matches(self):
        r = Retriever()
        results = r.retrieve(self.DOCUMENTS, "car", 5)
        assert {res.index for res in results} == {0, 1}

    def test_rm3_surfaces_relevant_document_without_literal_query_term(self):
        r = Retriever()
        results = r.retrieve_with_feedback(self.DOCUMENTS, "car", 5)
        indexes = {res.index for res in results}
        assert 0 in indexes and 1 in indexes
        assert 2 in indexes, "RM3 should surface the Tesla/Rivian doc via expansion (battery, range)"

    def test_rm3_never_ranks_unrelated_document_above_genuine_matches(self):
        r = Retriever()
        results = {res.index: res.score for res in r.retrieve_with_feedback(self.DOCUMENTS, "car", 5)}
        if 3 in results:
            assert results[3] < results[0]
            assert results[3] < results[1]

    @pytest.mark.parametrize("query", ["", "   "])
    def test_empty_query_returns_empty(self, query):
        r = Retriever()
        assert r.retrieve(self.DOCUMENTS, query, 5) == []
        assert r.retrieve_with_feedback(self.DOCUMENTS, query, 5) == []

    def test_no_matching_documents_returns_empty_never_throws(self):
        r = Retriever()
        assert r.retrieve(self.DOCUMENTS, "xyzzyplugh", 5) == []
        assert r.retrieve_with_feedback(self.DOCUMENTS, "xyzzyplugh", 5) == []

    def test_empty_document_list_returns_empty_never_throws(self):
        r = Retriever()
        assert r.retrieve([], "car", 5) == []
