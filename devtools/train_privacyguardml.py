# Synthelion — Python port of Caveman.PrivacyGuard (https://github.com/francescopaolopassaro/Caveman.PrivacyGuard)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Train PrivacyGuardML — Synthelion's own PII-confirmation model, replacing
the external `urchade/gliner_small-v2.1` dependency.

Same self-distillation philosophy as `train_synthelionml.py`, but the ground
truth here isn't a compressor's keep/drop decision — it's Synthelion's own
checksum validators (`synthelion/privacy_validators.py`) and rule patterns
(`synthelion/privacy_rules.yaml`), used to *generate* synthetic PII values that
are inserted into real multilingual sentences drawn from the same Wikipedia
corpora SynthelionML trains on (`devtools/wikipedia_corpus/<lang>/corpus.txt`).
The model then learns to find those values back by shape and context — a BIO
tagging task over 8 coarse categories — rather than a binary keep/drop.

Output is written to `synthelion/ml_models/privacyguardml/` (config.json,
vocab.json, model.bin), which `privacy_ml.get_ml_detector()` loads at runtime
whenever `privacy.use_ml = true` — fully offline, no downloads, CPU-only.

Usage (from repo root):
    python devtools/train_privacyguardml.py --corpora-dir devtools/wikipedia_corpus
    python devtools/train_privacyguardml.py --langs en,it,de,fr,es --max-examples-per-lang 3000
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

_log = logging.getLogger("synthelion.train_privacyguardml")

# Model hyperparameters — must match synthelion.privacyguardml
_D_MODEL = 128
_N_HEADS = 4
_N_LAYERS = 2
_FFN_DIM = 512
_DROPOUT = 0.1
_MAX_SEQ = 96
_VOCAB_SIZE = 40000  # PII-bearing sentences carry less lexical variety than
                     # general prose; a smaller fixed vocab keeps the checkpoint
                     # small without hurting shape recognition (OOV falls back
                     # to char-ngram hashing exactly as in SynthelionML).
_MIN_CONFIDENCE = 0.6  # inference threshold stored in config

_EUROPEAN_LANGS = [
    "af", "be", "bg", "ca", "cs", "da", "el", "et", "eu", "fi",
    "ga", "gl", "hr", "hu", "is", "la", "lt", "lv", "mk", "nl",
    "no", "pl", "pt", "ro", "sk", "sl", "sq", "sr", "sv",
]
_BASE_LANGS = ["en", "it", "de", "fr", "es", "ru", "uk", "hi", "zh", "ja"]
_DEFAULT_LANGS = _BASE_LANGS + _EUROPEAN_LANGS


def _build_vocab(examples: list[tuple[list[str], list[str]]], vocab_size: int) -> dict[str, int]:
    from synthelion.privacyguardml import _PAD, _UNK

    counts: Counter = Counter()
    for words, _tags in examples:
        counts.update(words)
    top = [w for w, _ in counts.most_common(vocab_size - 2)]
    word2id = {_PAD: 0, _UNK: 1}
    for w in top:
        word2id[w] = len(word2id)
    return word2id


def _encode_examples(
    examples: list[tuple[list[str], list[str]]],
    word2id: dict[str, int],
    tag2id: dict[str, int],
) -> tuple[list[list[int]], list[list[list[float]]], list[list[int]]]:
    from synthelion.privacyguardml import PrivacyGuardMLVocab, word_features, N_FEATURES, _UNK

    unk_id = word2id[_UNK]
    vocab_size = len(word2id)
    word_ids: list[list[int]] = []
    feats: list[list[list[float]]] = []
    tag_ids: list[list[int]] = []

    for words, tags in examples:
        wids: list[int] = []
        fts: list[list[float]] = []
        for w in words[:_MAX_SEQ]:
            wid = word2id.get(w)
            if wid is None or wid == unk_id:
                wid = PrivacyGuardMLVocab.char_ngram_hash(w) + vocab_size
            wids.append(wid)
            fts.append(word_features(w))
        tids = [tag2id[t] for t in tags[:_MAX_SEQ]]
        pad = _MAX_SEQ - len(wids)
        wids += [0] * pad
        fts += [[0.0] * N_FEATURES] * pad
        tids += [-100] * pad
        word_ids.append(wids)
        feats.append(fts)
        tag_ids.append(tids)
    return word_ids, feats, tag_ids


def _gather_sentences(corpora_dir: Path, langs: list[str], max_per_lang: int, max_bytes: int, rng: random.Random) -> list[str]:
    from train_synthelionml import _reservoir_sample

    sentences: list[str] = []
    for lang in langs:
        corpus_file = corpora_dir / lang / "corpus.txt"
        if not corpus_file.is_file():
            _log.warning("  skip %s: no corpus.txt", lang)
            continue
        texts = _reservoir_sample(corpus_file, max_per_lang, rng, max_bytes)
        sentences.extend(texts)
        _log.info("  %-3s sampled=%d", lang, len(texts))
    return sentences


def train(
    corpora_dir: Path,
    langs: list[str],
    max_examples_per_lang: int,
    examples_per_sentence: int,
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

    from privacyguardml_data import PIIValueGenerator, build_example
    from synthelion.privacyguardml import PrivacyGuardMLModel, TAGS, TAG2ID

    torch.manual_seed(seed)
    np.random.seed(seed)
    rng = random.Random(seed)

    _log.info("Gathering carrier sentences from %d languages", len(langs))
    sentences = _gather_sentences(corpora_dir, langs, max_examples_per_lang, max_bytes_per_lang, rng)
    if len(sentences) < 100:
        _log.error("Not enough carrier sentences (%d). Aborting.", len(sentences))
        sys.exit(2)
    _log.info("Carrier sentences: %d", len(sentences))

    generator = PIIValueGenerator()
    all_examples: list[tuple[list[str], list[str]]] = []
    for sentence in sentences:
        for _ in range(examples_per_sentence):
            ex = build_example(sentence, generator, rng)
            if ex is not None:
                all_examples.append(ex)

    if len(all_examples) < 100:
        _log.error("Not enough training examples (%d). Aborting.", len(all_examples))
        sys.exit(2)

    tag_counts: Counter = Counter()
    for _words, tags in all_examples:
        tag_counts.update(tags)
    _log.info("Total examples=%d tag distribution=%s", len(all_examples), dict(tag_counts.most_common()))

    rng.shuffle(all_examples)
    n_eval = int(len(all_examples) * eval_split)
    eval_examples = all_examples[:n_eval]
    train_examples = all_examples[n_eval:]
    _log.info("train=%d eval=%d", len(train_examples), len(eval_examples))

    word2id = _build_vocab(all_examples, vocab_size)
    vocab_words = ["<pad>", "<unk>"] + [w for w in word2id if w not in ("<pad>", "<unk>")]
    _log.info("Vocabulary size=%d", len(word2id))

    train_word_ids, train_feats, train_tags = _encode_examples(train_examples, word2id, TAG2ID)
    eval_word_ids, eval_feats, eval_tags = _encode_examples(eval_examples, word2id, TAG2ID)

    from synthelion.privacyguardml import N_FEATURES

    model = PrivacyGuardMLModel(
        actual_vocab_size=len(word2id),
        d_model=_D_MODEL,
        n_heads=_N_HEADS,
        n_layers=_N_LAYERS,
        ffn_dim=_FFN_DIM,
        dropout=_DROPOUT,
        n_features=N_FEATURES,
        n_tags=len(TAGS),
        max_seq_len=_MAX_SEQ,
    )
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)

    # Class weights: "O" dominates heavily (most tokens aren't PII) — down-weight
    # it so the loss doesn't collapse to "always predict O".
    total_tags = sum(tag_counts.values())
    o_count = tag_counts.get("O", 0)
    o_weight = max(0.05, 1.0 - o_count / max(1, total_tags))
    weights = [o_weight if t == "O" else 1.0 for t in TAGS]
    class_weights = torch.tensor(weights, dtype=torch.float)
    _log.info("class weights: O=%.3f others=1.0", o_weight)

    dev = torch.device("cpu")
    model = model.to(dev)

    def to_tensors(ids, feats, tags):
        return (
            torch.tensor(ids, dtype=torch.long, device=dev),
            torch.tensor(feats, dtype=torch.float, device=dev),
            torch.tensor(tags, dtype=torch.long, device=dev),
        )

    train_ids_t, train_feats_t, train_tags_t = to_tensors(train_word_ids, train_feats, train_tags)
    eval_ids_t, eval_feats_t, eval_tags_t = to_tensors(eval_word_ids, eval_feats, eval_tags)

    n_train = train_ids_t.shape[0]
    _log.info("Starting training: %d steps/epoch (batch=%d)", (n_train + batch_size - 1) // batch_size, batch_size)

    def run_epoch(ids_t, feats_t, tags_t, indices, training: bool) -> tuple[float, float]:
        running = 0.0
        correct = 0
        total = 0
        n = len(indices)
        for start in range(0, n, batch_size):
            idx = indices[start: start + batch_size]
            x = ids_t[idx]
            f = feats_t[idx]
            y = tags_t[idx]
            B, L = x.shape
            attn = (y != -100)
            # attention_mask must reflect real tokens, not label validity, but
            # padding rows always have y == -100, so this is equivalent and
            # avoids threading a separate mask tensor through encode/collate.
            if training:
                model.train()
                opt.zero_grad()
                logits = model(x, f, attn)
                loss = nn.functional.cross_entropy(
                    logits.reshape(-1, len(TAGS)), y.reshape(-1), weight=class_weights, ignore_index=-100,
                )
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
            else:
                model.eval()
                with torch.no_grad():
                    logits = model(x, f, attn)
                    loss = nn.functional.cross_entropy(
                        logits.reshape(-1, len(TAGS)), y.reshape(-1), weight=class_weights, ignore_index=-100,
                    )
            pred = logits.reshape(-1, len(TAGS)).argmax(-1)
            m = y.reshape(-1) != -100
            correct += int((pred[m] == y.reshape(-1)[m]).sum())
            total += int(m.sum())
            running += float(loss.item()) * B
        return running / n, correct / max(1, total)

    indices = list(range(n_train))
    for epoch in range(1, epochs + 1):
        rng.shuffle(indices)
        t0 = time.time()
        tr_loss, tr_acc = run_epoch(train_ids_t, train_feats_t, train_tags_t, indices, training=True)
        ev_loss, ev_acc = run_epoch(eval_ids_t, eval_feats_t, eval_tags_t, list(range(eval_ids_t.shape[0])), training=False)
        _log.info(
            "epoch %d/%d  train_loss=%.4f train_acc=%.4f  eval_loss=%.4f eval_acc=%.4f  (%.1fs)",
            epoch, epochs, tr_loss, tr_acc, ev_loss, ev_acc, time.time() - t0,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "model_name": "PrivacyGuardML",
        "model_type": "privacyguardml",
        "d_model": _D_MODEL,
        "n_heads": _N_HEADS,
        "n_layers": _N_LAYERS,
        "ffn_dim": _FFN_DIM,
        "dropout": _DROPOUT,
        "n_features": N_FEATURES,
        "n_tags": len(TAGS),
        "tags": TAGS,
        "max_seq_len": _MAX_SEQ,
        "vocab_size": len(word2id),
        "min_confidence": _MIN_CONFIDENCE,
        "trained_languages": langs,
        "training_examples": len(train_examples),
        "eval_examples": len(eval_examples),
    }
    with open(output_dir / "config.json", "w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)
    with open(output_dir / "vocab.json", "w", encoding="utf-8") as fh:
        json.dump({"words": vocab_words}, fh, ensure_ascii=False)
    torch.save(model.state_dict(), output_dir / "model.bin")

    with open(output_dir / "MODEL_INFO.txt", "w", encoding="utf-8") as fh:
        fh.write(
            "PrivacyGuardML model file\n"
            "==========================\n"
            "Generated by Synthelion's own training pipeline:\n"
            "  devtools/train_privacyguardml.py\n\n"
            "Training data: synthetic PII values (generated from Synthelion's own\n"
            "checksum validators in synthelion/privacy_validators.py and rule\n"
            "patterns in synthelion/privacy_rules.yaml) inserted into real\n"
            f"multilingual carrier sentences ({len(langs)} languages, Wikipedia corpora).\n"
            "Architecture: own transformer encoder, BIO tagging head.\n"
            "Runtime: fully offline, CPU-only. This is the only privacy.use_ml\n"
            "backend PrivacyGuard supports — no third-party model.\n"
        )
    _log.info("Checkpoint saved to %s (model.bin, config.json, vocab.json)", output_dir)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train PrivacyGuardML — Synthelion's own PII confirmation model")
    ap.add_argument("--corpora-dir", type=Path, default=Path("devtools/wikipedia_corpus"))
    ap.add_argument("--langs", default=None,
                    help="Comma-separated ISO 639-1 codes; default: all European + base set")
    ap.add_argument("--max-examples-per-lang", type=int, default=1500)
    ap.add_argument("--examples-per-sentence", type=int, default=2,
                    help="How many training examples to build per carrier sentence")
    ap.add_argument("--max-bytes-per-lang", type=int, default=50_000_000)
    ap.add_argument("--vocab-size", type=int, default=_VOCAB_SIZE)
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--eval-split", type=float, default=0.05)
    ap.add_argument("--output-dir", type=Path, default=Path("synthelion/ml_models/privacyguardml"))
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
        args.examples_per_sentence,
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
