# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""SynthelionML — learned per-token keep/drop prompt compressor.

A small, fully offline transformer encoder trained on Wikipedia corpora to
predict which tokens can be dropped while preserving meaning.  The model is
trained using self-distillation: the rule-based SYNTACTIC compressor provides
ground-truth labels, and the encoder learns to generalise beyond simple rules
by attending to surrounding token context.

Architecture (5 M params, CPU-friendly):
    Char-ngram hashing → word embedding + feature embedding → positional encoding →
    2-layer transformer encoder (d=128, h=4) → linear(2) keep/drop logits.

Inference:
    Tokenise text → predict per-word keep/drop → rebuild string, always
    retaining punctuation, numbers, URLs, and sentence boundaries.

    If the model checkpoint is absent or torch is not installed, the level
    gracefully falls back to the rule-based SYNTACTIC compressor (no error
    raised).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Torch lazy import
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
# Model resolution: find checkpoint on disk (offline only)
# ---------------------------------------------------------------------------

_MODEL_DIR_NAME = "synthelionml"
_BUNDLED_ROOTS: list[Path] = []

def _additional_roots() -> list[Path]:
    """Environment / user roots (same logic as privacy_ml)."""
    roots: list[Path] = []
    env = os.environ.get("SYNTHELION_ML_MODELS_DIR")
    if env:
        roots.append(Path(env))
    user_home = Path.home() / ".synthelion" / "ml_models"
    roots.append(user_home)
    pkg_root = Path(__file__).resolve().parent / "ml_models"
    roots.append(pkg_root)
    return roots


def _looks_like_model_dir(d: Path) -> bool:
    if not d.is_dir():
        return False
    has_config = (d / "config.json").is_file()
    has_weights = any(d.glob("*.bin")) or any(d.glob("*.safetensors"))
    return has_config and has_weights


def resolve_ml_model_path(short_name: str | None = None) -> Path | None:
    """Locate a model directory containing config.json + weights.

    Resolution order (first match wins):
        1. `SYNTHELION_ML_MODEL` env var — explicit checkpoint dir
        2. `SYNTHELION_ML_MODELS_DIR/<name>` — model store root
        3. `~/.synthelion/ml_models/<name>`
        4. packaged `synthelion/ml_models/<name>`
    """
    env_path = os.environ.get("SYNTHELION_ML_MODEL")
    if env_path and _looks_like_model_dir(Path(env_path)):
        return Path(env_path)
    name = short_name or _MODEL_DIR_NAME
    for root in _additional_roots():
        candidate = root / name
        if _looks_like_model_dir(candidate):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

_PAD = "<pad>"
_UNK = "<unk>"
_SOS = "<s>"
_EOS = "<eos>"
_SPECIAL = {_PAD, _UNK, _SOS, _EOS}
# Small bucketing keeps the OOV fallback embedding light: with 8192 buckets the
# whole model stays ~3M parameters (~12 MB fp32), fine for CPU-only inference.
_CHAR_NGRAM_BUCKETS = 8_192


class SynthelionMLVocab:
    """Word vocabulary with char-n-gram fallback for OOV tokens."""

    __slots__ = ("word2id", "id2word", "vocab_size")

    def __init__(self, word2id: dict[str, int], id2word: dict[int, str]) -> None:
        self.word2id = word2id
        self.id2word = id2word
        self.vocab_size = len(word2id)

    @classmethod
    def load(cls, path: Path) -> "SynthelionMLVocab":
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
        return self.word2id.get(word, self.word2id[_UNK])

    @staticmethod
    def char_ngram_hash(word: str, nbuckets: int = _CHAR_NGRAM_BUCKETS) -> int:
        """Deterministic hash of word's character trigrams (OOV fallback).

        Uses md5 (never Python's builtin hash, which is randomized per process
        and would break the training/inference word-id mapping).
        """
        word = " " + word + " "
        if len(word) < 5:
            grams = [word]
        else:
            grams = [word[i:i + 3] for i in range(len(word) - 2)]
        combined = "|".join(grams)
        return int(hashlib.md5(combined.encode("utf-8")).hexdigest(), 16) % nbuckets


# ---------------------------------------------------------------------------
# Feature extraction (no torch dependency)
# ---------------------------------------------------------------------------

def _word_features(
    word: str,
    fw: frozenset[str],
    proper_nouns: frozenset[str] | None,
    iso3: str,
) -> list[float]:
    """Per-token feature vector (scalar features, not embeddings).

    Returns [is_stopword, is_capitalized, length_bucket_0..15].
    These are summed into the embedding at model init time (no runtime cost).
    """
    lower = word.lower()
    is_sw = 1.0 if lower in fw else 0.0
    is_cap = 1.0 if word and word[0].isupper() else 0.0
    # length bucket 0–15
    l = min(len(word), 15)
    buckets = [0.0] * 16
    buckets[l] = 1.0
    return [is_sw, is_cap] + buckets


# ---------------------------------------------------------------------------
# PyTorch model (only instantiated when torch is available)
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    import torch


def _build_model_if_torch(
    checkpoint_dir: Path,
):
    """Load SynthelionMLModel from checkpoint_dir, return (model, vocab, config)."""
    if not _ensure_torch():
        return None
    import torch

    config_path = checkpoint_dir / "config.json"
    vocab_path = checkpoint_dir / "vocab.json"

    with open(config_path, "r", encoding="utf-8") as fh:
        config = json.load(fh)

    vocab = SynthelionMLVocab.load(vocab_path)
    d_model = config.get("d_model", 128)
    n_heads = config.get("n_heads", 4)
    n_layers = config.get("n_layers", 2)
    ffn_dim = config.get("ffn_dim", 512)
    dropout = config.get("dropout", 0.1)
    n_features = config.get("n_features", 18)

    model = SynthelionMLModel(
        actual_vocab_size=vocab.vocab_size,
        d_model=d_model,
        n_heads=n_heads,
        n_layers=n_layers,
        ffn_dim=ffn_dim,
        dropout=dropout,
        n_features=n_features,
        max_seq_len=config.get("max_seq_len", 512),
    )
    # Locate weights file
    weights_path: Path | None = None
    for pat in ("model.bin", "model.safetensors", "synthelionml.bin"):
        p = checkpoint_dir / pat
        if p.exists():
            weights_path = p
            break
    if weights_path is None:
        _log.warning("SynthelionML checkpoint dir has no weights file: %s", checkpoint_dir)
        return None

    model.load_state_dict(torch.load(weights_path, map_location="cpu", weights_only=True))
    model.eval()
    return model, vocab, config


def _make_model_class():
    """Build the torch.nn.Module subclass (lazily — torch is only needed at
    model instantiation, never at module import time)."""
    import torch
    import torch.nn as nn

    class SynthelionMLModel(nn.Module):
        """Minimal transformer encoder for per-token keep/drop classification.

        Pure torch implementation — no external transformer library. With the
        default hyperparameters (vocab 10k, ngram buckets 8k, d_model=128,
        n_layers=2) the model has ~3M parameters (~12 MB fp32), keeping CPU-only
        inference fast and the shipped file light.
        """

        def __init__(
            self,
            actual_vocab_size: int,
            d_model: int = 128,
            n_heads: int = 4,
            n_layers: int = 2,
            ffn_dim: int = 512,
            dropout: float = 0.1,
            n_features: int = 18,
            max_seq_len: int = 512,
        ) -> None:
            super().__init__()
            self.d_model = d_model
            self.max_seq_len = max_seq_len
            total_vocab = actual_vocab_size + _CHAR_NGRAM_BUCKETS
            self._word_emb = nn.Embedding(total_vocab, d_model, padding_idx=0)
            self._feat_proj = nn.Linear(n_features, d_model)
            self._pos_emb = nn.Embedding(max_seq_len, d_model)
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=d_model,
                nhead=n_heads,
                dim_feedforward=ffn_dim,
                dropout=dropout,
                batch_first=True,
                activation="gelu",
            )
            self._encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
            self._head = nn.Linear(d_model, 2)
            self._dropout = nn.Dropout(dropout)

        def forward(
            self,
            word_ids,           # (B, L) int — word vocab id OR char_ngram_id + vocab_size
            features,           # (B, L, n_features) float
            attention_mask,     # (B, L) bool — True for real tokens
        ):
            """Returns logits (B, L, 2) for keep/drop classification."""
            B, L = word_ids.shape
            pos = torch.arange(L, device=word_ids.device).unsqueeze(0)
            x = self._dropout(self._word_emb(word_ids) + self._feat_proj(features) + self._pos_emb(pos))
            # TransformerEncoder expects src_key_padding_mask: True = ignore
            pad_mask = ~attention_mask
            x = self._encoder(x, src_key_padding_mask=pad_mask)
            return self._head(x)

        def predict_keep_probs(self, word_ids, features, attention_mask):
            """Returns keep probabilities (B, L) in [0,1]."""
            import torch.nn.functional as F
            with torch.no_grad():
                logits = self.forward(word_ids, features, attention_mask)
                return F.softmax(logits, dim=-1)[..., 1]  # index 1 = keep

    return SynthelionMLModel


_SynthelionMLModelClass = None


def SynthelionMLModel(*args, **kwargs):
    """Factory returning an instance of the lazily-built torch model class."""
    global _SynthelionMLModelClass
    if _SynthelionMLModelClass is None:
        _SynthelionMLModelClass = _make_model_class()
    return _SynthelionMLModelClass(*args, **kwargs)


# ---------------------------------------------------------------------------
# Compressor singleton
# ---------------------------------------------------------------------------

class SynthelionMLCompressor:
    """Lazy-loaded, thread-safe, offline learned prompt compressor.

    Model resolution order (first match wins):
        1. `SYNTHELION_ML_MODEL` env var  (explicit path to checkpoint dir)
        2. `~/.synthelion/ml_models/synthelionml/`
        3. `synthelion/ml_models/synthelionml/`  (bundled wheel)

    If no checkpoint is found, `is_available()` returns False and the
    SYNTHELION_ML compression level silently falls back to SYNTACTIC rules.
    """

    _instance: "SynthelionMLCompressor | None" = None
    _lock = threading.Lock()

    def __init__(self, model_path: Path | None = None) -> None:
        self._model_path = model_path or resolve_ml_model_path()
        self._model = None
        self._vocab: SynthelionMLVocab | None = None
        self._config: dict = {}
        self._device = None
        self._loaded = False
        self._threshold = 0.5
        self._min_compression = 0.0

        if self._model_path is not None:
            self._load()

    @classmethod
    def get_instance(cls) -> "SynthelionMLCompressor":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for tests)."""
        with cls._lock:
            cls._instance = None

    def is_available(self) -> bool:
        return self._loaded

    def _load(self) -> None:
        if not _ensure_torch() or self._model_path is None:
            return
        try:
            import torch
            result = _build_model_if_torch(self._model_path)
            if result is None:
                return
            self._device = torch.device("cpu")
            model, vocab, config = result
            self._model = model.to(self._device)
            self._vocab = vocab
            self._config = config
            self._threshold = config.get("keep_threshold", 0.5)
            self._min_compression = config.get("min_compression", 0.0)
            self._loaded = True
            _log.info("SynthelionML loaded from %s", self._model_path)
        except Exception as exc:
            _log.warning("SynthelionML load failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compress_tokens(
        self,
        tokens: list,  # list of core._Token
        fw: frozenset[str],
        lemmas: dict[str, str],
        proper_nouns: frozenset[str],
        iso3: str,
        pos_tags: dict[str, str],
        budget: int | None = None,
        min_compression: float | None = None,
    ) -> list[str]:
        """Classify each word token as keep/drop and return surviving strings.

        Same contract as the rule-based filters in core.py: punctuation tokens are
        dropped, protected tokens / numbers / URLs are always kept, and the model
        decides on plain content words.

        ``budget`` caps the number of surviving word tokens.  ``min_compression``
        (0.0–1.0) guarantees a minimum compression ratio — the lowest-scoring
        words are dropped by rank until the target ratio is reached, always
        respecting the always-keep set.  Both are honoured independently; when
        neither is set the static ``self._threshold`` controls the cutoff.
        """
        if not self._loaded or self._model is None:
            return [t.text for t in tokens if not t.is_punct]

        from synthelion.core import _is_negation

        # ---- Always-keep classification ----
        keep_set: set[int] = set()
        word_indices: list[int] = []   # token indices the model must score
        word_strings: list[str] = []
        n_words = 0  # total non-punct tokens

        for i, tok in enumerate(tokens):
            if tok.is_punct:
                continue
            n_words += 1
            if tok.protected or _is_number(tok.text) or _looks_like_url_or_email(tok.text):
                keep_set.add(i)
                continue
            if _is_proper(tok.text, proper_nouns):
                keep_set.add(i)
                continue
            if _is_negation(tok.text, iso3):
                keep_set.add(i)
                continue
            word_indices.append(i)
            word_strings.append(tok.text)

        # ---- Model scoring ----
        if word_strings:
            scores = self._score_words(word_strings, fw, iso3)
            mc = min_compression if min_compression is not None else (self._min_compression or None)

            # Priority 1: explicit budget (absolute cap)
            if scores and budget is not None and budget > 0:
                reserved = len(keep_set)
                room = max(0, budget - reserved)
                if room > 0:
                    order = sorted(range(len(scores)), key=lambda j: scores[j], reverse=True)
                    threshold = scores[order[min(room, len(order)) - 1]]
                else:
                    threshold = float("inf")
                for j, orig_idx in enumerate(word_indices):
                    if scores[j] >= threshold:
                        keep_set.add(orig_idx)

            # Priority 2: min_compression ratio (rank-based drop by keep-probability)
            elif scores and mc is not None and mc > 0:
                target_keep = max(1, math.ceil((1.0 - mc) * n_words))
                reserved = len(keep_set)
                room = max(0, target_keep - reserved)
                if room > 0:
                    order = sorted(range(len(scores)), key=lambda j: scores[j], reverse=True)
                    for j in order[:room]:
                        keep_set.add(word_indices[j])

            # Fallback: static threshold
            else:
                for j, orig_idx in enumerate(word_indices):
                    if scores[j] >= self._threshold:
                        keep_set.add(orig_idx)

        # Safety floor: keep at least one word per sentence
        _apply_sentence_floor(tokens, keep_set)

        return [tok.text for i, tok in enumerate(tokens) if i in keep_set]

    def compress(
        self,
        text: str,
        iso3: str | None = None,
        budget: int | None = None,
        min_compression: float | None = None,
    ) -> str:
        """High-level compress: raw text → compressed text (no internal token types)."""
        from synthelion.core import _join_filtered, _tokenize
        from synthelion.detector import LanguageDetector
        from synthelion.word_provider import FunctionWordProvider

        if not self._loaded:
            return text

        lang = iso3 or LanguageDetector(FunctionWordProvider()).detect(text)
        provider = FunctionWordProvider()
        fw = provider.get_function_words(lang)
        lemmas = provider.get_lemma_map(lang)
        proper = provider.get_proper_nouns(lang)
        pos_tags = provider.get_pos_tags(lang)

        mc = min_compression if min_compression is not None else self._min_compression
        filtered = self.compress_tokens(_tokenize(text), fw, lemmas, proper, lang, pos_tags,
                                        budget=budget, min_compression=mc or None)
        return _join_filtered(filtered)

    # ------------------------------------------------------------------
    # Model inference
    # ------------------------------------------------------------------

    def _score_words(self, words: list[str], fw: frozenset[str], iso3: str) -> list[float]:
        """Return keep probability per word (0.0 when unavailable)."""
        if not self._loaded or self._model is None or self._vocab is None:
            return [0.0] * len(words)
        import torch

        max_seq = self._config.get("max_seq_len", 512)
        scores: list[float] = []
        for start in range(0, len(words), max_seq):
            chunk = words[start:start + max_seq]
            wid_list: list[int] = []
            feat_list: list[list[float]] = []
            for w in chunk:
                wid = self._vocab.encode_word(w)
                if wid == self._vocab.word2id.get(_UNK, 1):
                    wid = SynthelionMLVocab.char_ngram_hash(w) + self._vocab.vocab_size
                wid_list.append(wid)
                feat_list.append(_word_features(w, fw, None, iso3))

            L = len(chunk)
            wids = torch.tensor([wid_list], dtype=torch.long, device=self._device)
            feats = torch.tensor([feat_list], dtype=torch.float, device=self._device)
            mask = torch.ones((1, L), dtype=torch.bool, device=self._device)
            probs = self._model.predict_keep_probs(wids, feats, mask).squeeze(0)
            scores.extend(float(p) for p in probs.tolist())
        return scores


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_number(text: str) -> bool:
    stripped = text.replace(",", "").replace(".", "").replace("-", "").replace("+", "")
    return stripped.isdigit()


def _looks_like_url_or_email(text: str) -> bool:
    t = text.lower()
    return "@" in t or t.startswith("http") or t.startswith("www.") or t.endswith((".com", ".it", ".org", ".net", ".io"))


def _is_proper(word: str, proper_nouns: frozenset[str]) -> bool:
    if word and word[0].isupper() and not word.isupper():
        return True
    return word.lower() in proper_nouns if proper_nouns else False


def _apply_sentence_floor(tokens: list, keep_set: set[int]) -> None:
    """Ensure at least one word per sentence is kept."""
    # Find sentence boundaries (punctuation: . ! ? ; or start/end of tokens)
    sentence_start = 0
    for i, tok in enumerate(tokens):
        if i == 0:
            continue
        if tok.is_punct and tok.text in {".", "!", "?", ";", ":", "\n"}:
            # sentence ending at i-1
            _ensure_one_keep(tokens, keep_set, sentence_start, i)
            sentence_start = i + 1
    _ensure_one_keep(tokens, keep_set, sentence_start, len(tokens))


def _ensure_one_keep(tokens: list, keep_set: set[int], start: int, end: int) -> None:
    """If no token in [start, end) is kept, keep the first content word."""
    for i in range(start, end):
        if i in keep_set:
            return
    # find first non-punct word
    for i in range(start, end):
        if not tokens[i].is_punct:
            keep_set.add(i)
            return
