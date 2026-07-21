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

from synthelion.privacy_session import PrivacySession
from synthelion.privacy_validators import get_validator

_RULES_TIMEOUT = 2.0  # seconds — regex compile safety net, mirrors the C# RegexHelper timeout


@dataclass
class CompiledRule:
    category: str
    pattern: re.Pattern
    base_weight: int
    validator: Any
    context_keywords: list[str]
    is_high_confidence: bool
    compliance_tags: list[str]


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

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rules: list[CompiledRule] = []
        self._whitelist: set[str] = set()
        self._load_rules_from_text(_load_default_rules_text())

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

        with self._lock:
            rules_snapshot = list(self._rules)
            whitelist_snapshot = set(self._whitelist)

        for rule in rules_snapshot:
            matches = list(rule.pattern.finditer(normalized))
            if not matches:
                continue
            rule_matches = 0
            any_valid = False
            for m in matches:
                if m.group() in whitelist_snapshot:
                    continue
                is_valid = rule.validator(m.group()) if rule.validator else True
                if is_valid:
                    any_valid = True
                rule_matches += 1
                total_matches += 1
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
            masked = self._mask_text(normalized, detected, rules_snapshot, whitelist_snapshot, session)
            result.masked_text = masked
            result.warning_message = result.warning_message + loc["masked_suffix"]

        return result

    def analyze_batch(
        self, texts: list[str], language: str = "en", session: PrivacySession | None = None, auto_masking: bool = False,
    ) -> list[PrivacyAnalysisResult]:
        return [self.analyze(t, language, session, auto_masking) for t in texts]

    @staticmethod
    def restore_text(text: str, session: PrivacySession) -> str:
        return session.restore(text)

    # ── internals ────────────────────────────────────────────────────────────

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
    ) -> str:
        intervals: list[tuple[int, int, str, str]] = []
        for rule in rules:
            if rule.category not in detected:
                continue
            for m in rule.pattern.finditer(text):
                if m.group() in whitelist:
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
