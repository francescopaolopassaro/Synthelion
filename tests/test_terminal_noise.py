# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for terminal_noise.py (ANSI/spinner/progress-bar stripping)."""
from __future__ import annotations

from synthelion.terminal_noise import strip_ansi_noise


class TestStripAnsiNoise:
    def test_strips_color_codes(self):
        s = "\x1b[32mSuccess\x1b[0m: build finished"
        assert strip_ansi_noise(s) == "Success: build finished"

    def test_strips_cursor_movement(self):
        s = "\x1b[2K\x1b[1Gline one\nline two"
        assert strip_ansi_noise(s) == "line one\nline two"

    def test_strips_isolated_spinner_lines(self):
        s = "Installing dependencies\n⠋\n⠙\n⠹\nDone"
        assert strip_ansi_noise(s) == "Installing dependencies\nDone"

    def test_spinner_glyph_inside_text_not_stripped(self):
        s = "note: this char ⠋ appears mid-sentence"
        assert strip_ansi_noise(s) == s

    def test_strips_unicode_progress_bar_line(self):
        s = "Downloading\n████████████░░░░░░░░ 60%\nDone"
        assert strip_ansi_noise(s) == "Downloading\nDone"

    def test_strips_ascii_bracket_progress_bar_with_percent(self):
        s = "Downloading\n[=========>      ] 55%\nDone"
        assert strip_ansi_noise(s) == "Downloading\nDone"

    def test_does_not_strip_plain_dash_divider(self):
        s = "Section A\n----------\nSection B"
        assert strip_ansi_noise(s) == s

    def test_does_not_strip_markdown_table_separator(self):
        s = "| a | b |\n|---|---|\n| 1 | 2 |"
        assert strip_ansi_noise(s) == s

    def test_collapses_in_place_carriage_return_overwrite(self):
        s = "Progress: 10%\rProgress: 50%\rProgress: 100%\nDone"
        assert strip_ansi_noise(s) == "Progress: 100%\nDone"

    def test_ordinary_text_unchanged(self):
        s = "This is a completely ordinary line of text.\nAnd a second one."
        assert strip_ansi_noise(s) == s

    def test_empty_text(self):
        assert strip_ansi_noise("") == ""

    def test_combined_realistic_npm_output(self):
        s = (
            "\x1b[1mnpm install\x1b[0m\n"
            "⠋\n⠙\n⠹\n"
            "[=========>      ] 70%\r[===============>] 100%\n"
            "added 42 packages in 3s\n"
        )
        cleaned = strip_ansi_noise(s)
        assert "\x1b" not in cleaned
        assert "⠋" not in cleaned
        assert "added 42 packages in 3s" in cleaned
