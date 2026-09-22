# Synthelion — Python port of Caveman.PrivacyGuard (https://github.com/francescopaolopassaro/Caveman.PrivacyGuard)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""PrivacyGuardML — Synthelion's own PII-confirmation model. The sole ML
backend for PrivacyGuard's `privacy.use_ml` tier; no third-party model is
used or supported.

Same self-distillation philosophy as SynthelionML (`synthelionml.py`), same
tiny transformer encoder, same char-n-gram OOV fallback and offline-only model
resolution — but a per-token BIO tagging head over every PrivacyGuard category
instead of a binary keep/drop head, trained on synthetic examples built from
Synthelion's own checksum validators (`privacy_validators.py`) and rule
patterns (`privacy_rules.yaml`) inserted into real multilingual sentences
(`devtools/train_privacyguardml.py`, `devtools/privacyguardml_data.py`).

**What this model is for, precisely.** PrivacyAnalyzer's core tier is regex +
algorithmic checksum (or context keyword, for the rules with no checksum),
zero-ML, and stays the default. This model is only the *opt-in confirmation
signal* (`privacy.use_ml = true`): a value that matches a `requires_context`
rule but has no context keyword nearby can be confirmed by an overlapping
prediction from this model. A failed checksum still vetoes detection
regardless of what this model says — it can only recover recall the strict
context gate intentionally trades away, never introduce a false positive
PrivacyAnalyzer's own validator would reject.

Runtime contract: `PrivacyGuardMLDetector.detect(text) -> list[MLSpan]`.
`get_ml_detector()` in `privacy_ml.py` resolves the bundled checkpoint and
always returns this detector — there is nothing else to dispatch to.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Torch lazy import — identical pattern to synthelionml.py, so a machine with
# no torch installed still imports this module and everything else that
# depends on it; only actually building/loading the model needs torch.
# ---------------------------------------------------------------------------

_torch_available: bool | None = None


def _ensure_torch() -> bool:
    global _torch_available
    if _torch_available is not None:
        return _torch_available
    try:
        import torch  # noqa: F401
        _torch_available = True
    except ImportError:
        _torch_available = False
    return _torch_available


# ---------------------------------------------------------------------------
# Tag space
# ---------------------------------------------------------------------------

CATEGORIES: tuple[str, ...] = (
    "PHONE", "EMAIL", "CREDITCARD", "IBAN",
    "NATIONALID", "TAXID", "SSN", "GPS",
    # Non-checksum PrivacyGuard categories — every rule in privacy_rules.yaml
    # now has an ML confirmation path, not only the checksum-validated subset.
    "VEHICLEPLATE", "BADGEID", "BUSINESSID", "SECRET", "SOCIALHANDLE",
    "LEGALCASE", "PNRCODE", "MINORDATA",
)

# The label strings PrivacyAnalyzer's _ML_LABEL_CATEGORIES table expects.
ML_LABEL_OF: dict[str, str] = {
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


def build_tag_vocab() -> tuple[list[str], dict[str, int]]:
    tags = ["O"]
    for cat in CATEGORIES:
        tags += [f"B-{cat}", f"I-{cat}"]
    return tags, {t: i for i, t in enumerate(tags)}


TAGS, TAG2ID = build_tag_vocab()


# ---------------------------------------------------------------------------
# Model resolution — offline only, same three-root order as SynthelionML:
# SYNTHELION_ML_MODELS_DIR env, ~/.synthelion/ml_models, packaged
# synthelion/ml_models/.
# ---------------------------------------------------------------------------

_MODEL_DIR_NAME = "privacyguardml"


def resolve_model_path(env_dir: str | None = None) -> Path | None:
    from synthelion.privacy_ml import models_root_candidates

    def _looks_like(d: Path) -> bool:
        return (d / "config.json").is_file() and any(
            (d / w).is_file() for w in ("model.bin", "model.safetensors")
        )

    for root in models_root_candidates(env_dir):
        candidate = root / _MODEL_DIR_NAME
        if _looks_like(candidate):
            return candidate

    from synthelion._asset_download import PRIVACYGUARDML_REPO_ID, fetch_once
    downloaded = fetch_once(
        PRIVACYGUARDML_REPO_ID, "model",
        Path.home() / ".synthelion" / "ml_models" / _MODEL_DIR_NAME,
        "PrivacyGuardML checkpoint",
    )
    if downloaded is not None and _looks_like(downloaded):
        return downloaded
    return None


# ---------------------------------------------------------------------------
# Vocabulary — same char-n-gram-hash-for-OOV scheme as SynthelionML, kept as a
# separate class (not imported from synthelionml.py) so this module has no
# dependency on the compression model ever being present.
# ---------------------------------------------------------------------------

_PAD = "<pad>"
_UNK = "<unk>"
_CHAR_NGRAM_BUCKETS = 8_192


class PrivacyGuardMLVocab:
    __slots__ = ("word2id", "id2word", "vocab_size")

    def __init__(self, word2id: dict[str, int], id2word: dict[int, str]) -> None:
        self.word2id = word2id
        self.id2word = id2word
        self.vocab_size = len(word2id)

    @classmethod
    def load(cls, path: Path) -> "PrivacyGuardMLVocab":
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        word2id = {w: i for i, w in enumerate(data["words"])}
        id2word = {i: w for w, i in word2id.items()}
        return cls(word2id, id2word)

    def save(self, path: Path) -> None:
        words = [self.id2word[i] for i in range(self.vocab_size)]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"words": words}, fh)

    def encode_word(self, word: str) -> int:
        wid = self.word2id.get(word)
        if wid is not None:
            return wid
        return self.char_ngram_hash(word) + self.vocab_size

    @staticmethod
    def char_ngram_hash(word: str, nbuckets: int = _CHAR_NGRAM_BUCKETS) -> int:
        """md5, never Python's randomized `hash` — must agree between the
        training run that built the vocab and every later inference process."""
        word = " " + word + " "
        grams = [word] if len(word) < 5 else [word[i:i + 3] for i in range(len(word) - 2)]
        combined = "|".join(grams)
        return int(hashlib.md5(combined.encode("utf-8")).hexdigest(), 16) % nbuckets


def word_features(word: str) -> list[float]:
    """[has_digit, has_at, has_plus, has_dash_or_dot, is_upper, length_bucket_0..15].

    Shape-oriented on purpose — this model's whole job is recognising PII by
    *shape*, unlike SynthelionML's linguistic (stopword/lemma) features. No
    per-language word lists needed, so the same feature function serves every
    language the training corpus covers.
    """
    has_digit = 1.0 if any(c.isdigit() for c in word) else 0.0
    has_at = 1.0 if "@" in word else 0.0
    has_plus = 1.0 if word.startswith("+") else 0.0
    has_sep = 1.0 if any(c in "-./" for c in word) else 0.0
    is_upper = 1.0 if word.isupper() and len(word) > 1 else 0.0
    length_bucket = [0.0] * 16
    length_bucket[min(len(word), 15)] = 1.0
    return [has_digit, has_at, has_plus, has_sep, is_upper] + length_bucket


N_FEATURES = 21  # 5 scalar + 16 length-bucket


# ---------------------------------------------------------------------------
# PyTorch model — lazily built, same reasoning as SynthelionML: torch is only
# imported when a model instance is actually constructed.
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    import torch


def _make_model_class():
    import torch
    import torch.nn as nn

    class PrivacyGuardMLModel(nn.Module):
        """Per-token BIO tagging over `len(TAGS)` classes.

        Same encoder shape as SynthelionML (d=128, 2 layers, 4 heads) — the
        task is simpler (shape recognition, not linguistic judgement), so
        there was no reason to reach for a bigger model.
        """

        def __init__(
            self,
            actual_vocab_size: int,
            d_model: int = 128,
            n_heads: int = 4,
            n_layers: int = 2,
            ffn_dim: int = 512,
            dropout: float = 0.1,
            n_features: int = N_FEATURES,
            n_tags: int = len(TAGS),
            max_seq_len: int = 96,
        ) -> None:
            super().__init__()
            self.d_model = d_model
            self.max_seq_len = max_seq_len
            total_vocab = actual_vocab_size + _CHAR_NGRAM_BUCKETS
            self._word_emb = nn.Embedding(total_vocab, d_model, padding_idx=0)
            self._feat_proj = nn.Linear(n_features, d_model)
            self._pos_emb = nn.Embedding(max_seq_len, d_model)
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=d_model, nhead=n_heads, dim_feedforward=ffn_dim,
                dropout=dropout, batch_first=True, activation="gelu",
            )
            self._encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
            self._head = nn.Linear(d_model, n_tags)
            self._dropout = nn.Dropout(dropout)

        def forward(self, word_ids, features, attention_mask):
            B, L = word_ids.shape
            pos = torch.arange(L, device=word_ids.device).unsqueeze(0)
            x = self._dropout(self._word_emb(word_ids) + self._feat_proj(features) + self._pos_emb(pos))
            pad_mask = ~attention_mask
            x = self._encoder(x, src_key_padding_mask=pad_mask)
            return self._head(x)

        def predict_tag_probs(self, word_ids, features, attention_mask):
            import torch.nn.functional as F
            with torch.no_grad():
                return F.softmax(self.forward(word_ids, features, attention_mask), dim=-1)

    return PrivacyGuardMLModel


_ModelClass = None


def PrivacyGuardMLModel(*args, **kwargs):
    global _ModelClass
    if _ModelClass is None:
        _ModelClass = _make_model_class()
    return _ModelClass(*args, **kwargs)


def _build_model_if_torch(checkpoint_dir: Path):
    if not _ensure_torch():
        return None
    import torch

    with open(checkpoint_dir / "config.json", "r", encoding="utf-8") as fh:
        config = json.load(fh)
    vocab = PrivacyGuardMLVocab.load(checkpoint_dir / "vocab.json")

    model = PrivacyGuardMLModel(
        actual_vocab_size=vocab.vocab_size,
        d_model=config.get("d_model", 128),
        n_heads=config.get("n_heads", 4),
        n_layers=config.get("n_layers", 2),
        ffn_dim=config.get("ffn_dim", 512),
        dropout=config.get("dropout", 0.1),
        n_features=config.get("n_features", N_FEATURES),
        n_tags=config.get("n_tags", len(TAGS)),
        max_seq_len=config.get("max_seq_len", 96),
    )
    weights_path = None
    for pat in ("model.bin", "model.safetensors"):
        p = checkpoint_dir / pat
        if p.exists():
            weights_path = p
            break
    if weights_path is None:
        _log.warning("PrivacyGuardML checkpoint dir has no weights file: %s", checkpoint_dir)
        return None
    model.load_state_dict(torch.load(weights_path, map_location="cpu", weights_only=True))
    model.eval()
    return model, vocab, config


# ---------------------------------------------------------------------------
# Inference wrapper — `.detect(text) -> list[MLSpan]`.
# ---------------------------------------------------------------------------

class PrivacyGuardMLDetector:
    """Lazy, thread-safe, offline BIO-tagging PII detector.

    Loaded once from disk (never downloaded), reused across calls; one lock
    serialises inference since a single torch model instance isn't safe under
    concurrent forward passes.
    """

    def __init__(self, model_path: "Path | None" = None, min_confidence: float = 0.6) -> None:
        self._model_path = model_path if model_path is not None else resolve_model_path()
        self._min_confidence = min_confidence
        self._model = None
        self._vocab: "PrivacyGuardMLVocab | None" = None
        self._config: dict = {}
        self._loaded = False
        self._init_lock = threading.Lock()
        self._infer_lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return _MODEL_DIR_NAME

    def is_available(self) -> bool:
        self._ensure_model()
        return self._loaded

    def _ensure_model(self):
        if self._model is not None or (self._loaded is False and self._model_path is None):
            return self._model
        with self._init_lock:
            if self._model is not None:
                return self._model
            if self._model_path is None:
                _log.warning(
                    "privacy.use_ml is enabled but no local PrivacyGuardML model is installed — "
                    "run `python devtools/train_privacyguardml.py` once, or point "
                    "SYNTHELION_ML_MODELS_DIR at a directory containing one. Falling back to "
                    "regex-only analysis."
                )
                return None
            try:
                result = _build_model_if_torch(self._model_path)
            except Exception as exc:  # noqa: BLE001
                _log.warning("PrivacyGuardML load failed (%s); falling back to regex-only analysis", exc)
                return None
            if result is None:
                return None
            self._model, self._vocab, self._config = result
            self._loaded = True
            _log.info("PrivacyGuardML loaded from %s", self._model_path)
            return self._model

    def detect(self, text: str) -> list:
        from synthelion.privacy_ml import MLSpan
        from synthelion.core import _tokenize

        model = self._ensure_model()
        if model is None or not text.strip():
            return []

        tokens = _tokenize(text)
        word_tokens = [t for t in tokens if not t.is_punct]
        if not word_tokens:
            return []

        import torch

        max_seq = self._config.get("max_seq_len", 96)
        word_ids: list[int] = []
        feats: list[list[float]] = []
        for tok in word_tokens[:max_seq]:
            word_ids.append(self._vocab.encode_word(tok.text))
            feats.append(word_features(tok.text))
        length = len(word_ids)
        pad = max_seq - length
        word_ids += [0] * pad
        feats += [[0.0] * N_FEATURES] * pad

        ids_t = torch.tensor([word_ids], dtype=torch.long)
        feats_t = torch.tensor([feats], dtype=torch.float)
        mask_t = torch.zeros((1, max_seq), dtype=torch.bool)
        mask_t[0, :length] = True

        try:
            with self._infer_lock:
                probs = model.predict_tag_probs(ids_t, feats_t, mask_t)[0]
        except Exception as exc:  # noqa: BLE001
            _log.warning("PrivacyGuardML inference failed (%s); falling back to regex-only", exc)
            return []

        confidences, tag_ids = probs.max(dim=-1)
        tag_names = [TAGS[int(t)] for t in tag_ids[:length]]
        confs = [float(c) for c in confidences[:length]]

        spans_char = self._locate_spans(text, [t.text for t in word_tokens[:length]])

        results = []
        i = 0
        while i < length:
            tag = tag_names[i]
            if not tag.startswith("B-"):
                i += 1
                continue
            category = tag[2:]
            j = i + 1
            while j < length and tag_names[j] == f"I-{category}":
                j += 1
            span_confidences = confs[i:j]
            span_char_starts = [s for s in spans_char[i:j] if s is not None]
            if not span_char_starts:
                i = j
                continue
            start = min(s for s, _ in span_char_starts)
            end = max(e for _, e in span_char_starts)
            if start < end <= len(text):
                results.append(MLSpan(
                    start, end, text[start:end], ML_LABEL_OF.get(category, category.lower()),
                    sum(span_confidences) / len(span_confidences),
                ))
            i = j

        return [s for s in results if s.confidence >= self._min_confidence]

    @staticmethod
    def _locate_spans(text: str, words: list[str]) -> list[tuple[int, int] | None]:
        spans: list[tuple[int, int] | None] = []
        cursor = 0
        for w in words:
            idx = text.find(w, cursor)
            if idx == -1:
                idx = text.find(w)
            if idx == -1:
                spans.append(None)
                continue
            spans.append((idx, idx + len(w)))
            cursor = idx + len(w)
        return spans
