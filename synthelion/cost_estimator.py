# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

from synthelion.tokenizer import LlmModel

# Default USD→EUR conversion rate (indicative, overridable).
DEFAULT_USD_TO_EUR = 0.92

# Indicative input prices (USD per 1K tokens). May be out of date — pass your own
# price for accuracy. Self-hosted models default to 0.
_DEFAULT_USD_PER_1K: dict[LlmModel, float] = {
    LlmModel.GPT4: 0.03,
    LlmModel.GPT3_5_TURBO: 0.0015,
    LlmModel.CLAUDE3: 0.015,
    LlmModel.LLAMA3: 0.0,
    LlmModel.GEMMA3: 0.0,
}


def default_usd_per_1k_tokens(model: LlmModel) -> float:
    """Indicative input price in USD per 1K tokens for a model."""
    return _DEFAULT_USD_PER_1K.get(model, 0.0)


def usd(tokens: int, usd_per_1k: float) -> float:
    """Cost in USD for `tokens` at the given USD price per 1K tokens."""
    return tokens / 1000 * usd_per_1k


def eur(tokens: int, usd_per_1k: float, usd_to_eur: float = DEFAULT_USD_TO_EUR) -> float:
    """Cost in EUR for `tokens` given a USD price and a USD→EUR rate."""
    return usd(tokens, usd_per_1k) * usd_to_eur
