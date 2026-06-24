# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
#
# Generates supplementary .br worddata files:
#   {iso3}.fw.yaml.br     — curated grammatical function words (for compression)
#   {iso3}.excl.yaml.br   — exclusive markers + ambiguous word list (for detection)
#   {iso3}.generic.yaml.br — generic content words removed in aggressive mode
#
# Usage:
#   python scripts/generate_worddata.py
#   (run from project root; reads from C:\Sorgenti\Personal\caveman\worddata)
"""Generate .fw.yaml.br, .excl.yaml.br and .generic.yaml.br worddata files."""
from __future__ import annotations

import pathlib
import sys

import brotli

CAVEMAN_WD = pathlib.Path(r"C:\Sorgenti\Personal\caveman\worddata")
OUTPUT_WD = pathlib.Path(__file__).parent.parent / "synthelion" / "worddata"

CURATED_LANGS = ["eng", "ita", "fra", "deu", "spa", "por", "nld"]

# ---------------------------------------------------------------------------
# Curated grammatical function words — only true function words (articles,
# pronouns, prepositions, conjunctions, auxiliaries, modals).
# These are used for compression (removing grammatical glue).
# The full YAML stop-word lists are broader and used only for detection.
# ---------------------------------------------------------------------------
CURATED_FW: dict[str, list[str]] = {
    "eng": [
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
    ],
    "ita": [
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
        "vorrei", "avrei", "sarei", "potrei", "dovrei", "farei", "darei",
        "volevo", "avevo", "ero", "stavo",
        "siete", "abbiate", "siate",
        "degli", "sugli", "agli", "dagli", "negli",
        "perché", "però", "oppure", "nemmeno", "neppure", "neanche",
        "forse", "magari", "ecco", "certo", "sì",
        "grazie", "prego", "salve", "arrivederci",
    ],
    "fra": [
        "le", "la", "les",
        "un", "une", "des", "du", "de",
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
        "lorsque", "quand", "puisque", "si",
        "suis", "es", "est", "sommes", "etes", "sont",
        "ai", "as", "avons", "avez", "ont",
        "ete", "etre", "avoir",
        "ne", "pas", "plus",
        "tres", "aussi", "bien", "deja", "encore", "toujours", "jamais",
        "alors", "puis", "ainsi", "enfin",
        "trop", "assez", "moins", "beaucoup", "peu",
        "oui", "non",
    ],
    "deu": [
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
    ],
    "spa": [
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
    ],
    "por": [
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
    ],
    "nld": [
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
    ],
}

# ---------------------------------------------------------------------------
# Generic compression words per language (aggressive mode)
# These replace the mixed-romance frozenset in core.py
# ---------------------------------------------------------------------------
GENERIC_WORDS: dict[str, list[str]] = {
    "eng": [
        "want", "wants", "wanted", "know", "knows", "knew", "make", "makes", "made",
        "get", "gets", "got", "take", "takes", "took", "taken", "give", "gives", "gave",
        "come", "comes", "came", "go", "goes", "went", "gone", "see", "saw", "seen",
        "think", "thinks", "thought", "say", "says", "said", "tell", "tells", "told",
        "ask", "asks", "asked", "find", "finds", "found", "call", "calls", "called",
        "time", "day", "year", "way", "thing", "person", "people", "place", "world", "life",
        "hand", "eye", "head", "face", "voice", "long", "short", "big", "small", "old", "new",
        "good", "bad", "great", "first", "last", "next", "same", "other",
        "work", "look", "seem", "keep", "run", "move", "help", "show", "try", "turn",
        "today", "yesterday", "tomorrow", "morning", "afternoon", "evening", "night",
        "please", "sorry", "thank", "hello", "goodbye", "welcome",
    ],
    "ita": [
        "volere", "potere", "dovere", "sapere", "fare", "dire", "dare", "stare",
        "andare", "venire", "avere", "essere", "chiedere", "trovare", "chiamare",
        "tempo", "cosa", "modo", "parte", "volta", "caso", "giorno", "notte",
        "anno", "vita", "gente", "luogo", "mondo", "mano", "occhio", "testa",
        "persona", "persone", "casa", "nome", "parola", "lavoro",
        "grande", "piccolo", "nuovo", "vecchio", "bello", "buono", "cattivo",
        "lungo", "corto", "alto", "basso", "primo", "ultimo", "stesso", "altro",
        "molto", "poco", "tanto", "troppo",
        "sempre", "mai", "spesso", "ora", "poi", "dopo", "prima", "oggi", "ieri", "domani",
        "mattina", "pomeriggio", "sera", "notte",
        "grazie", "prego", "ciao", "salve", "arrivederci",
    ],
    "fra": [
        "pouvoir", "vouloir", "devoir", "savoir", "faire", "dire", "aller", "venir",
        "avoir", "etre", "demander", "trouver", "appeler",
        "temps", "chose", "facon", "partie", "fois", "cas", "jour", "nuit",
        "annee", "vie", "gens", "lieu", "monde", "main", "oeil", "tete",
        "personne", "maison", "nom", "mot", "travail",
        "grand", "petit", "nouveau", "vieux", "beau", "bon", "mauvais",
        "long", "court", "haut", "bas", "premier", "dernier", "meme", "autre",
        "beaucoup", "peu", "toujours", "jamais", "souvent",
        "maintenant", "puis", "apres", "avant", "hier", "demain",
        "bonjour", "merci", "pardon", "bonsoir", "bienvenue",
    ],
    "deu": [
        "sein", "haben", "werden", "koennen", "muessen", "wollen", "duerfen", "sollen", "moegen",
        "machen", "sagen", "geben", "kommen", "gehen", "sehen", "wissen", "denken",
        "finden", "nehmen", "lassen", "bringen", "halten", "setzen",
        "zeit", "jahr", "tag", "woche", "monat", "ding", "mensch", "welt",
        "gross", "klein", "neu", "alt", "gut", "schlecht", "schoen",
        "viel", "wenig", "lang", "kurz", "hoch", "niedrig",
        "immer", "nie", "oft", "jetzt", "dann", "heute", "gestern", "morgen",
        "danke", "bitte", "hallo", "tschues", "willkommen",
    ],
    "spa": [
        "querer", "poder", "deber", "saber", "hacer", "decir", "dar", "estar",
        "ir", "venir", "haber", "ser", "tener", "pedir", "encontrar", "llamar",
        "tiempo", "cosa", "modo", "parte", "vez", "caso", "dia", "noche",
        "anno", "vida", "gente", "lugar", "mundo", "mano", "ojo", "cabeza",
        "persona", "casa", "nombre", "palabra", "trabajo",
        "grande", "pequeno", "nuevo", "viejo", "bueno", "malo",
        "largo", "corto", "alto", "bajo", "primero", "ultimo", "mismo", "otro",
        "mucho", "poco", "siempre", "nunca", "ahora", "despues", "antes",
        "hoy", "ayer", "manana",
        "gracias", "por favor", "hola", "adios", "bienvenido",
    ],
    "por": [
        "querer", "poder", "dever", "saber", "fazer", "dizer", "dar", "estar",
        "ir", "vir", "haver", "ser", "ter", "pedir", "encontrar", "chamar",
        "tempo", "coisa", "modo", "parte", "vez", "caso", "dia", "noite",
        "ano", "vida", "gente", "lugar", "mundo", "mao", "olho", "cabeca",
        "pessoa", "casa", "nome", "palavra", "trabalho",
        "grande", "pequeno", "novo", "velho", "bom", "mau",
        "longo", "curto", "alto", "baixo", "primeiro", "ultimo", "mesmo", "outro",
        "muito", "pouco", "sempre", "nunca", "agora", "depois", "antes",
        "hoje", "ontem", "amanha",
        "obrigado", "por favor", "ola", "tchau", "bem-vindo",
    ],
    "nld": [
        "willen", "kunnen", "moeten", "mogen", "zullen", "maken", "zeggen",
        "geven", "komen", "gaan", "zien", "weten", "denken", "vinden",
        "nemen", "laten", "brengen", "houden", "zetten",
        "tijd", "jaar", "dag", "week", "maand", "ding", "mens", "wereld",
        "groot", "klein", "nieuw", "oud", "goed", "slecht", "mooi",
        "veel", "weinig", "lang", "kort", "hoog", "laag",
        "altijd", "nooit", "vaak", "nu", "dan", "vandaag", "gisteren", "morgen",
        "dank", "alsjeblieft", "hallo", "dag", "welkom",
    ],
    "rus": [
        "быть", "мочь", "сказать", "знать", "хотеть", "делать", "иметь",
        "идти", "приходить", "давать", "брать", "видеть", "думать",
        "время", "год", "день", "человек", "мир", "дело", "место", "жизнь",
        "большой", "маленький", "новый", "старый", "хороший", "плохой",
        "всегда", "никогда", "часто", "сейчас", "потом",
        "сегодня", "вчера", "завтра",
        "спасибо", "пожалуйста", "привет", "пока",
    ],
    "ukr": [
        "бути", "могти", "сказати", "знати", "хотіти", "робити", "мати",
        "йти", "приходити", "давати", "брати", "бачити", "думати",
        "час", "рік", "день", "людина", "світ", "справа", "місце", "життя",
        "великий", "маленький", "новий", "старий", "хороший", "поганий",
        "завжди", "ніколи", "часто", "зараз", "потім",
        "сьогодні", "вчора", "завтра",
        "дякую", "будь ласка", "привіт", "бувай",
    ],
}

# ---------------------------------------------------------------------------
# Helper: read function_words from a YAML file
# ---------------------------------------------------------------------------
def _read_fw(path: pathlib.Path) -> set[str]:
    words: set[str] = set()
    in_fw = False
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stripped = line.rstrip()
            if stripped == "function_words:":
                in_fw = True
                continue
            if in_fw:
                if stripped and not stripped[0].isspace():
                    break
                t = stripped.strip()
                if t.startswith("- "):
                    w = t[2:].strip().lower()
                    if w:
                        words.add(w)
    return words


def _is_clean(w: str) -> bool:
    """True if the word is safe for exclusive markers (ASCII alpha, len >= 3)."""
    return len(w) >= 3 and w.isalpha() and w.isascii()


# ---------------------------------------------------------------------------
# Build exclusive + ambiguous sets from caveman YAML sources
# ---------------------------------------------------------------------------
def build_excl_data(
    fw: dict[str, set[str]],
) -> dict[str, tuple[list[str], list[str]]]:
    """Return per-language (exclusive_markers, ambiguous_words) lists."""
    result: dict[str, tuple[list[str], list[str]]] = {}
    for lang in CURATED_LANGS:
        others: set[str] = set()
        for other in CURATED_LANGS:
            if other != lang:
                others |= fw[other]
        raw_excl = fw[lang] - others
        clean_excl = sorted(w for w in raw_excl if _is_clean(w))
        amb = sorted(
            w for w in fw[lang]
            if any(w in fw[other] for other in CURATED_LANGS if other != lang)
            and w.isascii()
        )
        result[lang] = (clean_excl, amb)
    return result


# ---------------------------------------------------------------------------
# YAML serialisers
# ---------------------------------------------------------------------------
def _yaml_list(name: str, items: list[str]) -> str:
    lines = [f"{name}:"]
    for item in items:
        lines.append(f"  - {item}")
    return "\n".join(lines)


def _make_excl_yaml(iso3: str, exclusive: list[str], ambiguous: list[str]) -> str:
    parts = [
        f"iso3: {iso3}",
        "",
        _yaml_list("exclusive_markers", exclusive),
        "",
        _yaml_list("ambiguous_with", ambiguous),
        "",
    ]
    return "\n".join(parts)


def _make_generic_yaml(iso3: str, words: list[str]) -> str:
    parts = [
        f"iso3: {iso3}",
        "",
        _yaml_list("generic_words", words),
        "",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Brotli writer
# ---------------------------------------------------------------------------
def write_br(yaml_text: str, out_path: pathlib.Path) -> None:
    data = brotli.compress(yaml_text.encode("utf-8"), quality=11)
    out_path.write_bytes(data)
    print(f"  wrote {out_path.name} ({len(data)} bytes)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    if not CAVEMAN_WD.exists():
        print(f"ERROR: caveman worddata not found at {CAVEMAN_WD}", file=sys.stderr)
        sys.exit(1)

    OUTPUT_WD.mkdir(parents=True, exist_ok=True)

    # 1. Write {iso3}.fw.yaml.br — curated grammatical function words (for compression)
    print("Writing .fw.yaml.br files (curated grammatical function words)...")
    for iso3, words in CURATED_FW.items():
        yaml = _make_generic_yaml(iso3, words).replace("generic_words:", "function_words:")
        write_br(yaml, OUTPUT_WD / f"{iso3}.fw.yaml.br")

    # 2. Load function words:
    #    - CURATED_FW (precise grammatical FW) for exclusive marker computation
    #    - Full YAML for ambiguous word computation (cross-YAML overlaps)
    print("\nLoading caveman YAML sources (for ambiguous word computation)...")
    yaml_fw: dict[str, set[str]] = {}
    for lang in CURATED_LANGS:
        src = CAVEMAN_WD / f"{lang}.yaml"
        yaml_fw[lang] = _read_fw(src) if src.exists() else set()
        print(f"  {lang}: {len(yaml_fw[lang])} YAML words, {len(CURATED_FW[lang])} curated words")

    # 3. Compute exclusive markers from CURATED_FW (more precise than YAML).
    #    Ambiguous words computed from full YAML (all cross-language overlaps).
    print("\nComputing exclusive markers (from curated FW)...")
    curated_sets = {lang: set(CURATED_FW[lang]) for lang in CURATED_LANGS}
    excl_data: dict[str, tuple[list[str], list[str]]] = {}
    for lang in CURATED_LANGS:
        others_curated: set[str] = set()
        others_yaml: set[str] = set()
        for other in CURATED_LANGS:
            if other != lang:
                others_curated |= curated_sets[other]
                others_yaml |= yaml_fw[other]
        raw_excl = curated_sets[lang] - others_curated
        clean_excl = sorted(w for w in raw_excl if _is_clean(w))
        # Ambiguous: in THIS lang curated FW AND in others' full YAML
        amb = sorted(
            w for w in curated_sets[lang]
            if any(w in yaml_fw[other] for other in CURATED_LANGS if other != lang)
            and w.isascii()
        )
        excl_data[lang] = (clean_excl, amb)
        print(f"  {lang}: {len(clean_excl)} exclusive, {len(amb)} ambiguous")

    # 4. Write {iso3}.excl.yaml.br — exclusive markers for disambiguation
    print("\nWriting .excl.yaml.br files...")
    for lang, (excl, amb) in excl_data.items():
        yaml = _make_excl_yaml(lang, excl, amb)
        write_br(yaml, OUTPUT_WD / f"{lang}.excl.yaml.br")

    # 5. Write {iso3}.generic.yaml.br — generic content words for aggressive mode
    print("\nWriting .generic.yaml.br files...")
    for iso3, words in GENERIC_WORDS.items():
        yaml = _make_generic_yaml(iso3, words)
        write_br(yaml, OUTPUT_WD / f"{iso3}.generic.yaml.br")

    print("\nDone.")


if __name__ == "__main__":
    main()
