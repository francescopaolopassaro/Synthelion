# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re
from dataclasses import dataclass, field

_BUG_PATTERNS = (
    "null", "nullptr", "null reference", "nullreference",
    "exception", "throw", "catch",
    "todo", "hack", "fixme", "xxx",
    "undefined", "undef",
    "memory leak", "deadlock",
    "infinite loop", "crash",
    "sqli", "xss", "injection", "exploit",
)

_SECURITY_PATTERNS = (
    "password", "secret", "token", "apikey", "api_key",
    "connectionstring", "connstring",
    "plaintext", "base64", "decrypt",
    "eval(", "exec(", "shell_exec",
)

_PERF_PATTERNS = (
    "for(", "foreach(", "while(", "n+1", "select *",
    "orderby", "sort", "distinct",
    "recursive", "iteration",
)

_FILE_RE = re.compile(r"^\+\+\+ b/(.+)")
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_VAR_NULL_RE = re.compile(r"^\s*var\s+\w+\s*=\s*null;?$")
_TRY_RE = re.compile(r"try\s*\{", re.IGNORECASE)


@dataclass
class ReviewComment:
    line: int
    severity: str = "info"
    emoji: str | None = None
    message: str = ""

    def __str__(self) -> str:
        return f"L{self.line}: {self.emoji} {self.severity}: {self.message}"


@dataclass
class ReviewResult:
    comments: list[ReviewComment] = field(default_factory=list)
    changed_files: int = 0
    additions: int = 0
    deletions: int = 0

    @property
    def total_issues(self) -> int:
        return len(self.comments)


def _extract_context(content: str, pattern: str) -> str:
    idx = content.lower().find(pattern.lower())
    if idx < 0:
        return pattern
    start = max(0, idx - 15)
    end = min(len(content), idx + len(pattern) + 15)
    ctx = content[start:end].strip()
    return ctx[:27] + "…" if len(ctx) > 30 else ctx


class ReviewService:
    """Generates single-line pull-request review comments from diffs.

    Ported from C# CavemanReviewService. Pure text-pattern heuristics — flags likely
    bugs, security-sensitive lines, perf-relevant constructs, and TODOs, one comment
    per changed line.
    """

    def review_diff(self, diff_text: str) -> ReviewResult:
        result = ReviewResult()
        if not diff_text or not diff_text.strip():
            return result

        lines = diff_text.split("\n")
        current_line = 0
        current_file = None
        in_hunk = False

        for line in lines:
            file_match = _FILE_RE.match(line)
            if file_match:
                current_file = file_match.group(1)
                result.changed_files += 1
                in_hunk = False
                continue

            hunk_match = _HUNK_RE.match(line)
            if hunk_match:
                current_line = int(hunk_match.group(1))
                in_hunk = True
                continue

            if not in_hunk:
                continue

            if line.startswith("+"):
                result.additions += 1
                content = line[1:]
                comment = self._analyze_line(current_line, content, current_file)
                if comment is not None:
                    result.comments.append(comment)
            elif line.startswith("-"):
                result.deletions += 1

            if line.startswith("+") or line.startswith("-") or line.startswith(" "):
                current_line += 1

        return result

    def _analyze_line(self, line: int, content: str, file: str | None) -> ReviewComment | None:
        content = content.strip()
        if not content:
            return None

        if len(content) > 200:
            return ReviewComment(line=line, severity="warning", emoji="\U0001f4c4",
                                  message=f"long line {len(content)}ch. Consider split.")

        low = content.lower()

        for pattern in _SECURITY_PATTERNS:
            if pattern in low:
                ctx = _extract_context(content, pattern)
                return ReviewComment(line=line, severity="critical", emoji="\U0001f6a8",
                                      message=f"security: possible {ctx} leak")

        for pattern in _BUG_PATTERNS:
            if pattern in low:
                if pattern in ("null", "nullptr"):
                    if not any(m in content for m in ("!=", "== null", "is null", "?.", "??")):
                        continue

                ctx = _extract_context(content, pattern)
                return ReviewComment(
                    line=line,
                    severity="info" if pattern == "todo" else "bug",
                    emoji="✅" if pattern == "todo" else "\U0001f534",
                    message=f"{pattern}: {ctx}",
                )

        for pattern in _PERF_PATTERNS:
            if pattern in low:
                ctx = _extract_context(content, pattern)
                return ReviewComment(line=line, severity="perf", emoji="⚡",
                                      message=f"perf: {ctx} may impact performance")

        if _VAR_NULL_RE.match(content):
            return ReviewComment(line=line, severity="warning", emoji="\U0001f6a7",
                                  message="var init null. Use default or nullable?")

        if _TRY_RE.search(content) and "catch" not in low and line > 0:
            return ReviewComment(line=line, severity="warning", emoji="\U0001f6a7",
                                  message="bare try without catch")

        if "todo" in low:
            todo = _extract_context(content, "todo")
            return ReviewComment(line=line, severity="info", emoji="✅", message=f"todo: {todo}")

        return None
