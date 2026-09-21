# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Detectors for the compliance controls that had no backend.

**What these are, stated plainly.** Synthelion is a zero-ML, offline product:
its detection is lexicons, patterns and structural checks, not classifiers.
Content moderation and factuality are areas where a trained model genuinely
outperforms a lexicon, and nothing here pretends otherwise. What these give is
a real, deterministic, explainable control with a documented recall limit —
which is worth considerably more than a registry entry claiming a capability
that does not exist, and rather less than a proper classifier.

Each detector returns `(fired, detail, categories)` and is deliberately biased
towards precision over recall: a compliance gate that blocks legitimate work
gets switched off by its operators within a week, at which point it protects
nothing at all.

Limits worth knowing before relying on any of this:

* toxicity / illegal activity — lexicon plus intent phrasing. Obfuscation,
  slang, non-English text and sarcasm are missed.
* PHI — clinical vocabulary near a person-shaped context. Prose describing a
  condition without any listed term is missed.
* code vulnerabilities — the well-known dangerous shapes (eval of input, shell
  injection, SQL string concatenation). This is not a SAST tool.
* grounding — lexical overlap with the supplied context, which detects an
  answer invented out of nothing, not a subtly wrong number.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Toxicity and hate speech
# ---------------------------------------------------------------------------

# Slurs are deliberately NOT enumerated in source. The list below is abusive
# language and dehumanising constructions; a deployment that needs slur
# coverage supplies it through `compliance.custom_rules`, where it can be
# maintained privately rather than shipped in a public package.
_ABUSE_TERMS = (
    "idiot", "moron", "imbecile", "scum", "vermin", "worthless", "pathetic",
    "disgusting", "stupid bitch", "shut the fuck up", "fuck you", "piece of shit",
    "cretino", "idiota", "imbecille", "coglione", "bastardo", "schifoso",
)
_ABUSE_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in _ABUSE_TERMS) + r")\b", re.I)

# Dehumanising / harassing constructions — matched as phrasing, not vocabulary,
# so they survive a word the lexicon does not carry.
_HARASSMENT_RE = re.compile(
    r"\b(?:"
    r"i\s+hope\s+you\s+(?:die|suffer|rot)|"
    r"you\s+(?:should|deserve\s+to)\s+(?:die|kill\s+yourself)|"
    r"kill\s+yourself|"
    r"(?:all|those)\s+\w+\s+(?:are|should\s+be)\s+(?:exterminated|eliminated|wiped\s+out)|"
    r"spero\s+che\s+(?:tu\s+)?(?:muoia|soffra)"
    r")\b", re.I)

# Protected-characteristic targeting: a group term plus a hostile predicate.
_GROUP_RE = re.compile(
    r"\b(?:muslims?|jews?|christians?|blacks?|asians?|women|men|gays?|lesbians?|"
    r"immigrants?|refugees?|disabled|musulmani|ebrei|neri|immigrati|donne)\b", re.I)
_HOSTILE_PREDICATE_RE = re.compile(
    r"\b(?:are\s+all\s+\w+|should\s+(?:be\s+)?(?:banned|deported|removed|killed)|"
    r"don'?t\s+deserve|are\s+(?:inferior|subhuman|animals|parasites)|"
    r"vanno\s+(?:cacciati|eliminati)|sono\s+tutti)\b", re.I)


def detect_toxicity(text: str) -> tuple[bool, str, list[str]]:
    """Abusive language, harassment and targeting of protected groups."""
    if not text:
        return False, "", []
    categories: list[str] = []
    if _HARASSMENT_RE.search(text):
        categories.append("harassment")
    if _ABUSE_RE.search(text):
        categories.append("abusive_language")
    # Hate speech needs both halves: a group term alone is ordinary discussion.
    if _GROUP_RE.search(text) and _HOSTILE_PREDICATE_RE.search(text):
        categories.append("hate_speech")
    if not categories:
        return False, "", []
    return True, f"matched: {', '.join(categories)}", categories


# ---------------------------------------------------------------------------
# Hazardous and illegal activity
# ---------------------------------------------------------------------------

# Intent phrasing ("how do I make", "step by step to synthesise") combined with
# a hazardous object. Either half alone is normal text — a chemistry lesson
# mentions methamphetamine, a news report mentions explosives.
_INTENT_RE = re.compile(
    r"\b(?:how\s+(?:do\s+i|to|can\s+i)|step[-\s]by[-\s]step|instructions?\s+(?:for|to)|"
    r"teach\s+me\s+(?:how\s+)?to|guide\s+(?:for|to)\s+making|"
    r"come\s+(?:si\s+)?(?:fa|faccio|posso)|istruzioni\s+per)\b", re.I)
_HAZARD_RE = re.compile(
    r"\b(?:"
    r"(?:build|make|construct|assemble|synthesi[sz]e|manufacture|cook)\s+(?:an?\s+|the\s+)?"
    r"(?:bomb|explosive|ied|pipe\s*bomb|molotov|firearm|silencer|meth|methamphetamine|"
    r"fentanyl|nerve\s+agent|ricin|sarin)|"
    r"untraceable\s+(?:gun|firearm|weapon)|ghost\s+gun|"
    r"(?:bomba|esplosivo|ordigno|droga\s+sintetica)"
    r")\b", re.I)
_SELF_HARM_RE = re.compile(
    r"\b(?:how\s+to\s+(?:kill\s+myself|commit\s+suicide|end\s+my\s+life)|"
    r"painless\s+(?:suicide|way\s+to\s+die)|suicide\s+methods?|"
    r"come\s+(?:suicidarsi|farla\s+finita))\b", re.I)


def detect_illegal_activity(text: str) -> tuple[bool, str, list[str]]:
    """Requests for weapons, controlled substances or self-harm instructions."""
    if not text:
        return False, "", []
    categories: list[str] = []
    if _SELF_HARM_RE.search(text):
        categories.append("self_harm")
    if _HAZARD_RE.search(text) and _INTENT_RE.search(text):
        categories.append("hazardous_instructions")
    elif _HAZARD_RE.search(text) and re.search(r"\b(?:for\s+me|please|can\s+you)\b", text, re.I):
        categories.append("hazardous_instructions")
    if not categories:
        return False, "", []
    return True, f"matched: {', '.join(categories)}", categories


# ---------------------------------------------------------------------------
# Health data (PHI)
# ---------------------------------------------------------------------------

_CLINICAL_TERMS = (
    "diagnosis", "diagnosed", "prognosis", "symptoms", "treatment", "therapy",
    "medication", "prescription", "dosage", "biopsy", "chemotherapy", "hiv",
    "aids", "cancer", "tumour", "tumor", "diabetes", "hepatitis", "psychiatric",
    "depression", "schizophrenia", "pregnancy", "blood test", "medical record",
    "patient", "clinical",
    "diagnosi", "prognosi", "terapia", "farmaco", "referto", "cartella clinica",
    "paziente", "gravidanza", "tumore", "depressione",
)
_CLINICAL_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in _CLINICAL_TERMS) + r")\b", re.I)
# A person context: a name-shaped token, an explicit patient/subject marker, or
# a date of birth. Clinical vocabulary alone is a medical text, not PHI.
_PERSON_CONTEXT_RE = re.compile(
    r"\b(?:patient|mr\.?|mrs\.?|ms\.?|paziente|sig\.?|sig\.?ra|born|d\.?o\.?b\.?|nato\s+il)\b"
    r"|\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", re.I | re.UNICODE)


def detect_phi(text: str) -> tuple[bool, str, list[str], str | None]:
    """Clinical content tied to an identifiable person, plus a masked version.

    Requires both halves on purpose: a medical article is not PHI, and a name
    on its own is ordinary PII already handled by PrivacyGuard.

    Returns the redacted text as a fourth element because the rule's action is
    REDACT: a redaction rule whose detector hands back nothing to substitute
    would report a finding and then change nothing at all.
    """
    if not text:
        return False, "", [], None
    terms = {m.group(0).lower() for m in _CLINICAL_RE.finditer(text)}
    if not terms:
        return False, "", [], None
    if not re.search(r"\b(?:patient|paziente|mr\.?|mrs\.?|ms\.?|sig\.?)\b", text, re.I) \
            and not re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", text):
        return False, "", [], None
    masked = _CLINICAL_RE.sub("[HEALTH]", text)
    return (True, f"{len(terms)} clinical term(s) beside a person reference",
            ["health_data"], masked)


# ---------------------------------------------------------------------------
# Cross-border transfer / data residency
# ---------------------------------------------------------------------------

# Host suffixes whose processing location is documented as inside the EEA.
# Everything else is treated as a third-country transfer, because "unknown" and
# "outside the EEA" carry the same obligation under GDPR Chapter V.
_EEA_HOST_SUFFIXES = (
    ".eu", ".europa.eu", ".de", ".fr", ".it", ".es", ".nl", ".be", ".ie",
    ".se", ".fi", ".dk", ".at", ".pl", ".pt", ".cz", ".gr", ".no", ".is",
)
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.I)


def detect_data_residency(text: str, allowed_hosts: "tuple[str, ...]" = ()) -> tuple[bool, str, list[str]]:
    """Flag endpoints that would take data outside the EEA.

    Deterministic, unlike everything else in this module: it reads the host of
    each URL. A host on the deployment's `allowed_hosts` list is accepted
    regardless of suffix — that is where an operator records a provider they
    hold standard contractual clauses for.
    """
    if not text:
        return False, "", []
    offending: list[str] = []
    for match in _URL_RE.finditer(text):
        host = (urlparse(match.group(0)).hostname or "").lower()
        if not host or host in ("localhost", "127.0.0.1"):
            continue
        if any(host == a.lower() or host.endswith("." + a.lower()) for a in allowed_hosts):
            continue
        if any(host.endswith(s) for s in _EEA_HOST_SUFFIXES):
            continue
        offending.append(host)
    if not offending:
        return False, "", []
    unique = sorted(set(offending))
    return True, f"endpoint(s) outside the EEA allow-list: {', '.join(unique[:5])}", ["third_country_transfer"]


# ---------------------------------------------------------------------------
# Code vulnerability patterns
# ---------------------------------------------------------------------------

_VULN_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("rce_eval", re.compile(r"\b(?:eval|exec)\s*\(\s*(?:input|request|req|params|argv|sys\.argv)", re.I)),
    ("shell_injection", re.compile(r"\b(?:os\.system|subprocess\.(?:call|run|Popen))\s*\([^)]*(?:\+|%|\.format|f\")", re.I)),
    ("shell_true", re.compile(r"subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True", re.I)),
    ("sql_concat", re.compile(r"(?:SELECT|INSERT|UPDATE|DELETE)\b[^;\"']*[\"']\s*(?:\+|%|\.format|\|\|)", re.I)),
    ("deserialisation", re.compile(r"\b(?:pickle\.loads|yaml\.load\s*\((?![^)]*Loader)|marshal\.loads)", re.I)),
    ("weak_hash", re.compile(r"\bhashlib\.(?:md5|sha1)\s*\(", re.I)),
    ("hardcoded_secret", re.compile(r"\b(?:password|passwd|secret|api_key)\s*=\s*[\"'][^\"']{6,}[\"']", re.I)),
    ("tls_verify_off", re.compile(r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false", re.I)),
    ("xss_innerhtml", re.compile(r"\.innerHTML\s*=\s*(?!['\"]\s*['\"])", re.I)),
)


def detect_code_vulnerabilities(text: str) -> tuple[bool, str, list[str]]:
    """Well-known dangerous code shapes (a subset of the OWASP Top 10).

    Pattern-based, like a linter's security rules — it finds the shapes it
    knows and nothing else. Not a substitute for a SAST tool.
    """
    if not text:
        return False, "", []
    hits = [name for name, pattern in _VULN_PATTERNS if pattern.search(text)]
    if not hits:
        return False, "", []
    return True, f"{len(hits)} pattern(s): {', '.join(hits)}", hits


# ---------------------------------------------------------------------------
# Copyright / licence
# ---------------------------------------------------------------------------

_LICENCE_RE = re.compile(
    r"\b(?:GNU\s+GENERAL\s+PUBLIC\s+LICENSE|GPL-[23]\.0|AGPL-3\.0|"
    r"Creative\s+Commons\s+Attribution|CC\s+BY-NC|"
    r"All\s+rights\s+reserved|©\s*\d{4}|Copyright\s+\(c\)\s*\d{4})\b", re.I)


def detect_copyright(text: str) -> tuple[bool, str, list[str]]:
    """Licence headers and copyright notices in generated output.

    Detects a *declared* licence or notice, which is the tractable half of the
    problem. It cannot tell that an unmarked passage was copied from a
    protected work — that needs a corpus to compare against.
    """
    if not text:
        return False, "", []
    hits = {m.group(0) for m in _LICENCE_RE.finditer(text)}
    if not hits:
        return False, "", []
    return True, f"licence/copyright notice present: {', '.join(sorted(hits)[:3])}", ["copyright_notice"]


# ---------------------------------------------------------------------------
# Grounding / hallucination
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"\b\w{4,}\b", re.UNICODE)


def detect_ungrounded(text: str, context: str, min_overlap: float = 0.35) -> tuple[bool, str, list[str]]:
    """How much of the answer is anchored in the supplied context.

    Lexical overlap, not entailment: it catches an answer invented with no
    relation to the retrieved material, and will not catch a fluent answer
    that quotes the context while stating a wrong number. Returns not-fired
    when no context was supplied — with nothing to check against, silence is
    the only honest result.
    """
    if not text or not context:
        return False, "", []
    answer_words = {w.lower() for w in _WORD_RE.findall(text)}
    if not answer_words:
        return False, "", []
    context_words = {w.lower() for w in _WORD_RE.findall(context)}
    overlap = len(answer_words & context_words) / len(answer_words)
    if overlap >= min_overlap:
        return False, "", []
    return True, (f"only {overlap:.0%} of the answer's terms appear in the supplied context "
                  f"(threshold {min_overlap:.0%})"), ["ungrounded_output"]


# ---------------------------------------------------------------------------
# Machine-readable marking of generated content (AI Act Art. 50(2))
# ---------------------------------------------------------------------------

# Unicode TAG block: a documented, machine-readable, visually invisible channel
# that survives copy/paste of plain text. It is a marking, not a robust
# watermark — anything that normalises Unicode will strip it, and it carries no
# cryptographic binding to the content.
_TAG_BASE = 0xE0000
_MARKER_PREFIX = "SYNTH1:"


def embed_content_marker(text: str, marker: str = "AI-GENERATED") -> str:
    """Append an invisible, machine-readable marker to generated content."""
    if not text:
        return text
    payload = _MARKER_PREFIX + marker
    encoded = "".join(chr(_TAG_BASE + ord(c)) for c in payload if 0x20 <= ord(c) <= 0x7E)
    return text + encoded


def extract_content_marker(text: str) -> str | None:
    """Read back a marker embedded by `embed_content_marker`, if present."""
    if not text:
        return None
    decoded = "".join(
        chr(ord(c) - _TAG_BASE) for c in text
        if _TAG_BASE + 0x20 <= ord(c) <= _TAG_BASE + 0x7E
    )
    if decoded.startswith(_MARKER_PREFIX):
        return decoded[len(_MARKER_PREFIX):]
    return None


def detect_missing_marker(text: str) -> tuple[bool, str, list[str]]:
    """Fires when generated output carries no machine-readable marking."""
    if not text:
        return False, "", []
    if extract_content_marker(text):
        return False, "", []
    return True, "generated content carries no machine-readable AI marking", ["unmarked_output"]
