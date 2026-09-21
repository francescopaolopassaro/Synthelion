# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# (c) 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Structured content must be compressed, not corrupted — and not refused.

Every compression level in core.py is a *word* filter: it drops low-signal
tokens, and punctuation is not a word. Applied to JSON that removes every
brace, quote and colon; applied to Python it removes `def` and `=`; applied to
SQL it removes FROM. The output is not "compressed", it is destroyed — and
silently, because nothing raises.

The fix routes structured input to its dedicated structure-aware compressor
instead, so it still shrinks. Two separate contracts are pinned here:

* shapes the router has a strategy for (JSON, code, SQL, HTML) must come back
  compressed *and* still usable — code that still parses, SQL that still has
  its clauses, JSON whose data survives the compact rewrite;
* shapes it has no strategy for (YAML/config) must come back untouched, never
  prose-compressed.
"""
from __future__ import annotations

import ast
import json

import pytest

from synthelion.core import CompressionService
from synthelion.models import CompressionLevel

JSON_SAMPLE = ('{"user": {"id": 42, "name": "Mario Rossi", "active": true, '
               '"roles": ["admin", "editor"]}, "updated_at": "2026-09-21T10:00:00Z"}')

PY_SAMPLE = '''def compute_total(items, discount=0.0):
    """Return the discounted total."""
    subtotal = sum(i.price * i.qty for i in items)
    if discount > 0:
        subtotal = subtotal * (1 - discount)
    return round(subtotal, 2)
'''

HTML_SAMPLE = ('<div class="card"><h2 id="title">Report</h2>'
               '<p>Revenue grew by <strong>12%</strong>.</p></div>')

SQL_SAMPLE = ('SELECT u.id, u.email, COUNT(o.id) AS orders\n'
              'FROM users u LEFT JOIN orders o ON o.user_id = u.id\n'
              "WHERE u.created_at >= '2026-01-01'\nGROUP BY u.id;")

YAML_SAMPLE = '''service:
  name: synthelion
  port: 8787
  features:
    - compression
    - privacy
'''

JS_SAMPLE = '''function debounce(fn, wait) {
  let timer = null;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), wait);
  };
}'''

ALL_LEVELS = [lvl for lvl in CompressionLevel if lvl is not CompressionLevel.NONE]


@pytest.fixture(scope="module")
def svc():
    return CompressionService()


class TestStructuredContentSurvives:
    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_json_keeps_its_data(self, svc, level):
        """JsonCrusher rewrites JSON into a compact key/value form on purpose —
        that is the token saving. What must survive is the *data*: every key
        and every value still present, none of it word-filtered away."""
        out = svc.compress(JSON_SAMPLE, level=level).compressed_text
        for fragment in ("id", "42", "Mario Rossi", "active", "admin", "editor",
                         "2026-09-21T10:00:00Z"):
            assert fragment in out, f"{fragment!r} was lost"

    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_json_actually_shrinks(self, svc, level):
        import json as _json
        big = _json.dumps({"users": [
            {"id": i, "name": f"User {i}", "email": f"u{i}@example.com",
             "roles": ["admin"], "active": True} for i in range(40)]}, indent=2)
        out = svc.compress(big, level=level).compressed_text
        assert len(out) < len(big) * 0.9, "structured routing produced no saving"

    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_python_stays_parseable(self, svc, level):
        out = svc.compress(PY_SAMPLE, level=level).compressed_text
        ast.parse(out)

    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_html_keeps_its_readable_content(self, svc, level):
        """HtmlExtractor pulls the readable text out of markup — the markup
        itself is chrome an agent does not need. The content must survive;
        case does not, since the extracted text is then lemmatised."""
        out = svc.compress(HTML_SAMPLE, level=level).compressed_text.lower()
        assert "report" in out and "12%" in out

    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_sql_keeps_its_clauses(self, svc, level):
        out = svc.compress(SQL_SAMPLE, level=level).compressed_text.upper()
        for keyword in ("SELECT", "FROM", "WHERE", "GROUP BY"):
            assert keyword in out, f"{keyword} was dropped"

    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_yaml_is_returned_untouched(self, svc, level):
        """No YAML strategy exists, so the only safe answer is to leave it
        alone — prose-compressing it strips the colons that are the structure."""
        result = svc.compress(YAML_SAMPLE, level=level)
        assert result.compressed_text == YAML_SAMPLE
        assert result.error_message and "no structure-aware" in result.error_message

    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_javascript_keeps_its_syntax(self, svc, level):
        out = svc.compress(JS_SAMPLE, level=level).compressed_text
        assert "function" in out and "{" in out and "}" in out

    @pytest.mark.parametrize("level", ALL_LEVELS)
    def test_python_actually_shrinks(self, svc, level):
        from pathlib import Path
        source = Path("synthelion/cache_aligner.py").read_text(encoding="utf-8")
        out = svc.compress(source, level=level).compressed_text
        ast.parse(out)                      # still valid Python
        assert len(out) < len(source)       # and smaller


class TestProseStillCompresses:
    """The guard must be narrow: ordinary text still has to shrink."""

    @pytest.mark.parametrize("text", [
        "The quarterly financial report shows that revenue increased significantly "
        "during the last three months of the year.",
        "Il rapporto trimestrale mostra che i ricavi sono aumentati in modo "
        "significativo negli ultimi tre mesi dell'anno.",
        # A colon in prose must not be read as a config key.
        "Note: the meeting is postponed. Reason: the client asked for more time. "
        "We will reschedule it as soon as possible.",
    ])
    def test_prose_is_still_compressed(self, svc, text):
        out = svc.compress(text, level=CompressionLevel.AGGRESSIVE).compressed_text
        assert len(out) < len(text)

    def test_short_indented_prose_is_not_mistaken_for_yaml(self, svc):
        text = ("Summary of the meeting.\n"
                "The budget was approved by the committee.\n"
                "The timeline remains tight for the next release.")
        out = svc.compress(text, level=CompressionLevel.AGGRESSIVE).compressed_text
        assert len(out) < len(text)


class TestRouterOverride:
    """ContentRouter classifies first and may deliberately choose prose; the
    guard must not veto that decision."""

    def test_json_schema_still_reaches_the_nlp_compressor(self):
        from synthelion.content_router import ContentRouter
        schema = json.dumps({
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "The full name of the customer placing the order"},
                "email": {"type": "string",
                          "description": "A valid email address used to send the confirmation"},
            },
            "required": ["name"],
        })
        result = ContentRouter().route(schema)
        assert result.strategy_used.startswith("NlpCompression")

    def test_allow_structured_opt_out_works(self, svc):
        out = svc.compress(JSON_SAMPLE, level=CompressionLevel.AGGRESSIVE,
                           allow_structured=True).compressed_text
        assert out != JSON_SAMPLE          # the opt-out really does bypass the guard

    def test_router_does_not_destroy_structured_content(self):
        """The routed path is the supported way to compress these — it must
        produce something that is still machine-readable."""
        from synthelion.content_router import ContentRouter
        router = ContentRouter()
        py = router.route(PY_SAMPLE)
        ast.parse(py.compressed)
        sql = router.route(SQL_SAMPLE)
        assert "FROM" in sql.compressed.upper()
