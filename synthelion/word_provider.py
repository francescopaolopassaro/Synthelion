# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import importlib.resources
import threading
from functools import lru_cache

import brotli

from synthelion.models import WordDataFile

# ---------------------------------------------------------------------------
# Curated inline function-word lists (ported from C# FunctionWordProvider)
# ---------------------------------------------------------------------------
_CURATED: dict[str, frozenset[str]] = {
    "eng": frozenset({
        "a", "an", "the", "this", "that", "these", "those",
        "i", "you", "he", "she", "it", "we", "they",
        "me", "him", "her", "us", "them",
        "my", "your", "his", "its", "our", "their",
        "mine", "yours", "hers", "ours", "theirs",
        "myself", "yourself", "himself", "herself", "itself", "ourselves", "themselves",
        "who", "whom", "whose", "which", "what",
        "in", "on", "at", "to", "for", "of", "with", "by", "from",
        "into", "onto", "upon", "within", "without",
        "during", "before", "after",
        "above", "below", "between", "among", "amongst",
        "across", "against", "around", "behind", "beneath",
        "beside", "besides", "beyond", "inside",
        "near", "off", "outside", "over", "past",
        "through", "toward", "towards", "under", "underneath",
        "via", "per",
        "and", "or", "but", "if", "because", "although", "though",
        "while", "whereas", "unless", "since", "so", "yet",
        "nor", "both", "whether", "either", "neither",
        "be", "am", "is", "are", "was", "were", "been", "being",
        "have", "has", "had", "having",
        "do", "does", "did", "doing", "done",
        "will", "would", "shall", "should",
        "can", "could", "may", "might", "must",
        "need", "dare", "ought",
        "not", "no", "nor", "never",
        "as", "than",
        "very", "too", "quite", "rather",
        "here", "there", "where",
        "when", "why", "how",
        "then", "now",
        "just", "only", "even",
        "also", "still", "already",
        "indeed", "however", "therefore",
        "otherwise", "nevertheless",
        "maybe", "perhaps",
        "please", "yes",
        "oh", "ah",
        "any", "some", "every", "each", "all", "few", "many", "much", "several",
        "nothing", "something", "anything", "everything",
        "someone", "anyone", "everyone", "none",
        "such", "same", "else", "other", "another",
        "more", "most", "less", "least",
        "up", "down", "out", "well",
    }),
    "ita": frozenset({
        "il", "lo", "la", "i", "gli", "le",
        "un", "uno", "una",
        "questo", "questa", "questi", "queste", "quel", "quella", "quelli", "quelle",
        "io", "tu", "lui", "lei", "noi", "voi", "loro",
        "mi", "ti", "si", "ci", "vi", "ne",
        "mio", "tuo", "suo", "nostro", "vostro",
        "mia", "tua", "sua", "nostra", "vostra",
        "miei", "tuoi", "suoi", "nostri", "vostri",
        "mie", "tue", "sue", "nostre", "vostre",
        "che", "cui", "chi",
        "in", "a", "da", "di", "con", "su", "per", "tra", "fra",
        "del", "dello", "della", "dei", "degli", "delle",
        "al", "allo", "alla", "ai", "agli", "alle",
        "dal", "dallo", "dalla", "dai", "dagli", "dalle",
        "nel", "nello", "nella", "nei", "negli", "nelle",
        "sul", "sullo", "sulla", "sui", "sugli", "sulle",
        "e", "ed", "o", "od", "ma",
        "se", "come", "mentre", "quando", "dove",
        "non", "neppure", "nemmeno",
        "sono", "sei", "siamo", "siete", "sia", "siano",
        "ho", "hai", "ha", "abbiamo", "avete", "hanno",
        "sto", "stai", "sta", "stiamo", "state", "stanno",
        "posso", "puoi", "puo", "possiamo", "potete", "possono",
        "voglio", "vuoi", "vuole", "vogliamo", "volete", "vogliono",
        "devo", "devi", "deve", "dobbiamo", "dovete", "devono",
        "qui", "qua", "li",
        "gia", "piu", "meno", "molto", "poco", "troppo",
        "anche", "pure", "ancora", "sempre", "mai",
        "poi", "dopo", "prima", "ora", "adesso",
        "allora", "dunque", "quindi", "inoltre", "perche",
        "fa", "fanno", "fare", "essere", "avere", "stare", "potere", "volere", "dovere",
        # Distinctive Italian forms rarely shared with other Romance languages
        "vorrei", "avrei", "sarei", "potrei", "dovrei", "farei", "darei",
        "volevo", "avevo", "ero", "stavo",
        "siete", "abbiate", "siate",
        "degli", "sugli", "negli",
        "perché", "però", "oppure", "nemmeno", "neppure", "neanche",
        "forse", "magari", "ecco", "certo", "sì",
        "grazie", "prego", "salve", "arrivederci",
    }),
    "fra": frozenset({
        "le", "la", "les", "l",
        "un", "une", "des", "du", "de", "d",
        "ce", "cet", "cette", "ces",
        "mon", "ton", "son", "ma", "ta", "sa",
        "mes", "tes", "ses", "nos", "vos", "leurs", "notre", "votre",
        "chaque", "quelques", "tout", "toute", "tous", "toutes",
        "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles",
        "me", "te", "se", "lui", "leur", "moi", "toi", "soi", "eux",
        "qui", "que", "quoi", "dont", "ou",
        "a", "dans", "par", "pour", "en", "vers", "avec",
        "sans", "sous", "sur", "chez", "entre", "pendant", "depuis",
        "et", "ou", "mais", "donc", "car", "ni",
        "que", "lorsque", "quand", "puisque", "si",
        "suis", "es", "est", "sommes", "etes", "sont",
        "ai", "as", "avons", "avez", "ont",
        "ete", "etre", "avoir",
        "ne", "pas", "plus",
        "tres", "aussi", "bien", "deja", "encore", "toujours", "jamais",
        "alors", "puis", "ainsi", "enfin",
        "trop", "assez", "moins", "beaucoup", "peu",
        "oui", "non", "ce", "c", "ca", "y",
    }),
    "deu": frozenset({
        "der", "die", "das", "den", "dem", "des",
        "ein", "eine", "einer", "eines", "einem", "einen",
        "mein", "dein", "sein", "ihr", "unser", "euer",
        "meine", "deine", "seine", "ihre", "unsere", "eure",
        "dieser", "diese", "dieses", "diesen", "diesem",
        "ich", "du", "er", "sie", "es", "wir", "ihr",
        "mich", "dich", "sich", "uns", "euch", "mir", "dir", "ihm", "man",
        "in", "auf", "mit", "von", "zu", "aus", "bei", "nach",
        "um", "durch", "fur", "gegen", "ohne",
        "uber", "unter", "vor", "hinter", "neben", "zwischen", "an", "bis", "seit",
        "und", "oder", "aber", "denn", "weil",
        "dass", "wenn", "als", "ob",
        "wahrend", "nachdem", "bevor", "seitdem",
        "bin", "bist", "ist", "sind", "seid", "war", "waren",
        "habe", "hast", "hat", "haben", "habt",
        "kann", "kannst", "konnen", "konnt",
        "muss", "musst", "mussen",
        "soll", "sollst", "sollen", "sollt",
        "will", "willst", "wollen", "wollt",
        "darf", "darfst", "durfen", "durft",
        "mag", "magst", "mogen",
        "nicht", "kein", "keine", "keinen", "nichts", "nie", "niemals",
        "sehr", "viel", "wenig", "zu", "ganz", "etwas", "mehr", "weniger",
        "schon", "noch", "immer", "ja", "nein", "auch", "nur",
    }),
    "spa": frozenset({
        "el", "la", "los", "las", "un", "una", "unos", "unas",
        "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas",
        "aquel", "aquella", "aquellos", "aquellas",
        "mi", "tu", "su", "nuestro", "vuestro", "mis", "tus", "sus", "nuestros", "vuestros",
        "yo", "el", "ella", "usted", "nosotros", "vosotros", "ellos", "ellas", "ustedes",
        "me", "te", "se", "nos", "os", "lo", "le", "les",
        "a", "ante", "bajo", "con", "contra", "de", "desde",
        "durante", "en", "entre", "hacia", "hasta",
        "mediante", "para", "por", "segun", "sin", "sobre", "tras",
        "y", "e", "o", "u", "pero", "sino",
        "aunque", "porque", "pues", "como", "que", "si", "cuando", "mientras",
        "soy", "eres", "es", "somos", "sois", "son",
        "he", "has", "ha", "hemos", "habeis", "han",
        "estoy", "estas", "esta", "estamos", "estais", "estan",
        "tengo", "tienes", "tiene", "tenemos", "teneis", "tienen",
        "puedo", "puedes", "puede", "podemos", "podeis", "pueden",
        "quiero", "quieres", "quiere", "queremos", "quereis", "quieren",
        "debo", "debes", "debe", "debemos", "debeis", "deben",
        "no", "nada", "nadie", "ningun", "ninguna", "nunca", "jamas",
        "muy", "mucho", "poca", "poco", "bastante", "demasiado",
        "mas", "menos", "casi", "solo", "solamente",
        "tambien", "siempre", "ya", "aun", "todavia",
        "aqui", "ahi", "alli", "bien", "mal",
    }),
    "por": frozenset({
        "o", "a", "os", "as", "um", "uma", "uns", "umas",
        "este", "esta", "estes", "estas", "esse", "essa", "esses", "essas",
        "aquele", "aquela", "aqueles", "aquelas",
        "meu", "minha", "teu", "tua", "seu", "sua",
        "nosso", "nossa", "vosso", "vossa",
        "meus", "minhas", "teus", "tuas", "seus", "suas",
        "eu", "tu", "ele", "ela", "nos", "vos", "eles", "elas",
        "voce", "voces", "me", "te", "se", "lhe", "lhes",
        "a", "ante", "apos", "ate", "com", "contra", "de",
        "desde", "em", "entre", "para", "perante", "por",
        "sem", "sob", "sobre", "tras",
        "e", "mas", "ou", "porque", "pois", "como", "que", "se",
        "quando", "enquanto", "embora", "contudo", "entretanto", "portanto", "porem", "todavia",
        "sou", "somos", "sao", "estou", "esta", "estamos", "estao",
        "tenho", "tem", "temos", "hei", "ha", "havemos", "hao",
        "posso", "pode", "podemos", "podem",
        "quero", "quer", "queremos", "querem",
        "devo", "deve", "devemos", "devem",
        "nao", "nada", "ninguem", "nenhum", "nenhuma", "nunca", "jamais",
        "muito", "pouco", "bastante", "demais", "mais", "menos",
        "quase", "so", "somente", "tambem", "sempre", "ja", "ainda", "agora",
    }),
    "nld": frozenset({
        "de", "het", "een", "deze", "dit", "die", "dat",
        "mijn", "jouw", "zijn", "haar", "onze", "ons", "hun", "uw",
        "ik", "jij", "je", "u", "hij", "zij", "ze", "wij", "we", "jullie",
        "mij", "me", "jou", "hem", "hen",
        "in", "op", "met", "van", "naar", "uit", "bij", "door",
        "voor", "over", "onder", "tegen", "tussen",
        "tijdens", "na", "langs", "om", "zonder", "binnen", "buiten", "via", "per",
        "en", "of", "maar", "want", "dus", "omdat",
        "als", "wanneer", "terwijl", "hoewel", "indien", "tenzij", "nadat", "voordat",
        "ben", "bent", "is", "zijn", "was", "waren",
        "heb", "hebt", "heeft", "hebben", "had", "hadden",
        "kan", "kunt", "kunnen", "moet", "moeten",
        "mag", "mogen", "wil", "wilt", "willen",
        "zal", "zult", "zullen", "zou", "zouden",
        "word", "wordt", "werd", "werden", "geworden",
        "niet", "geen", "niets", "niemand", "nooit",
        "heel", "veel", "weinig", "erg", "nog", "al", "reeds",
        "pas", "slechts", "maar", "net", "even", "bijna", "haast",
        "ja", "nee", "ook",
    }),
}


class FunctionWordProvider:
    """Loads per-language function words, lemmas and proper nouns from embedded worddata.

    Ported from C# FunctionWordProvider. Language data files are brotli-compressed
    YAML blobs shipped with the package (synthelion/worddata/*.yaml.br + _index.br).
    """

    @classmethod
    def get_curated_iso3s(cls) -> frozenset[str]:
        """Return ISO 639-3 codes of languages with hand-curated function-word lists."""
        return frozenset(_CURATED.keys())

    _index_lock = threading.Lock()
    _index: dict[str, tuple[str, str, frozenset[str]]] | None = None  # iso3 → (iso1, name, fw)
    _fw_cache: dict[str, frozenset[str]] = {}
    _lemma_cache: dict[str, dict[str, str]] = {}
    _word_data_cache: dict[str, WordDataFile | None] = {}

    @classmethod
    def _worddata_path(cls) -> importlib.resources.abc.Traversable:
        return importlib.resources.files("synthelion.worddata")

    @classmethod
    def _load_index(cls) -> dict[str, tuple[str, str, frozenset[str]]]:
        if cls._index is not None:
            return cls._index
        with cls._index_lock:
            if cls._index is not None:
                return cls._index
            idx: dict[str, tuple[str, str, frozenset[str]]] = {}
            try:
                data = cls._worddata_path().joinpath("_index.br").read_bytes()
                raw = brotli.decompress(data)
                for line in raw.decode("utf-8").splitlines():
                    if not line:
                        continue
                    parts = line.split("\t")
                    if len(parts) < 3:
                        continue
                    iso3, iso1, name = parts[0], parts[1], parts[2]
                    fw = frozenset(p for p in parts[3:] if p)
                    idx[iso3] = (iso1, name, fw)
            except Exception:
                pass
            cls._index = idx
        return cls._index

    def get_function_words(self, iso3: str) -> frozenset[str]:
        iso3 = iso3.lower()
        if iso3 in _CURATED:
            return _CURATED[iso3]
        cached = FunctionWordProvider._fw_cache.get(iso3)
        if cached is not None:
            return cached
        idx = self._load_index()
        entry = idx.get(iso3)
        result = entry[2] if entry else frozenset()
        FunctionWordProvider._fw_cache[iso3] = result
        return result

    def get_all_supported_iso3(self) -> set[str]:
        supported = set(_CURATED.keys())
        supported.update(self._load_index().keys())
        return supported

    def is_function_word(self, word: str, iso3: str) -> bool:
        return word.strip().lower() in self.get_function_words(iso3)

    def load_word_data(self, iso3: str) -> WordDataFile | None:
        iso3 = iso3.lower()
        if iso3 in FunctionWordProvider._word_data_cache:
            return FunctionWordProvider._word_data_cache[iso3]
        try:
            data = self._worddata_path().joinpath(f"{iso3}.yaml.br").read_bytes()
            raw = brotli.decompress(data)
            result = _parse_yaml(raw.decode("utf-8"))
        except Exception:
            result = None
        FunctionWordProvider._word_data_cache[iso3] = result
        return result

    def get_lemma_map(self, iso3: str) -> dict[str, str]:
        iso3 = iso3.lower()
        if iso3 in FunctionWordProvider._lemma_cache:
            return FunctionWordProvider._lemma_cache[iso3]
        data = self.load_word_data(iso3)
        if data is None:
            FunctionWordProvider._lemma_cache[iso3] = {}
            return {}
        m: dict[str, str] = {}
        for lemma, forms in data.verbs.items():
            if not lemma:
                continue
            for f in forms:
                if f:
                    m[f.lower()] = lemma
        for form, lemma in data.lemmas.items():
            if form and lemma:
                m[form.lower()] = lemma
        FunctionWordProvider._lemma_cache[iso3] = m
        return m

    def get_proper_nouns(self, iso3: str) -> frozenset[str]:
        data = self.load_word_data(iso3)
        if data is None or not data.proper_nouns:
            return frozenset()
        return frozenset(n.lower() for n in data.proper_nouns if n)


# ---------------------------------------------------------------------------
# Streaming YAML parser — ported from C# FunctionWordProvider.ParseYaml
# ---------------------------------------------------------------------------
def _strip_quotes(s: str) -> str:
    if len(s) >= 2:
        if s[0] == '"' and s[-1] == '"':
            return s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        if s[0] == "'" and s[-1] == "'":
            return s[1:-1].replace("''", "'")
    return s


def _try_parse_kv(t: str) -> tuple[str, str] | None:
    if not t:
        return None
    if t[0] == '"':
        close = _closing_quote(t, 0)
        if close < 0:
            return None
        colon = t.find(":", close + 1)
        if colon < 0:
            return None
        key = _strip_quotes(t[: close + 1])
    else:
        colon = t.find(":")
        if colon < 0:
            return None
        key = _strip_quotes(t[:colon].strip())
    value = _strip_quotes(t[colon + 1 :].strip())
    return key, value


def _closing_quote(s: str, open_idx: int) -> int:
    i = open_idx + 1
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == '"':
            return i
        i += 1
    return -1


_SEC_NONE = 0
_SEC_FW = 1
_SEC_LEMMAS = 2
_SEC_VERBS = 3
_SEC_PROPER = 4


def _parse_yaml(text: str) -> WordDataFile:
    data = WordDataFile()
    section = _SEC_NONE
    current_verb: str | None = None

    for line in text.splitlines():
        if not line:
            continue
        if not line[0].isspace():
            key = line.rstrip()
            if key.startswith("iso3:"):
                data.iso3 = key[5:].strip()
                section = _SEC_NONE
            elif key.startswith("iso1:"):
                data.iso1 = key[5:].strip()
                section = _SEC_NONE
            elif key.startswith("name:"):
                data.name = key[5:].strip()
                section = _SEC_NONE
            elif key == "function_words:":
                section = _SEC_FW
            elif key == "lemmas:":
                section = _SEC_LEMMAS
            elif key == "verbs:":
                section = _SEC_VERBS
                current_verb = None
            elif key == "proper_nouns:":
                section = _SEC_PROPER
            else:
                section = _SEC_NONE
            continue

        t = line.strip()
        if section == _SEC_FW:
            if t and t[0] == "-":
                w = _strip_quotes(t[1:].strip())
                if w:
                    data.function_words.append(w)
        elif section == _SEC_LEMMAS:
            kv = _try_parse_kv(t)
            if kv and kv[0] and kv[1]:
                data.lemmas[kv[0]] = kv[1]
        elif section == _SEC_VERBS:
            if t and t[0] == "-":
                if current_verb is not None:
                    f = _strip_quotes(t[1:].strip())
                    if f:
                        data.verbs.setdefault(current_verb, []).append(f)
            else:
                kv = _try_parse_kv(t)
                if kv and kv[0]:
                    current_verb = kv[0]
                    if current_verb not in data.verbs:
                        data.verbs[current_verb] = []
        elif section == _SEC_PROPER:
            if t and t[0] == "-":
                n = _strip_quotes(t[1:].strip())
                if n:
                    data.proper_nouns.append(n)

    return data
