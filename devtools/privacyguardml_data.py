# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Synthetic labeled-PII example generation for training PrivacyGuardML.

Self-distillation here works the other way round from SynthelionML's: instead
of a rule-based system labeling *real* text, this generates values that
Synthelion's own checksum validators (`privacy_validators.py`) already agree
are structurally valid, then inserts them into *real* multilingual sentences
(Synthelion's existing Wikipedia corpora, the same ones SynthelionML trained
on) at random positions — with a context keyword nearby some of the time, bare
some of the time, since the model has to recognise a value by shape alone for
the cases PrivacyAnalyzer's own context gate is too strict to catch on its
own (that gap is the entire reason the ML confirmation tier exists).

Ground truth is exact by construction: the inserted value's character span is
known at insertion time, so labeling never depends on a second detection pass
— tokens overlapping that span get the category's BIO tag, everything else is
O. Negative examples (including "PII-shaped but checksum-invalid" numbers) are
sampled alongside real ones so the model learns the boundary, not just the
positive shape.
"""
from __future__ import annotations

import random
import re
from pathlib import Path

import yaml

from pii_pattern_sampler import PatternSampler, generate_matching

# ---------------------------------------------------------------------------
# Coarse label set — must match privacy_analyzer._ML_LABEL_CATEGORIES's keys
# and privacy_ml.DEFAULT_ML_LABELS, since PrivacyAnalyzer only ever asks
# "does this ML label confirm that rule category", never anything finer.
# ---------------------------------------------------------------------------
CATEGORIES: tuple[str, ...] = (
    "PHONE", "EMAIL", "CREDITCARD", "IBAN",
    "NATIONALID", "TAXID", "SSN", "GPS",
    "VEHICLEPLATE", "BADGEID", "BUSINESSID", "SECRET", "SOCIALHANDLE",
    "LEGALCASE", "PNRCODE", "MINORDATA",
)

# The original 8 are checksum-backed (or, for PHONE/EMAIL/GPS, unambiguous by
# shape) — the primary reason the ML confirmation tier exists at all. The 8
# added later have no checksum and some overlap the primary categories' raw
# digit-run shape (French SIREN/SIRET looks exactly like a phone number
# without its "+"). Sampling all 16 uniformly halved the primary categories'
# training density and measurably hurt confidence on the flagship bare-phone
# case (confirmed A/B against the 8-category checkpoint) — weighting restores
# it without dropping the secondary categories.
_PRIMARY_CATEGORIES = frozenset({
    "PHONE", "EMAIL", "CREDITCARD", "IBAN", "NATIONALID", "TAXID", "SSN", "GPS",
})
# weight=4.0 -> each primary category gets ~10% of insertions (vs ~6.25% at
# uniform-16, close to the original ~12.5% at uniform-8), each secondary ~2.5%.
_PRIMARY_WEIGHT = 4.0
_SECONDARY_WEIGHT = 1.0

_ML_LABEL_OF: dict[str, str] = {
    "PHONE": "phone number",
    "EMAIL": "email address",
    "CREDITCARD": "credit card number",
    "IBAN": "iban number",
    "NATIONALID": "national identification number",
    "TAXID": "tax identification number",
    "SSN": "social security number",
    "GPS": "gps coordinates",
    "VEHICLEPLATE": "vehicle license plate",
    "BADGEID": "employee badge id",
    "BUSINESSID": "business identification number",
    "SECRET": "credential or secret",
    "SOCIALHANDLE": "social media handle",
    "LEGALCASE": "legal case number",
    "PNRCODE": "booking reference",
    "MINORDATA": "minor age indicator",
}


def _load_fine_to_coarse() -> dict[str, str]:
    """Fine rule category ("Italian Tax Code (CF)") -> coarse bucket, read
    straight from privacy_analyzer's own confirmation table so this never
    drifts from what actually gets confirmed at runtime."""
    from synthelion.privacy_analyzer import _ML_LABEL_CATEGORIES

    label_to_coarse = {
        "phone number": "PHONE", "email address": "EMAIL",
        "credit card number": "CREDITCARD", "iban number": "IBAN",
        "national identification number": "NATIONALID",
        "tax identification number": "TAXID",
        "social security number": "SSN", "gps coordinates": "GPS",
        "vehicle license plate": "VEHICLEPLATE",
        "employee badge id": "BADGEID",
        "business identification number": "BUSINESSID",
        "credential or secret": "SECRET",
        "social media handle": "SOCIALHANDLE",
        "legal case number": "LEGALCASE",
        "booking reference": "PNRCODE",
        "minor age indicator": "MINORDATA",
    }
    out: dict[str, str] = {}
    for ml_label, fine_categories in _ML_LABEL_CATEGORIES.items():
        coarse = label_to_coarse.get(ml_label)
        if not coarse:
            continue
        for fine in fine_categories:
            out[fine] = coarse
    # IBAN/Credit Card aren't behind requires_context, so they're not routed
    # through _ML_LABEL_CATEGORIES by fine-category name the same way — map
    # them directly.
    out["IBAN"] = "IBAN"
    out["Credit Card"] = "CREDITCARD"
    return out


# ---------------------------------------------------------------------------
# Direct generators — faster and more reliable than brute force for formats
# whose algorithm is simple to run forwards.
# ---------------------------------------------------------------------------

def _gen_iban(rng: random.Random) -> str:
    """A real IBAN: correct ISO 7064 mod-97 check digits, computed directly
    rather than brute-forced — the algorithm is a straight rearrange-and-mod.

    Letters are rare in a real BBAN (only a handful of countries mix them in
    at all — IT's one check letter, NL/GB's bank-code letters); most bodies
    are pure digit runs. Injecting them 30% of the time (the original rate)
    made almost every training IBAN fragment into several short alnum chunks
    and left the model never seeing a long pure-digit continuation token —
    exactly the shape a real DE/FR/ES/PT/BE IBAN's tail is. Dropped to 8%.
    Formatted display (space every 4 chars, as banks print it) is included
    some of the time so that shape is trained too, not just the compact one.
    """
    country = rng.choice(["IT", "DE", "FR", "ES", "NL", "GB", "BE", "PT"])
    body_len = {"IT": 23, "DE": 18, "FR": 23, "ES": 20, "NL": 14, "GB": 18, "BE": 12, "PT": 21}[country]
    body = "".join(rng.choice("0123456789") if rng.random() < 0.92 else rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                  for _ in range(body_len))
    rearranged = body + country + "00"
    numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    remainder = int(numeric) % 97
    check = 98 - remainder
    compact = f"{country}{check:02d}{body}"
    if rng.random() < 0.3:
        return " ".join(compact[i:i + 4] for i in range(0, len(compact), 4))
    return compact


def _gen_creditcard(rng: random.Random) -> str:
    """16 digits with a real Luhn check digit, computed directly.

    Cards are printed in 4-4-4-4 groups as often as they're typed compact —
    without some spaced examples the model never learns a multi-token
    CREDITCARD span, only the single-token compact one.
    """
    prefix = rng.choice(["4", "51", "52", "53", "54", "55", "34", "37"])
    body = prefix + "".join(rng.choice("0123456789") for _ in range(15 - len(prefix)))
    digits = [int(c) for c in body]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    check = (10 - total % 10) % 10
    compact = body + str(check)
    if rng.random() < 0.35:
        sep = rng.choice([" ", "-"])
        return sep.join(compact[i:i + 4] for i in range(0, len(compact), 4))
    return compact


def _gen_email(rng: random.Random) -> str:
    local = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(4, 10)))
    if rng.random() < 0.5:
        local += "." + "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(3, 8)))
    domain = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(4, 9)))
    tld = rng.choice(["com", "org", "net", "it", "de", "fr", "es", "eu", "io"])
    return f"{local}@{domain}.{tld}"


def _gen_phone(rng: random.Random) -> str:
    """E.164-ish digit run, compact most of the time but sometimes grouped
    the way people actually type phone numbers ("+39 333 1234567",
    "555-123-4567") — the compact-only original left the model with zero
    I-PHONE training examples, so a spaced phone number was never confirmed.
    """
    length = rng.randint(8, 13)
    digits = "".join(rng.choice("0123456789") for _ in range(length))
    compact = ("+" if rng.random() < 0.7 else "") + rng.choice("123456789") + digits[1:]
    if rng.random() < 0.35:
        sep = rng.choice([" ", "-"])
        group_size = rng.choice([3, 4])
        groups = [compact[i:i + group_size] for i in range(0, len(compact), group_size)]
        return sep.join(g for g in groups if g)
    return compact


def _gen_gps(rng: random.Random) -> str:
    lat = round(rng.uniform(-89.9, 89.9), rng.choice([3, 4, 5]))
    lon = round(rng.uniform(-179.9, 179.9), rng.choice([3, 4, 5]))
    return f"{lat}, {lon}"


def _gen_personnummer_se(rng: random.Random) -> str:
    """The shipped pattern and validator disagree on length (pattern allows
    12 raw digits, the validator wants exactly 10) — a pre-existing
    inconsistency in privacy_rules.yaml, not something to silently paper over
    at runtime. Generated directly here so training data isn't blocked on it."""
    while True:
        digits = [rng.randint(0, 9) for _ in range(9)]
        total = 0
        for i, d in enumerate(digits):
            n = d * (2 if i % 2 == 0 else 1)
            total += n - 9 if n > 9 else n
        check = (10 - total % 10) % 10
        raw = "".join(map(str, digits)) + str(check)
        if rng.random() < 0.5:
            return raw[:6] + "-" + raw[6:]
        return raw


_DIRECT_GENERATORS = {
    "IBAN": _gen_iban,
    "LUHN": _gen_creditcard,
    "PERSONNUMMER_SE": _gen_personnummer_se,
}


class PIIValueGenerator:
    """One compiled sampler per (fine category, validator) pair, built once
    from privacy_rules.yaml, reused for every value drawn during generation."""

    def __init__(self, rules_path: "Path | None" = None) -> None:
        from synthelion.privacy_validators import PRIVACY_VALIDATORS

        path = rules_path or (Path(__file__).resolve().parents[1] / "synthelion" / "privacy_rules.yaml")
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        fine_to_coarse = _load_fine_to_coarse()

        # coarse -> list of (fine_category, pattern, validator_name)
        self._by_coarse: dict[str, list[tuple[str, str, str | None]]] = {c: [] for c in CATEGORIES}
        for country in doc["countries"]:
            for rule in country["rules"]:
                coarse = fine_to_coarse.get(rule["category"])
                if coarse is None:
                    continue
                self._by_coarse[coarse].append((rule["category"], rule["pattern"], rule.get("validator_name")))
        self._validators = PRIVACY_VALIDATORS

    def coarse_categories(self) -> tuple[str, ...]:
        return tuple(c for c in CATEGORIES if self._by_coarse.get(c) or c in ("PHONE", "EMAIL", "GPS"))

    def coarse_category_weights(self) -> list[float]:
        """Sampling weights aligned with `coarse_categories()`'s order — see
        `_PRIMARY_CATEGORIES` for why this isn't uniform."""
        return [
            _PRIMARY_WEIGHT if c in _PRIMARY_CATEGORIES else _SECONDARY_WEIGHT
            for c in self.coarse_categories()
        ]

    def generate(self, coarse: str, rng: random.Random) -> str | None:
        if coarse == "EMAIL":
            return _gen_email(rng)
        if coarse == "PHONE":
            return _gen_phone(rng)
        if coarse == "GPS":
            return _gen_gps(rng)
        if coarse == "CREDITCARD":
            return _gen_creditcard(rng)
        if coarse == "IBAN":
            return _gen_iban(rng)

        entries = self._by_coarse.get(coarse) or []
        if not entries:
            return None
        _fine, pattern, validator_name = rng.choice(entries)
        direct = _DIRECT_GENERATORS.get(validator_name or "")
        if direct is not None:
            return direct(rng)
        validator = self._validators.get(validator_name) if validator_name else None
        return generate_matching(pattern, validator, rng, max_tries=20_000)

    def ml_label(self, coarse: str) -> str:
        return _ML_LABEL_OF[coarse]


# ---------------------------------------------------------------------------
# Distractor generation — PII-shaped but checksum-invalid, for negatives that
# actually stress the boundary instead of always being obviously clean prose.
# ---------------------------------------------------------------------------

def _locate_token_spans(text: str, tokens: list) -> list[tuple[int, int] | None]:
    """Character (start, end) for each token, found by sequential search.

    `core._tokenize` doesn't track offsets, and inference needs them to turn
    model output back into `MLSpan`s over the original text — so both training
    and inference share this exact recovery function, rather than inference
    reinventing it and risking the two disagreeing on edge cases.
    """
    spans: list[tuple[int, int] | None] = []
    cursor = 0
    for tok in tokens:
        idx = text.find(tok.text, cursor)
        if idx == -1:
            idx = text.find(tok.text)
        if idx == -1:
            spans.append(None)
            continue
        spans.append((idx, idx + len(tok.text)))
        cursor = idx + len(tok.text)
    return spans


def build_example(
    sentence: str,
    generator: PIIValueGenerator,
    rng: random.Random,
    p_insert: float = 0.55,
    p_distractor: float = 0.15,
    p_context: float = 0.5,
    context_words: dict[str, list[str]] | None = None,
) -> tuple[list[str], list[str]] | None:
    """One (words, bio_tags) training example from a real sentence.

    With probability `p_insert`, a real generated value for a random category
    is inserted at a random word boundary — with a nearby context keyword
    some of the time (`p_context`), bare the rest, since the model has to
    recognise a value by shape alone for exactly the cases the regex+context
    gate is too strict to confirm on its own. With `p_distractor` instead, a
    checksum-invalid look-alike is inserted and labeled O — the negative that
    actually teaches the boundary, not just "ordinary prose has no PII".
    Otherwise the sentence is used verbatim as a clean negative.
    """
    from synthelion.core import _tokenize

    words = sentence.split()
    if len(words) < 4:
        return None
    inserted_value = None
    coarse = None

    roll = rng.random()
    if roll < p_insert:
        cats = generator.coarse_categories()
        coarse = rng.choices(cats, weights=generator.coarse_category_weights(), k=1)[0]
        inserted_value = generator.generate(coarse, rng)
    elif roll < p_insert + p_distractor:
        coarse = rng.choice(CATEGORIES)
        inserted_value = generate_distractor(coarse, rng)
    label_this = inserted_value is not None and roll < p_insert

    if inserted_value is not None:
        pos = rng.randint(1, len(words) - 1)
        piece = inserted_value
        if label_this and context_words and coarse in context_words and rng.random() < p_context:
            piece = f"{rng.choice(context_words[coarse])} {inserted_value}"
        words = words[:pos] + [piece] + words[pos:]

    text = " ".join(words)
    tokens = _tokenize(text)
    if not any(not t.is_punct for t in tokens):
        return None

    labels = ["O"] * len(tokens)
    if label_this:
        val_start = text.find(inserted_value)
        val_end = val_start + len(inserted_value)
        spans = _locate_token_spans(text, tokens)
        first = True
        for i, span in enumerate(spans):
            if span is None or tokens[i].is_punct:
                continue
            s, e = span
            # Overlap, not exact containment — the value's own tokenization
            # can disagree slightly at the boundary with the full sentence's.
            if s < val_end and e > val_start:
                labels[i] = f"B-{coarse}" if first else f"I-{coarse}"
                first = False

    word_tokens = [t.text for t in tokens if not t.is_punct]
    word_labels = [lab for tok, lab in zip(tokens, labels) if not tok.is_punct]
    if not word_tokens:
        return None
    return word_tokens, word_labels


def generate_distractor(coarse: str, rng: random.Random) -> str | None:
    """A value that LOOKS like the category but fails validation — teaches
    the model that shape alone is not sufficient, mirroring the real
    checksum-hardening work already done in privacy_analyzer.py."""
    if coarse == "IBAN":
        return "IT" + "".join(rng.choice("0123456789") for _ in range(25))  # wrong check digits
    if coarse == "CREDITCARD":
        return "4" + "".join(rng.choice("0123456789") for _ in range(15))  # ~90% fail Luhn
    if coarse in ("NATIONALID", "TAXID", "SSN"):
        return "".join(rng.choice("0123456789") for _ in range(rng.randint(8, 13)))
    if coarse == "PHONE":
        return "".join(rng.choice("0123456789") for _ in range(rng.randint(3, 6)))  # too short to be E.164
    if coarse == "GPS":
        return str(rng.randint(1000, 99999))  # a plain number, not a coordinate pair
    return None
