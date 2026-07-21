# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for response_style.py (output-side verbosity guidance generator)."""
from __future__ import annotations

from synthelion.response_style import get_style_guidance


class TestGetStyleGuidance:
    def test_default_is_lite(self):
        g = get_style_guidance()
        assert "no opening pleasantries" in g

    def test_lite_explicit(self):
        assert get_style_guidance("lite") == get_style_guidance()

    def test_full_includes_lite_content_and_bugfix_structure(self):
        g = get_style_guidance("full")
        assert "no opening pleasantries" in g
        assert "root cause" in g

    def test_ultra_includes_full_and_lite_content_and_synonym_note(self):
        g = get_style_guidance("ultra")
        assert "no opening pleasantries" in g
        assert "root cause" in g
        assert "shorter synonym" in g

    def test_levels_are_strictly_increasing_in_length(self):
        lite, full, ultra = get_style_guidance("lite"), get_style_guidance("full"), get_style_guidance("ultra")
        assert len(lite) < len(full) < len(ultra)

    def test_invalid_level_falls_back_to_lite(self):
        assert get_style_guidance("nonsense") == get_style_guidance("lite")

    def test_level_case_insensitive(self):
        assert get_style_guidance("LITE") == get_style_guidance("lite")
        assert get_style_guidance("Full") == get_style_guidance("full")

    def test_cjk_language_appends_note(self):
        g_plain = get_style_guidance("lite")
        g_cjk = get_style_guidance("lite", language="zho")
        assert "CJK" in g_cjk
        assert g_cjk.startswith(g_plain)
        assert len(g_cjk) > len(g_plain)

    def test_japanese_and_korean_also_trigger_cjk_note(self):
        assert "CJK" in get_style_guidance("lite", language="jpn")
        assert "CJK" in get_style_guidance("lite", language="kor")

    def test_non_cjk_language_no_note(self):
        g = get_style_guidance("lite", language="eng")
        assert "CJK" not in g

    def test_language_case_insensitive(self):
        assert "CJK" in get_style_guidance("lite", language="ZHO")

    def test_no_language_no_note(self):
        assert "CJK" not in get_style_guidance("lite")
