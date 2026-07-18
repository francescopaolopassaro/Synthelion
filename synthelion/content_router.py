# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import hashlib
import time
from threading import Lock

from synthelion.compressors.code_compressor import CodeCompressor
from synthelion.compressors.diff_compressor import DiffCompressor
from synthelion.compressors.html_extractor import HtmlExtractor
from synthelion.compressors.json_crusher import JsonCrusher
from synthelion.compressors.log_compressor import LogCompressor
from synthelion.compressors.tabular import TabularCompressor
from synthelion.content_detector import ContentDetector
from synthelion.core import CompressionService
from synthelion.models import (
    CompressionLevel,
    CompressionProfile,
    ContentType,
    RoutedCompressionResult,
)

_CACHE_TTL = 1800   # 30 minutes
_CACHE_MAX = 512    # max entries — evict oldest 25% when full


def _approx_tokens(text: str) -> int:
    return len(text) // 4


class ContentRouter:
    """Routes content to the best compressor based on detected type.

    Ported from C# CavemanContentRouter. Two-tier in-process cache (hash → result,
    TTL 30 min). Supports CompressionProfile presets.
    """

    def __init__(
        self,
        prose_level: CompressionLevel = CompressionLevel.SEMANTIC,
        max_json_items: int = 15,
        compression_service: CompressionService | None = None,
    ) -> None:
        self._prose_level = prose_level
        self._detector = ContentDetector()
        self._nlp = compression_service or CompressionService()
        self._json = JsonCrusher(max_json_items)
        self._html = HtmlExtractor()
        self._diff = DiffCompressor()
        self._log = LogCompressor()
        self._code = CodeCompressor()
        self._table = TabularCompressor()
        self._cache: dict[str, tuple[RoutedCompressionResult, float]] = {}
        self._cache_lock = Lock()

    @classmethod
    def from_profile(cls, profile: CompressionProfile) -> "ContentRouter":
        params = {
            CompressionProfile.LIGHT:      (CompressionLevel.LIGHT, 25),
            CompressionProfile.BALANCED:   (CompressionLevel.SEMANTIC, 15),
            CompressionProfile.AGENT:      (CompressionLevel.SEMANTIC, 10),
            CompressionProfile.AGGRESSIVE: (CompressionLevel.AGGRESSIVE, 8),
        }
        level, max_items = params.get(profile, (CompressionLevel.SEMANTIC, 15))
        return cls(prose_level=level, max_json_items=max_items)

    def route(self, content: str, query: str | None = None) -> RoutedCompressionResult:
        if not content or not content.strip():
            return RoutedCompressionResult(
                compressed=content, original=content,
                detected_type=ContentType.PLAIN_TEXT,
                strategy_used="Passthrough",
            )

        cache_key = hashlib.md5(content.encode()).hexdigest()
        with self._cache_lock:
            entry = self._cache.get(cache_key)
            if entry and time.time() - entry[1] < _CACHE_TTL:
                return entry[0]

        try:
            result = self._route_inner(content, query)
        except Exception as exc:
            result = RoutedCompressionResult(
                compressed=content, original=content,
                detected_type=ContentType.PLAIN_TEXT,
                strategy_used="Error",
                error_message=str(exc),
            )

        with self._cache_lock:
            self._cache[cache_key] = (result, time.time())
            if len(self._cache) > _CACHE_MAX:
                # Evict oldest 25% of entries
                sorted_keys = sorted(self._cache, key=lambda k: self._cache[k][1])
                for k in sorted_keys[: _CACHE_MAX // 4]:
                    del self._cache[k]

        return result

    def _route_inner(self, content: str, query: str | None) -> RoutedCompressionResult:
        detection = self._detector.detect(content)
        ct = detection.type
        tb = _approx_tokens(content)

        if ct == ContentType.JSON_ARRAY:
            r = self._json.crush(content, query)
            compressed = r["compressed"]
            return RoutedCompressionResult(
                compressed=compressed, original=content,
                detected_type=ct,
                strategy_used=f"JsonCrush:{r['strategy']}",
                tokens_before=tb, tokens_after=_approx_tokens(compressed),
                ccr_hash=r.get("ccr_hash"),
            )

        if ct == ContentType.GIT_DIFF:
            compressed, _ = self._diff.compress(content)
            return RoutedCompressionResult(
                compressed=compressed, original=content,
                detected_type=ct, strategy_used="DiffCompression",
                tokens_before=tb, tokens_after=_approx_tokens(compressed),
            )

        if ct == ContentType.LOG_OR_STACKTRACE:
            compressed, _ = self._log.compress(content)
            return RoutedCompressionResult(
                compressed=compressed, original=content,
                detected_type=ct, strategy_used="LogCompression",
                tokens_before=tb, tokens_after=_approx_tokens(compressed),
            )

        if ct == ContentType.HTML:
            extracted = self._html.extract(content)
            nlp_result = self._nlp.compress(extracted, self._prose_level)
            compressed = nlp_result.compressed_text
            return RoutedCompressionResult(
                compressed=compressed, original=content,
                detected_type=ct, strategy_used="HtmlExtract+NlpCompression",
                tokens_before=tb, tokens_after=_approx_tokens(compressed),
            )

        if ct == ContentType.CODE:
            compressed, lang, _, _ = self._code.compress(content)
            return RoutedCompressionResult(
                compressed=compressed, original=content,
                detected_type=ct, strategy_used=f"CodeCompression:{lang}",
                tokens_before=tb, tokens_after=_approx_tokens(compressed),
            )

        if ct == ContentType.TABULAR:
            compressed, was = self._table.compress(content)
            return RoutedCompressionResult(
                compressed=compressed, original=content,
                detected_type=ct, strategy_used="TabularCompression" if was else "Passthrough",
                tokens_before=tb, tokens_after=_approx_tokens(compressed),
            )

        if ct == ContentType.SEARCH_RESULTS:
            nlp_result = self._nlp.compress(content, self._prose_level)
            compressed = nlp_result.compressed_text
            return RoutedCompressionResult(
                compressed=compressed, original=content,
                detected_type=ct, strategy_used="NlpCompression",
                tokens_before=tb, tokens_after=_approx_tokens(compressed),
            )

        # PlainText / JsonObject → NLP compression
        nlp_result = self._nlp.compress(content, self._prose_level)
        compressed = nlp_result.compressed_text
        return RoutedCompressionResult(
            compressed=compressed, original=content,
            detected_type=ct, strategy_used="NlpCompression",
            tokens_before=tb, tokens_after=_approx_tokens(compressed),
        )
