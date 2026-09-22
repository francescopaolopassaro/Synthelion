---
license: mit
tags:
- nlp
- function-words
- stopwords
- idf
- part-of-speech
- multilingual
language:
- af
- ar
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
- he
- hi
- hr
- hu
- id
- is
- it
- ja
- ko
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
- th
- tr
- uk
- ur
- vi
- zh
---

# Synthelion worddata

Per-language linguistic data used by [Synthelion](https://github.com/francescopaolopassaro/Synthelion)'s rule-based prompt compressor: function words (stopwords), lemma maps, proper-noun lists, part-of-speech tags, and IDF (inverse document frequency) scores, for 56+ languages.

This data is loaded at runtime by every `compress()` call — it is not an ML model, just precomputed per-language tables. It is downloaded once into `~/.synthelion/worddata/` on first use (or via `synthelion worddata install`) rather than bundled in the PyPI wheel, to keep the published package under PyPI's size limits.

## Files

Brotli-compressed (`.br`) YAML/JSON per language (ISO 639-3 code):

| Suffix | Contents |
|--------|----------|
| `<lang>.yaml.br` | Function words / stopwords |
| `<lang>.pos.yaml.br` | Part-of-speech tag map |
| `<lang>.idf.br` | Inverse document frequency scores |
| `<lang>.generic.yaml.br` | Generic/high-frequency word list |
| `<lang>.excl.yaml.br` | Exclusion list overrides |
| `_index.br` | ISO 639-1 <-> ISO 639-3 language index |

## License

MIT License. See [LICENSE](LICENSE) for details.
