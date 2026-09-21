# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Per-agent-type guardrail policy engine.

EnterpriseGuard answers "is this content/path forbidden for anyone?". This
module answers the narrower question "is this tool call acceptable *for this
kind of agent*?" — a `terraform apply` is routine for an ops agent and
nonsense for a support agent, and a refund of $5000 means something only to
the latter.

Three things here do not exist anywhere else in Synthelion:

* **Agent profiles.** A named rule pack per agent type (dev, support, rag,
  data, ops, browser), each stacked on a baseline that applies to every agent.
* **Gating.** EnterpriseGuard is binary allow/block. Several requirements ask
  for "require explicit approval" instead, which is a third outcome: the call
  is legitimate but a human has to authorise it (force push, `terraform apply`,
  IAM escalation, a large export, a refund over the threshold).
* **Chain breaking.** Some attacks are invisible one call at a time and only
  exist as a *sequence* — read something private, then send it outward. The
  chain breaker correlates those steps within a session and cuts the second
  one, even though neither call is forbidden on its own.

What it deliberately does NOT reimplement, delegating instead:
  credentials/secrets and protected paths -> `enterprise_guard`
  SSRF / metadata endpoints              -> `ssrf_guard`
  runaway loops                          -> `loop_guard`
  PII masking                            -> `privacy_analyzer`
  spend caps                             -> proxy `_BudgetTracker` / enterprise quotas

Every rule carries the requirement id it implements, so a decision can always
be traced back to the spec it came from.
"""
from __future__ import annotations

import fnmatch
import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from synthelion.analytics._atomic_append import append_line

# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

BASE = "base"
DEV = "dev"
SUPPORT = "support"
RAG = "rag"
DATA = "data"
OPS = "ops"
BROWSER = "browser"

PROFILES: tuple[str, ...] = (BASE, DEV, SUPPORT, RAG, DATA, OPS, BROWSER)

PROFILE_LABELS: dict[str, str] = {
    BASE: "Baseline (all agents)",
    DEV: "Coding / Dev agent",
    SUPPORT: "Customer-support agent",
    RAG: "RAG / Research assistant",
    DATA: "Data-analytics agent",
    OPS: "DevOps / Ops agent",
    BROWSER: "Browser / Computer-use agent",
}


class Verdict(Enum):
    ALLOW = "allow"
    GATE = "gate"      # legitimate, but needs explicit human approval
    BLOCK = "block"


@dataclass(frozen=True)
class PolicyDecision:
    verdict: Verdict
    requirement: str | None = None   # e.g. "REQ-DEV-02"
    rule_name: str | None = None
    reason: str | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "requirement": self.requirement,
            "rule_name": self.rule_name,
            "reason": self.reason,
        }


_ALLOW = PolicyDecision(Verdict.ALLOW)


@dataclass(frozen=True)
class Rule:
    """One guardrail. `pattern` is matched against the *text* of a tool call —
    its command string, URL, SQL or typed input, depending on the tool."""
    requirement: str
    name: str
    pattern: re.Pattern
    verdict: Verdict
    reason: str


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Rule packs
#
# Kept as data, not code, so the set a profile enforces is inspectable (the
# dashboard lists them) and a new requirement is one row rather than a branch.
# ---------------------------------------------------------------------------

_BASE_RULES: tuple[Rule, ...] = (
    # REQ-BASE-02 — destructive shell and secret-file reads. EnterpriseGuard
    # already blocks reading a protected *path*; these catch the shell forms
    # that never name one directly.
    Rule("REQ-BASE-02", "recursive delete", _rx(r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+/?\S*"),
         Verdict.BLOCK, "Recursive delete is blocked for every agent profile."),
    Rule("REQ-BASE-02", "disk overwrite", _rx(r"\b(mkfs|dd)\b[^|;]*\bof=/dev/"),
         Verdict.BLOCK, "Writing directly to a block device is blocked."),
    Rule("REQ-BASE-02", "remote script piped to shell", _rx(r"\b(curl|wget)\b[^|;]*\|\s*(sudo\s+)?(ba)?sh"),
         Verdict.BLOCK, "Piping a downloaded script straight into a shell is blocked."),
    Rule("REQ-BASE-02", "history/credential file read", _rx(r"\b(cat|less|more|head|tail|type)\b[^|;]*(\.bash_history|\.zsh_history|shadow|id_rsa|\.aws/credentials)"),
         Verdict.BLOCK, "Reading credential or shell-history files is blocked."),
)

_DEV_RULES: tuple[Rule, ...] = (
    # REQ-DEV-02 — force push is legitimate but destructive: gate, don't block.
    Rule("REQ-DEV-02", "git force push", _rx(r"\bgit\s+push\b[^|;]*(--force\b(?!-with-lease)|(?<![\w-])-f(?![\w-]))"),
         Verdict.GATE, "Force push rewrites published history — explicit approval required."),
    Rule("REQ-DEV-02", "git history rewrite", _rx(r"\bgit\s+(reset\s+--hard|rebase\b[^|;]*--root|filter-branch|filter-repo)\b"),
         Verdict.GATE, "Rewriting git history requires explicit approval."),
    Rule("REQ-DEV-01", "branch deletion on remote", _rx(r"\bgit\s+push\b[^|;]*(--delete|:\s*\w)"),
         Verdict.GATE, "Deleting a remote branch requires explicit approval."),
    # REQ-DEV-03 — private issue content leaving through a public PR.
    Rule("REQ-DEV-03", "public PR from private issue", _rx(r"\bgh\s+pr\s+create\b[^|;]*(--public|--repo\s+\S+)"),
         Verdict.GATE, "Opening a PR on another repo can carry internal context outward — approval required."),
)

_SUPPORT_RULES: tuple[Rule, ...] = (
    # REQ-SUPP-03 — bulk export and access-changing actions.
    Rule("REQ-SUPP-03", "bulk customer export", _rx(r"\b(export|download)\b[^|;]*\b(all_customers|customers|users)\b[^|;]*\b(csv|json|xlsx|dump)\b"),
         Verdict.GATE, "Bulk customer export requires explicit approval."),
    Rule("REQ-SUPP-03", "account access change", _rx(r"\b(reset_password|change_email|disable_2fa|disable_mfa|transfer_ownership)\b"),
         Verdict.GATE, "Changing a customer's account access requires explicit approval."),
)

_RAG_RULES: tuple[Rule, ...] = (
    # REQ-RAG-01 — only http/https may be fetched. Non-http schemes reach
    # local files and services that a web-fetching agent has no business in.
    Rule("REQ-RAG-01", "non-http scheme", _rx(r"\b(file|ftp|gopher|dict|ldap|tftp|jar|netdoc)://"),
         Verdict.BLOCK, "Only http:// and https:// may be fetched."),
)

_DATA_RULES: tuple[Rule, ...] = (
    # REQ-DATA-01 — destructive DDL is never routine for an analytics agent.
    Rule("REQ-DATA-01", "destructive DDL", _rx(r"\b(drop\s+(table|database|schema)|truncate\s+table)\b"),
         Verdict.BLOCK, "DROP/TRUNCATE is blocked for analytics agents."),
    Rule("REQ-DATA-01", "credential table read", _rx(r"\bfrom\s+\W?(users?_credentials|credentials|secrets|api_keys|auth_tokens|passwords)\W?\b"),
         Verdict.BLOCK, "Reading credential tables is blocked."),
    # REQ-DATA-02 — writes and large exports are legitimate but need a human.
    Rule("REQ-DATA-02", "unscoped delete/update", _rx(r"\b(delete\s+from|update)\s+\w+(?![\s\S]*\bwhere\b)"),
         Verdict.GATE, "A DELETE/UPDATE without a WHERE clause requires explicit approval."),
    Rule("REQ-DATA-02", "scoped delete/update", _rx(r"\b(delete\s+from|update)\s+\w+[\s\S]*\bwhere\b"),
         Verdict.GATE, "Data modification requires explicit approval."),
)

_OPS_RULES: tuple[Rule, ...] = (
    # REQ-OPS-01 — infrastructure destruction.
    Rule("REQ-OPS-01", "terraform destroy", _rx(r"\bterraform\s+destroy\b"),
         Verdict.BLOCK, "Destroying infrastructure is blocked."),
    Rule("REQ-OPS-01", "kubernetes mass delete", _rx(r"\bkubectl\s+delete\b[^|;]*(--all\b|\bnamespace\b)"),
         Verdict.BLOCK, "Deleting a namespace or all resources is blocked."),
    Rule("REQ-OPS-01", "cloud resource deletion", _rx(r"\b(aws|az|gcloud)\b[^|;]*\b(delete|destroy|terminate|rm)\b"),
         Verdict.GATE, "Deleting a cloud resource requires explicit approval."),
    # REQ-OPS-02 — apply, IAM escalation, production secrets.
    Rule("REQ-OPS-02", "terraform apply", _rx(r"\bterraform\s+apply\b"),
         Verdict.GATE, "`terraform apply` changes live infrastructure — approval required."),
    Rule("REQ-OPS-02", "IAM escalation", _rx(r"\b(attach-(role|user)-policy|add-iam-policy-binding|create-role-binding|AdministratorAccess|roles/owner)\b"),
         Verdict.GATE, "Granting IAM privileges requires explicit approval."),
    Rule("REQ-OPS-02", "production secret read", _rx(r"\b(vault\s+(kv\s+)?get|secretsmanager\s+get-secret-value|kubectl\s+get\s+secret)\b"),
         Verdict.GATE, "Reading a production secret requires explicit approval."),
)

_BROWSER_RULES: tuple[Rule, ...] = (
    # REQ-BROWSER-01 — the agent must never handle credentials or session state.
    Rule("REQ-BROWSER-01", "browser storage read", _rx(r"\b(document\.cookie|localStorage|sessionStorage|indexedDB)\b"),
         Verdict.BLOCK, "Reading cookies or browser storage is blocked."),
    Rule("REQ-BROWSER-01", "credential typing", _rx(r"\b(password|passwd|otp|2fa|cvv|card[_\s-]?number)\b"),
         Verdict.BLOCK, "The agent must not type credentials — hand control to the user."),
    # REQ-BROWSER-02 — irreversible or financial UI actions.
    Rule("REQ-BROWSER-02", "financial/irreversible click", _rx(r"\b(place\s+order|confirm\s+payment|buy\s+now|pay\s+now|delete\s+account|transfer\s+funds|checkout)\b"),
         Verdict.GATE, "Financial or irreversible actions require explicit confirmation."),
)

RULE_PACKS: dict[str, tuple[Rule, ...]] = {
    BASE: _BASE_RULES,
    DEV: _DEV_RULES,
    SUPPORT: _SUPPORT_RULES,
    RAG: _RAG_RULES,
    DATA: _DATA_RULES,
    OPS: _OPS_RULES,
    BROWSER: _BROWSER_RULES,
}


def rules_for(profile: str) -> tuple[Rule, ...]:
    """Baseline rules plus the profile's own. An unknown profile still gets
    the baseline — failing open to *no* rules would be the wrong default."""
    return _BASE_RULES + RULE_PACKS.get(profile, ())


# ---------------------------------------------------------------------------
# Chain breaking (REQ-BASE-03, REQ-DEV-03, REQ-RAG-02, REQ-DATA-03)
# ---------------------------------------------------------------------------

_CHAIN_FILE = "agent_policy_chain.jsonl"
_CHAIN_TTL = 1800.0   # 30 min — an exfil chain spans one working session
_CHAIN_CAP = 5000

# Tool-name shapes that mean "this call read something private" and "this call
# sends data outward". Matched case-insensitively against the tool name.
_PRIVATE_READ_TOOLS = ("read", "retrieve", "search", "query", "fetch_document", "get_secret", "glob", "grep")
_EGRESS_TOOLS = ("webfetch", "web_fetch", "http", "post", "send", "email", "slack", "upload", "curl", "publish")


def _chain_path(directory: "Path | None" = None) -> Path:
    # Path.home() resolved per call, never cached at import — same rule as
    # loop_guard/ledger, so tests that monkeypatch it stay isolated.
    d = directory or (Path.home() / ".synthelion")
    d.mkdir(parents=True, exist_ok=True)
    return d / _CHAIN_FILE


def _read_chain(session_id: str, directory: "Path | None" = None) -> list[dict]:
    path = _chain_path(directory)
    if not path.exists():
        return []
    now = time.time()
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("session") != session_id:
                    continue
                if now - rec.get("ts", 0) > _CHAIN_TTL:
                    continue
                out.append(rec)
    except OSError:
        return []
    return out[-_CHAIN_CAP:]


def record_private_read(session_id: str, detail: str = "", directory: "Path | None" = None) -> None:
    """Mark that this session has read private/internal content.

    Append-only and cross-process on purpose: the agent's read may happen in
    an MCP server process and the egress attempt in a CLI hook process, so an
    in-memory flag would never see both halves of the chain.
    """
    try:
        append_line(
            _chain_path(directory),
            (json.dumps({"session": session_id, "ts": time.time(), "detail": detail[:120]},
                        ensure_ascii=False) + "\n").encode("utf-8"),
        )
    except OSError:
        pass


def reset_chain(session_id: str, directory: "Path | None" = None) -> None:
    """Clear a session's chain state (an approved, reviewed egress)."""
    try:
        append_line(
            _chain_path(directory),
            (json.dumps({"session": session_id, "ts": time.time(), "reset": True}) + "\n").encode("utf-8"),
        )
    except OSError:
        pass


def _chain_is_armed(session_id: str, directory: "Path | None" = None) -> bool:
    armed = False
    for rec in _read_chain(session_id, directory):
        if rec.get("reset"):
            armed = False
        else:
            armed = True
    return armed


def _is_tool(tool_name: str, needles: tuple[str, ...]) -> bool:
    name = (tool_name or "").lower()
    return any(n in name for n in needles)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_TEXT_ARG_NAMES = (
    "command", "cmd", "script", "query", "sql", "url", "uri", "text",
    "input", "value", "body", "prompt", "content", "selector", "action",
)


def _call_text(tool_input: dict) -> str:
    """Flatten the argument values a rule could plausibly match against."""
    parts: list[str] = []
    for key in _TEXT_ARG_NAMES:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    return "\n".join(parts)


@dataclass
class AgentPolicy:
    """Evaluates one agent profile's rule pack against a tool call."""
    profile: str = BASE
    enabled: bool = True
    gate_enabled: bool = True
    chain_breaker: bool = True
    refund_cap_usd: float = 100.0
    extra_blocked_tools: list[str] = field(default_factory=list)

    @classmethod
    def from_config(cls, profile: str | None = None) -> "AgentPolicy":
        from synthelion.config import load_config
        cfg = load_config().get("agent_policy", {})
        return cls(
            profile=profile or cfg.get("profile", BASE),
            enabled=cfg.get("enabled", True),
            gate_enabled=cfg.get("gate_enabled", True),
            chain_breaker=cfg.get("chain_breaker", True),
            refund_cap_usd=float(cfg.get("refund_cap_usd", 100.0)),
            extra_blocked_tools=list(cfg.get("blocked_tools", [])),
        )

    # -- individual checks ------------------------------------------------

    def _check_blocked_tool(self, tool_name: str) -> PolicyDecision | None:
        for pattern in self.extra_blocked_tools:
            if fnmatch.fnmatch((tool_name or "").lower(), pattern.lower()):
                return PolicyDecision(
                    Verdict.BLOCK, "REQ-BASE-02", "blocked tool",
                    f"Tool {tool_name!r} is blocked by policy.")
        return None

    def _check_rules(self, text: str) -> PolicyDecision | None:
        if not text:
            return None
        # Blocks win over gates regardless of declaration order, so a call that
        # trips both is refused rather than merely queued for approval.
        gated: PolicyDecision | None = None
        for rule in rules_for(self.profile):
            if not rule.pattern.search(text):
                continue
            if rule.verdict is Verdict.BLOCK:
                return PolicyDecision(Verdict.BLOCK, rule.requirement, rule.name, rule.reason)
            if gated is None:
                gated = PolicyDecision(Verdict.GATE, rule.requirement, rule.name, rule.reason)
        if gated and not self.gate_enabled:
            return None
        return gated

    def _check_refund(self, tool_name: str, tool_input: dict) -> PolicyDecision | None:
        """REQ-SUPP-02 — refunds above the cap need approval."""
        if self.profile != SUPPORT:
            return None
        if "refund" not in (tool_name or "").lower():
            return None
        amount = tool_input.get("amount") or tool_input.get("amount_usd") or tool_input.get("value")
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return None
        if amount > self.refund_cap_usd:
            return PolicyDecision(
                Verdict.GATE, "REQ-SUPP-02", "refund over cap",
                f"Refund of ${amount:,.2f} exceeds the ${self.refund_cap_usd:,.2f} auto-approval cap.")
        return None

    def _check_chain(self, tool_name: str, session_id: str, directory: "Path | None" = None) -> PolicyDecision | None:
        """Cut the second half of a read-private -> send-outward sequence."""
        if not self.chain_breaker or not session_id:
            return None
        if not _is_tool(tool_name, _EGRESS_TOOLS):
            return None
        if not _chain_is_armed(session_id, directory):
            return None
        return PolicyDecision(
            Verdict.BLOCK, "REQ-BASE-03", "exfiltration chain",
            "This session already read private content; sending data outward is blocked. "
            "Reset the chain explicitly if the egress has been reviewed.")

    # -- public API -------------------------------------------------------

    def check_tool_call(
        self,
        tool_name: str,
        tool_input: dict | None = None,
        session_id: str = "",
        directory: "Path | None" = None,
    ) -> PolicyDecision:
        if not self.enabled:
            return _ALLOW
        tool_input = tool_input or {}

        for decision in (
            self._check_blocked_tool(tool_name),
            self._check_chain(tool_name, session_id, directory),
            self._check_refund(tool_name, tool_input),
            self._check_rules(_call_text(tool_input)),
        ):
            if decision is not None:
                if decision.verdict is not Verdict.ALLOW:
                    _record_decision(decision, self.profile, tool_name)
                return decision

        # Allowed — but if it read private content, arm the chain breaker so a
        # later egress in the same session is caught.
        if self.chain_breaker and session_id and _is_tool(tool_name, _PRIVATE_READ_TOOLS):
            record_private_read(session_id, tool_name, directory)
        return _ALLOW


# ---------------------------------------------------------------------------
# Decision log — cross-process, same contract as enterprise_guard's events
# ---------------------------------------------------------------------------

_EVENTS_FILE = "agent_policy_events.jsonl"


def _events_path(directory: "Path | None" = None) -> Path:
    d = directory or (Path.home() / ".synthelion")
    d.mkdir(parents=True, exist_ok=True)
    return d / _EVENTS_FILE


def _record_decision(decision: PolicyDecision, profile: str, tool_name: str,
                     directory: "Path | None" = None) -> None:
    # Never persists the call's arguments — the log itself must not become a
    # place a secret or a customer's data ends up stored.
    event = {
        "timestamp": time.time(),
        "profile": profile,
        "tool": tool_name,
        "verdict": decision.verdict.value,
        "requirement": decision.requirement,
        "rule_name": decision.rule_name,
    }
    try:
        append_line(_events_path(directory), (json.dumps(event) + "\n").encode("utf-8"))
    except OSError:
        pass


def recent_decisions(limit: int = 100, directory: "Path | None" = None) -> list[dict]:
    path = _events_path(directory)
    if not path.exists():
        return []
    events: list[dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    events.sort(key=lambda e: e.get("timestamp", 0), reverse=True)
    return events[:limit]


def describe_profile(profile: str) -> dict:
    """Machine-readable view of what a profile enforces (dashboard/CLI)."""
    return {
        "profile": profile,
        "label": PROFILE_LABELS.get(profile, profile),
        "rules": [
            {
                "requirement": r.requirement,
                "name": r.name,
                "verdict": r.verdict.value,
                "reason": r.reason,
            }
            for r in rules_for(profile)
        ],
    }
