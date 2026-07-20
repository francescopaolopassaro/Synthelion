# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for the Caveman C# 1.4.0 features ported into Synthelion:
CacheAligner, SafetyGuard, WasteAnalyzer, RelevanceFilter, SharedContext,
OutputShaper, CcrStore, cost_estimator, ModelTokenizer, and the devtools
(CommitGenerator, ReviewService, CavecrewService, ProjectWiki).
"""
from __future__ import annotations

import os
import time

import pytest

from synthelion.cache_aligner import CacheAligner
from synthelion.ccr_store import CcrStore
from synthelion.cost_estimator import default_usd_per_1k_tokens, eur, usd
from synthelion.devtools.commit_generator import CommitGenerator
from synthelion.devtools.crew_service import CavecrewService
from synthelion.devtools.review_service import ReviewService
from synthelion.devtools.wiki import ProjectWiki
from synthelion.models import CompressionLevel, VerbosityLevel
from synthelion.output_shaper import OutputShaper
from synthelion.relevance_filter import RelevanceFilter
from synthelion.safety_guard import SafetyGuard, SafetyLevel
from synthelion.shared_context import SharedContext
from synthelion.tokenizer import LlmModel, ModelTokenizer
from synthelion.waste_analyzer import WasteAnalyzer


# ---------------------------------------------------------------------------
# CacheAligner
# ---------------------------------------------------------------------------

def test_cache_aligner_detects_uuid_and_iso8601():
    prompt = "session id: 550e8400-e29b-41d4-a716-446655440000 at 2026-07-20T10:00:00Z"
    aligner = CacheAligner()
    findings = aligner.scan(prompt)
    labels = {f.label for f in findings}
    assert "UUID" in labels
    assert "ISO8601" in labels
    assert aligner.has_volatile_tokens(prompt)


def test_cache_aligner_clean_prompt():
    aligner = CacheAligner()
    assert aligner.scan("You are a helpful assistant.") == []
    assert not aligner.has_volatile_tokens("")


# ---------------------------------------------------------------------------
# SafetyGuard
# ---------------------------------------------------------------------------

def test_safety_guard_critical_and_destructive():
    guard = SafetyGuard()
    assert guard.check("this diff contains a sql injection vulnerability").level == SafetyLevel.CRITICAL
    assert guard.check("run rm -rf / to clean up").level == SafetyLevel.CRITICAL
    assert not guard.should_compress("rm -rf /tmp/build")


def test_safety_guard_warning_and_normal():
    guard = SafetyGuard()
    assert guard.check("this is a production deploy").level == SafetyLevel.WARNING
    verdict = guard.check("hello, how are you today?")
    assert verdict.level == SafetyLevel.NORMAL
    assert verdict.should_compress


def test_safety_guard_word_boundaries_avoid_false_positives():
    guard = SafetyGuard()
    # "dos" and "rce" must not match inside "dose"/"force"/"source"
    assert guard.check("take one dose of medicine").level == SafetyLevel.NORMAL
    assert guard.check("use force to open the source file").level == SafetyLevel.NORMAL


# ---------------------------------------------------------------------------
# WasteAnalyzer
# ---------------------------------------------------------------------------

def test_waste_analyzer_detects_html_and_whitespace():
    content = "<div class='x'><p>hello</p></div>" + " " * 10 + "\n\n\n\nmore text"
    analysis = WasteAnalyzer().analyze(content)
    assert analysis.html_noise_tokens > 0
    assert analysis.whitespace_tokens > 0
    assert analysis.total_waste_tokens > 0


def test_waste_analyzer_empty_content():
    assert WasteAnalyzer().analyze("").total_waste_tokens == 0


def test_waste_analyzer_messages_aggregate():
    msgs = ["<span>a</span>", "<span>b</span>"]
    agg = WasteAnalyzer().analyze_messages(msgs)
    single = WasteAnalyzer().analyze(msgs[0])
    assert agg.html_noise_tokens == single.html_noise_tokens * 2


# ---------------------------------------------------------------------------
# RelevanceFilter
# ---------------------------------------------------------------------------

def test_relevance_filter_ranks_relevant_block_first():
    text = (
        "The weather today is sunny and warm.\n\n"
        "Python is a popular programming language for data science.\n\n"
        "Cats are wonderful pets and very independent."
    )
    rf = RelevanceFilter()
    hits = rf.rank(text, "programming language", iso3="eng")
    assert hits
    assert "Python" in hits[0].text


def test_relevance_filter_focus_keeps_original_order():
    text = "First block about cars.\n\nSecond block about music.\n\nThird block about cars and music."
    rf = RelevanceFilter()
    focused = rf.focus(text, "cars music", top_k=2, iso3="eng")
    assert focused.index("First") < focused.index("Third") if "First" in focused else True


def test_relevance_filter_empty_inputs():
    rf = RelevanceFilter()
    assert rf.rank("", "query") == []
    assert rf.rank("text", "") == []
    assert rf.focus("text", "", top_k=1) == ""


# ---------------------------------------------------------------------------
# SharedContext
# ---------------------------------------------------------------------------

def test_shared_context_put_get_roundtrip():
    ctx = SharedContext(ttl_seconds=60)
    entry = ctx.put("k1", "This is some example content to compress for sharing between agents.", agent_name="agent-a")
    assert entry.tokens_before > 0
    compressed = ctx.get("k1")
    original = ctx.get("k1", full=True)
    assert compressed is not None
    assert original == "This is some example content to compress for sharing between agents."


def test_shared_context_expired_entry_returns_none():
    ctx = SharedContext(ttl_seconds=0.05)
    ctx.put("k1", "some content here")
    time.sleep(0.1)
    assert ctx.get("k1") is None
    assert ctx.get_entry("k1") is None


def test_shared_context_missing_key():
    ctx = SharedContext()
    assert ctx.get("nope") is None


# ---------------------------------------------------------------------------
# OutputShaper
# ---------------------------------------------------------------------------

def test_output_shaper_injects_and_is_idempotent():
    shaper = OutputShaper()
    prompt = "You are an assistant."
    shaped = shaper.shape_system_prompt(prompt, VerbosityLevel.NO_RESTATEMENT)
    assert shaper.has_verbosity_steering(shaped)
    shaped_twice = shaper.shape_system_prompt(shaped, VerbosityLevel.NO_RESTATEMENT)
    assert shaped == shaped_twice


def test_output_shaper_off_is_noop():
    shaper = OutputShaper()
    prompt = "You are an assistant."
    assert shaper.shape_system_prompt(prompt, VerbosityLevel.OFF) == prompt


def test_output_shaper_remove_steering():
    shaper = OutputShaper()
    shaped = shaper.shape_system_prompt("Base prompt.", VerbosityLevel.MINIMUM_TOKENS)
    removed = shaper.remove_verbosity_steering(shaped)
    assert not shaper.has_verbosity_steering(removed)
    assert removed.strip() == "Base prompt."


def test_output_shaper_reshape_at_different_level_replaces_block():
    shaper = OutputShaper()
    shaped = shaper.shape_system_prompt("Base.", VerbosityLevel.SKIP_CEREMONY)
    reshaped = shaper.shape_system_prompt(shaped, VerbosityLevel.MINIMUM_TOKENS)
    assert f"synthelion-verbosity-{VerbosityLevel.MINIMUM_TOKENS.value}" in reshaped
    assert f"synthelion-verbosity-{VerbosityLevel.SKIP_CEREMONY.value} -->" not in reshaped


# ---------------------------------------------------------------------------
# CcrStore
# ---------------------------------------------------------------------------

def test_ccr_store_roundtrip_and_expiry():
    store = CcrStore(ttl_seconds=0.05)
    store.store("hash1", '{"a": 1}')
    assert store.retrieve("hash1") == '{"a": 1}'
    time.sleep(0.1)
    assert store.retrieve("hash1") is None


def test_ccr_store_missing_key():
    store = CcrStore()
    assert store.retrieve("missing") is None


def test_json_crusher_lossy_drop_populates_ccr_store():
    import json
    from synthelion.compressors.json_crusher import JsonCrusher
    from synthelion.ccr_store import get_instance

    rows = [{"id": i, "name": f"item-{i}", "extra_field_to_avoid_csv_win": "x" * 20} for i in range(30)]
    result = JsonCrusher(max_items=5).crush(json.dumps(rows), query="item")
    if result["strategy"] == "LossyRowDrop":
        assert result["ccr_hash"] is not None
        retrieved = get_instance().retrieve(result["ccr_hash"])
        assert retrieved is not None


# ---------------------------------------------------------------------------
# cost_estimator
# ---------------------------------------------------------------------------

def test_cost_estimator_usd_and_eur():
    price = default_usd_per_1k_tokens(LlmModel.GPT4)
    assert price == pytest.approx(0.03)
    cost_usd = usd(1000, price)
    assert cost_usd == pytest.approx(0.03)
    cost_eur = eur(1000, price)
    assert cost_eur == pytest.approx(0.03 * 0.92)


def test_cost_estimator_self_hosted_is_free():
    assert default_usd_per_1k_tokens(LlmModel.LLAMA3) == 0.0


# ---------------------------------------------------------------------------
# ModelTokenizer
# ---------------------------------------------------------------------------

def test_model_tokenizer_counts_tokens():
    tok = ModelTokenizer()
    n = tok.count_tokens("Hello world, this is a longer sentence to tokenize.")
    assert n > 0


def test_model_tokenizer_empty_text():
    assert ModelTokenizer().count_tokens("") == 0


def test_model_tokenizer_all_models_relative_scale():
    tok = ModelTokenizer()
    counts = tok.count_all_models("Some reasonably long piece of text for token estimation.")
    assert counts["llama3"] >= counts["gpt4"]
    assert counts["claude3"] <= counts["gpt4"]


# ---------------------------------------------------------------------------
# CommitGenerator
# ---------------------------------------------------------------------------

def test_commit_generator_detects_fix_type():
    diff = (
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-def broken():\n"
        "+def fixed_bug_in_parser():\n"
    )
    suggestion = CommitGenerator().generate_from_diff(diff)
    assert suggestion.type == "fix"
    assert suggestion.full_message.startswith("fix")


def test_commit_generator_empty_diff():
    suggestion = CommitGenerator().generate_from_diff("")
    assert suggestion.type == "chore"
    assert suggestion.full_message == "chore: empty diff"


def test_commit_generator_scope_from_single_dir():
    diff = "--- a/services/api.py\n+++ b/services/api.py\n@@ -1 +1 @@\n+add new feature\n"
    suggestion = CommitGenerator().generate_from_diff(diff)
    assert suggestion.scope == "services"


# ---------------------------------------------------------------------------
# ReviewService
# ---------------------------------------------------------------------------

def test_review_service_flags_security_pattern():
    diff = (
        "+++ b/config.py\n"
        "@@ -0,0 +1,2 @@\n"
        '+password = "hunter2"\n'
    )
    result = ReviewService().review_diff(diff)
    assert result.total_issues >= 1
    assert any(c.severity == "critical" for c in result.comments)


def test_review_service_empty_diff():
    result = ReviewService().review_diff("")
    assert result.total_issues == 0
    assert result.changed_files == 0


def test_review_service_todo_comment():
    diff = "+++ b/file.py\n@@ -0,0 +1 @@\n+# TODO: refactor this later\n"
    result = ReviewService().review_diff(diff)
    assert any("todo" in c.message.lower() for c in result.comments)


# ---------------------------------------------------------------------------
# CavecrewService
# ---------------------------------------------------------------------------

def test_cavecrew_investigate_missing_path():
    result = CavecrewService().investigate("Z:/does/not/exist/at/all")
    assert result.summary == "Path not found"


def test_cavecrew_investigate_this_repo_finds_symbols(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text("class Foo:\n    def bar(self):\n        pass\n")
    result = CavecrewService().investigate(str(tmp_path))
    assert "Mapped" in result.summary
    assert any("Foo" in d or "bar" in d for d in result.details)


def test_cavecrew_review_delegates_to_review_service():
    diff = "+++ b/config.py\n@@ -0,0 +1 @@\n+token = \"abc\"\n"
    result = CavecrewService().review(diff)
    assert result.agent == "cavecrew-reviewer"
    assert "Reviewed diff" in result.summary


def test_cavecrew_build_reports_missing_files():
    result = CavecrewService().build("fix parser", ["Z:/nope.py"])
    assert any("not found" in d.lower() for d in result.details)


# ---------------------------------------------------------------------------
# ProjectWiki
# ---------------------------------------------------------------------------

def test_project_wiki_generates_markdown(tmp_path):
    (tmp_path / "main.py").write_text("print('hello world')\n")
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")

    wiki = ProjectWiki()
    markdown = wiki.generate(str(tmp_path))

    assert "Project Wiki" in markdown
    assert "main.py" in markdown
    assert "requests" in markdown


def test_project_wiki_missing_directory_raises():
    with pytest.raises(NotADirectoryError):
        ProjectWiki().generate("Z:/definitely/not/a/real/path")


def test_project_wiki_metadata_only(tmp_path):
    (tmp_path / "main.py").write_text("x = 1\n")
    wiki = ProjectWiki()
    markdown = wiki.generate(str(tmp_path), include_contents=False)
    assert "Key Components" not in markdown
    assert "File Structure" in markdown


def test_project_wiki_synthesizes_overview_from_readme(tmp_path):
    (tmp_path / "README.md").write_text(
        "# MyLib\nThis library helps developers compress prompts. "
        "It supports many languages. It has zero dependencies. It is fast."
    )
    (tmp_path / "main.py").write_text("def run():\n    pass\n")
    markdown = ProjectWiki().generate(str(tmp_path))
    assert "Overview" in markdown
    assert "compress prompts" in markdown


def test_project_wiki_media_archive_overview(tmp_path):
    for i in range(5):
        (tmp_path / f"photo{i}.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 50)
    markdown = ProjectWiki().generate(str(tmp_path))
    assert "Media & Binary Assets" in markdown
    assert "image" in markdown


def test_project_wiki_npm_dependencies_and_engines(tmp_path):
    import json
    pkg = {
        "name": "my-app", "version": "2.1.0",
        "engines": {"node": ">=18.0.0", "npm": ">=9.0.0"},
        "packageManager": "pnpm@8.6.0",
        "dependencies": {"react": "^18.2.0"},
        "devDependencies": {"typescript": "^5.3.0"},
        "peerDependencies": {"react-dom": "^18.2.0"},
        "optionalDependencies": {"fsevents": "^2.3.0"},
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    (tmp_path / "tsconfig.json").write_text("{}")
    (tmp_path / "index.ts").write_text("function main() {}\n")

    markdown = ProjectWiki().generate(str(tmp_path))
    assert "NodeJs/TypeScript" in markdown
    assert "node: >=18.0.0" in markdown
    assert "npm: >=9.0.0" in markdown
    assert "pnpm: 8.6.0" in markdown
    assert "npm:peer" in markdown
    assert "react-dom @ ^18.2.0" in markdown
    assert "npm:optional" in markdown
    assert "fsevents @ ^2.3.0" in markdown
