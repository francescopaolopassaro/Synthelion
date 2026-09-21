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
    ComplianceRule(
        id="CREDENTIAL_SHAPE_SCREEN",
        title="Credential-shape secondary screen",
        category=Category.SECURITY,
        backend="sensitive_guard",
        risk_level=RiskLevel.MEDIUM,
        action=Action.WARN,
        scope=Scope.BOTH,
        description="A second, deliberately conservative pass for credential-shaped strings on the "
                    "persistence path (sensitive_guard). Narrower than SECRETS_DETECTION and not a "
                    "content-safety control: it does not screen for toxicity, hate speech or "
                    "illegal-activity requests — see the NOT_IMPLEMENTED entries below.",
        legal=(
            LegalReference(_NIS2, "Art. 21", "Technical measures to manage cybersecurity risk."),
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

    # ── Declared but NOT implemented ───────────────────────────────────────
    #
    # These controls are required by the compliance specification and do not
    # exist yet. They ship disabled, with backend "not_implemented", so they
    # surface as *uncovered obligations* in the traceability matrix and the
    # technical file. Omitting them entirely would be the dishonest option: a
    # reader would see a complete-looking matrix and conclude the obligation
    # is met. Enabling one without building it would be worse still.
    ComplianceRule(
        id="TOXICITY_HATE_SPEECH",
        title="Toxicity and hate-speech filter",
        category=Category.SAFETY,
        backend="toxicity",
        risk_level=RiskLevel.HIGH,
        action=Action.BLOCK,
        scope=Scope.BOTH,
        description="Abusive language, harassment and targeting of protected groups. "
                    "Lexicon and phrasing based, not a trained classifier: obfuscation, slang and "
                    "non-English text are missed. Precision-biased on purpose.",
        legal=(
            LegalReference(_AI_ACT, "Art. 5", "Prohibited practices."),
            LegalReference("DSA (Reg. 2022/2065)", "Art. 34", "Systemic-risk mitigation for harmful content."),
        ),
    ),
    ComplianceRule(
        id="ILLEGAL_ACTIVITY",
        title="Hazardous and illegal-activity screening",
        category=Category.SAFETY,
        backend="illegal_activity",
        risk_level=RiskLevel.HIGH,
        action=Action.BLOCK,
        scope=Scope.BOTH,
        description="Requests for weapons, controlled substances or self-harm instructions. "
                    "Requires intent phrasing beside a hazardous object, so a news report or a "
                    "chemistry lesson does not fire it.",
        legal=(LegalReference(_AI_ACT, "Art. 5", "Prohibited practices."),),
    ),
    ComplianceRule(
        id="PHI_HEALTH_DATA",
        title="Health data (PHI) detection",
        category=Category.PRIVACY,
        backend="phi",
        risk_level=RiskLevel.HIGH,
        action=Action.REDACT,
        scope=Scope.BOTH,
        description="Clinical vocabulary tied to an identifiable person. A medical article is not "
                    "PHI and a bare name is ordinary PII, so both halves are required.",
        legal=(LegalReference(_GDPR, "Art. 9", "Special categories — data concerning health."),),
    ),
    ComplianceRule(
        id="DATA_RESIDENCY",
        title="Cross-border transfer and data residency control",
        category=Category.PRIVACY,
        backend="data_residency",
        risk_level=RiskLevel.HIGH,
        action=Action.BLOCK,
        scope=Scope.INPUT,
        description="Flags endpoints outside the EEA allow-list. Deterministic host check; an "
                    "unknown host counts as a third-country transfer, since both carry the same "
                    "obligation. Providers covered by standard contractual clauses go in "
                    "compliance.allowed_hosts.",
        legal=(LegalReference(_GDPR, "Chapter V", "Transfers of personal data to third countries."),),
    ),
    ComplianceRule(
        id="CODE_VULNERABILITY",
        title="Code security and vulnerability scanning",
        category=Category.SECURITY,
        backend="code_vulnerability",
        risk_level=RiskLevel.MEDIUM,
        action=Action.WARN,
        scope=Scope.BOTH,
        description="Well-known dangerous code shapes — eval of input, shell injection, SQL "
                    "concatenation, unsafe deserialisation, disabled TLS verification. Pattern "
                    "based, like a linter's security rules; not a SAST tool.",
        legal=(LegalReference(_AI_ACT, "Art. 15", "Accuracy, robustness and cybersecurity."),),
    ),
    ComplianceRule(
        id="HALLUCINATION_CHECK",
        title="Factuality and hallucination detection",
        category=Category.QUALITY,
        backend="grounding",
        risk_level=RiskLevel.MEDIUM,
        action=Action.WARN,
        scope=Scope.OUTPUT,
        description="Lexical grounding of the answer against the supplied context. Catches an "
                    "answer invented out of nothing; will not catch a fluent answer with a wrong "
                    "number. Silent when no context is supplied.",
        legal=(LegalReference(_AI_ACT, "Art. 15", "Accuracy of the AI system."),),
    ),
    ComplianceRule(
        id="COPYRIGHT_CHECK",
        title="Copyright and licence screening",
        category=Category.QUALITY,
        backend="copyright",
        risk_level=RiskLevel.MEDIUM,
        action=Action.WARN,
        scope=Scope.OUTPUT,
        description="Licence headers and copyright notices in generated output. Detects a declared "
                    "licence; it cannot tell that an unmarked passage was copied from a protected "
                    "work, which would need a corpus to compare against.",
        legal=(LegalReference(_AI_ACT, "Art. 53", "GPAI obligations — Union copyright law."),),
    ),
    ComplianceRule(
        id="AI_WATERMARKING",
        title="Machine-readable marking of generated content",
        category=Category.CONTENT,
        backend="content_marker",
        risk_level=RiskLevel.MEDIUM,
        action=Action.REDACT,   # marking the content *is* a rewrite
        scope=Scope.OUTPUT,
        description="Marks generated content with an invisible, machine-readable tag (AI Act Art. "
                    "50(2)) and flags output that carries none. A marking, not a robust watermark: "
                    "Unicode normalisation strips it.",
        legal=(LegalReference(_AI_ACT, "Art. 50(2)", "Marking of AI-generated content in a machine-readable format."),),
    ),
    ComplianceRule(
        id="RAG_PROVENANCE",
        title="Data provenance and RAG source citation",
        category=Category.QUALITY,
        backend="rag_provenance",
        risk_level=RiskLevel.LOW,
        action=Action.LOG_ONLY,
        scope=Scope.OUTPUT,
        description="Records the retrieved sources behind an answer in the audit trail. The caller supplies them via `sources=`; the rule reports when an answer was produced with none, which is the case an auditor needs to see.",
        legal=(LegalReference(_AI_ACT, "Art. 13", "Transparency and provision of information to deployers."),),
    ),
    ComplianceRule(
        id="CUSTOM_RULES",
        title="Administrator-defined regex and keyword rules",
        category=Category.CUSTOM,
        backend="custom_registry",
        risk_level=RiskLevel.LOW,
        action=Action.WARN,
        scope=Scope.BOTH,
        description="Administrator-defined regex and keyword rules, configured under `compliance.custom_rules` and merged into this registry at load time. This entry is the capability marker; each configured rule appears in the registry in its own right.",
        legal=(),
    ),
)



def default_rules() -> list[ComplianceRule]:
    """Fresh copies, so a caller mutating a rule can't corrupt the registry."""
    import copy
    return [copy.deepcopy(r) for r in DEFAULT_RULES]


def custom_rules_from_config(entries: "list[dict] | None" = None) -> list[ComplianceRule]:
    """Build admin-defined rules from `compliance.custom_rules` in the config.

    Each entry needs an `id` and either `pattern` (a regular expression) or
    `keywords` (a list of terms, matched whole-word and case-insensitively).
    Everything else falls back to a conservative default — warn, medium risk,
    both scopes — so a half-filled entry cannot silently become a blocker.

    An invalid regex is skipped rather than raised: one malformed rule in the
    config must not take the whole engine down, and the skip is visible because
    the rule then never appears in the registry or the traceability matrix.
    """
    import logging
    import re as _re

    log = logging.getLogger(__name__)
    if entries is None:
        from synthelion.config import load_config
        entries = load_config().get("compliance", {}).get("custom_rules", []) or []

    out: list[ComplianceRule] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        pattern = entry.get("pattern")
        keywords = entry.get("keywords") or []
        if not pattern and keywords:
            # Word-boundary anchored so a keyword cannot match inside a longer
            # word ("art" must not fire on "start"). The  has to reach the
            # regex engine as an escape sequence, not as a literal backspace.
            alternatives = "|".join(_re.escape(str(k)) for k in keywords)
            pattern = chr(92) + 'b(' + alternatives + ')' + chr(92) + 'b'
        if not pattern:
            continue
        try:
            _re.compile(pattern, _re.IGNORECASE)
        except _re.error as exc:
            log.warning("compliance.custom_rules: skipping %r — invalid regex: %s",
                        entry["id"], exc)
            continue
        try:
            rule = ComplianceRule(
                id=str(entry["id"]),
                title=entry.get("title") or str(entry["id"]),
                category=Category(entry.get("category", "custom")),
                backend="custom_regex",
                risk_level=RiskLevel(entry.get("risk_level", "medium")),
                action=Action(entry.get("action", "warn")),
                scope=Scope(entry.get("scope", "both")),
                enabled=bool(entry.get("enabled", True)),
                description=entry.get("description", "Administrator-defined rule."),
                legal=tuple(
                    LegalReference(r.get("framework", ""), r.get("article", ""), r.get("obligation", ""))
                    for r in entry.get("legal", []) if isinstance(r, dict)
                ),
            )
        except ValueError as exc:      # an unknown category/risk/action/scope
            log.warning("compliance.custom_rules: skipping %r — %s", entry["id"], exc)
            continue
        rule.pattern = pattern         # type: ignore[attr-defined]
        out.append(rule)
    return out


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
