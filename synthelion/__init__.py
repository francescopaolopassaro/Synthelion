# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Synthelion: token compressor for LLMs. 50+ languages, zero ML models.

Python port of Caveman (C#) by Passaro Francesco Paolo (Digitalsolutions.it).
Original: https://github.com/francescopaolopassaro/caveman
"""
from synthelion.models import (
    CompressionLevel,
    CompressionProfile,
    CompressionResult,
    ContentType,
    RoutedCompressionResult,
    VerbosityLevel,
)
from synthelion.word_provider import FunctionWordProvider
from synthelion.detector import LanguageDetector
from synthelion.core import CompressionFilter, CompressionService
from synthelion.content_detector import ContentDetector
from synthelion.content_router import ContentRouter

__version__ = "1.0.6"
__author__ = "Passaro Francesco Paolo"


def count_tokens(text: str, mode: str = "approx") -> int:
    """Estimate token count of *text*.

    mode="approx"  → GPT-style estimate: len(text) // 4  (fast, ±15%)
    mode="words"   → whitespace word count (language-dependent)
    """
    if not text:
        return 0
    if mode == "words":
        return len(text.split())
    return len(text) // 4


__all__ = [
    "CompressionLevel",
    "CompressionProfile",
    "CompressionResult",
    "CompressionFilter",
    "ContentType",
    "RoutedCompressionResult",
    "VerbosityLevel",
    "FunctionWordProvider",
    "LanguageDetector",
    "CompressionService",
    "ContentDetector",
    "ContentRouter",
    "count_tokens",
]
