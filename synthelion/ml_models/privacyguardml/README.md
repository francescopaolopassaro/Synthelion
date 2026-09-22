---
license: mit
library_name: privacyguardml
tags:
- token-classification
- pii-detection
- ner
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

# PrivacyGuardML

PII confirmation model for [Synthelion](https://github.com/francescopaolopassaro/Synthelion)'s PrivacyGuard — the opt-in ML-assisted confirmation tier (`privacy.use_ml`).

A small, fully offline transformer encoder trained with self-distillation: synthetic PII values are generated from Synthelion's own checksum validators and rule patterns, inserted into real multilingual sentences, and the encoder learns to find them back by shape and context via per-token BIO tagging. It is the sole ML backend PrivacyGuard supports — no third-party model.

**What it's for, precisely.** PrivacyGuard's core tier is regex + algorithmic checksum (or context keyword, for the rules with no checksum), zero-ML, and stays the default. This model is only the confirmation signal: a value that matches a rule's shape but has no context keyword nearby can be confirmed by an overlapping prediction from this model. A failed checksum still vetoes detection regardless of what the model says — it can only recover recall the strict context gate intentionally trades away, never introduce a false positive the validator would reject.

## Architecture

```
Char-ngram hashing -> word embedding + shape-feature embedding -> positional encoding
-> 2-layer TransformerEncoder (d=128, h=4) -> Linear(33) BIO-tag logits
```

| Parameter | Value |
|-----------|-------|
| d_model | 128 |
| n_heads | 4 |
| n_layers | 2 |
| ffn_dim | 512 |
| Vocabulary | 40,000 words + 8,192 char-ngram buckets |
| Max seq len | 96 |
| Input features | 21 (digit/at/plus/separator/uppercase flags + length buckets) |
| Output | 33-class BIO tag logits (16 categories x B/I + O) |

## Categories

Checksum-backed: `PHONE`, `EMAIL`, `CREDITCARD`, `IBAN`, `NATIONALID`, `TAXID`, `SSN`, `GPS`.
Context-only (no checksum, PrivacyGuard's remaining rule categories): `VEHICLEPLATE`, `BADGEID`, `BUSINESSID`, `SECRET`, `SOCIALHANDLE`, `LEGALCASE`, `PNRCODE`, `MINORDATA`.

## Quick start

```python
from synthelion.privacyguardml import PrivacyGuardMLDetector, resolve_model_path

detector = PrivacyGuardMLDetector(resolve_model_path(), min_confidence=0.6)
for span in detector.detect("Contact me at mario.rossi@example.com or IT60X0542811101000000123456"):
    print(span)  # MLSpan(start, end, value, label, confidence)
```

## Training

- **Data**: synthetic PII values (from Synthelion's checksum validators and `privacy_rules.yaml` patterns) inserted into real multilingual carrier sentences (Wikipedia corpora)
- **Labels**: self-distillation — ground truth is exact by construction (the inserted value's span is known at insertion time)
- **Sampling**: checksum-backed categories weighted 4x over context-only categories, to keep primary-category confidence high while still covering the full catalog
- **Languages**: 39 (see `config.json` -> `trained_languages`)
- **Examples**: 106,123 training / 5,585 eval
- **Runtime**: fully offline, CPU-only

## Files

| File | Description |
|------|-------------|
| `config.json` | Model hyperparameters, tag vocabulary, training metadata |
| `vocab.json` | Word vocabulary (40k words) |
| `model.bin` | PyTorch weights |
| `MODEL_INFO.txt` | Training provenance |

## License

MIT License. See [LICENSE](LICENSE) for details.
