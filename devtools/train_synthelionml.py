# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Train the SynthelionML multilingual prompt-compressor model.

The model is fully ours: architecture, weights, and training data.  It is
trained on our own Wikipedia corpora (`devtools/wikipedia_corpus/<lang>/
corpus.txt`) using self-distillation — a token's ground-truth keep/drop label
comes from Synthelion's own rule-based SYNTACTIC compressor, and the encoder
learns to generalise those decisions using surrounding context.

Output is written to `synthelion/ml_models/synthelionml/` (config.json,
vocab.json, model.bin), which is what the SYNTHELION_ML compression level loads
at runtime — fully offline, no downloads.

Usage (from repo root):
    python devtools/train_synthelionml.py --corpora-dir devtools/wikipedia_corpus
    python devtools/train_synthelionml.py --langs en,it,de,fr,es --max-examples-per-lang 3000
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from collections import Counter
from pathlib import Path

_log = logging.getLogger("synthelion.train_synthelionml")

# Model hyperparameters — must match synthelion.synthelionml
_D_MODEL = 128
_N_HEADS = 4
_N_LAYERS = 2
_FFN_DIM = 512
_DROPOUT = 0.1
_MAX_SEQ = 96          # training window length
_VOCAB_SIZE = 10000    # light for CPU-only inference (~12 MB checkpoint)
_KEEP_THRESHOLD = 0.6  # inference threshold stored in config

# Default training scope: kept deliberately small so the checkpoint file stays
# light for CPU-only inference.  Extend for more languages by passing --langs.
_DEFAULT_LANGS = ["en", "it", "de", "fr", "es"]


def _reservoir_sample(path: Path, max_examples: int, rng: random.Random, max_bytes: int) -> list[str]:
    """Deterministic reservoir sample of lines from a possibly huge corpus file.

    Reads at most `max_bytes` of the file (so a 465 MB English dump doesn't stall
    the trainer), keeps the first `max_examples` lines that qualify (5–80
    non-punct words), then probabilistically replaces them.
    """
    from synthelion.core import _tokenize

    sample: list[str] = []
    seen = 0
    read = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            read += len(line.encode("utf-8", errors="replace"))
            if read > max_bytes:
                break
            text = line.strip()
            if len(text) < 30:
                continue
            tokens = _tokenize(text)
            n_words = sum(1 for t in tokens if not t.is_punct)
            if not (5 <= n_words <= 80):
                continue
            seen += 1
            if len(sample) < max_examples:
                sample.append(text)
            else:
                j = rng.randint(0, seen - 1)
                if j < max_examples:
                    sample[j] = text
    return sample


def _build_examples(
    texts: list[str],
    iso3: str,
    provider,
    generic_fallback,
) -> list[tuple[list[str], list[int], list[list[float]]]]:
    """Turn lines into (words, keep_labels, features) using the SYNTACTIC keep-mask.

    The label is 1 when the token survives the rule-based SYNTACTIC compressor —
    our own ground truth. Only word tokens are modelled (punctuation is dropped
    by every compression level and is never part of the learned decision).
    Features are computed per language so training and inference see the same
    stopword signal (no train/serve skew).
    """
    from synthelion.core import _syntactic_keep_mask, _tokenize
    from synthelion.synthelionml import _word_features

    fw = provider.get_function_words(iso3)
    lemmas = provider.get_lemma_map(iso3)
    proper = provider.get_proper_nouns(iso3)
    pos_tags = provider.get_pos_tags(iso3)
    generic = provider.get_generic_words(iso3) or generic_fallback

    examples: list[tuple[list[str], list[int], list[list[float]]]] = []
    for text in texts:
        tokens = _tokenize(text)
        if not any(not t.is_punct for t in tokens):
            continue
        keep, _ = _syntactic_keep_mask(tokens, fw, lemmas, proper, iso3, generic, pos_tags)
        words: list[str] = []
        labels: list[int] = []
        feats: list[list[float]] = []
        for i, tok in enumerate(tokens):
            if tok.is_punct:
                continue
            words.append(tok.text)
            labels.append(1 if keep[i] else 0)
            feats.append(_word_features(tok.text, fw, proper, iso3))
        if not words:
            continue
        words = words[: _MAX_SEQ]
        labels = labels[: _MAX_SEQ]
        feats = feats[: _MAX_SEQ]
        examples.append((words, labels, feats))
    return examples


def _build_vocab(examples, vocab_size: int) -> dict[str, int]:
    from synthelion.synthelionml import _PAD, _UNK

    counts: Counter = Counter()
    for words, _labels, _feats in examples:
        counts.update(words)
    top = [w for w, _ in counts.most_common(vocab_size - 2)]
    word2id = {_PAD: 0, _UNK: 1}
    for w in top:
        word2id[w] = len(word2id)
    return word2id


def _encode_examples(
    examples,
    word2id: dict[str, int],
) -> tuple[list[list[int]], list[list[list[float]]], list[list[int]]]:
    """Encode words → (word_ids_or_ngram, features, labels), padded to _MAX_SEQ."""
    from synthelion.synthelionml import SynthelionMLVocab, _UNK

    unk_id = word2id[_UNK]
    vocab_size = len(word2id)
    word_ids: list[list[int]] = []
    feats: list[list[list[float]]] = []
    labels: list[list[int]] = []

    for words, label, feat in examples:
        wids: list[int] = []
        for w in words:
            wid = word2id.get(w)
            if wid is None or wid == unk_id:
                wid = SynthelionMLVocab.char_ngram_hash(w) + vocab_size
            wids.append(wid)
        pad = _MAX_SEQ - len(words)
        wids += [0] * pad
        feat = feat + [[0.0] * 18] * pad
        labels.append(label + [-100] * pad)
        word_ids.append(wids)
        feats.append(feat)
    return word_ids, feats, labels


def train(
    corpora_dir: Path,
    langs: list[str],
    max_examples_per_lang: int,
    vocab_size: int,
    epochs: int,
    batch_size: int,
    lr: float,
    eval_split: float,
    output_dir: Path,
    seed: int,
    max_bytes_per_lang: int,
) -> None:
    import numpy as np
    import torch
    import torch.nn as nn

    from synthelion.synthelionml import SynthelionMLModel, _word_features
    from synthelion.word_provider import FunctionWordProvider

    torch.manual_seed(seed)
    np.random.seed(seed)
    rng = random.Random(seed)

    provider = FunctionWordProvider()
    generic_fallback = frozenset()
    # Build the iso1 (2-letter) → iso3 (3-letter) map from the bundled word data
    # so we can pass correct language codes to the SYNTACTIC label generator.
    iso1_to_iso3 = {v[0]: k for k, v in provider._load_index().items()}

    all_examples: list[tuple[list[str], list[int], list[list[float]]]] = []
    lang_use: dict[str, int] = {}
    _log.info("Sampling %d examples/language from %d languages", max_examples_per_lang, len(langs))
    for lang in langs:
        iso3 = iso1_to_iso3.get(lang, lang)
        corpus_file = corpora_dir / lang / "corpus.txt"
        if not corpus_file.is_file():
            _log.warning("  skip %s: no corpus.txt", lang)
            continue
        texts = _reservoir_sample(corpus_file, max_examples_per_lang, rng, max_bytes_per_lang)
        if not texts:
            _log.warning("  skip %s: empty sample", lang)
            continue
        ex = _build_examples(texts, iso3, provider, generic_fallback)
        all_examples.extend(ex)
        lang_use[lang] = len(ex)
        _log.info("  %-3s (iso3=%s) sampled=%d kept=%d", lang, iso3, len(texts), len(ex))

    if len(all_examples) < 100:
        _log.error("Not enough training examples (%d). Aborting.", len(all_examples))
        sys.exit(2)

    total_words = sum(len(w) for w, _l, _f in all_examples)
    _log.info("Total examples=%d total word tokens=%d", len(all_examples), total_words)

    # Language split seed for reproducible train/eval split
    rng.shuffle(all_examples)
    n_eval = int(len(all_examples) * eval_split)
    eval_examples = all_examples[:n_eval]
    train_examples = all_examples[n_eval:]
    _log.info("train=%d eval=%d", len(train_examples), len(eval_examples))

    # Vocabulary from ALL examples (eval too) — fixed before training
    word2id = _build_vocab(all_examples, vocab_size)
    vocab_words = ["<pad>", "<unk>"] + [w for w in word2id if w not in ("<pad>", "<unk>")]
    _log.info("Vocabulary size=%d (of %d unique words)", len(word2id), len(set(w for ex, _l, _f in all_examples for w in ex)))

    # Features were computed per-language inside _build_examples — no re-derivation.
    train_word_ids, train_feats, train_labels = _encode_examples(train_examples, word2id)

    # Encode eval
    eval_word_ids, eval_feats, eval_labels = _encode_examples(eval_examples, word2id)

    # ------------------------------------------------------------------
    # Model
    # ------------------------------------------------------------------
    model = SynthelionMLModel(
        actual_vocab_size=len(word2id),
        d_model=_D_MODEL,
        n_heads=_N_HEADS,
        n_layers=_N_LAYERS,
        ffn_dim=_FFN_DIM,
        dropout=_DROPOUT,
        n_features=18,
        max_seq_len=_MAX_SEQ,
    )
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)

    # Class imbalance: drop is rarer than keep during rule-label distillation.
    keep_count = sum(l.count(1) for l in train_labels)
    drop_count = sum(l.count(0) for l in train_labels)
    _log.info("label distribution: keep=%d drop=%d (ratio=%.3f)", keep_count, drop_count, keep_count / max(1, drop_count))
    # Class weights: [drop, keep] inversely proportional.
    w_keep = keep_count / max(1, drop_count + keep_count)
    w_drop = 1.0 - w_keep
    class_weights = torch.tensor([w_drop, w_keep], dtype=torch.float)

    dev = torch.device("cpu")
    model = model.to(dev)

    def to_tensors(n_ids, n_feats, n_labels, device):
        return (
            torch.tensor(n_ids, dtype=torch.long, device=device),
            torch.tensor(n_feats, dtype=torch.float, device=device),
            torch.tensor(n_labels, dtype=torch.long, device=device),
        )

    train_ids_t, train_feats_t, train_labels_t = to_tensors(train_word_ids, train_feats, train_labels, dev)
    eval_ids_t, eval_feats_t, eval_labels_t = to_tensors(eval_word_ids, eval_feats, eval_labels, dev)

    n_train = train_ids_t.shape[0]
    _log.info("Starting training: %d steps/epoch (batch=%d)", (n_train + batch_size - 1) // batch_size, batch_size)

    def run_epoch(ids_t, feats_t, labels_t, indices, training: bool) -> float:
        running = 0.0
        correct = 0
        total = 0
        n = len(indices)
        for start in range(0, n, batch_size):
            idx = indices[start: start + batch_size]
            x = ids_t[idx]
            f = feats_t[idx]
            y = labels_t[idx]
            B, L = x.shape
            attn = torch.ones((B, L), dtype=torch.bool, device=dev)
            if training:
                model.train()
                opt.zero_grad()
                logits = model(x, f, attn)
                loss = nn.functional.cross_entropy(logits.reshape(-1, 2), y.reshape(-1), weight=class_weights, ignore_index=-100)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
            else:
                model.eval()
                with torch.no_grad():
                    logits = model(x, f, attn)
                    loss = nn.functional.cross_entropy(logits.reshape(-1, 2), y.reshape(-1), weight=class_weights, ignore_index=-100)
            pred = logits.reshape(-1, 2).argmax(-1)
            m = y.reshape(-1) != -100
            correct += int((pred[m] == y.reshape(-1)[m]).sum())
            total += int(m.sum())
            running += float(loss.item()) * B
        return running / n, correct / max(1, total)

    indices = list(range(n_train))
    for epoch in range(1, epochs + 1):
        rng.shuffle(indices)
        t0 = time.time()
        tr_loss, tr_acc = run_epoch(train_ids_t, train_feats_t, train_labels_t, indices, training=True)
        ev_loss, ev_acc = run_epoch(eval_ids_t, eval_feats_t, eval_labels_t, list(range(eval_ids_t.shape[0])), training=False)
        _log.info(
            "epoch %d/%d  train_loss=%.4f train_acc=%.4f  eval_loss=%.4f eval_acc=%.4f  (%.1fs)",
            epoch, epochs, tr_loss, tr_acc, ev_loss, ev_acc, time.time() - t0,
        )

    # ------------------------------------------------------------------
    # Save checkpoint (our model file)
    # ------------------------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "model_name": "SynthelionML",
        "d_model": _D_MODEL,
        "n_heads": _N_HEADS,
        "n_layers": _N_LAYERS,
        "ffn_dim": _FFN_DIM,
        "dropout": _DROPOUT,
        "n_features": 18,
        "max_seq_len": _MAX_SEQ,
        "vocab_size": len(word2id),
        "keep_threshold": _KEEP_THRESHOLD,
        "trained_languages": sorted(lang_use.keys()),
        "languages_used": len(lang_use),
        "training_examples": len(train_examples),
        "eval_examples": len(eval_examples),
        "vocab_words": vocab_words,
    }
    with open(output_dir / "config.json", "w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)
    with open(output_dir / "vocab.json", "w", encoding="utf-8") as fh:
        json.dump({"words": vocab_words}, fh, ensure_ascii=False)
    torch.save(model.state_dict(), output_dir / "model.bin")

    with open(output_dir / "MODEL_INFO.txt", "w", encoding="utf-8") as fh:
        fh.write(
            "SynthelionML model file\n"
            "======================\n"
            "This model is generated by Synthelion's own training pipeline:\n"
            "  devtools/train_synthelionml.py\n\n"
            "Training data: Synthelion's Wikipedia corpora "
            f"({len(lang_use)} languages).\n"
            "Ground-truth labels: Synthelion's rule-based SYNTACTIC compressor\n"
            "  (self-distillation). Architecture is own transformer encoder.\n"
            "Runtime: fully offline, CPU-only.\n"
        )
    _log.info("Checkpoint saved to %s (model.bin, config.json, vocab.json)", output_dir)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train the SynthelionML multilingual compressor")
    ap.add_argument("--corpora-dir", type=Path, default=Path("devtools/wikipedia_corpus"))
    ap.add_argument("--langs", default=None, help="Comma-separated ISO 639-1 codes; default: en,it,de,fr,es")
    ap.add_argument("--max-examples-per-lang", type=int, default=1200)
    ap.add_argument("--max-bytes-per-lang", type=int, default=40_000_000,
                    help="Stop reading each corpus file after this many bytes")
    ap.add_argument("--vocab-size", type=int, default=_VOCAB_SIZE)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--eval-split", type=float, default=0.05)
    ap.add_argument("--output-dir", type=Path, default=Path("synthelion/ml_models/synthelionml"))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.langs:
        langs = args.langs.split(",")
    else:
        langs = _DEFAULT_LANGS
    missing = [l for l in langs if not (args.corpora_dir / l / "corpus.txt").is_file()]
    if missing:
        _log.error("Missing corpus files for language(s): %s", ", ".join(missing))
        return 1

    train(
        args.corpora_dir,
        langs,
        args.max_examples_per_lang,
        args.vocab_size,
        args.epochs,
        args.batch_size,
        args.lr,
        args.eval_split,
        args.output_dir,
        args.seed,
        args.max_bytes_per_lang,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())