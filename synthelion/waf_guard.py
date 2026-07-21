# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Application-layer WAF + firewall — request pattern inspection (SQLi, XSS, path
traversal, command injection, scanner probes, bad user agents), IP allow/block
lists with expiry, auto-ban on repeated violations, and a lightweight per-IP rate
limiter ("firewall" layer, distinct from the WAF's pattern-based inspection but
sharing the same IP block list).

Every entry point is a pure function/method with no dependency on any particular
HTTP handler — `WafEngine.gate(...)` is the single call any network-facing
component in Synthelion should make. Today that's `synthelion/plugins/dashboard.py`
(the only component that actually opens a network socket — the MCP server is
stdio-only, see mcp_server.py); if a network transport is ever added there too,
it calls the same `gate()`.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from synthelion.analytics._atomic_append import append_line

_IP_RULES_FILE = "waf_ip_rules.json"
_EVENTS_FILE = "waf_events.jsonl"
_EVENTS_CAP = 8000


def _storage_dir(directory: Path | None = None) -> Path:
    # Path.home() re-read every call, not cached at module scope — see
    # ledger.py's identical comment: a cached constant would defeat tests that
    # monkeypatch Path.home() to an isolated tmp_path.
    d = directory or (Path.home() / ".synthelion")
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass(frozen=True)
class WafRule:
    category: str
    name: str
    severity: str  # "Low" | "Medium" | "High"
    pattern: re.Pattern
    target: str = "url"  # "url" (path+query) | "ua" (User-Agent) | "path"


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


# Direct 1:1 port of digitalsolutions/Models/Waf.cs WafRules.All — same regex
# text, categories, names and severities as the C# WAF this was ported from.
WAF_RULES: list[WafRule] = [
    # SQL Injection
    WafRule("SqlInjection", "UNION SELECT", "High", _rx(r"\bunion\b\s+\bselect\b")),
    WafRule("SqlInjection", "SELECT ... FROM", "Medium", _rx(r"\bselect\b[\s\S]{1,60}\bfrom\b")),
    WafRule("SqlInjection", "OR 1=1", "High", _rx(r"\bor\b\s+\d+\s*=\s*\d+")),
    WafRule("SqlInjection", "SQL comment / stacked", "Medium", _rx(r"('|%27)\s*(;|--|#)")),
    WafRule("SqlInjection", "Time-based", "High", _rx(r"\b(sleep|benchmark|pg_sleep|waitfor\s+delay)\s*\(")),
    WafRule("SqlInjection", "information_schema", "High", _rx(r"information_schema|\bdrop\b\s+\btable\b|\binsert\b\s+\binto\b")),
    # XSS
    WafRule("Xss", "<script>", "High", _rx(r"<\s*script\b")),
    WafRule("Xss", "event handler", "Medium", _rx(r"\bon(error|load|click|mouseover)\s*=")),
    WafRule("Xss", "javascript: URI", "Medium", _rx(r"javascript:\s*\w")),
    WafRule("Xss", "iframe/svg/img onload", "Medium", _rx(r"<\s*(iframe|svg|img)\b[^>]*on\w+\s*=")),
    WafRule("Xss", "document.cookie", "Medium", _rx(r"document\s*\.\s*cookie")),
    # Path Traversal
    WafRule("PathTraversal", "../ traversal", "High", _rx(r"(\.\./|\.\.\\|%2e%2e%2f|%2e%2e/|%252e%252e)")),
    WafRule("PathTraversal", "sensitive file", "High", _rx(r"(/etc/passwd|/etc/shadow|c:\\windows|boot\.ini|win\.ini)")),
    # Command Injection
    WafRule("CommandInjection", "shell chain", "High", _rx(r"(;|\||&&)\s*(cat|ls|id|whoami|wget|curl|nc|bash|sh|rm|chmod|ping)\b")),
    WafRule("CommandInjection", "command substitution", "High", _rx(r"\$\([^)]+\)|`[^`]+`")),
    # Scanner probes
    WafRule("ScannerProbe", "config/secret probe", "Medium", _rx(r"(/\.env|/\.git/|/\.aws/|/\.ssh/|/config\.php|/wp-config)"), target="path"),
    WafRule("ScannerProbe", "CMS/admin probe", "Low", _rx(r"(/wp-login|/wp-admin|/xmlrpc\.php|/phpmyadmin|/administrator/|/boaform|/owa/)"), target="path"),
    WafRule("ScannerProbe", "PHP probe", "Low", _rx(r"\.(php|asp|jsp|cgi)(\?|$)"), target="path"),
    # Bad user agents
    WafRule("BadUserAgent", "attack tool", "High", _rx(r"(sqlmap|nikto|nmap|masscan|acunetix|nessus|dirbuster|gobuster|wpscan|hydra|metasploit|zgrab|nuclei|fuzzer)"), target="ua"),
]

_CATEGORY_CONFIG_KEY = {
    "SqlInjection": "rule_sql_injection",
    "Xss": "rule_xss",
    "PathTraversal": "rule_path_traversal",
    "CommandInjection": "rule_command_injection",
    "BadUserAgent": "rule_bad_user_agent",
    "ScannerProbe": "rule_scanner_probe",
}

CATEGORY_LABELS = {
    "SqlInjection": "SQL Injection",
    "Xss": "Cross-Site Scripting",
    "PathTraversal": "Path Traversal",
    "CommandInjection": "Command Injection",
    "BadUserAgent": "Malicious User-Agent",
    "ScannerProbe": "Scanner/Probe",
}


def category_enabled(category: str, cfg: dict[str, Any]) -> bool:
    key = _CATEGORY_CONFIG_KEY.get(category)
    return bool(cfg.get(key, True)) if key else True


@dataclass
class WafInspectResult:
    matched: bool = False
    category: str = ""
    rule_name: str = ""
    severity: str = "Medium"
    sample: str | None = None


@dataclass
class WafIpRule:
    ip: str
    kind: str  # "Block" | "Allow"
    reason: str | None = None
    expires_at: float | None = None  # unix timestamp, None = permanent
    auto: bool = False
    hits: int = 0

    @property
    def is_active(self) -> bool:
        return self.expires_at is None or self.expires_at > time.time()

    def to_dict(self) -> dict:
        return {
            "ip": self.ip, "kind": self.kind, "reason": self.reason,
            "expires_at": self.expires_at, "auto": self.auto, "hits": self.hits,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WafIpRule":
        return cls(
            ip=d["ip"], kind=d.get("kind", "Block"), reason=d.get("reason"),
            expires_at=d.get("expires_at"), auto=d.get("auto", False), hits=d.get("hits", 0),
        )


@dataclass
class WafEvent:
    ip: str
    method: str
    path: str
    query: str | None
    user_agent: str | None
    category: str
    rule_name: str
    matched_sample: str | None
    action: str  # "Detected" | "Blocked"
    severity: str = "Medium"
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "ts": self.ts, "ip": self.ip, "method": self.method, "path": self.path,
            "query": self.query, "user_agent": self.user_agent, "category": self.category,
            "rule_name": self.rule_name, "matched_sample": self.matched_sample,
            "action": self.action, "severity": self.severity,
        }


@dataclass
class WafDecision:
    allowed: bool
    blocked: bool = False
    banned_now: bool = False
    reason: str = ""
    category: str = ""
    rule_name: str = ""
    severity: str = "Medium"


def inspect(target_url: str, user_agent: str | None, cfg: dict[str, Any]) -> WafInspectResult:
    """Scans *target_url* (path+query, ideally both raw and url-decoded joined by
    a space) and *user_agent* against every enabled rule, returning the first
    match — mirrors WafService.Inspect in the C# original."""
    ua = user_agent or ""
    for rule in WAF_RULES:
        if not category_enabled(rule.category, cfg):
            continue
        haystack = ua if rule.target == "ua" else target_url
        if not haystack:
            continue
        m = rule.pattern.search(haystack)
        if m:
            sample = m.group(0)
            if len(sample) > 120:
                sample = sample[:120]
            return WafInspectResult(True, rule.category, rule.name, rule.severity, sample)
    return WafInspectResult(False)


class WafEngine:
    """Stateful WAF/firewall engine: IP allow/block list (persisted JSON), event
    log (persisted JSONL, mirrors SavingsLedger's append-only pattern), auto-ban,
    and an in-memory sliding-window rate limiter. One instance per process is
    enough (see `get_waf_engine()`); the IP-rules file is the only state shared
    across processes, and it's small enough to read-and-rewrite on every change."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = _storage_dir(directory)
        self._ip_rules_path = self._dir / _IP_RULES_FILE
        self._events_path = self._dir / _EVENTS_FILE
        self._lock = threading.Lock()
        self._log_counter = 0
        # ip -> list of request timestamps in the current window (rate limiter,
        # in-memory only — a restart resets it, which is fine for a soft limit).
        self._rate_window: dict[str, list[float]] = {}

    # ── IP rules ─────────────────────────────────────────────────────────────

    def _load_ip_rules(self) -> list[WafIpRule]:
        if not self._ip_rules_path.exists():
            return []
        try:
            with open(self._ip_rules_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return [WafIpRule.from_dict(d) for d in data]
        except (OSError, json.JSONDecodeError, KeyError):
            return []

    def _save_ip_rules(self, rules: list[WafIpRule]) -> None:
        tmp = self._ip_rules_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump([r.to_dict() for r in rules], fh, indent=2, ensure_ascii=False)
        os.replace(tmp, self._ip_rules_path)

    def list_ip_rules(self) -> list[WafIpRule]:
        return self._load_ip_rules()

    def is_allowlisted(self, ip: str) -> bool:
        return any(r.kind == "Allow" and r.ip == ip and r.is_active for r in self._load_ip_rules())

    def get_active_block(self, ip: str) -> WafIpRule | None:
        for r in self._load_ip_rules():
            if r.kind == "Block" and r.ip == ip and r.is_active:
                return r
        return None

    def add_ip_rule(self, ip: str, kind: str, reason: str | None = None,
                     minutes: int | None = None, auto: bool = False) -> None:
        ip = (ip or "").strip()
        if not ip:
            return
        with self._lock:
            rules = [r for r in self._load_ip_rules() if not (r.ip == ip and r.kind == kind)]
            expires_at = time.time() + minutes * 60 if minutes and minutes > 0 else None
            rules.append(WafIpRule(ip=ip, kind=kind, reason=reason, expires_at=expires_at, auto=auto))
            self._save_ip_rules(rules)

    def delete_ip_rule(self, ip: str, kind: str) -> None:
        with self._lock:
            rules = [r for r in self._load_ip_rules() if not (r.ip == ip and r.kind == kind)]
            self._save_ip_rules(rules)

    # ── detection ────────────────────────────────────────────────────────────

    def inspect(self, target_url: str, user_agent: str | None, cfg: dict[str, Any]) -> WafInspectResult:
        return inspect(target_url, user_agent, cfg)

    # ── events ───────────────────────────────────────────────────────────────

    def log_event(self, event: WafEvent, retention_days: int = 30) -> None:
        try:
            append_line(self._events_path, (json.dumps(event.to_dict(), ensure_ascii=False) + "\n").encode("utf-8"))
        except OSError:
            return
        self._log_counter += 1
        if self._log_counter % 50 == 0:
            self._trim(retention_days)

    def all_events(self, limit: int = 200, since_days: float | None = None) -> list[dict]:
        events = self._load_events()
        if since_days is not None:
            cutoff = time.time() - since_days * 86400
            events = [e for e in events if _event_ts(e) >= cutoff]
        events.sort(key=lambda e: e.get("ts", ""), reverse=True)
        return events[:limit]

    def _load_events(self) -> list[dict]:
        if not self._events_path.exists():
            return []
        out: list[dict] = []
        try:
            with open(self._events_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []
        return out

    def _trim(self, retention_days: int) -> None:
        cutoff = time.time() - max(1, retention_days) * 86400
        events = [e for e in self._load_events() if _event_ts(e) >= cutoff]
        if len(events) > _EVENTS_CAP:
            events.sort(key=lambda e: e.get("ts", ""))
            events = events[-_EVENTS_CAP:]
        tmp = self._events_path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for e in events:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        os.replace(tmp, self._events_path)

    # ── auto-ban ─────────────────────────────────────────────────────────────

    def register_offense(self, ip: str, cfg: dict[str, Any]) -> bool:
        """Bans *ip* if it has exceeded the violation threshold within the
        configured window. The triggering event must already be logged before
        calling this (mirrors RegisterOffense in the C# original, which counts
        the just-logged event as part of the total)."""
        if not cfg.get("auto_ban_enabled", True) or not ip:
            return False
        if self.get_active_block(ip) is not None:
            return False
        window_minutes = cfg.get("auto_ban_window_minutes", 10)
        cutoff = time.time() - max(1, window_minutes) * 60
        count = sum(
            1 for e in self._load_events()
            if e.get("ip") == ip and _event_ts(e) >= cutoff
            and e.get("category") not in ("AutoBan", "IpBlock", "RateLimit")
            and e.get("action") in ("Detected", "Blocked")
        )
        threshold = cfg.get("auto_ban_threshold", 8)
        if count >= threshold:
            self.add_ip_rule(
                ip, "Block", f"Auto-ban: {count} violations in {window_minutes} min",
                cfg.get("auto_ban_duration_minutes", 120), auto=True,
            )
            return True
        return False

    # ── rate limiter (firewall layer) ───────────────────────────────────────

    def check_rate_limit(self, ip: str, cfg: dict[str, Any]) -> bool:
        """Returns True if *ip* has just exceeded its requests-per-minute budget
        (and should be banned) — in-memory sliding window, not persisted (a soft
        limit that resets on restart is an acceptable trade-off for this use
        case; it does not need to survive process restarts to be useful)."""
        if not cfg.get("rate_limit_enabled", True) or not ip:
            return False
        limit = cfg.get("rate_limit_requests_per_minute", 120)
        now = time.time()
        with self._lock:
            window = self._rate_window.setdefault(ip, [])
            window.append(now)
            cutoff = now - 60
            window[:] = [t for t in window if t >= cutoff]
            if len(window) > limit:
                return True
        return False

    # ── unified gate ─────────────────────────────────────────────────────────

    def gate(
        self, ip: str, method: str, path: str, query: str, user_agent: str | None,
        body: str, cfg: dict[str, Any],
    ) -> WafDecision:
        """Single entry point combining allow/blocklist, rate limiting, and
        pattern inspection — the one call any network-facing component should
        make (dashboard today; any future network transport for the MCP server
        calls the same method, see module docstring)."""
        if not cfg.get("enabled", True):
            return WafDecision(allowed=True)

        if ip and self.is_allowlisted(ip):
            return WafDecision(allowed=True)

        block_mode = bool(cfg.get("block_mode", False))

        if ip:
            active_block = self.get_active_block(ip)
            if active_block is not None:
                if block_mode:
                    self.log_event(WafEvent(ip, method, path, query, user_agent,
                                             "IpBlock", "IP in blocklist", None, "Blocked", "High"),
                                    cfg.get("log_retention_days", 30))
                    return WafDecision(allowed=False, blocked=True, reason=active_block.reason or "IP blocked")
                # Detect-only: an active block exists but we don't enforce it.

        if ip and self.check_rate_limit(ip, cfg):
            self.add_ip_rule(ip, "Block", "Rate limit exceeded", cfg.get("rate_limit_ban_minutes", 15), auto=True)
            self.log_event(WafEvent(ip, method, path, query, user_agent,
                                     "RateLimit", "Requests per minute exceeded", None,
                                     "Blocked" if block_mode else "Detected", "Medium"),
                            cfg.get("log_retention_days", 30))
            if block_mode:
                return WafDecision(allowed=False, blocked=True, banned_now=True, reason="Rate limit exceeded",
                                    category="RateLimit", severity="Medium")

        raw = f"{path} {query}".strip()
        try:
            from urllib.parse import unquote
            decoded = unquote(raw)
        except Exception:
            decoded = raw
        target = f"{raw} {decoded}"

        result = self.inspect(target, user_agent, cfg)
        if not result.matched and cfg.get("inspect_body", False) and body:
            result = self.inspect(body, user_agent, cfg)

        if result.matched:
            action = "Blocked" if block_mode else "Detected"
            self.log_event(
                WafEvent(ip, method, path, query, user_agent, result.category, result.rule_name,
                         result.sample, action, result.severity),
                cfg.get("log_retention_days", 30),
            )
            banned = self.register_offense(ip, cfg) if ip else False
            if banned:
                self.log_event(
                    WafEvent(ip, method, path, query, user_agent, "AutoBan",
                             "Auto-ban threshold exceeded", None, action, "High"),
                    cfg.get("log_retention_days", 30),
                )
            if block_mode:
                return WafDecision(
                    allowed=False, blocked=True, banned_now=banned, reason=result.rule_name,
                    category=result.category, rule_name=result.rule_name, severity=result.severity,
                )

        return WafDecision(allowed=True)


def _event_ts(event: dict) -> float:
    try:
        return datetime.fromisoformat(event["ts"]).timestamp()
    except (KeyError, ValueError, TypeError):
        return 0.0


_engine: WafEngine | None = None
_engine_lock = threading.Lock()


def get_waf_engine() -> WafEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = WafEngine()
    return _engine
