# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Compliance rule registry and regulatory traceability matrix.

The rules here are almost entirely *bindings*, not new detection logic: each
one names an existing Synthelion guard (PrivacyGuard, EnterpriseGuard, the
prompt-injection guard, the agent-policy engine, ...) and wraps it in the
vocabulary a compliance officer actually works in — a risk level, a
remediation action, an input/output scope, and the specific articles of law
the control exists to satisfy.

That last part is the piece that exists nowhere else in the codebase. A guard
can tell you "this text contains an IBAN"; only this table can tell you that
the control answers GDPR Art. 5(1)(c) and Art. 25, and that switching it off
leaves a documented gap in the technical file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Category(str, Enum):
    PRIVACY = "privacy"
    SECURITY = "security"
    SAFETY = "safety"
    CONTENT = "content"
    QUALITY = "quality"
    CUSTOM = "custom"


class RiskLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Action(str, Enum):
    """What the engine does when a rule fires."""
    BLOCK = "block"          # refuse the call outright
    REDACT = "redact"        # rewrite the text, then continue
    WARN = "warn"            # attach a disclaimer, then continue
    LOG_ONLY = "log_only"    # allow, record in the audit trail


class Scope(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    BOTH = "both"

    def covers(self, scope: "Scope") -> bool:
        return self is Scope.BOTH or self is scope


@dataclass(frozen=True)
class LegalReference:
    framework: str     # "EU AI Act", "GDPR", "NIS 2", ...
    article: str       # "Art. 25", "Art. 5(1)(c)", "Annex IV"
    obligation: str    # what the article actually requires, in one line


@dataclass
class ComplianceRule:
    """One control. `backend` names the guard that implements the detection —
    the engine dispatches on it, so a rule is configuration, not code."""
    id: str
    title: str
    category: Category
    backend: str
    risk_level: RiskLevel = RiskLevel.MEDIUM
    action: Action = Action.LOG_ONLY
    scope: Scope = Scope.BOTH
    enabled: bool = True
    description: str = ""
    legal: tuple[LegalReference, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category.value,
            "backend": self.backend,
            "risk_level": self.risk_level.value,
            "action": self.action.value,
            "scope": self.scope.value,
            "enabled": self.enabled,
            "description": self.description,
            "legal": [
                {"framework": r.framework, "article": r.article, "obligation": r.obligation}
                for r in self.legal
            ],
        }


_AI_ACT = "EU AI Act (Reg. 2024/1689)"
_GDPR = "GDPR (Reg. 2016/679)"
_NIS2 = "NIS 2 / DORA"
_ISO = "ISO/IEC 42001"


# ---------------------------------------------------------------------------
# The registry.
#
# Every `backend` here must be dispatchable in engine.py. A rule whose backend
# has no implementation is reported as "not implemented" rather than silently
# passing — a compliance control that quietly does nothing is worse than an
# absent one, because the technical file would claim coverage that isn't there.
# ---------------------------------------------------------------------------

DEFAULT_RULES: tuple[ComplianceRule, ...] = (
    # ── Privacy ────────────────────────────────────────────────────────────
    ComplianceRule(
        id="PII_REDACTION",
        title="PII detection and redaction",
        category=Category.PRIVACY,
        backend="privacy_analyzer",
        risk_level=RiskLevel.HIGH,
        action=Action.REDACT,
        scope=Scope.BOTH,
        description="Names, national IDs, phone numbers, addresses and email are masked with "
                    "recoverable placeholders before the text reaches a third-party model.",
        legal=(
            LegalReference(_GDPR, "Art. 5(1)(c)", "Data minimisation — only data necessary for the purpose may be processed."),
            LegalReference(_GDPR, "Art. 25", "Privacy by design and by default."),
            LegalReference(_AI_ACT, "Art. 10", "Data governance for high-risk systems."),
        ),
    ),
    ComplianceRule(
        id="FINANCIAL_DATA",
        title="Financial and health data protection",
        category=Category.PRIVACY,
        backend="privacy_analyzer",
        risk_level=RiskLevel.HIGH,
        action=Action.REDACT,
        scope=Scope.BOTH,
        description="Payment card numbers (PCI-DSS), IBANs and health identifiers are detected "
                    "and masked. Backed by the same analyzer as PII_REDACTION, scoped to its "
                    "financial and health categories.",
        legal=(
            LegalReference(_GDPR, "Art. 9", "Special categories of personal data."),
            LegalReference(_NIS2, "PCI-DSS", "Protection of cardholder data."),
        ),
    ),
    # ── Security ───────────────────────────────────────────────────────────
    ComplianceRule(
        id="SECRETS_DETECTION",
        title="Secrets and API key detection",
        category=Category.SECURITY,
        backend="enterprise_guard",
        risk_level=RiskLevel.HIGH,
        action=Action.BLOCK,
        scope=Scope.BOTH,
        description="Cloud credentials, database connection strings, private keys and API tokens. "
                    "Always blocks rather than redacts — a live secret has no safe redacted form.",
        legal=(
            LegalReference(_NIS2, "Art. 21", "Technical measures to manage cybersecurity risk."),
            LegalReference(_ISO, "A.8", "Protection of authentication information."),
        ),
    ),
    ComplianceRule(
        id="PROMPT_INJECTION",
        title="Prompt injection and jailbreak defence",
        category=Category.SECURITY,
        backend="prompt_injection_guard",
        risk_level=RiskLevel.HIGH,
        action=Action.BLOCK,
        scope=Scope.INPUT,
        description="Heuristic detection of attempts to override system instructions, exfiltrate "
                    "the system prompt, or coerce the model out of its configured behaviour.",
        legal=(
            LegalReference(_AI_ACT, "Art. 15", "Accuracy, robustness and cybersecurity."),
        ),
    ),
    ComplianceRule(
        id="AGENT_POLICY",
        title="Per-agent-type guardrails",
        category=Category.SECURITY,
        backend="agent_policy",
        risk_level=RiskLevel.HIGH,
        action=Action.BLOCK,
        scope=Scope.INPUT,
        description="Destructive commands, gated operations requiring human approval, and the "
                    "read-private-then-send-outward exfiltration chain.",
        legal=(
            LegalReference(_AI_ACT, "Art. 15", "Robustness against adversarial use."),
            LegalReference(_AI_ACT, "Art. 14", "Human oversight — gated actions require an operator."),
        ),
    ),
    ComplianceRule(
        id="DESTRUCTIVE_COMMANDS",
        title="Destructive command detection",
        category=Category.SECURITY,
        backend="safety_guard",
        risk_level=RiskLevel.MEDIUM,
        action=Action.WARN,
        scope=Scope.OUTPUT,
        description="Flags destructive shell commands present in generated output before a human "
                    "or an agent can act on them.",
        legal=(
            LegalReference(_AI_ACT, "Art. 15", "Robustness — preventing harmful automated action."),
        ),
    ),
    # ── Safety / content ───────────────────────────────────────────────────
    ComplianceRule(
        id="SENSITIVE_CONTENT",
        title="Sensitive content screening",
        category=Category.SAFETY,
        backend="sensitive_guard",
        risk_level=RiskLevel.MEDIUM,
        action=Action.WARN,
        scope=Scope.BOTH,
        description="Screens for sensitive material that should not transit to a third-party model.",
        legal=(
            LegalReference(_AI_ACT, "Art. 5", "Prohibited practices."),
        ),
    ),
    # ── Transparency ───────────────────────────────────────────────────────
    ComplianceRule(
        id="AI_DISCLOSURE",
        title="AI interaction disclosure",
        category=Category.CONTENT,
        backend="ai_transparency_notice",
        risk_level=RiskLevel.MEDIUM,
        action=Action.WARN,
        scope=Scope.OUTPUT,
        description="Attaches the notice informing the person that they are interacting with an "
                    "automated system, in their configured language.",
        legal=(
            LegalReference(_AI_ACT, "Art. 50", "Transparency obligations for certain AI systems."),
        ),
    ),
    # ── Quality ────────────────────────────────────────────────────────────
    ComplianceRule(
        id="OUTPUT_SANITISATION",
        title="Output sanitisation",
        category=Category.QUALITY,
        backend="output_sanitiser",
        risk_level=RiskLevel.LOW,
        action=Action.REDACT,
        scope=Scope.OUTPUT,
        description="Strips script tags and event-handler attributes from generated output before "
                    "it reaches a client that may render it.",
        legal=(
            LegalReference(_AI_ACT, "Art. 15", "Robustness of system output."),
        ),
    ),
)


def default_rules() -> list[ComplianceRule]:
    """Fresh copies, so a caller mutating a rule can't corrupt the registry."""
    import copy
    return [copy.deepcopy(r) for r in DEFAULT_RULES]


def traceability_matrix(rules: "list[ComplianceRule] | None" = None) -> list[dict]:
    """Functionality → legal obligation, one row per rule/article pair.

    This is section 5 of the compliance specification, generated from the live
    configuration rather than maintained by hand — so a rule that is switched
    off shows up as an uncovered obligation instead of silently continuing to
    look compliant on paper.
    """
    rows: list[dict] = []
    for rule in rules if rules is not None else default_rules():
        for ref in rule.legal:
            rows.append({
                "rule_id": rule.id,
                "module": rule.title,
                "category": rule.category.value,
                "framework": ref.framework,
                "article": ref.article,
                "obligation": ref.obligation,
                "enabled": rule.enabled,
                "risk_level": rule.risk_level.value,
                "action": rule.action.value,
            })
    return rows


def coverage_gaps(rules: "list[ComplianceRule] | None" = None) -> list[dict]:
    """Obligations left uncovered because their rule is disabled.

    The technical file has to state this honestly: an operator who turned a
    control off needs it recorded, not quietly omitted.
    """
    return [row for row in traceability_matrix(rules) if not row["enabled"]]
