# Synthelion — Python port of Caveman.PrivacyGuard (https://github.com/francescopaolopassaro/Caveman.PrivacyGuard)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Enterprise-grade PII & privacy analyzer for AI/LLM workflows — detects, scores,
and (optionally) masks sensitive data across 33 country/region rule sets (EU + UK,
Switzerland, China, Russia, Ukraine) with GDPR/EU AI Act/NIS2/PCI-DSS/NIST
compliance-flag mapping. Direct port of Caveman.PrivacyGuard (C#, same scoring
formula, same rule schema, same ~30 checksum validators in `privacy_validators.py`)
— not a from-scratch reimplementation, since the whole point is to bring years of
tuning on that library over to Synthelion unchanged.

Zero ML: every detection is a compiled regex plus (for high-value categories) a
real algorithmic checksum validator — same design philosophy as the rest of
Synthelion.
"""
from __future__ import annotations

import importlib.resources
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import regex as re
import yaml

from synthelion.privacy_ml import DEFAULT_MODEL_NAME as _DEFAULT_ML_MODEL, MLSpan, get_ml_detector
from synthelion.privacy_session import PrivacySession
from synthelion.privacy_validators import get_validator

_RULES_TIMEOUT = 2.0  # seconds — regex compile safety net, mirrors the C# RegexHelper timeout
_CONTEXT_WINDOW = 25  # chars scanned on each side of a format match for context_keywords
# Short keywords ("tel", "id", "nn") are substring-checked, a bare "tel" would match
# "hotel" and "nn" would match "annual", so keywords shorter than this length must
# appear as a whole word instead. Long/multi-word keywords stay substring-based.
_KEYWORD_WORD_LEN = 6


def _keyword_in_window(keyword: str, window: str) -> bool:
    """Context-keyword match: long/multi-word keywords are substrings, short ones
    ("tel", "id", "nn") must stand as a whole word so "hotel" cannot confirm a phone
    number nor "annual" a Belgian registry number."""
    if len(keyword) >= _KEYWORD_WORD_LEN:
        return keyword in window
    return re.search(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", window) is not None


@dataclass
class CompiledRule:
    category: str
    pattern: re.Pattern
    base_weight: int
    validator: Any
    context_keywords: list[str]
    is_high_confidence: bool
    compliance_tags: list[str]
    requires_context: bool = False


@dataclass
class PrivacyAnalysisResult:
    score: int = 0
    risk_level: str = "None"
    detected_categories: list[str] = field(default_factory=list)
    compliance_flags: list[str] = field(default_factory=list)
    warning_message: str = ""
    match_count: int = 0
    density_score: float = 0.0
    matches_per_category: dict[str, int] = field(default_factory=dict)
    masked_text: str = ""
    session: PrivacySession | None = None
    # Count of matches that were confirmed via the optional ML tier
    # (privacy.use_ml) instead of a context keyword. 0 unless ML is enabled.
    ml_assisted_count: int = 0

    @property
    def is_safe_for_ai(self) -> bool:
        return self.score <= 15


_PERSONAL_ID_CATEGORIES = frozenset({
    "Email", "Phone E.164", "Italian Tax Code (CF)", "Spanish Tax/ID Number (NIF/NIE)", "Polish PESEL",
    "Dutch BSN", "French Social Security (NIR)", "Swedish Personal ID", "Danish CPR Number", "Finnish Personal ID (Hetu)",
    "Irish PPSN", "Belgian National Registry", "Czech Birth Number", "Romanian Personal Code (CNP)", "Bulgarian EGN",
    "Croatian OIB", "Slovenian EMSO", "Lithuanian Personal Code", "Latvian Personal Code", "Estonian Personal ID",
    "German Tax ID (Steuer-Id)", "Hungarian Tax ID", "Portuguese Tax Number (NIF)", "Greek Tax Number (AFM)",
    "Cypriot ID Number", "Maltese ID Number", "Luxembourg National ID", "Slovak Birth Number",
})
_FINANCIAL_ID_CATEGORIES = frozenset({
    "Credit Card", "IBAN", "Italian VAT Number", "French Business ID (SIREN/SIRET)", "Polish VAT (NIP)",
    "Austrian VAT (UID)",
})

# Which analyzer category the optional ML tier's labels are allowed to confirm.
# Strict on purpose: a "phone number" span must not turn a bare ID run into a
# phone detection and an "ID number" span must not confirm the Phone rule — the
# model's semantic judgment is coupled to the right rule family. Labels outside
# this table confirm nothing.
_ML_LABEL_CATEGORIES: dict[str, frozenset[str]] = {
    "phone number": frozenset({"Phone E.164"}),
    "email address": frozenset({"Email"}),
    "credit card number": frozenset({"Credit Card"}),
    "iban number": frozenset({"IBAN"}),
    "bank account number": frozenset({"IBAN"}),
    "bank account number (iban)": frozenset({"IBAN"}),
    "national identification number": frozenset(_PERSONAL_ID_CATEGORIES - {"Email", "Phone E.164"}) | frozenset({
        "Maltese ID Number",
        # Non-EU / ID-card-style rules with a real checksum (IDCARD_DE, NINO_GB,
        # AHV_CH, ID_CN) that were simply missing from this table — found while
        # verifying every checksum-validated privacy_rules.yaml category has an
        # ML confirmation path (see devtools/train_privacyguardml.py).
        "German ID Card", "UK National Insurance Number (NINO)", "Swiss AHV/AVS Number",
        "Chinese Resident ID Number",
    }),
    "tax identification number": frozenset({
        "Italian Tax Code (CF)", "German Tax ID (Steuer-Id)", "Hungarian Tax ID",
        "Portuguese Tax Number (NIF)", "Greek Tax Number (AFM)", "Polish VAT (NIP)",
        "Italian VAT Number", "Spanish Tax/ID Number (NIF/NIE)", "Czech Business ID",
        "Russian Taxpayer ID (INN)", "Ukrainian Taxpayer Number (RNOKPP)",
    }),
    "social security number": frozenset({
        "French Social Security (NIR)",
        # No checksum on either (both are shape + context_keywords rules,
        # same posture PrivacyGuard already accepts for these two) — ML
        # confirmation helps exactly the same way it does everywhere else:
        # recovering a bare value when the context keyword isn't nearby.
        "Austrian Social Insurance", "Greek Social Security (AMKA)",
    }),
    "gps coordinates": frozenset({"GPS Coordinates"}),
    "passport number": frozenset(),
    "driver's license number": frozenset(),
    # Remaining PrivacyGuard rule categories with no checksum, added so every
    # catalog entry — including non-financial/non-identity ones like legal
    # acts and credentials — has an ML confirmation path, not just the
    # checksum-validated subset.
    "vehicle license plate": frozenset({"EU Vehicle License Plate"}),
    "employee badge id": frozenset({"Employee / Badge ID"}),
    "business identification number": frozenset({
        "French Business ID (SIREN/SIRET)", "Austrian VAT (UID)",
    }),
    "credential or secret": frozenset({"Password/Secret", "JWT/Token"}),
    "social media handle": frozenset({"Social / Messenger Handle"}),
    "legal case number": frozenset({"Legal Case / File Number"}),
    "booking reference": frozenset({"PNR / Booking Code"}),
    "minor age indicator": frozenset({"Minor Data (<16)"}),
}

# (en, it, de, fr, es) localized message tables.
_LOCALES: dict[str, dict[str, str]] = {
    "en": {
        "safe": "Safe (AI Ready)", "low": "Low (Monitoring)", "medium": "Medium (Anonymization Required)",
        "high": "High (Block Recommended)", "critical": "Critical (Absolute Prohibition)",
        "empty": "✅ No sensitive data detected. AI processing is safe.",
        "masked_suffix": "\n\U0001f6e1️ Sensitive data automatically masked before AI submission.",
        "warn_safe": "⚠️ Minor indicators: {0}. Verify format.",
        "warn_low": "⚠️ Data detected: {0}. Logging and monitoring recommended.",
        "warn_medium": "⛔ Data detected: {0}. Pseudonymization mandatory before AI.",
        "warn_high": "\U0001f6a8 Data detected: {0}. Do not send to public models. Use isolated sandbox.",
        "warn_critical": "\U0001f6d1 CRITICAL SENSITIVE DATA: {0}. Submission prohibited. Require on-premise processing.",
    },
    "it": {
        "safe": "Sicuro (AI Ready)", "low": "Basso (Monitoraggio)", "medium": "Medio (Anonimizzazione Obbligatoria)",
        "high": "Alto (Blocco Consigliato)", "critical": "Critico (Divieto Assoluto)",
        "empty": "✅ Nessun dato sensibile rilevato. Elaborazione AI sicura.",
        "masked_suffix": "\n\U0001f6e1️ Dati sensibili automaticamente mascherati.",
        "warn_safe": "⚠️ Minimi indicatori: {0}. Verifica formato.",
        "warn_low": "⚠️ Dati rilevati: {0}. Consigliato logging.",
        "warn_medium": "⛔ Dati rilevati: {0}. Pseudonimizzazione obbligatoria.",
        "warn_high": "\U0001f6a8 Dati rilevati: {0}. Non inviare a modelli pubblici.",
        "warn_critical": "\U0001f6d1 DATI SENSIBILI CRITICI: {0}. VIETATO l'invio.",
    },
    "de": {
        "safe": "Sicher (AI Ready)", "low": "Niedrig (Überwachung)", "medium": "Mittel (Anonymisierung erforderlich)",
        "high": "Hoch (Blockade empfohlen)", "critical": "Kritisch (Absolutes Verbot)",
        "empty": "✅ Keine sensiblen Daten erkannt. KI-Verarbeitung sicher.",
        "masked_suffix": "\n\U0001f6e1️ Sensible Daten wurden automatisch maskiert.",
        "warn_safe": "⚠️ Geringe Hinweise: {0}. Format prüfen.",
        "warn_low": "⚠️ Daten erkannt: {0}. Protokollierung empfohlen.",
        "warn_medium": "⛔ Daten erkannt: {0}. Pseudonymisierung vor KI erforderlich.",
        "warn_high": "\U0001f6a8 Daten erkannt: {0}. Nicht an öffentliche Modelle senden.",
        "warn_critical": "\U0001f6d1 KRITISCHE SENSIBLE DATEN: {0}. Übermittlung verboten. On-Premise erforderlich.",
    },
    "fr": {
        "safe": "Sûr (AI Ready)", "low": "Faible (Surveillance)", "medium": "Moyen (Anonymisation requise)",
        "high": "Élevé (Blocage recommandé)", "critical": "Critique (Interdiction absolue)",
        "empty": "✅ Aucune donnée sensible détectée. Traitement IA sûr.",
        "masked_suffix": "\n\U0001f6e1️ Données sensibles automatiquement masquées.",
        "warn_safe": "⚠️ Indicateurs mineurs : {0}. Vérifiez le format.",
        "warn_low": "⚠️ Données détectées : {0}. Journalisation recommandée.",
        "warn_medium": "⛔ Données détectées : {0}. Pseudonymisation obligatoire avant l'IA.",
        "warn_high": "\U0001f6a8 Données détectées : {0}. Ne pas envoyer aux modèles publics.",
        "warn_critical": "\U0001f6d1 DONNÉES SENSIBLES CRITIQUES : {0}. Envoi interdit. Traitement local requis.",
    },
    "es": {
        "safe": "Seguro (AI Ready)", "low": "Bajo (Monitoreo)", "medium": "Medio (Anonimización requerida)",
        "high": "Alto (Bloqueo recomendado)", "critical": "Crítico (Prohibición absoluta)",
        "empty": "✅ No se detectaron datos sensibles. Procesamiento con IA seguro.",
        "masked_suffix": "\n\U0001f6e1️ Datos sensibles enmascarados automáticamente.",
        "warn_safe": "⚠️ Indicadores menores: {0}. Verifique el formato.",
        "warn_low": "⚠️ Datos detectados: {0}. Se recomienda registro.",
        "warn_medium": "⛔ Datos detectados: {0}. Pseudonimización obligatoria antes de IA.",
        "warn_high": "\U0001f6a8 Datos detectados: {0}. No enviar a modelos públicos.",
        "warn_critical": "\U0001f6d1 DATOS SENSIBLES CRÍTICOS: {0}. Envío prohibido. Requiere procesamiento local.",
    },
}


def _get_locale(language: str) -> dict[str, str]:
    return _LOCALES.get((language or "en").lower(), _LOCALES["en"])


def _risk_level(score: int, loc: dict[str, str]) -> str:
    if score <= 15:
        return loc["safe"]
    if score <= 35:
        return loc["low"]
    if score <= 60:
        return loc["medium"]
    if score <= 85:
        return loc["high"]
    return loc["critical"]


def _load_default_rules_text() -> str:
    ref = importlib.resources.files("synthelion").joinpath("privacy_rules.yaml")
    return ref.read_text(encoding="utf-8")


class PrivacyBlockedError(RuntimeError):
    """Raised (instead of silently masking-and-continuing) when
    ``privacy.block_on_risk`` is enabled and a message's PII score reaches
    ``privacy.block_min_score``. Every agent entry point that shares this
    guard (RagAgent -> Claude/OpenAI/CrewAI adapters, the MCP/OpenAI-function
    `compress` tool, the Claude Code hook) raises/reports this the same way,
    so blocking behaves identically no matter which agent is talking to the
    text — not just Claude Code's terminal hook.
    """

    def __init__(self, result: "PrivacyAnalysisResult", notice: str) -> None:
        self.result = result
        self.notice = notice
        super().__init__(notice)


def build_privacy_notice(
    result: "PrivacyAnalysisResult", transparency_notice: str | None = None, blocked: bool = False,
) -> str:
    """Single source of truth for the human-readable PII/privacy breakdown +
    EU AI Act Art.50 transparency notice — shared by the CLI/hook, the RAG
    agent adapters (Claude/OpenAI/CrewAI), and the MCP/OpenAI-function
    `compress` tool, so the disclosure looks identical everywhere."""
    lines: list[str] = []
    if blocked:
        lines.append("[Synthelion] Blocked: high PII/privacy risk detected.")
    if result.detected_categories:
        cats = ", ".join(result.detected_categories)
        if lines:
            lines.append("")
        lines += [
            "PII / Privacy",
            f"Score: {result.score} - Risk: {result.risk_level}",
            "",
            f"Categories: {cats}",
            "",
            f"Compliance: {', '.join(result.compliance_flags)}",
            "",
            f"Masked: [{cats}]",
        ]
    if transparency_notice:
        if lines:
            lines.append("")
        lines.append(transparency_notice)
    return "\n".join(lines)


class PrivacyAnalyzer:
    """Thread-safe. One instance can be reused across calls/threads."""

    def __init__(
        self,
        use_ml: bool = False,
        ml_model: str | None = None,
        ml_min_confidence: float = 0.6,
        ml_detector: Any | None = None,
    ) -> None:
        """``use_ml=False`` (the default) is exactly today's regex+checksum
        analyzer, zero ML, no extra CPU. With ``use_ml=True`` the analysis asks
        Synthelion's own PrivacyGuardML model (`privacyguardml.PrivacyGuardMLDetector`,
        via `privacy_ml.get_ml_detector`) to confirm genuinely-sensitive bare
        values that the context-keyword gate would otherwise reject — see
        :func:`_match_is_confirmed`. ``ml_detector``
        lets callers inject a detector (used by tests); it defaults to the
        module-level cached :func:`privacy_ml.get_ml_detector`."""
        self._lock = threading.Lock()
        self._rules: list[CompiledRule] = []
        self._whitelist: set[str] = set()
        self._use_ml = use_ml
        self._ml_model = ml_model or _DEFAULT_ML_MODEL
        self._ml_min_confidence = ml_min_confidence
        self._injected_ml_detector = ml_detector
        self._load_rules_from_text(_load_default_rules_text())

    @classmethod
    def from_config(cls, pcfg: dict[str, Any]) -> "PrivacyAnalyzer":
        """Build an analyzer from an effective ``privacy_config()`` dict —
        the config-keys used are ``use_ml``, ``ml_model``, ``ml_min_confidence``
        and (list) ``whitelist``. Every production entry point (CLI, proxy,
        dashboard, MCP/OpenAI tools, RagAgent) constructs through this one
        factory so the optional ML tier follows the config everywhere."""
        analyzer = cls(
            use_ml=bool(pcfg.get("use_ml", False)),
            ml_model=pcfg.get("ml_model") or None,
            ml_min_confidence=float(pcfg.get("ml_min_confidence", 0.6) or 0.6),
        )
        whitelist = pcfg.get("whitelist")
        if whitelist:
            analyzer.add_to_whitelist(*whitelist)
        return analyzer

    # ── rule loading ─────────────────────────────────────────────────────────

    def _compile_rules(self, doc: dict) -> list[CompiledRule]:
        rules: list[CompiledRule] = []
        for country in doc.get("countries", []):
            for rule in country.get("rules", []):
                validator = None
                validator_name = rule.get("validator_name")
                if validator_name:
                    validator = get_validator(validator_name)
                pattern = re.compile(rule["pattern"])
                rules.append(CompiledRule(
                    category=rule["category"],
                    pattern=pattern,
                    base_weight=int(rule.get("base_weight", 0)),
                    validator=validator,
                    context_keywords=[k.lower() for k in (rule.get("context_keywords") or [])],
                    is_high_confidence=bool(rule.get("is_high_confidence", False)),
                    compliance_tags=list(rule.get("compliance_tags") or []),
                    requires_context=bool(rule.get("requires_context", False)),
                ))
        return rules

    def _load_rules_from_text(self, yaml_text: str, replace: bool = True) -> None:
        doc = yaml.safe_load(yaml_text) or {}
        compiled = self._compile_rules(doc)
        with self._lock:
            if replace:
                self._rules = compiled
            else:
                self._rules.extend(compiled)

    def load_custom_yaml(self, file_path: str, replace: bool = False) -> None:
        self._load_rules_from_text(Path(file_path).read_text(encoding="utf-8"), replace)

    def load_custom_yaml_from_string(self, yaml_content: str, replace: bool = False) -> None:
        self._load_rules_from_text(yaml_content, replace)

    def clear_rules(self) -> None:
        with self._lock:
            self._rules = []

    def get_loaded_categories(self) -> list[str]:
        with self._lock:
            return sorted({r.category for r in self._rules})

    # ── whitelist ────────────────────────────────────────────────────────────

    def add_to_whitelist(self, *values: str) -> None:
        with self._lock:
            self._whitelist.update(values)

    def remove_from_whitelist(self, *values: str) -> None:
        with self._lock:
            self._whitelist.difference_update(values)

    def clear_whitelist(self) -> None:
        with self._lock:
            self._whitelist.clear()

    def is_whitelisted(self, value: str) -> bool:
        with self._lock:
            return value in self._whitelist

    # ── analysis ─────────────────────────────────────────────────────────────

    def analyze(
        self,
        text: str,
        language: str = "en",
        session: PrivacySession | None = None,
        auto_masking: bool = False,
    ) -> PrivacyAnalysisResult:
        loc = _get_locale(language)
        if not text or not text.strip():
            return PrivacyAnalysisResult(score=0, risk_level="None", warning_message=loc["empty"])

        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        detected: dict[str, tuple[int, bool]] = {}
        base_score = 0.0
        total_matches = 0
        ml_assisted = 0

        with self._lock:
            rules_snapshot = list(self._rules)
            whitelist_snapshot = set(self._whitelist)

        ml_spans: list[MLSpan] | None = None
        if self._use_ml:
            ml_spans = self._run_ml_detection(normalized)

        for rule in rules_snapshot:
            rule_matches = 0
            any_valid = False
            for m in rule.pattern.finditer(normalized):
                if m.group() in whitelist_snapshot:
                    continue
                if self._match_is_confirmed(rule, m, normalized, ml_spans):
                    any_valid = True
                    rule_matches += 1
                    total_matches += 1
                    if rule.requires_context and ml_spans is not None and not self._context_is_ok(rule, m, normalized):
                        ml_assisted += 1
            if rule_matches > 0:
                detected[rule.category] = (rule_matches, any_valid)
                weight = rule.base_weight * (1.3 if any_valid else 0.5) * (1.2 if rule.is_high_confidence else 0.8)
                base_score += rule_matches * weight

        context_boost = self._calculate_context_boost(normalized, detected, rules_snapshot)
        density_bonus = min((total_matches / max(1, len(normalized) / 100.0)) * 0.7, 1.0)
        correlation_mult = min(1.0 + (len(detected) * 0.12), 2.2)
        final_score = int(max(0.0, min(100.0, (base_score * correlation_mult) + (context_boost * 12) + (density_bonus * 18))))

        result = PrivacyAnalysisResult(
            score=final_score,
            risk_level=_risk_level(final_score, loc),
            detected_categories=sorted(detected.keys()),
            matches_per_category={k: v[0] for k, v in detected.items()},
            compliance_flags=self._map_compliance_flags(detected.keys(), rules_snapshot),
            warning_message=self._generate_warning(final_score, detected, loc),
            match_count=total_matches,
            density_score=density_bonus,
            masked_text="",
            session=session if auto_masking else None,
        )

        if auto_masking:
            masked = self._mask_text(normalized, detected, rules_snapshot, whitelist_snapshot, session, ml_spans)
            result.masked_text = masked
            result.warning_message = result.warning_message + loc["masked_suffix"]

        if ml_assisted:
            result.ml_assisted_count = ml_assisted

        return result

    def analyze_batch(
        self, texts: list[str], language: str = "en", session: PrivacySession | None = None, auto_masking: bool = False,
    ) -> list[PrivacyAnalysisResult]:
        return [self.analyze(t, language, session, auto_masking) for t in texts]

    @staticmethod
    def restore_text(text: str, session: PrivacySession) -> str:
        return session.restore(text)

    # ── internals ────────────────────────────────────────────────────────────

    def _match_is_confirmed(self, rule: CompiledRule, m: re.Match, text: str, ml_spans: list[MLSpan] | None = None) -> bool:
        """Only "confirmed" matches count as a detection (and get masked).

        Five rules, in order of precedence (a lower one never overrides a higher
        one):

        * A rule with a checksum validator is NEVER confirmed by a value that
          fails that checksum — the algorithmic validator is the ground truth,
          and the optional ML tier cannot override it.
        * A non-context rule (strong structure: Email, IBAN, ...) is confirmed by
          the pattern alone.
        * A ``requires_context`` rule is confirmed when a ``context_keywords``
          term appears near the match AND the checksum passes (a random 9-13
          digit number behaves like a prose number, and even one that happens to
          pass a modulo-11 checksum is not PII unless a domain keyword anchors it).
          A ``+``-prefixed number is E.164 by definition and counts as its own
          anchor (the ``\\b\\+?`` boundary form could never capture the ``+``).
        * Only when the context keyword is missing AND the checksum passes does
          the optional ML tier step in: a ``privacy.use_ml`` entity span
          overlapping the match confirms a genuinely sensitive bare value
          (no context keyword needed). This recovers recall the strict gate
          trades away without ever adding a false positive.
        """
        if not rule.requires_context:
            return self._checksum_is_ok(rule, m)
        if not self._checksum_is_ok(rule, m):
            return False
        if self._context_is_ok(rule, m, text):
            return True
        # ML only ever confirms a *gated* rule whose checksum passed but whose
        # context keyword is missing — and only when the span's entity label
        # points at this rule's category (a "national ID" span must not confirm
        # a phone detection, nor vice versa).
        return bool(ml_spans) and any(
            s.start < m.end() and s.end > m.start() and self._ml_label_matches(s.label, rule.category)
            for s in ml_spans
        )

    @staticmethod
    def _ml_label_matches(label: str, category: str) -> bool:
        """Does an ML entity ``label`` (e.g. "national identification number")
        authorize confirming ``category``? Labels outside the table confirm
        nothing — see ``_ML_LABEL_CATEGORIES``."""
        allowed = _ML_LABEL_CATEGORIES.get((label or "").strip().lower().rstrip("."))
        return allowed is not None and category in allowed

    @staticmethod
    def _checksum_is_ok(rule: CompiledRule, m: re.Match) -> bool:
        """True when the rule has no validator or the matched value passes it."""
        return rule.validator is None or bool(rule.validator(m.group()))

    def _context_is_ok(self, rule: CompiledRule, m: re.Match, text: str) -> bool:
        """Context-keyword confirmation for ``requires_context`` rules. A
        ``+``-prefixed phone is E.164 by definition and needs no prose keyword."""
        if not rule.context_keywords:
            return False
        if rule.category == "Phone E.164" and m.group().startswith("+"):
            return True
        start = max(0, m.start() - _CONTEXT_WINDOW)
        end = min(len(text), m.end() + _CONTEXT_WINDOW)
        window = text[start:end].lower()
        return any(_keyword_in_window(k, window) for k in rule.context_keywords)

    def _run_ml_detection(self, text: str) -> list[MLSpan]:
        """Run the optional ML layer once per analyzed text. Any failure (missing
        package/model, no network, inference error) degrades gracefully to []."""
        try:
            detector = self._injected_ml_detector or get_ml_detector(self._ml_model, self._ml_min_confidence)
            return detector.detect(text) if detector is not None else []
        except Exception:
            return []

    def _calculate_context_boost(
        self, text: str, detected: dict[str, tuple[int, bool]], rules: list[CompiledRule],
    ) -> float:
        boost = 0.0
        for rule in rules:
            if not rule.context_keywords or rule.category not in detected:
                continue
            for m in rule.pattern.finditer(text):
                start = max(0, m.start() - 25)
                end = min(len(text), m.end() + 25)
                window = text[start:end].lower()
                if any(k in window for k in rule.context_keywords):
                    boost += 0.12
        return min(boost, 1.0)

    def _generate_warning(self, score: int, detected: dict[str, tuple[int, bool]], loc: dict[str, str]) -> str:
        if not detected:
            return loc["empty"]
        cats = ", ".join(detected.keys())
        level = _risk_level(score, loc)
        if level == loc["safe"]:
            return loc["warn_safe"].format(cats)
        if level == loc["low"]:
            return loc["warn_low"].format(cats)
        if level == loc["medium"]:
            return loc["warn_medium"].format(cats)
        if level == loc["high"]:
            return loc["warn_high"].format(cats)
        if level == loc["critical"]:
            return loc["warn_critical"].format(cats)
        return "Check input format."

    def _map_compliance_flags(self, categories, rules: list[CompiledRule]) -> list[str]:
        cats = set(categories)
        flags: list[str] = []
        for rule in rules:
            if rule.category in cats and rule.compliance_tags:
                flags.extend(rule.compliance_tags)

        if cats & _PERSONAL_ID_CATEGORIES:
            flags.append("GDPR/DSGVO/RGPD/RODO - Personal Identifiers")
        if cats & _FINANCIAL_ID_CATEGORIES:
            flags.append("PCI-DSS & SEPA - Financial/Payment Data")
        if "Password/Secret" in cats or "JWT/Token" in cats:
            flags.append("NIST 800-53 - Credentials & Secrets")
            flags.append("NIS2 Art.21 - Cybersecurity Risk Management (Credential Exposure)")
        if "GPS Coordinates" in cats:
            flags.append("GDPR Art.4(1) - Location Tracking")
        if "EU Vehicle License Plate" in cats:
            flags.append("GDPR Art.4(1) - Indirect Identifiers")
        if "PNR / Booking Code" in cats:
            flags.append("GDPR Art.4(1) - Mobility Data")
        if "Social / Messenger Handle" in cats:
            flags.append("GDPR Art.4(1) - Digital Identity")
        if "Minor Data (<16)" in cats:
            flags.append("GDPR Art.8 - Enhanced Minor Protection")
            flags.append("EU AI Act Art.5 - Vulnerable Groups Protection")
        if "Legal Case / File Number" in cats:
            flags.append("GDPR Art.10 - Judicial Data")
            flags.append("EU AI Act Annex III(8) - Law Enforcement & Justice")
        if "Employee / Badge ID" in cats:
            flags.append("GDPR Art.4(1) - Employment Data")
            flags.append("EU AI Act Annex III(4) - Employment/Worker Management")
        if cats & _FINANCIAL_ID_CATEGORIES:
            flags.append("EU AI Act Annex III(5) - Credit Scoring & Essential Services")

        # dedup, preserve first-seen order
        seen: set[str] = set()
        out = []
        for f in flags:
            if f not in seen:
                seen.add(f)
                out.append(f)
        return out

    def _mask_text(
        self,
        text: str,
        detected: dict[str, tuple[int, bool]],
        rules: list[CompiledRule],
        whitelist: set[str],
        session: PrivacySession | None,
        ml_spans: list[MLSpan] | None = None,
    ) -> str:
        intervals: list[tuple[int, int, str, str]] = []
        for rule in rules:
            if rule.category not in detected:
                continue
            for m in rule.pattern.finditer(text):
                if m.group() in whitelist:
                    continue
                if not self._match_is_confirmed(rule, m, text, ml_spans):
                    continue
                intervals.append((m.start(), m.end(), rule.category, m.group()))

        intervals.sort(key=lambda t: t[0])
        merged: list[list] = []
        for start, end, cat, val in intervals:
            if not merged or start >= merged[-1][1]:
                merged.append([start, end, cat, val])
            else:
                merged[-1][1] = max(merged[-1][1], end)

        out = text
        for start, end, cat, val in reversed(merged):
            placeholder = session.add_entry(cat, val) if session is not None else f"[{cat.upper()}]"
            out = out[:start] + placeholder + out[end:]
        return out
