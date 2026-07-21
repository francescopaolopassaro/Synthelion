# Synthelion — Python port of the digitalsolutions WAF
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for the WAF/firewall port: rule inspection, IP allow/block list,
auto-ban, rate limiting, and the unified gate()."""
from __future__ import annotations

from pathlib import Path

import pytest

from synthelion.config import default_config, waf_config
from synthelion.waf_guard import WAF_RULES, WafEngine, inspect


@pytest.fixture()
def cfg():
    return waf_config(default_config())


class TestInspect:
    def test_sql_injection_union_select(self, cfg):
        r = inspect("/x?id=1 UNION SELECT username,password FROM users", "Mozilla/5.0", cfg)
        assert r.matched and r.category == "SqlInjection"

    def test_sql_injection_or_1_equals_1(self, cfg):
        r = inspect("/x?id=1 or 1=1", "Mozilla/5.0", cfg)
        assert r.matched and r.category == "SqlInjection"

    def test_xss_script_tag(self, cfg):
        r = inspect("/search?q=<script>alert(1)</script>", "Mozilla/5.0", cfg)
        assert r.matched and r.category == "Xss"

    def test_path_traversal(self, cfg):
        r = inspect("/download?file=../../../../etc/passwd", "Mozilla/5.0", cfg)
        assert r.matched and r.category == "PathTraversal"

    def test_command_injection(self, cfg):
        r = inspect("/run?cmd=; whoami", "Mozilla/5.0", cfg)
        assert r.matched and r.category == "CommandInjection"

    def test_scanner_probe_path(self, cfg):
        r = inspect("/wp-login.php", "Mozilla/5.0", cfg)
        assert r.matched and r.category == "ScannerProbe"

    def test_bad_user_agent(self, cfg):
        r = inspect("/anything", "sqlmap/1.6.12", cfg)
        assert r.matched and r.category == "BadUserAgent"

    def test_clean_request_no_match(self, cfg):
        r = inspect("/overview?range=30", "Mozilla/5.0 (Windows NT 10.0)", cfg)
        assert not r.matched

    def test_disabled_category_is_skipped(self, cfg):
        cfg2 = {**cfg, "rule_sql_injection": False}
        r = inspect("/x?id=1 UNION SELECT a FROM b", "Mozilla/5.0", cfg2)
        assert not r.matched

    def test_all_rules_have_valid_categories(self):
        assert len(WAF_RULES) >= 19
        for rule in WAF_RULES:
            assert rule.target in ("url", "ua", "path")


class TestIpRules:
    def test_add_and_get_active_block(self, tmp_path: Path):
        eng = WafEngine(tmp_path)
        eng.add_ip_rule("1.2.3.4", "Block", "test ban", minutes=None)
        assert eng.get_active_block("1.2.3.4") is not None
        assert not eng.is_allowlisted("1.2.3.4")

    def test_allowlist(self, tmp_path: Path):
        eng = WafEngine(tmp_path)
        eng.add_ip_rule("5.6.7.8", "Allow")
        assert eng.is_allowlisted("5.6.7.8")
        assert eng.get_active_block("5.6.7.8") is None

    def test_expired_rule_is_not_active(self):
        from synthelion.waf_guard import WafIpRule
        import time as _time
        rule = WafIpRule(ip="9.9.9.9", kind="Block", expires_at=_time.time() - 10)
        assert rule.is_active is False

    def test_permanent_rule_is_always_active(self):
        from synthelion.waf_guard import WafIpRule
        rule = WafIpRule(ip="9.9.9.9", kind="Block", expires_at=None)
        assert rule.is_active is True

    def test_delete_ip_rule(self, tmp_path: Path):
        eng = WafEngine(tmp_path)
        eng.add_ip_rule("1.1.1.1", "Block")
        eng.delete_ip_rule("1.1.1.1", "Block")
        assert eng.get_active_block("1.1.1.1") is None

    def test_re_adding_same_ip_kind_replaces_not_duplicates(self, tmp_path: Path):
        eng = WafEngine(tmp_path)
        eng.add_ip_rule("2.2.2.2", "Block", "first")
        eng.add_ip_rule("2.2.2.2", "Block", "second")
        rules = [r for r in eng.list_ip_rules() if r.ip == "2.2.2.2"]
        assert len(rules) == 1
        assert rules[0].reason == "second"


class TestEventsAndAutoBan:
    def test_log_event_and_all_events(self, tmp_path: Path, cfg):
        eng = WafEngine(tmp_path)
        decision = eng.gate("3.3.3.3", "GET", "/x", "id=1 UNION SELECT", "Mozilla",
                             "", {**cfg, "block_mode": True})
        assert not decision.allowed
        events = eng.all_events()
        assert len(events) == 1
        assert events[0]["ip"] == "3.3.3.3"
        assert events[0]["action"] == "Blocked"

    def test_detect_only_logs_but_does_not_block(self, tmp_path: Path, cfg):
        eng = WafEngine(tmp_path)
        decision = eng.gate("4.4.4.4", "GET", "/x", "id=1 UNION SELECT", "Mozilla",
                             "", {**cfg, "block_mode": False})
        assert decision.allowed
        events = eng.all_events()
        assert events[0]["action"] == "Detected"

    def test_auto_ban_triggers_after_threshold(self, tmp_path: Path, cfg):
        eng = WafEngine(tmp_path)
        cfg2 = {**cfg, "block_mode": True, "auto_ban_threshold": 3, "auto_ban_window_minutes": 10}
        banned = False
        for _ in range(3):
            decision = eng.gate("6.6.6.6", "GET", "/x", "id=1 UNION SELECT", "Mozilla", "", cfg2)
            banned = banned or decision.banned_now
        assert banned
        assert eng.get_active_block("6.6.6.6") is not None

    def test_clean_requests_never_logged(self, tmp_path: Path, cfg):
        eng = WafEngine(tmp_path)
        eng.gate("7.7.7.7", "GET", "/overview", "range=30", "Mozilla/5.0", "", cfg)
        assert eng.all_events() == []


class TestRateLimit:
    def test_rate_limit_triggers_over_threshold(self, tmp_path: Path, cfg):
        eng = WafEngine(tmp_path)
        cfg2 = {**cfg, "rate_limit_requests_per_minute": 3}
        exceeded = [eng.check_rate_limit("8.8.8.8", cfg2) for _ in range(6)]
        assert any(exceeded)

    def test_rate_limit_disabled_never_triggers(self, tmp_path: Path, cfg):
        eng = WafEngine(tmp_path)
        cfg2 = {**cfg, "rate_limit_enabled": False, "rate_limit_requests_per_minute": 1}
        exceeded = [eng.check_rate_limit("1.1.1.9", cfg2) for _ in range(10)]
        assert not any(exceeded)


class TestGate:
    def test_allowlisted_ip_always_allowed_even_with_attack_payload(self, tmp_path: Path, cfg):
        eng = WafEngine(tmp_path)
        eng.add_ip_rule("10.0.0.1", "Allow")
        decision = eng.gate("10.0.0.1", "GET", "/x", "id=1 UNION SELECT", "sqlmap",
                             "", {**cfg, "block_mode": True})
        assert decision.allowed

    def test_disabled_waf_allows_everything(self, tmp_path: Path, cfg):
        eng = WafEngine(tmp_path)
        cfg2 = {**cfg, "enabled": False, "block_mode": True}
        decision = eng.gate("11.0.0.1", "GET", "/x", "id=1 UNION SELECT", "sqlmap", "", cfg2)
        assert decision.allowed

    def test_active_ip_block_rejects_in_block_mode(self, tmp_path: Path, cfg):
        eng = WafEngine(tmp_path)
        eng.add_ip_rule("12.0.0.1", "Block", "manual ban")
        decision = eng.gate("12.0.0.1", "GET", "/overview", "", "Mozilla/5.0",
                             "", {**cfg, "block_mode": True})
        assert not decision.allowed
