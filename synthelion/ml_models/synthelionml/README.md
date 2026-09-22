---
license: mit
library_name: synthelionml
tags:
- text-classification
- token-classification
- prompt-compression
- transformer encoder
- multilingual
language:
- af
- be
- bg
- ca
- cs
- da
- de
- el
- en
- es
- et
- eu
- fi
- fr
- ga
- gl
- hi
- hr
- hu
- is
- it
- ja
- la
- lt
- lv
- mk
- nl
- no
- pl
- pt
- ro
- ru
- sk
- sl
- sq
- sr
- sv
- uk
- zh
---

# SynthelionML

Learned per-token keep/drop prompt compressor for [Synthelion](https://github.com/francescopaolopassaro/Synthelion).

A small, fully offline transformer encoder trained on Wikipedia corpora (39 languages) to predict which tokens can be dropped while preserving meaning. The model is trained using self-distillation: the rule-based SYNTACTIC compressor provides ground-truth labels, and the encoder learns to generalise beyond simple rules by attending to surrounding token context.

## Architecture

```
Char-ngram hashing -> word embedding + feature embedding -> positional encoding
-> 2-layer TransformerEncoder (d=128, h=4) -> Linear(2) keep/drop logits
```

| Parameter | Value |
|-----------|-------|
| Parameters | 10.4M |
| d_model | 128 |
| n_heads | 4 |
| n_layers | 2 |
| ffn_dim | 512 |
| Vocabulary | 70,000 words + 8,192 char-ngram buckets |
| Max seq len | 96 |
| Input features | 18 (stopword, capitalization, length buckets) |
| Output | 2-class logits (drop / keep) |

## Formats

| File | Format | Size | Use case |
|------|--------|------|----------|
| `model.bin` | PyTorch state_dict | 39.8 MB | PyTorch inference (native) |
| `model.safetensors` | SafeTensors | 39.8 MB | HuggingFace / cross-framework |
| `synthelionml.onnx` | ONNX opset 17 | 39.8 MB | ONNX Runtime, JS, C#, mobile |

## Quick start

### PyTorch (native)

```python
from synthelion.synthelionml import SynthelionMLCompressor

compressor = SynthelionMLCompressor.get_instance()
compressed = compressor.compress("Your long prompt text here...")
```

### ONNX Runtime

```python
import onnxruntime as ort
import numpy as np

sess = ort.InferenceSession("synthelionml.onnx")

word_ids = np.array([[...]], dtype=np.int64)       # (1, seq_len)
features = np.random.randn(1, seq_len, 18).astype(np.float32)
mask = np.ones((1, seq_len), dtype=np.bool_)

logits = sess.run(None, {
    "word_ids": word_ids,
    "features": features,
    "attention_mask": mask,
})[0]  # (1, seq_len, 2) — logits for [drop, keep]
```

### SafeTensors (HuggingFace)

```python
from safetensors.torch import load_file

weights = load_file("model.safetensors")
# keys use "/" separator: "_word_emb.weight", "_encoder.layers.0.self_attn.in_proj_weight", etc.
```

## Training

- **Data**: Synthelion's Wikipedia corpora (74,100 training examples, 3,900 eval)
- **Labels**: Self-distillation from the aggressive rule-based compressor
- **Languages**: 39 (see `config.json` -> `trained_languages`)
- **Min compression**: 70% (rank-based ratio controller)
- **Runtime**: Fully offline, CPU-only

## Files

| File | Description |
|------|-------------|
| `config.json` | Model hyperparameters and training metadata |
| `vocab.json` | Word vocabulary (70k words) |
| `tokenizer.json` | HuggingFace-compatible tokenizer config |
| `preprocessor_config.json` | Feature extractor settings |
| `model.bin` | PyTorch weights |
| `model.safetensors` | SafeTensors weights |
| `model.safetensors.index.json` | SafeTensors shard index |
| `synthelionml.onnx` | ONNX export |
| `MODEL_INFO.txt` | Training provenance |

## License

MIT License. See [LICENSE](LICENSE) for details.
