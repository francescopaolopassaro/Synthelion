"""Convert SynthelionML from PyTorch checkpoint to ONNX + SafeTensors.

Usage:
    python convert_synthelionml.py

Outputs (in the source checkpoint directory):
    synthelionml.onnx          — ONNX model
    model.safetensors          — SafeTensors weights
    config.json                — updated with SafeTensors metadata
    tokenizer.json             — HuggingFace-compatible tokenizer config
    preprocessor_config.json   — feature extractor config
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────────
SRC = Path(r"C:\Sorgenti\Personal\Synthelion\synthelion\ml_models\synthelionml")
OUT = SRC  # write back into the same directory


def load_model():
    """Load SynthelionML PyTorch model from checkpoint."""
    import torch
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "Synthelion"))
    from synthelion.synthelionml import _build_model_if_torch

    result = _build_model_if_torch(SRC)
    if result is None:
        raise RuntimeError("Failed to load model from %s" % SRC)
    model, vocab, config = result
    return model, vocab, config


def export_onnx(model, config):
    """Export model to ONNX format."""
    import torch

    d_model = config.get("d_model", 128)
    n_features = config.get("n_features", 18)
    max_seq_len = config.get("max_seq_len", 96)

    # Dummy inputs
    B, L = 1, 16
    word_ids = torch.zeros(B, L, dtype=torch.long)
    features = torch.zeros(B, L, n_features)
    attention_mask = torch.ones(B, L, dtype=torch.bool)

    onnx_path = OUT / "synthelionml.onnx"
    torch.onnx.export(
        model,
        (word_ids, features, attention_mask),
        str(onnx_path),
        input_names=["word_ids", "features", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={
            "word_ids": {0: "batch", 1: "seq_len"},
            "features": {0: "batch", 1: "seq_len"},
            "attention_mask": {0: "batch", 1: "seq_len"},
            "logits": {0: "batch", 1: "seq_len"},
        },
        opset_version=17,
        do_constant_folding=True,
        dynamo=False,
    )
    size_mb = onnx_path.stat().st_size / (1024 * 1024)
    print(f"ONNX exported: {onnx_path}  ({size_mb:.1f} MB)")
    return onnx_path


def export_safetensors(model, config):
    """Export model weights to SafeTensors format."""
    from safetensors.torch import save_file

    state_dict = model.state_dict()
    # Rename keys to HuggingFace convention
    hf_state = {}
    for k, v in state_dict.items():
        hk = k.replace(".", "/")
        hf_state[hk] = v

    safetensors_path = OUT / "model.safetensors"
    save_file(hf_state, str(safetensors_path))
    size_mb = safetensors_path.stat().st_size / (1024 * 1024)
    print(f"SafeTensors exported: {safetensors_path}  ({size_mb:.1f} MB)")

    # Write index file
    index = {
        "metadata": {"total_size": sum(v.numel() * v.element_size() for v in state_dict.values())},
        "weight_map": {k: "model.safetensors" for k in hf_state},
    }
    index_path = OUT / "model.safetensors.index.json"
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)
    print(f"Index written: {index_path}")
    return safetensors_path


def export_hf_config(config, vocab):
    """Write HuggingFace-compatible config and tokenizer files."""
    # config.json — model architecture
    hf_config = {
        "model_type": "synthelionml",
        "architectures": ["SynthelionMLForTokenClassification"],
        "d_model": config.get("d_model", 128),
        "n_heads": config.get("n_heads", 4),
        "n_layers": config.get("n_layers", 2),
        "ffn_dim": config.get("ffn_dim", 512),
        "dropout": config.get("dropout", 0.1),
        "n_features": config.get("n_features", 18),
        "max_seq_len": config.get("max_seq_len", 96),
        "vocab_size": vocab.vocab_size,
        "char_ngram_buckets": 8192,
        "num_labels": 2,
        "id2label": {"0": "drop", "1": "keep"},
        "label2id": {"drop": 0, "keep": 1},
        "keep_threshold": config.get("keep_threshold", 0.6),
        "min_compression": config.get("min_compression", 0.7),
        "trained_languages": config.get("trained_languages", []),
        "languages_used": config.get("languages_used", 0),
        "training_examples": config.get("training_examples", 0),
        "eval_examples": config.get("eval_examples", 0),
        "transformers_version": "4.40.0",
    }
    config_path = OUT / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(hf_config, f, indent=2, ensure_ascii=False)
    print(f"Config written: {config_path}")

    # tokenizer.json — minimal HuggingFace tokenizer config
    tokenizer = {
        "model": {
            "type": "WordLevel",
            "unk_token": "<unk>",
            "vocab": vocab.word2id,
        },
        "pre_tokenizer": {
            "type": "Whitespace",
        },
        "decoder": {
            "type": "WordPiece",
            "wordpiece": "##",
            "continuing_subword_prefix": "##",
        },
        "added_tokens": [
            {"id": 0, "content": "<pad>", "special": True},
            {"id": 1, "content": "<unk>", "special": True},
            {"id": 2, "content": "<s>", "special": True},
            {"id": 3, "content": "<eos>", "special": True},
        ],
    }
    tokenizer_path = OUT / "tokenizer.json"
    with open(tokenizer_path, "w", encoding="utf-8") as f:
        json.dump(tokenizer, f, indent=2, ensure_ascii=False)
    print(f"Tokenizer written: {tokenizer_path}")

    # preprocessor_config.json — feature extractor settings
    preprocessor = {
        "feature_extractor_type": "SynthelionMLFeatureExtractor",
        "n_features": config.get("n_features", 18),
        "char_ngram_buckets": 8192,
        "function_words_path": None,
    }
    preproc_path = OUT / "preprocessor_config.json"
    with open(preproc_path, "w", encoding="utf-8") as f:
        json.dump(preprocessor, f, indent=2)
    print(f"Preprocessor config written: {preproc_path}")


def main():
    print("=" * 60)
    print("SynthelionML Converter: PyTorch -> ONNX + SafeTensors")
    print("=" * 60)

    model, vocab, config = load_model()
    print(f"\nModel loaded: {sum(p.numel() for p in model.parameters()):,} parameters")
    print(f"  d_model={config.get('d_model')}, n_heads={config.get('n_heads')}, "
          f"n_layers={config.get('n_layers')}, vocab={vocab.vocab_size}")

    print("\n--- Exporting ONNX ---")
    export_onnx(model, config)

    print("\n--- Exporting SafeTensors ---")
    export_safetensors(model, config)

    print("\n--- Writing HuggingFace config files ---")
    export_hf_config(config, vocab)

    print("\n" + "=" * 60)
    print("Done! Files written to:", OUT)
    print("=" * 60)


if __name__ == "__main__":
    main()
