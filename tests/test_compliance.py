# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# (c) 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for the AI Compliance Engine (synthelion/compliance/)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from synthelion.compliance import (
    ACTIVE, INACTIVE, STAGING, Action, ComplianceEngine, Scope,
    coverage_gaps, default_rules, traceability_matrix,
)
from synthelion.compliance import audit, documents
from synthelion.compliance.pdf import PdfDocument, wrap


def _isolate(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def _engine(**kw):
    """Engine built from the default registry, independent of local config."""
    return ComplianceEngine(rules=default_rules(), **kw)


# ---------------------------------------------------------------------------
# Rules and traceability
# ---------------------------------------------------------------------------

class TestRules:
    def test_every_implemented_rule_has_a_legal_reference(self):
        for rule in default_rules():
            if rule.backend == "not_implemented" and not rule.legal:
                continue        # CUSTOM_RULES answers no specific article
            assert rule.legal, f"{rule.id} has no legal reference"
            for ref in rule.legal:
                assert ref.framework and ref.article and ref.obligation

    def test_every_enabled_rule_backend_is_dispatchable(self):
        """An *enabled* rule naming a backend nothing implements would silently
        pass. Rules declared `not_implemented` ship disabled on purpose, so the
        gap is reported instead of hidden."""
        engine = _engine()
        for rule in engine.rules:
            if not rule.enabled:
                continue
            state, _ = engine._backend_state(rule.backend)
            assert state != "unavailable", f"{rule.id} -> {rule.backend} is not implemented"

    def test_unimplemented_rules_are_declared_not_omitted(self):
        """The registry must name the controls the specification asks for but
        that do not exist, so the technical file reports them as uncovered
        rather than presenting a complete-looking matrix."""
        rules = default_rules()
        declared = {r.id for r in rules if r.backend == "not_implemented"}
        assert {"TOXICITY_HATE_SPEECH", "HALLUCINATION_CHECK", "PHI_HEALTH_DATA"} <= declared
        for rule in rules:
            if rule.backend == "not_implemented":
                assert rule.enabled is False, f"{rule.id} claims coverage it does not have"
                assert "NOT IMPLEMENTED" in rule.description

    def test_default_rules_are_independent_copies(self):
        a, b = default_rules(), default_rules()
        a[0].enabled = False
        assert b[0].enabled is True

    def test_traceability_matrix_has_a_row_per_article(self):
        rules = default_rules()
        expected = sum(len(r.legal) for r in rules)
        assert len(traceability_matrix(rules)) == expected

    def test_disabling_a_rule_adds_it_to_the_coverage_gaps(self):
        rules = default_rules()
        before = {g["rule_id"] for g in coverage_gaps(rules)}
        assert "PII_REDACTION" not in before
        next(r for r in rules if r.id == "PII_REDACTION").enabled = False
        after = {g["rule_id"] for g in coverage_gaps(rules)}
        assert "PII_REDACTION" in after
        assert after - before == {"PII_REDACTION"}

    def test_scope_covers(self):
        assert Scope.BOTH.covers(Scope.INPUT) and Scope.BOTH.covers(Scope.OUTPUT)
        assert Scope.INPUT.covers(Scope.INPUT)
        assert not Scope.INPUT.covers(Scope.OUTPUT)


# ---------------------------------------------------------------------------
# Engine behaviour
# ---------------------------------------------------------------------------

class TestEngine:
    def test_clean_text_is_allowed(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        r = _engine().evaluate("The quarterly report is ready for review.", write_audit=False)
        assert r.allowed and r.decision == "allow"

    def test_pii_is_redacted_not_blocked(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        r = _engine().evaluate("write to mario.rossi@example.com", write_audit=False)
        assert r.allowed and r.decision == "redact"
        assert "mario.rossi@example.com" not in r.text

    def test_privacy_and_financial_rules_report_independently(self, tmp_path, monkeypatch):
        """Both rules share one analyzer; whichever runs first must not hide
        the other's finding by redacting the payload out from under it."""
        _isolate(tmp_path, monkeypatch)
        r = _engine().evaluate(
            "IBAN IT60X0542811101000000123456 and mail a@b.com", write_audit=False)
        fired = {f.rule_id for f in r.findings}
        assert {"PII_REDACTION", "FINANCIAL_DATA"} <= fired

    def test_inactive_engine_changes_nothing(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        text = "mail a@b.com"
        r = _engine(status=INACTIVE).evaluate(text, write_audit=False)
        assert r.allowed and r.text == text and r.findings == []

    def test_staging_records_findings_but_never_modifies(self, tmp_path, monkeypatch):
        """The whole point of staging: measure a policy against real traffic
        before it starts refusing or rewriting anything."""
        _isolate(tmp_path, monkeypatch)
        text = "mail a@b.com"
        r = _engine(status=STAGING).evaluate(text, write_audit=False)
        assert r.allowed
        assert r.text == text          # not redacted
        assert r.findings              # but recorded

    def test_output_sanitisation_strips_active_markup(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        r = _engine().evaluate("<p>ok</p><script>steal()</script>",
                               scope=Scope.OUTPUT, write_audit=False)
        assert "<script" not in r.text and "<p>ok</p>" in r.text

    def test_output_sanitisation_strips_inline_handlers(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        r = _engine().evaluate('<img src=x onerror="steal()">',
                               scope=Scope.OUTPUT, write_audit=False)
        assert "onerror" not in r.text

    def test_input_only_rules_do_not_run_on_output(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        engine = _engine()
        ids = {r.id for r in engine.active_rules(Scope.OUTPUT)}
        assert "PROMPT_INJECTION" not in ids   # scope=input
        assert "AI_DISCLOSURE" in ids          # scope=output

    def test_disclosure_disclaimer_is_attached_to_output(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        r = _engine().evaluate("Here is the answer.", scope=Scope.OUTPUT, write_audit=False)
        assert r.disclaimers

    def test_block_action_refuses_and_keeps_original_text(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        rules = default_rules()
        for r in rules:
            r.enabled = r.id == "PII_REDACTION"
        next(r for r in rules if r.id == "PII_REDACTION").action = Action.BLOCK
        result = ComplianceEngine(rules=rules).evaluate("mail a@b.com", write_audit=False)
        assert result.blocked and result.decision == "block"
        assert result.text == "mail a@b.com"

    def test_disabled_rule_does_not_run(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        rules = default_rules()
        for r in rules:
            r.enabled = False
        result = ComplianceEngine(rules=rules).evaluate("mail a@b.com", write_audit=False)
        assert result.findings == [] and result.decision == "allow"


class TestBackendHealth:
    def test_health_reports_every_rule(self):
        engine = _engine()
        assert len(engine.backend_health()) == len(engine.rules)

    def test_enabled_rule_with_disabled_guard_is_flagged(self, monkeypatch):
        """The dangerous combination: the policy says the control is on, the
        guard behind it is off, and the technical file would claim coverage."""
        import synthelion.compliance.engine as engine_mod

        real = engine_mod.ComplianceEngine._backend_state

        def fake(self, backend):
            if backend == "enterprise_guard":
                return "disabled", "switched off in the configuration"
            return real(self, backend)

        monkeypatch.setattr(engine_mod.ComplianceEngine, "_backend_state", fake)
        bad = _engine().ineffective_rules()
        assert any(h["rule_id"] == "SECRETS_DETECTION" for h in bad)

    def test_disabled_rule_is_not_reported_as_ineffective(self, monkeypatch):
        """An intentionally-off rule is a coverage gap, not a broken control."""
        import synthelion.compliance.engine as engine_mod
        real = engine_mod.ComplianceEngine._backend_state
        monkeypatch.setattr(
            engine_mod.ComplianceEngine, "_backend_state",
            lambda self, b: ("disabled", "off") if b == "enterprise_guard" else real(self, b))
        rules = default_rules()
        next(r for r in rules if r.id == "SECRETS_DETECTION").enabled = False
        assert ComplianceEngine(rules=rules).ineffective_rules() == []


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

class TestAuditTrail:
    def test_entry_is_written_and_chain_verifies(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        engine = _engine()
        for i in range(3):
            engine.evaluate(f"mail user{i}@example.com")
        assert audit.verify_chain().valid
        assert audit.verify_chain().entries == 3

    def test_audit_never_stores_payload_text(self, tmp_path, monkeypatch):
        """An audit log of prompts would recreate the exposure the privacy
        rules exist to prevent — and become personal data itself."""
        _isolate(tmp_path, monkeypatch)
        secret = "contact giuseppe.verdi@example.com about invoice 12345"
        _engine().evaluate(secret)
        raw = json.dumps(audit.read_entries())
        assert "giuseppe.verdi@example.com" not in raw
        assert audit.text_fingerprint(secret) in raw

    def test_edited_entry_breaks_the_chain(self, tmp_path, monkeypatch):
        home = _isolate(tmp_path, monkeypatch)
        engine = _engine()
        for i in range(3):
            engine.evaluate(f"mail user{i}@example.com")

        path = home / ".synthelion" / "compliance_audit.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[1])
        entry["decision"] = "allow"           # tamper
        lines[1] = json.dumps(entry, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        verification = audit.verify_chain()
        assert not verification.valid
        assert verification.broken_at == 1

    def test_removed_entry_breaks_the_chain(self, tmp_path, monkeypatch):
        home = _isolate(tmp_path, monkeypatch)
        engine = _engine()
        for i in range(3):
            engine.evaluate(f"mail user{i}@example.com")
        path = home / ".synthelion" / "compliance_audit.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        del lines[1]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert not audit.verify_chain().valid

    def test_statistics_aggregate_findings(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        engine = _engine()
        engine.evaluate("mail a@b.com")
        engine.evaluate("nothing to see here")
        stats = audit.statistics()
        assert stats["total_calls"] == 2
        assert stats["calls_with_findings"] >= 1
        assert stats["by_category"].get("privacy", 0) >= 1

    def test_conformity_receipt_is_bound_to_its_entry(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        result = _engine().evaluate("all clear")
        receipt = audit.conformity_receipt(result.audit_entry)
        assert receipt["chain_hash"] == result.audit_entry["hash"]
        assert receipt["request_hash"] == result.audit_entry["request_hash"]

    def test_empty_log_verifies_as_valid(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        v = audit.verify_chain()
        assert v.valid and v.entries == 0


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class TestDocuments:
    @pytest.mark.parametrize("kind", ["technical-file", "dpia", "fria", "executive-report"])
    def test_every_document_generates_and_renders(self, kind, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        doc = documents.generate(kind, engine=_engine())
        assert doc["document"] and doc["generated_at"]
        out = documents.to_pdf(doc, tmp_path / f"{kind}.pdf")
        data = out.read_bytes()
        assert data.startswith(b"%PDF-1.4")
        assert data.rstrip().endswith(b"%%EOF")
        assert len(data) > 1000

    @pytest.mark.parametrize("kind", ["technical-file", "dpia", "fria", "executive-report"])
    def test_every_generated_section_reaches_the_pdf(self, kind, tmp_path, monkeypatch):
        """A section generated into the dict but not rendered is invisible in
        the document a regulator actually reads — `backend_health` and the
        FRIA's `oversight_measures` were both dropped that way."""
        _isolate(tmp_path, monkeypatch)
        doc = documents.generate(kind, engine=_engine())
        rendered = {
            "document", "generated_at", "disclaimer", "system", "engine", "guardrails",
            "traceability_matrix", "record_keeping", "human_oversight",
            "processing_description", "measures", "necessity_and_proportionality",
            "deployment_context", "risks", "rights_assessment", "oversight_measures",
            "statistics", "audit_chain", "backend_health", "ineffective_controls",
            "coverage_gaps", "open_items",
            "period_days",          # carried in the document title
        }
        unrendered = set(doc) - rendered
        assert not unrendered, f"{kind}: generated but never rendered: {sorted(unrendered)}"

    @pytest.mark.parametrize("kind", ["technical-file", "dpia", "fria", "executive-report"])
    def test_no_python_repr_leaks_into_the_pdf(self, kind, tmp_path, monkeypatch):
        """Handing `key_values` a list of dicts printed 2 kB of Python repr
        into the DPIA. Structures must be rendered as tables or bullet lists."""
        _isolate(tmp_path, monkeypatch)
        out = documents.to_pdf(documents.generate(kind, engine=_engine()), tmp_path / f"{kind}.pdf")
        data = out.read_bytes()
        for marker in (b"{'id':", b"'risk_level':", b"'backend':", b"[{'"):
            assert marker not in data, f"{kind}: raw Python repr reached the page"

    def test_unknown_document_kind_is_rejected(self):
        with pytest.raises(ValueError):
            documents.generate("not-a-document")

    def test_documents_are_json_serialisable(self, tmp_path, monkeypatch):
        """The dict is the source of truth — nothing may exist only in the PDF."""
        _isolate(tmp_path, monkeypatch)
        for kind in documents.GENERATORS:
            json.dumps(documents.generate(kind, engine=_engine()))

    def test_technical_file_reports_disabled_controls(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        rules = default_rules()
        next(r for r in rules if r.id == "PROMPT_INJECTION").enabled = False
        doc = documents.technical_file(engine=ComplianceEngine(rules=rules))
        assert any(g["rule_id"] == "PROMPT_INJECTION" for g in doc["coverage_gaps"])

    def test_assessments_flag_items_needing_human_judgement(self, tmp_path, monkeypatch):
        """A DPIA/FRIA must not auto-fill judgements it cannot make."""
        _isolate(tmp_path, monkeypatch)
        for kind in ("dpia", "fria"):
            doc = documents.generate(kind, engine=_engine())
            assert doc["open_items"]
            assert "requires human assessment" in json.dumps(doc)


class TestPdfWriter:
    def test_xref_offsets_point_at_their_objects(self, tmp_path):
        """A wrong offset yields a file readers reject — cheap to get wrong,
        so assert the structure rather than just the byte count."""
        doc = PdfDocument("Title", "Subtitle")
        doc.heading("Section")
        doc.paragraph("Body text. " * 200)     # forces a page break
        doc.table(["A", "B"], [["1", "2"]], [0.5, 0.5])
        doc.bar_chart([("x", 10), ("y", 5)])
        data = bytes(doc.to_bytes())

        start = int(re.search(rb"startxref\s+(\d+)", data).group(1))
        assert data[start:start + 4] == b"xref"
        lines = data[start:].split(b"trailer")[0].splitlines()
        offsets = [int(l.strip()[:10]) for l in lines[2:]
                   if len(l.strip()) >= 18 and l.strip().endswith((b"n", b"f"))]
        for i, off in enumerate(offsets):
            if i == 0:
                continue                        # free head entry
            assert data[off:off + len(f"{i} 0 obj".encode())] == f"{i} 0 obj".encode()

    def test_non_ascii_is_transliterated_not_dropped(self, tmp_path):
        """An accented name silently vanishing from a compliance document
        would be worse than an approximated one."""
        doc = PdfDocument("Rapporto")
        doc.paragraph("Società è français — naïve")
        data = doc.to_bytes()
        assert b"Societ" in data and b"fran" in data

    def test_long_word_is_hard_split_instead_of_overflowing(self):
        lines = wrap("A" * 500, 10, 200)
        assert len(lines) > 1
        assert all(line for line in lines)

    def test_multiple_pages_are_emitted(self):
        doc = PdfDocument("Long")
        for _ in range(12):
            doc.paragraph("Paragraph text that fills the page. " * 30)
        data = doc.to_bytes()
        count = int(re.search(rb"/Type\s*/Pages\s*/Count\s+(\d+)", data).group(1))
        assert count > 1
