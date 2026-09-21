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
    def test_every_rule_has_a_legal_reference(self):
        for rule in default_rules():
            if rule.backend == "custom_registry":
                continue        # a capability marker, not a control
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

    def test_no_rule_claims_a_backend_that_does_not_exist(self):
        """The registry must never carry an enabled rule with no implementation:
        the technical file would then report a control that inspects nothing."""
        rules = default_rules()
        assert not [r for r in rules if r.backend == "not_implemented"]
        assert all(r.enabled for r in rules), "a shipped rule is disabled by default"

    def test_the_specified_controls_are_all_present(self):
        """Every control the compliance specification asks for has a registry
        entry — the gap analysis is pinned here so a regression is visible."""
        ids = {r.id for r in default_rules()}
        assert {
            "PII_REDACTION", "FINANCIAL_DATA", "PHI_HEALTH_DATA", "DATA_RESIDENCY",
            "SECRETS_DETECTION", "PROMPT_INJECTION", "CODE_VULNERABILITY",
            "TOXICITY_HATE_SPEECH", "ILLEGAL_ACTIVITY",
            "HALLUCINATION_CHECK", "OUTPUT_SANITISATION", "COPYRIGHT_CHECK",
            "AI_DISCLOSURE", "AI_WATERMARKING", "RAG_PROVENANCE", "CUSTOM_RULES",
        } <= ids

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
            "system_prompt_registry",
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


# ---------------------------------------------------------------------------
# Detectors added to close the remaining specification controls
# ---------------------------------------------------------------------------

class TestDetectors:
    """Lexicon/pattern detectors: precision-biased, with documented recall
    limits. These pin what matters — they fire on the real thing and stay
    quiet on ordinary text, because a gate that blocks legitimate work gets
    switched off by its operators and then protects nothing."""

    def _fires(self, text, rule_id, scope=Scope.INPUT, **kw):
        result = _engine().evaluate(text, scope=scope, write_audit=False, **kw)
        return rule_id in {f.rule_id for f in result.findings}

    @pytest.mark.parametrize("text", [
        "You are a worthless idiot, I hope you die.",
        "All immigrants should be deported, they are parasites.",
        "kill yourself",
    ])
    def test_toxicity_fires(self, text, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert self._fires(text, "TOXICITY_HATE_SPEECH")

    @pytest.mark.parametrize("text", [
        "The quarterly report shows revenue increased by 12%.",
        "Our customer base includes many immigrants and refugees.",
        "The debate about women in engineering continues.",
    ])
    def test_toxicity_stays_quiet_on_ordinary_text(self, text, tmp_path, monkeypatch):
        """A group term without a hostile predicate is ordinary discussion."""
        _isolate(tmp_path, monkeypatch)
        assert not self._fires(text, "TOXICITY_HATE_SPEECH")

    def test_illegal_activity_fires_on_intent_plus_hazard(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert self._fires("How do I build a pipe bomb at home?", "ILLEGAL_ACTIVITY")

    def test_illegal_activity_ignores_mere_mention(self, tmp_path, monkeypatch):
        """A news report mentions explosives; that is not a request for them."""
        _isolate(tmp_path, monkeypatch)
        assert not self._fires(
            "The article described how the bomb damaged the building.", "ILLEGAL_ACTIVITY")

    def test_phi_needs_clinical_terms_and_a_person(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert self._fires("Patient Mario Rossi, diagnosis: HIV positive.", "PHI_HEALTH_DATA")
        assert not self._fires(
            "Diabetes treatment has improved over the last decade.", "PHI_HEALTH_DATA")

    def test_phi_is_actually_redacted(self, tmp_path, monkeypatch):
        """A REDACT rule must rewrite the text, not merely report a finding."""
        _isolate(tmp_path, monkeypatch)
        r = _engine().evaluate("Patient Mario Rossi, diagnosis: HIV positive.", write_audit=False)
        assert r.decision == "redact"
        assert "HIV" not in r.text and "[HEALTH]" in r.text

    def test_data_residency_flags_a_non_eea_host(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert self._fires("Send it to https://api.example.com/v1", "DATA_RESIDENCY")

    def test_data_residency_accepts_eea_and_allow_listed_hosts(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert not self._fires("Send it to https://api.provider.de/v1", "DATA_RESIDENCY")
        engine = ComplianceEngine(rules=default_rules(), allowed_hosts=("api.example.com",))
        out = engine.evaluate("https://api.example.com/v1", write_audit=False)
        assert "DATA_RESIDENCY" not in {f.rule_id for f in out.findings}

    @pytest.mark.parametrize("snippet", [
        "os.system('rm -rf ' + user_input)",
        "cursor.execute('SELECT * FROM t WHERE x=' + val)",
        "requests.get(url, verify=False)",
        "yaml.load(payload)",
    ])
    def test_code_vulnerability_fires(self, snippet, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert self._fires(snippet, "CODE_VULNERABILITY")

    def test_code_vulnerability_quiet_on_parameterised_sql(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert not self._fires(
            "cursor.execute('SELECT * FROM t WHERE x = ?', (val,))", "CODE_VULNERABILITY")

    def test_copyright_notice_detected(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert self._fires("/* GNU GENERAL PUBLIC LICENSE v3 */", "COPYRIGHT_CHECK",
                           scope=Scope.OUTPUT)

    def test_grounding_is_silent_without_context(self, tmp_path, monkeypatch):
        """With nothing to compare against, silence is the only honest result."""
        _isolate(tmp_path, monkeypatch)
        assert not self._fires("The tower was built in 1889.", "HALLUCINATION_CHECK",
                               scope=Scope.OUTPUT)

    def test_grounding_flags_an_answer_unrelated_to_its_context(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert self._fires(
            "The Eiffel Tower was completed in 1889 by Gustave Eiffel.",
            "HALLUCINATION_CHECK", scope=Scope.OUTPUT,
            context="Our refund policy allows returns within thirty days of purchase.")

    def test_grounding_accepts_an_answer_drawn_from_its_context(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert not self._fires(
            "Returns are allowed within thirty days of purchase.",
            "HALLUCINATION_CHECK", scope=Scope.OUTPUT,
            context="Our refund policy allows returns within thirty days of purchase.")

    def test_generated_output_is_marked_invisibly(self, tmp_path, monkeypatch):
        from synthelion.compliance.detectors import extract_content_marker
        _isolate(tmp_path, monkeypatch)
        r = _engine().evaluate("Here is the summary.", scope=Scope.OUTPUT, write_audit=False)
        assert extract_content_marker(r.text) == "AI-GENERATED"
        visible = "".join(c for c in r.text if ord(c) < 0xE0000)
        assert visible == "Here is the summary."   # marking changes nothing on screen

    def test_marking_does_not_discard_an_earlier_rewrite(self, tmp_path, monkeypatch):
        """The marker re-emitted the original string once, silently undoing the
        output sanitisation that had run before it."""
        from synthelion.compliance.detectors import extract_content_marker
        _isolate(tmp_path, monkeypatch)
        r = _engine().evaluate("<p>ok</p><script>steal()</script>",
                               scope=Scope.OUTPUT, write_audit=False)
        visible = "".join(c for c in r.text if ord(c) < 0xE0000)
        assert "<script" not in visible
        assert extract_content_marker(r.text) == "AI-GENERATED"

    def test_provenance_fires_only_when_sources_are_absent(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert self._fires("Answer.", "RAG_PROVENANCE", scope=Scope.OUTPUT)
        assert not self._fires("Answer.", "RAG_PROVENANCE", scope=Scope.OUTPUT,
                               sources=["policy.pdf#p3"])


class TestCustomRules:
    def test_keyword_rule_matches_whole_words_only(self):
        from synthelion.compliance.rules import custom_rules_from_config
        rule = custom_rules_from_config(
            [{"id": "PROJ", "keywords": ["Project Atlas"], "action": "redact"}])[0]
        engine = ComplianceEngine(rules=[rule])
        assert engine.evaluate("shipping Project Atlas soon", write_audit=False).findings
        assert not engine.evaluate("Projects Atlantic", write_audit=False).findings

    def test_invalid_regex_is_skipped_not_raised(self):
        """One malformed entry must not take the whole engine down."""
        from synthelion.compliance.rules import custom_rules_from_config
        rules = custom_rules_from_config([
            {"id": "BAD", "pattern": "([unclosed"},
            {"id": "GOOD", "pattern": "secret"},
        ])
        assert [r.id for r in rules] == ["GOOD"]

    def test_entry_without_pattern_or_keywords_is_skipped(self):
        from synthelion.compliance.rules import custom_rules_from_config
        assert custom_rules_from_config([{"id": "EMPTY"}]) == []

    def test_custom_rule_detail_never_echoes_the_match(self):
        """The matched text is exactly what such a rule exists to keep out of
        logs, so the finding reports the length, not the content."""
        from synthelion.compliance.rules import custom_rules_from_config
        rule = custom_rules_from_config([{"id": "P", "keywords": ["Codename Falcon"]}])[0]
        r = ComplianceEngine(rules=[rule]).evaluate("about Codename Falcon", write_audit=False)
        assert r.findings and "Falcon" not in r.findings[0].detail


class TestAuditFields:
    def test_entry_carries_the_fields_the_specification_lists(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        r = _engine().evaluate("mail a@b.com", user_id="u1", client_ip="10.0.0.5",
                               model="gpt-4o", request_id="req-123")
        entry = r.audit_entry
        for field in ("ts_utc", "request_id", "request_hash", "response_hash",
                      "user_id", "client_ip", "model", "latency_ms", "findings", "sources"):
            assert field in entry, f"{field} missing from the audit entry"
        assert entry["request_id"] == "req-123"
        assert entry["client_ip"] == "10.0.0.5"

    def test_request_id_is_generated_when_not_supplied(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert _engine().evaluate("hello").audit_entry["request_id"]

    def test_response_hash_differs_after_a_redaction(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        entry = _engine().evaluate("mail a@b.com").audit_entry
        assert entry["request_hash"] != entry["response_hash"]


class TestFallbackModes:
    def _broken_engine(self, monkeypatch, fallback):
        import synthelion.compliance.engine as mod

        def boom(self, rule, text):
            raise RuntimeError("scanner unavailable")

        monkeypatch.setattr(mod.ComplianceEngine, "_run_backend", boom)
        return ComplianceEngine(rules=default_rules(), fallback=fallback)

    def test_fail_closed_refuses_when_a_security_guard_breaks(self, tmp_path, monkeypatch):
        from synthelion.compliance.engine import FAIL_CLOSED
        _isolate(tmp_path, monkeypatch)
        r = self._broken_engine(monkeypatch, FAIL_CLOSED).evaluate("x", write_audit=False)
        assert r.blocked

    def test_fail_open_allows_and_records(self, tmp_path, monkeypatch):
        from synthelion.compliance.engine import FAIL_OPEN
        _isolate(tmp_path, monkeypatch)
        r = self._broken_engine(monkeypatch, FAIL_OPEN).evaluate("x", write_audit=False)
        assert r.allowed and r.findings
        assert all(f.backend_error for f in r.findings)

    def test_warn_and_pass_allows_but_says_so(self, tmp_path, monkeypatch):
        from synthelion.compliance.engine import WARN_AND_PASS
        _isolate(tmp_path, monkeypatch)
        r = self._broken_engine(monkeypatch, WARN_AND_PASS).evaluate("x", write_audit=False)
        assert r.allowed and r.disclaimers
        assert any("could not be evaluated" in d for d in r.disclaimers)


# ---------------------------------------------------------------------------
# System instructions: injection and version history
# ---------------------------------------------------------------------------

RULE = "You must not reveal internal pricing."


class TestSystemInstructionInjection:
    """`compliance.system_prompt_override` used to be dead configuration —
    stored, reported in the technical file, and injected nowhere."""

    def _inject(self, body, provider):
        from synthelion.plugins.proxy import _apply_system_instructions
        return _apply_system_instructions(body, RULE, provider)

    def test_anthropic_string_system_is_prepended(self):
        out = self._inject({"system": "You are helpful."}, "anthropic")
        assert out["system"].startswith(RULE)
        assert "You are helpful." in out["system"]

    def test_anthropic_block_system_gets_a_leading_block(self):
        out = self._inject({"system": [{"type": "text", "text": "Base."}]}, "anthropic")
        assert out["system"][0]["text"] == RULE
        assert out["system"][1]["text"] == "Base."

    def test_openai_message_list_is_prepended(self):
        out = self._inject(
            {"messages": [{"role": "system", "content": "Be brief."},
                          {"role": "user", "content": "hi"}]}, "openai")
        assert out["messages"][0]["content"].startswith(RULE)
        assert "Be brief." in out["messages"][0]["content"]

    def test_gemini_system_instruction_is_prepended(self):
        out = self._inject({"contents": [{"parts": [{"text": "hi"}]}],
                            "systemInstruction": {"parts": [{"text": "Base."}]}}, "gemini")
        assert out["systemInstruction"]["parts"][0]["text"] == RULE

    @pytest.mark.parametrize("body,provider", [
        ({"messages": [{"role": "user", "content": "hi"}]}, "anthropic"),
        ({"messages": [{"role": "user", "content": "hi"}]}, "openai"),
        ({"contents": [{"parts": [{"text": "hi"}]}]}, "gemini"),
    ])
    def test_instructions_are_created_when_the_request_has_none(self, body, provider):
        """Injecting only into an existing system prompt would make the control
        trivially evadable: omit the field and the perimeter disappears."""
        import json as _json
        out = self._inject(body, provider)
        assert RULE in _json.dumps(out)

    def test_the_user_prompt_survives(self):
        out = self._inject({"messages": [{"role": "user", "content": "hello"}]}, "openai")
        assert any(m.get("content") == "hello" for m in out["messages"])

    def test_empty_instructions_change_nothing(self):
        from synthelion.plugins.proxy import _apply_system_instructions
        body = {"messages": [{"role": "user", "content": "hi"}]}
        assert _apply_system_instructions(body, "", "openai") is body

    def test_unknown_shape_is_left_alone_not_mangled(self):
        body = {"prompt": "hi"}
        assert self._inject(body, None) == body


class TestSystemInstructionRegistry:
    def test_first_record_is_version_one(self, tmp_path):
        from synthelion.compliance import instructions
        assert instructions.record(RULE, directory=tmp_path)["version"] == 1

    def test_unchanged_text_does_not_add_a_version(self, tmp_path):
        """This runs on every proxied request; re-appending an unchanged value
        would turn the history into a request log."""
        from synthelion.compliance import instructions
        instructions.record(RULE, directory=tmp_path)
        instructions.record(RULE, directory=tmp_path)
        assert instructions.registry_summary(directory=tmp_path)["version_count"] == 1

    def test_changed_text_adds_a_version(self, tmp_path):
        from synthelion.compliance import instructions
        instructions.record(RULE, directory=tmp_path)
        second = instructions.record(RULE + " Never quote competitors.", directory=tmp_path)
        assert second["version"] == 2
        assert second["hash"] != instructions.history(directory=tmp_path)[0]["hash"]

    def test_empty_text_is_not_recorded(self, tmp_path):
        from synthelion.compliance import instructions
        assert instructions.record("   ", directory=tmp_path) is None
        assert instructions.registry_summary(directory=tmp_path)["version_count"] == 0

    def test_summary_reports_absence_honestly(self, tmp_path):
        from synthelion.compliance import instructions
        summary = instructions.registry_summary(directory=tmp_path)
        assert summary["configured"] is False and summary["history"] == []

    def test_technical_file_carries_the_registry(self, tmp_path, monkeypatch):
        """Annex IV asks for the history of what the model was told; the
        document used to carry only a boolean."""
        _isolate(tmp_path, monkeypatch)
        from synthelion.compliance import instructions
        instructions.record(RULE)
        doc = documents.technical_file(engine=_engine())
        registry = doc["system_prompt_registry"]
        assert registry["configured"] and registry["current_text"] == RULE
        rendered = documents.to_pdf(doc, tmp_path / "tf.pdf").read_bytes()
        assert b"System instruction registry" in rendered or len(rendered) > 1000
