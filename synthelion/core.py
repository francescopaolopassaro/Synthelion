# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from synthelion.detector import LanguageDetector
from synthelion.models import CompressionLevel, CompressionResult
from synthelion.word_provider import FunctionWordProvider

_WORD_SPLIT = re.compile(
    r"[\w]+(?:'[\w]+)?|[^\w\s]", re.UNICODE
)

# Languages that capitalise all common nouns — the positional proper-noun
# heuristic is disabled for these (same as C# CapitalizedNounLanguages).
_CAPITALIZED_NOUN_LANGS = frozenset({"deu"})

# Language group → suffix lists (ported verbatim from C# IsDescriptiveWord)
_EN_ADV = ("ly", "wise", "wards")
_EN_ADJ = ("ous", "al", "ive", "able", "ible", "ful", "less", "ic", "ical", "ant", "ent", "ish", "like", "some")
_ROMANCE_ADV = ("mente",)
_ROMANCE_ADJ = ("oso", "osa", "ivo", "iva", "abile", "ibile", "ale", "are", "ese", "ista")
_GERMANIC_ADJ = ("lich", "ig", "isch", "sam", "bar", "haft", "los", "voll", "arm", "reich")
_SLAVIC_ADJ = ("ный", "ная", "ное", "ные", "ний", "ня", "нє", "ова", "еви", "ски", "цки", "скиј", "чки")


def _lang_group(iso3: str) -> str:
    return {
        "eng": "en",
        "ita": "romance", "fra": "romance", "spa": "romance", "por": "romance",
        "ron": "romance", "cat": "romance", "glg": "romance", "lat": "romance",
        "deu": "germanic", "nld": "germanic", "afr": "germanic",
        "swe": "germanic", "dan": "germanic", "nor": "germanic", "isl": "germanic",
        "rus": "slavic", "ukr": "slavic", "bel": "slavic", "bul": "slavic",
        "srp": "slavic", "hrv": "slavic", "slv": "slavic", "slk": "slavic",
        "ces": "slavic", "pol": "slavic", "mkd": "slavic",
        "ara": "semitic", "heb": "semitic", "fas": "semitic", "urd": "semitic",
        "hin": "indic", "ben": "indic", "mar": "indic", "tel": "indic",
        "tam": "indic", "kan": "indic",
        "zho": "east_asian", "jpn": "east_asian", "kor": "east_asian",
        "tha": "east_asian", "vie": "east_asian",
        "tur": "uralic_altaic", "kaz": "uralic_altaic", "fin": "uralic_altaic",
        "est": "uralic_altaic", "hun": "uralic_altaic", "hye": "uralic_altaic",
        "ell": "uralic_altaic",
    }.get(iso3.lower(), "other")


def _is_descriptive(word: str, group: str) -> bool:
    if len(word) < 4:
        return False
    w = word.lower()
    if group == "en":
        return any(w.endswith(s) and len(w) > len(s) + 1 for s in _EN_ADV) or \
               any(w.endswith(s) and len(w) > len(s) + 2 for s in _EN_ADJ)
    if group == "romance":
        if w.endswith("mente") and len(w) > 7:
            return True
        return any(w.endswith(s) and len(w) > len(s) + 2 for s in _ROMANCE_ADJ)
    if group == "germanic":
        return any(w.endswith(s) and len(w) > len(s) + 2 for s in _GERMANIC_ADJ)
    if group == "slavic":
        return any(w.endswith(s) and len(w) > len(s) + 2 for s in _SLAVIC_ADJ)
    if group == "semitic":
        return len(w) > 5 and (w.startswith("al") or w.startswith("el"))
    if group == "uralic_altaic":
        return any(w.endswith(s) for s in ("лар", "лер", "дар", "дер", "тар", "тер", "мен", "бен", "пен"))
    return False


def _is_number(token: str) -> bool:
    return all(c.isdigit() or c in ".,- " for c in token) and bool(token)


# Generic word sets per language group (ported from C# GetGenericWords)
def _generic_words(group: str) -> frozenset[str]:
    if group == "en":
        return frozenset({
            "want", "wants", "wanted", "know", "knows", "knew", "make", "makes", "made",
            "get", "gets", "got", "take", "takes", "took", "taken", "give", "gives", "gave", "given",
            "come", "comes", "came", "go", "goes", "went", "gone", "see", "saw", "seen",
            "think", "thinks", "thought", "say", "says", "said", "tell", "tells", "told",
            "ask", "asks", "asked", "find", "finds", "found", "call", "calls", "called",
            "time", "times", "day", "days", "year", "years", "way", "ways", "thing", "things",
            "person", "people", "place", "places", "part", "parts", "world", "life",
            "hand", "hands", "eye", "eyes", "head", "face", "voice",
            "long", "short", "big", "small", "high", "low", "old", "new", "young",
            "good", "bad", "great", "little", "much", "many", "more", "most",
            "first", "last", "next", "same", "other", "another", "own",
            "work", "works", "worked", "working", "look", "looks", "looked",
            "seem", "seems", "seemed", "keep", "keeps", "kept", "let", "lets",
            "put", "puts", "run", "runs", "ran", "move", "moves", "moved",
            "help", "helps", "helped", "show", "shows", "showed", "shown",
            "try", "tries", "tried", "turn", "turns", "turned",
            "today", "yesterday", "tomorrow", "now", "then", "ago", "later",
            "always", "never", "often", "sometimes", "usually",
            "morning", "afternoon", "evening", "night",
            "please", "sorry", "thank", "hello", "goodbye", "welcome",
        })
    if group == "romance":
        return frozenset({
            "volere", "potere", "dovere", "sapere", "fare", "dire", "dare", "stare",
            "andare", "venire", "avere", "essere", "chiedere", "trovare",
            "tempo", "cosa", "modo", "parte", "volta", "caso", "giorno", "notte",
            "anno", "vita", "gente", "luogo", "mondo", "mano", "occhio", "testa",
            "persona", "persone", "casa", "nome", "parola",
            "grande", "piccolo", "nuovo", "vecchio", "bello", "buono", "cattivo",
            "lungo", "corto", "alto", "basso", "primo", "ultimo", "stesso", "altro",
            "molto", "poco", "tanto", "troppo", "piu", "meno",
            "sempre", "mai", "spesso", "ora", "poi", "dopo", "prima", "oggi", "ieri", "domani",
            "querer", "poder", "deber", "saber", "hacer", "decir", "dar", "estar",
            "ir", "venir", "haber", "ser", "tener",
            "tiempo", "año", "día", "noche", "vida", "persona", "casa", "mundo",
            "grande", "pequeño", "nuevo", "viejo", "bueno", "malo",
            "pouvoir", "vouloir", "devoir", "savoir", "faire", "dire", "aller", "venir",
            "temps", "jour", "nuit", "vie", "monde", "personne", "maison",
        })
    if group == "germanic":
        return frozenset({
            "sein", "haben", "werden", "können", "müssen", "wollen", "dürfen", "sollen", "mögen",
            "machen", "sagen", "geben", "kommen", "gehen", "sehen", "wissen", "denken",
            "finden", "nehmen", "tun", "lassen", "bringen", "halten", "setzen",
            "zeit", "jahr", "tag", "woche", "monat", "ding", "mensch", "welt",
            "groß", "klein", "neu", "alt", "gut", "schlecht", "schön",
            "viel", "wenig", "lang", "kurz", "hoch", "niedrig",
            "immer", "nie", "oft", "jetzt", "dann", "heute", "gestern", "morgen",
        })
    if group == "slavic":
        return frozenset({
            "быть", "мочь", "сказать", "знать", "хотеть", "делать", "иметь",
            "время", "год", "день", "человек", "мир", "дело", "место",
            "большой", "маленький", "новый", "старый", "хороший", "плохой",
            "всегда", "никогда", "сейчас", "потом", "сегодня", "вчера", "завтра",
        })
    return frozenset({
        "time", "day", "year", "person", "thing", "place", "world", "life",
        "big", "small", "new", "old", "good", "bad",
        "now", "then", "today", "yesterday", "tomorrow", "always", "never",
    })


@dataclass
class CompressionFilter:
    keep_only: set[str] | None = None  # categories: FUNC, PUNCT, NUM, PROPN, CONTENT
    remove: set[str] | None = None
    custom_predicate: Callable[[str], bool] | None = None


def _categorize(word: str, fw: frozenset[str]) -> str:
    if word.lower() in fw:
        return "FUNC"
    if _is_number(word):
        return "NUM"
    if word and word[0].isupper() and len(word) > 1:
        return "PROPN"
    return "CONTENT"


class CompressionService:
    """NLP prompt compressor: strips function words and lemmatizes tokens.

    Ported from C# CavemanCompressionService. Supports Light, Semantic and
    Aggressive compression levels across 50+ languages. Zero ML model dependency.
    """

    def __init__(
        self,
        word_provider: FunctionWordProvider | None = None,
        detector: LanguageDetector | None = None,
    ) -> None:
        self._provider = word_provider or FunctionWordProvider()
        self._detector = detector or LanguageDetector(self._provider)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_language(self, text: str) -> str:
        return self._detector.detect(text)

    def detect_language_scores(self, text: str) -> dict[str, float]:
        return self._detector.detect_with_scores(text)

    def compress(
        self,
        text: str,
        level: CompressionLevel = CompressionLevel.SEMANTIC,
        iso3: str | None = None,
        custom_filter: CompressionFilter | None = None,
    ) -> CompressionResult:
        if not text or not text.strip():
            return CompressionResult(compressed_text="")
        try:
            lang = iso3 or self._detector.detect(text)
            return self.apply_compression(text, lang, level, custom_filter)
        except Exception as exc:
            return CompressionResult(compressed_text=text, error_message=str(exc))

    def compress_batch(
        self,
        texts: list[str],
        level: CompressionLevel = CompressionLevel.SEMANTIC,
    ) -> list[CompressionResult]:
        return [self.compress(t, level) for t in texts]

    def apply_compression(
        self,
        text: str,
        iso3: str,
        level: CompressionLevel,
        custom_filter: CompressionFilter | None = None,
    ) -> CompressionResult:
        if not text or not text.strip():
            return CompressionResult(compressed_text="")

        fw = self._provider.get_function_words(iso3)
        lemmas = self._provider.get_lemma_map(iso3)
        proper_nouns = self._provider.get_proper_nouns(iso3)

        tokens = _tokenize(text)
        original_count = len(tokens)

        if level == CompressionLevel.NONE and custom_filter is None:
            return CompressionResult(
                compressed_text=text,
                original_tokens=original_count,
                compressed_tokens=original_count,
            )

        if custom_filter is not None:
            filtered = _apply_custom(tokens, fw, custom_filter)
        elif level == CompressionLevel.LIGHT:
            filtered = _filter_light(tokens, fw)
        elif level == CompressionLevel.SEMANTIC:
            filtered = _filter_semantic(tokens, fw, lemmas, proper_nouns, iso3)
        else:  # AGGRESSIVE
            filtered = _filter_aggressive(tokens, fw, lemmas, proper_nouns, iso3)

        compressed = " ".join(filtered)
        return CompressionResult(
            compressed_text=compressed,
            original_tokens=original_count,
            compressed_tokens=len(filtered),
        )


# ------------------------------------------------------------------
# Internal tokenization
# ------------------------------------------------------------------

class _Token:
    __slots__ = ("text", "is_punct")

    def __init__(self, text: str, is_punct: bool) -> None:
        self.text = text
        self.is_punct = is_punct


def _tokenize(text: str) -> list[_Token]:
    tokens = []
    for m in _WORD_SPLIT.finditer(text):
        t = m.group()
        is_punct = not (t[0].isalpha() or t[0].isdigit())
        tokens.append(_Token(t, is_punct))
    return tokens


# ------------------------------------------------------------------
# Proper-noun detection
# ------------------------------------------------------------------

def _detect_proper_nouns(
    tokens: list[_Token],
    iso3: str,
    proper_nouns: frozenset[str],
) -> list[bool]:
    cap_noun_lang = iso3.lower() in _CAPITALIZED_NOUN_LANGS
    has_gazetteer = bool(proper_nouns)
    result = [False] * len(tokens)
    sentence_start = True

    for i, tok in enumerate(tokens):
        if tok.is_punct:
            if tok.text in (".", "!", "?", "…"):
                sentence_start = True
            continue
        if tok.text and tok.text[0].isupper():
            in_gazetteer = has_gazetteer and tok.text.lower() in proper_nouns
            if cap_noun_lang:
                result[i] = in_gazetteer
            else:
                result[i] = (not sentence_start) or in_gazetteer
        sentence_start = False

    return result


# ------------------------------------------------------------------
# Compression filters
# ------------------------------------------------------------------

def _filter_light(tokens: list[_Token], fw: frozenset[str]) -> list[str]:
    return [
        t.text for t in tokens
        if not t.is_punct and t.text.lower() not in fw
    ]


def _lemma_or_lower(text: str, lemmas: dict[str, str]) -> str:
    lower = text.lower()
    return lemmas.get(lower, lower)


def _filter_semantic(
    tokens: list[_Token],
    fw: frozenset[str],
    lemmas: dict[str, str],
    proper_nouns: frozenset[str],
    iso3: str,
) -> list[str]:
    is_proper = _detect_proper_nouns(tokens, iso3, proper_nouns)
    out = []
    for i, tok in enumerate(tokens):
        if tok.is_punct:
            continue
        if is_proper[i]:
            out.append(tok.text)
            continue
        if _is_number(tok.text):
            continue
        if tok.text.lower() in fw:
            continue
        normalized = _lemma_or_lower(tok.text, lemmas)
        if normalized in fw:
            continue
        out.append(normalized)
    return out


def _filter_aggressive(
    tokens: list[_Token],
    fw: frozenset[str],
    lemmas: dict[str, str],
    proper_nouns: frozenset[str],
    iso3: str,
) -> list[str]:
    group = _lang_group(iso3)
    generic = _generic_words(group)
    is_proper = _detect_proper_nouns(tokens, iso3, proper_nouns)
    out = []
    for i, tok in enumerate(tokens):
        if tok.is_punct:
            continue
        if is_proper[i]:
            out.append(tok.text)
            continue
        if len(tok.text) <= 1 and not tok.text[0:1].isalpha():
            continue
        if _is_number(tok.text):
            continue
        lower = tok.text.lower()
        if lower in fw:
            continue
        normalized = _lemma_or_lower(tok.text, lemmas)
        if len(normalized) <= 1:
            continue
        if normalized in fw or normalized in generic:
            continue
        if _is_descriptive(normalized, group):
            continue
        out.append(normalized)
    return out


def _apply_custom(
    tokens: list[_Token],
    fw: frozenset[str],
    f: CompressionFilter,
) -> list[str]:
    out = []
    for tok in tokens:
        if tok.is_punct and f.remove and "PUNCT" in f.remove:
            continue
        if f.keep_only is not None:
            cat = _categorize(tok.text, fw)
            if cat not in f.keep_only:
                continue
        elif f.remove and "FUNC" in f.remove:
            if tok.text.lower() in fw:
                continue
        if f.custom_predicate is not None and not f.custom_predicate(tok.text):
            continue
        out.append(tok.text)
    return out
