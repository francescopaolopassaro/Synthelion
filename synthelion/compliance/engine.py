# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""The compliance engine — one gate in front of every guard Synthelion has.

This module runs almost no detection of its own. Its job is to take the
guards that already exist, apply them in the order and with the semantics a
compliance policy describes (risk level, remediation action, input/output
scope), and produce a single decision plus an audit record.

Engine states mirror the specification:
  active   — rules are enforced
  staging  — every rule is evaluated and logged, but nothing is ever blocked
             or rewritten, so a policy can be trialled against real traffic
             before it starts refusing calls
  inactive — the gate is off

The fallback policy decides what happens when a guard itself fails (a backend
raises, a model is missing). `fail_closed` refuses the call; `fail_open`
allows it and records the failure. Default is fail_closed for the security and
privacy categories and fail_open for the advisory ones — a broken toxicity
check should not take down the gateway, a broken secrets scanner should.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from synthelion.compliance import audit
from synthelion.compliance.rules import (
    Action, Category, ComplianceRule, RiskLevel, Scope, default_rules,
)

ACTIVE = "active"
STAGING = "staging"
INACTIVE = "inactive"

FAIL_CLOSED = "fail_closed"
FAIL_OPEN = "fail_open"
# Third mode from the specification: forward the call, but attach a disclaimer
# so the caller knows a control could not be evaluated — louder than fail_open
# (which only records it), safer than fail_closed for advisory categories.
WARN_AND_PASS = "warn_and_pass"

# A backend failure in these categories is a security event, not a hiccup:
# if the secrets scanner is down we cannot claim the payload is clean.
_FAIL_CLOSED_CATEGORIES = frozenset({Category.SECURITY, Category.PRIVACY})

# Backends implemented in compliance/detectors.py rather than by an existing
# Synthelion guard.
_DETECTOR_BACKENDS = frozenset({
    "toxicity", "illegal_activity", "phi", "data_residency",
    "code_vulnerability", "copyright", "grounding", "content_marker",
    "rag_provenance", "custom_registry",
})


@dataclass
class Finding:
    rule_id: str
    title: str
    category: str
    risk_level: str
    action: str
    detail: str = ""
    matched_categories: list[str] = field(default_factory=list)
    backend_error: str = ""

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id, "title": self.title, "category": self.category,
            "risk_level": self.risk_level, "action": self.action, "detail": self.detail,
            "matched_categories": self.matched_categories, "backend_error": self.backend_error,
        }


@dataclass
class ComplianceResult:
    allowed: bool
    text: str
    decision: str                      # allow | redact | warn | block
    findings: list[Finding] = field(default_factory=list)
    disclaimers: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    engine_status: str = ACTIVE
    audit_entry: dict | None = None

    @property
    def blocked(self) -> bool:
        return not self.allowed

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "decision": self.decision,
            "text": self.text,
            "findings": [f.to_dict() for f in self.findings],
            "disclaimers": self.disclaimers,
            "latency_ms": round(self.latency_ms, 3),
            "engine_status": self.engine_status,
            "audit": self.audit_entry,
        }


class ComplianceEngine:
    """Evaluates text against the configured rule set."""

    def __init__(
        self,
        rules: "list[ComplianceRule] | None" = None,
        status: str = ACTIVE,
        fallback: str = FAIL_CLOSED,
        language: str = "en",
        system_prompt_override: str = "",
        agent_profile: str = "base",
        allowed_hosts: "tuple[str, ...]" = (),
    ) -> None:
        self.rules = rules if rules is not None else default_rules()
        self.status = status
        self.fallback = fallback
        self.language = language
        self.system_prompt_override = system_prompt_override
        self.agent_profile = agent_profile
        self.allowed_hosts = tuple(allowed_hosts)
        # Set per evaluation by `context=`/`sources=`; the grounding and
        # provenance rules read them.
        self._context = ""
        self._sources: list[str] = []

    @classmethod
    def from_config(cls) -> "ComplianceEngine":
        from synthelion.config import load_config
        cfg = load_config().get("compliance", {})
        rules = default_rules()

        # Per-rule overrides from config, applied on top of the defaults so a
        # deployment only states what it changes.
        overrides = cfg.get("rules", {})
        for rule in rules:
            o = overrides.get(rule.id)
            if not isinstance(o, dict):
                continue
            if "enabled" in o:
                rule.enabled = bool(o["enabled"])
            if o.get("risk_level"):
                rule.risk_level = RiskLevel(o["risk_level"])
            if o.get("action"):
                rule.action = Action(o["action"])
            if o.get("scope"):
                rule.scope = Scope(o["scope"])

        # Admin-defined rules extend the built-in registry; a custom id that
        # collides with a built-in one replaces it, so an operator can re-scope
        # a shipped rule without editing code.
        from synthelion.compliance.rules import custom_rules_from_config
        custom = custom_rules_from_config(cfg.get("custom_rules"))
        by_id = {r.id: r for r in rules}
        for rule in custom:
            by_id[rule.id] = rule
        rules = list(by_id.values())

        return cls(
            rules=rules,
            status=cfg.get("status", ACTIVE),
            fallback=cfg.get("fallback", FAIL_CLOSED),
            language=cfg.get("language", "en"),
            system_prompt_override=cfg.get("system_prompt_override", ""),
            agent_profile=cfg.get("agent_profile", "base"),
            allowed_hosts=tuple(cfg.get("allowed_hosts", []) or []),
        )

    # -- rule management --------------------------------------------------

    def rule(self, rule_id: str) -> ComplianceRule | None:
        return next((r for r in self.rules if r.id == rule_id), None)

    def active_rules(self, scope: Scope) -> list[ComplianceRule]:
        return [r for r in self.rules if r.enabled and r.scope.covers(scope)]

    # -- backends ---------------------------------------------------------
    #
    # Each returns (fired, detail, matched_categories, replacement_text|None).
    # Detection lives in the guard modules; these are adapters.

    def _run_backend(self, rule: ComplianceRule, text: str) -> tuple[bool, str, list[str], str | None]:
        backend = rule.backend
        if backend == "privacy_analyzer":
            return self._backend_privacy(rule, text)
        if backend == "enterprise_guard":
            return self._backend_secrets(text)
        if backend == "prompt_injection_guard":
            return self._backend_injection(text)
        if backend == "agent_policy":
            return self._backend_agent_policy(text)
        if backend == "safety_guard":
            return self._backend_safety(text)
        if backend == "sensitive_guard":
            return self._backend_sensitive(text)
        if backend == "ai_transparency_notice":
            return self._backend_disclosure()
        if backend == "output_sanitiser":
            return self._backend_sanitise(text)
        if backend == "custom_regex":
            return self._backend_custom(rule, text)
        if backend in _DETECTOR_BACKENDS:
            return self._backend_detector(backend, text)
        raise NotImplementedError(f"no backend implementing {backend!r}")

    def _backend_detector(self, backend: str, text: str):
        """Adapters for the compliance-specific detectors (detectors.py)."""
        from synthelion.compliance import detectors as d
        if backend == "toxicity":
            fired, detail, cats = d.detect_toxicity(text)
        elif backend == "illegal_activity":
            fired, detail, cats = d.detect_illegal_activity(text)
        elif backend == "phi":
            return d.detect_phi(text)          # already returns a replacement
        elif backend == "data_residency":
            fired, detail, cats = d.detect_data_residency(text, self.allowed_hosts)
        elif backend == "code_vulnerability":
            fired, detail, cats = d.detect_code_vulnerabilities(text)
        elif backend == "copyright":
            fired, detail, cats = d.detect_copyright(text)
        elif backend == "grounding":
            # Nothing to compare against unless the caller supplied context.
            fired, detail, cats = d.detect_ungrounded(text, self._context)
        elif backend == "rag_provenance":
            # Fires when an answer was produced with no recorded sources —
            # that absence is the finding an auditor needs, not the presence.
            if self._sources:
                return False, "", [], None
            fired, detail, cats = True, "no retrieval sources recorded for this answer", ["no_provenance"]
        elif backend == "custom_registry":
            # A capability marker, not a detector: each configured custom rule
            # is evaluated as its own registry entry.
            return False, "", [], None
        elif backend == "content_marker":
            fired, detail, cats = d.detect_missing_marker(text)
            if fired:
                # The remediation *is* the marking: attach it rather than only
                # reporting that it is absent.
                return True, detail, cats, d.embed_content_marker(text)
        else:
            raise NotImplementedError(f"no detector for {backend!r}")
        return fired, detail, cats, None

    # PrivacyAnalyzer reports one flat category list, but the two privacy rules
    # answer to different articles (general PII -> Art. 5/25; financial and
    # health data -> Art. 9 and PCI-DSS). Split its output so each rule only
    # fires for its own slice — otherwise the second rule can never fire
    # independently and the traceability matrix would credit a control that
    # never actually reports anything.
    _FINANCIAL_CATEGORIES = frozenset({
        "Credit Card", "IBAN", "Bank Account", "SWIFT/BIC", "Health", "Medical",
    })

    def _privacy_analysis(self, text: str):
        """One analysis per evaluation, shared by every privacy rule.

        Both privacy rules run the same analyzer. Letting each one re-scan the
        *current* text would mean whichever runs first redacts the payload and
        the second then finds nothing — so a real IBAN would be masked but
        never recorded against the control that answers for it. Analysing the
        original text once and sharing the result keeps each control's finding
        independent (and halves the work).
        """
        cached = getattr(self, "_privacy_cache", None)
        if cached is not None and cached[0] == text:
            return cached[1]
        from synthelion.privacy_analyzer import PrivacyAnalyzer
        result = PrivacyAnalyzer().analyze(text, language=self.language, auto_masking=True)
        self._privacy_cache = (text, result)
        return result

    def _backend_privacy(self, rule: ComplianceRule, text: str):
        result = self._privacy_analysis(text)
        if not result.detected_categories:
            return False, "", [], None

        financial = rule.id == "FINANCIAL_DATA"
        mine = [c for c in result.detected_categories
                if (c in self._FINANCIAL_CATEGORIES) is financial]
        if not mine:
            return False, "", [], None

        detail = f"{len(mine)} category/ies matched, overall risk {result.risk_level}"
        # Masking is all-or-nothing in the analyzer, so whichever privacy rule
        # runs first redacts everything it found; the other still reports its
        # own categories for the audit trail.
        replacement = (result.masked_text or None) if rule.action is Action.REDACT else None
        return True, detail, mine, replacement

    def _backend_secrets(self, text: str):
        from synthelion.enterprise_guard import EnterpriseGuard
        result = EnterpriseGuard().check_text(text, source="compliance")
        if not result.blocked:
            return False, "", [], None
        return True, result.reason or "", [result.category or "secret"], None

    def _backend_injection(self, text: str):
        from synthelion.prompt_injection_guard import PromptInjectionGuard
        result = PromptInjectionGuard().analyze(text)
        if result.is_clean:
            return False, "", [], None
        return True, f"score {result.score}, risk {result.risk_level}", list(result.detected_categories), None

    def _backend_agent_policy(self, text: str):
        from synthelion.agent_policy import AgentPolicy, Verdict
        decision = AgentPolicy(profile=self.agent_profile).check_tool_call(
            "compliance_gate", {"command": text, "text": text})
        if decision.verdict is Verdict.ALLOW:
            return False, "", [], None
        detail = f"{decision.verdict.value}: {decision.reason or ''}"
        return True, detail, [decision.requirement or "policy"], None

    def _backend_safety(self, text: str):
        from synthelion.safety_guard import find_destructive_command
        found = find_destructive_command(text)
        if not found:
            return False, "", [], None
        return True, f"destructive command: {found}", ["destructive_command"], None

    def _backend_sensitive(self, text: str):
        from synthelion.sensitive_guard import find_sensitive
        found = find_sensitive(text)
        if not found:
            return False, "", [], None
        return True, f"sensitive content: {found}", ["sensitive"], None

    def _backend_disclosure(self):
        # Always "fires": the disclosure is an obligation to attach a notice,
        # not a detection. Its action is WARN, so it contributes a disclaimer.
        from synthelion.ai_transparency_notice import get_transparency_notice
        return True, "AI interaction disclosure attached", ["transparency"], None

    def _backend_custom(self, rule: ComplianceRule, text: str):
        """Administrator-defined regex/keyword rule."""
        import re
        pattern = getattr(rule, "pattern", "")
        if not pattern:
            return False, "", [], None
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return False, "", [], None
        # Report *that* it matched and how long the match was — never the
        # matched text itself, which is exactly the content the rule exists to
        # keep out of logs.
        return True, f"custom rule matched ({len(match.group(0))} chars)", [rule.id], None

    def _backend_sanitise(self, text: str):
        import re
        cleaned = re.sub(r"(?is)<script\b.*?</script\s*>", "", text)
        cleaned = re.sub(r"(?is)<\s*(iframe|object|embed)\b[^>]*>.*?<\s*/\s*\1\s*>", "", cleaned)
        # Inline event handlers survive tag-stripping, so remove them too.
        cleaned = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", cleaned)
        if cleaned == text:
            return False, "", [], None
        return True, "removed active markup from output", ["active_markup"], cleaned

    # -- backend health ---------------------------------------------------

    def _backend_state(self, backend: str) -> tuple[str, str]:
        """(state, note) for one backend: operational | disabled | unavailable."""
        try:
            if backend == "enterprise_guard":
                from synthelion.enterprise_guard import EnterpriseGuard
                guard = EnterpriseGuard()
                if not guard.enabled:
                    return "disabled", "enterprise_guard.enabled is false in the configuration"
                if not any(guard.categories.get(c, True) for c in
                           ("cloud_credentials", "database_connections", "private_keys", "api_tokens")):
                    return "disabled", "every credential category is switched off"
                return "operational", ""
            if backend == "agent_policy":
                from synthelion.agent_policy import AgentPolicy
                if not AgentPolicy.from_config().enabled:
                    return "disabled", "agent_policy.enabled is false in the configuration"
                return "operational", ""
            if backend in ("privacy_analyzer", "prompt_injection_guard", "safety_guard",
                           "sensitive_guard", "ai_transparency_notice", "output_sanitiser",
                           "custom_regex") or backend in _DETECTOR_BACKENDS:
                return "operational", ""
            if backend == "not_implemented":
                return "unavailable", "declared in the registry but not built — see the rule description"
            return "unavailable", f"no backend implementing {backend!r}"
        except Exception as exc:  # noqa: BLE001
            return "unavailable", str(exc)[:160]

    def backend_health(self) -> list[dict]:
        """Per-rule operational state.

        A rule can be *enabled* in the compliance policy while the guard that
        actually implements it is switched off elsewhere in the configuration.
        That combination is the dangerous one: the technical file would list
        the control as active while nothing inspects anything. Reporting it
        explicitly is the whole point of this check.
        """
        out = []
        for rule in self.rules:
            state, note = self._backend_state(rule.backend)
            out.append({
                "rule_id": rule.id,
                "title": rule.title,
                "backend": rule.backend,
                "rule_enabled": rule.enabled,
                "backend_state": state,
                "effective": rule.enabled and state == "operational",
                "note": note,
            })
        return out

    def ineffective_rules(self) -> list[dict]:
        """Rules switched on whose backend cannot actually enforce them."""
        return [h for h in self.backend_health()
                if h["rule_enabled"] and not h["effective"]]

    # -- evaluation -------------------------------------------------------

    def evaluate(
        self,
        text: str,
        scope: Scope = Scope.INPUT,
        user_id: str = "",
        model: str = "",
        client_ip: str = "",
        request_id: str = "",
        context: str = "",
        sources: "list[str] | None" = None,
        write_audit: bool = True,
        directory=None,
    ) -> ComplianceResult:
        started = time.perf_counter()
        # Retrieved material the answer should be grounded in (RAG). Empty
        # unless the caller supplies it, and the grounding rule stays silent
        # in that case rather than guessing.
        self._context = context or ""
        self._sources = list(sources or [])

        if self.status == INACTIVE:
            return ComplianceResult(True, text, "allow", engine_status=INACTIVE,
                                    latency_ms=(time.perf_counter() - started) * 1000)

        findings: list[Finding] = []
        disclaimers: list[str] = []
        current = text
        blocked = False

        # Detection always runs against the original payload so every control
        # reports independently; only transforming backends see the accumulated
        # text, so successive redactions still compose.
        self._privacy_cache = None
        _TRANSFORMING = {"output_sanitiser"}

        for rule in self.active_rules(scope):
            subject = current if rule.backend in _TRANSFORMING else text
            try:
                fired, detail, categories, replacement = self._run_backend(rule, subject)
            except NotImplementedError as exc:
                # A rule the registry promises but nothing implements must be
                # visible, never silently "clean" — the technical file would
                # otherwise claim a control that does not exist.
                findings.append(Finding(rule.id, rule.title, rule.category.value,
                                        rule.risk_level.value, "log_only",
                                        detail="rule not implemented", backend_error=str(exc)))
                continue
            except Exception as exc:  # noqa: BLE001 — a guard failing is itself a compliance event
                fail_closed = (self.fallback == FAIL_CLOSED
                               and rule.category in _FAIL_CLOSED_CATEGORIES)
                warn_pass = self.fallback == WARN_AND_PASS
                findings.append(Finding(
                    rule.id, rule.title, rule.category.value, rule.risk_level.value,
                    Action.BLOCK.value if fail_closed else
                    (Action.WARN.value if warn_pass else Action.LOG_ONLY.value),
                    detail="backend failed", backend_error=str(exc)[:200]))
                if fail_closed and self.status == ACTIVE:
                    blocked = True
                elif warn_pass and self.status == ACTIVE:
                    disclaimers.append(
                        f"[{rule.title}] could not be evaluated — this response was not checked "
                        f"against that control.")
                continue

            if not fired:
                continue

            findings.append(Finding(rule.id, rule.title, rule.category.value,
                                    rule.risk_level.value, rule.action.value,
                                    detail=detail, matched_categories=categories))

            # Staging evaluates and records everything but changes nothing —
            # that is the whole point of trialling a policy against real traffic.
            if self.status == STAGING:
                continue

            if rule.action is Action.BLOCK:
                blocked = True
            elif rule.action is Action.REDACT:
                if replacement is not None:
                    current = replacement
                else:
                    # Detected, but the backend had nothing masked to put in
                    # its place. A visible disclaimer is the honest outcome:
                    # silently doing nothing would let the audit trail record a
                    # redaction that never happened.
                    disclaimers.append(
                        f"[{rule.title}] detected but not redacted — {detail}")
            elif rule.action is Action.WARN:
                if rule.backend == "ai_transparency_notice":
                    from synthelion.ai_transparency_notice import get_transparency_notice
                    disclaimers.append(get_transparency_notice(self.language))
                else:
                    disclaimers.append(f"[{rule.title}] {detail}")

        decision = "block" if blocked else (
            "redact" if current != text else ("warn" if disclaimers else "allow"))
        latency = (time.perf_counter() - started) * 1000

        result = ComplianceResult(
            allowed=not blocked,
            text=text if blocked else current,
            decision=decision,
            findings=findings,
            disclaimers=disclaimers,
            latency_ms=latency,
            engine_status=self.status,
        )

        if write_audit:
            result.audit_entry = audit.record(
                scope=scope.value,
                decision=decision,
                findings=[f.to_dict() for f in findings],
                request_hash=audit.text_fingerprint(text),
                # The text as it leaves the gate: for an output-scope call this
                # is the response, and it differs from request_hash whenever a
                # redaction rewrote it.
                response_hash=audit.text_fingerprint(result.text),
                user_id=user_id,
                client_ip=client_ip,
                request_id=request_id,
                model=model,
                sources=self._sources,
                latency_ms=latency,
                directory=directory,
            )
        return result
