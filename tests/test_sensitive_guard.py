# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for the credential-shape detector (sensitive_guard.py)."""
from __future__ import annotations

from synthelion.sensitive_guard import find_sensitive


class TestFindSensitive:
    def test_detects_private_key_block(self):
        s = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        assert find_sensitive(s) == "private-key-block"

    def test_detects_aws_access_key(self):
        assert find_sensitive("key=AKIAIOSFODNN7EXAMPLE") == "aws-access-key"

    def test_ignores_akia_prefix_too_short(self):
        assert find_sensitive("AKIASHORT") is None

    def test_detects_github_pat_classic(self):
        assert find_sensitive("token: ghp_abcdefghijklmnopqrstuvwxyzABCDEF") == "github-token"

    def test_detects_github_pat_fine_grained(self):
        assert find_sensitive("github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") == "github-token"

    def test_detects_slack_bot_token(self):
        # Built via concatenation rather than a single literal so the contiguous
        # secret-shaped string never appears verbatim in the source file (GitHub's
        # push-protection secret scanner flags it even though it's a test fixture).
        fake_token = "xox" + "b-" + "1234567890-1234567890-abcdefghijklmnop"
        assert find_sensitive(f"SLACK_TOKEN={fake_token}") == "slack-token"

    def test_detects_openai_style_key(self):
        assert find_sensitive("OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456") == "api-secret-key"

    def test_ignores_prose_ending_in_sk_dash(self):
        assert find_sensitive("this is a desk-based risk-averse task-oriented plan") is None

    def test_detects_bearer_token(self):
        s = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature"
        assert find_sensitive(s) == "bearer-token"

    def test_detects_aws_secret_line(self):
        s = "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        assert find_sensitive(s) == "aws-secret-line"

    def test_detects_dotenv_bulk_secrets(self):
        s = "DB_PASSWORD=hunter2\nSTRIPE_SECRET=sk_live_xxx\nAPI_TOKEN=abc123\nDEBUG=true"
        assert find_sensitive(s) == "dotenv-bulk-secrets"

    def test_ignores_single_dotenv_secret_line(self):
        assert find_sensitive("DB_PASSWORD=hunter2\nDEBUG=true\nPORT=8080") is None

    def test_ignores_clean_env_dump(self):
        s = "PATH=/usr/bin:/bin\nHOME=/Users/dev\nSHELL=/bin/zsh\nLANG=C.UTF-8\nTERM=xterm-256color"
        assert find_sensitive(s) is None

    def test_ignores_ordinary_prose(self):
        s = "This function returns a Result and logs an error if the token is invalid."
        assert find_sensitive(s) is None

    def test_empty_text_returns_none(self):
        assert find_sensitive("") is None
        assert find_sensitive(None) is None  # defensive: callers may pass a falsy value

    def test_scan_cap_ignores_secrets_past_64kb(self):
        padding = "x" * (64 * 1024 + 10)
        s = f"{padding}\nAKIAIOSFODNN7EXAMPLE"
        assert find_sensitive(s) is None, "secret past the scan cap must not be found"

    def test_secret_within_scan_cap_is_found(self):
        s = "AKIAIOSFODNN7EXAMPLE\n" + "x" * (64 * 1024)
        assert find_sensitive(s) == "aws-access-key"

    def test_returns_first_matching_class_deterministically(self):
        s = "-----BEGIN RSA PRIVATE KEY-----\nkey\n-----END RSA PRIVATE KEY-----\nAKIAIOSFODNN7EXAMPLE"
        assert find_sensitive(s) == "private-key-block"
