# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import os
import re
from dataclasses import dataclass

_CONVENTIONAL_TYPES = ("feat", "fix", "docs", "style", "refactor", "perf", "test", "chore", "ci")

_BREAKING_KEYWORDS = ("breaking", "breaking change", "major", "remove", "removed", "api change")

# Order matters: first match wins, mirroring the C# Dictionary insertion-order scan.
_TYPE_PATTERNS = (
    ("feat:", "feat"), ("feature:", "feat"), ("add", "feat"), ("new", "feat"), ("implement", "feat"),
    ("bug", "fix"), ("fix", "fix"), ("fixes", "fix"), ("fixed", "fix"), ("hotfix", "fix"), ("patch", "fix"),
    ("doc", "docs"), ("docs", "docs"), ("document", "docs"),
    ("style", "style"), ("format", "style"),
    ("refactor", "refactor"), ("refactoring", "refactor"),
    ("perf", "perf"), ("performance", "perf"), ("optimize", "perf"),
    ("test", "test"), ("tests", "test"),
    ("chore", "chore"), ("bump", "chore"), ("update dep", "chore"), ("upgrade", "chore"),
    ("ci", "ci"), ("pipeline", "ci"), ("build", "ci"),
)

_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "out", "off", "over",
    "under", "again", "further", "then", "once", "this", "that", "these",
    "those", "not", "or", "and", "but", "if", "because", "so", "than",
    "too", "very", "just", "also", "about", "now", "get", "got", "set",
})

_KEYWORD_RE = re.compile(r"\b[A-Z][a-z]+|[a-z]{3,}\b")


@dataclass
class CommitSuggestion:
    full_message: str = ""
    type: str = ""
    scope: str | None = None
    subject: str = ""

    @property
    def subject_length(self) -> int:
        return len(self.subject)


class CommitGenerator:
    """Generates ultra-compact conventional commit messages from git diffs.

    Ported from C# CavemanCommitGenerator. Pure text heuristics — no LLM call.
    """

    def generate_from_diff(self, diff_text: str) -> CommitSuggestion:
        if not diff_text or not diff_text.strip():
            return CommitSuggestion(full_message="chore: empty diff", type="chore", subject="empty diff")

        lines = [l for l in diff_text.split("\n") if l]
        file_paths: set[str] = set()
        added_lines: list[str] = []
        removed_lines: list[str] = []

        for line in lines:
            if line.startswith("+++ b/") or line.startswith("--- a/"):
                path = line[6:].strip()
                if path and path != "/dev/null":
                    file_paths.add(path)
            elif line.startswith("+") and not line.startswith("+++"):
                content = line[1:].strip()
                if content:
                    added_lines.append(content)
            elif line.startswith("-") and not line.startswith("---"):
                content = line[1:].strip()
                if content:
                    removed_lines.append(content)

        has_breaking = any(
            k in line.lower()
            for line in added_lines + removed_lines
            for k in _BREAKING_KEYWORDS
        )

        commit_type = self._detect_type(added_lines, removed_lines)
        scope = self._detect_scope(file_paths)
        subject = self._build_subject(commit_type, added_lines, removed_lines, file_paths)

        prefix = f"{commit_type}!" if has_breaking else commit_type
        scope_part = f"({scope})" if scope else ""
        full_message = f"{prefix}{scope_part}: {subject}" if has_breaking else f"{commit_type}{scope_part}: {subject}"

        if len(full_message) > 50 and len(subject) > 10:
            max_subject_len = 50 - (len(commit_type) + len(scope or "") + 4)
            if max_subject_len > 5 and len(subject) > max_subject_len:
                subject = subject[: max_subject_len - 1] + "…"
            full_message = f"{commit_type}{scope_part}: {subject}"

        return CommitSuggestion(full_message=full_message, type=commit_type, scope=scope, subject=subject)

    def _detect_type(self, added: list[str], removed: list[str]) -> str:
        all_content = " ".join(added + removed).lower()

        for pattern, commit_type in _TYPE_PATTERNS:
            if pattern in all_content:
                return commit_type

        if len(removed) > len(added):
            return "fix"

        return "feat"

    def _detect_scope(self, paths: set[str]) -> str | None:
        dirs = list(dict.fromkeys(
            p.replace("\\", "/").split("/")[0]
            for p in paths
            if p.replace("\\", "/").split("/")[0]
        ))

        if len(dirs) == 1:
            d = dirs[0]
            if len(d) > 15 or len(d) == 0:
                return None
            return d.rstrip(":")

        return None

    def _build_subject(self, commit_type: str, added: list[str], removed: list[str], files: set[str]) -> str:
        keywords: list[str] = []

        for line in added + removed:
            words = [
                w.lower() for w in _KEYWORD_RE.findall(line)
                if w.lower() not in _STOP_WORDS
            ][:3]
            keywords.extend(words)

        if not keywords:
            keywords = [
                os.path.splitext(os.path.basename(f))[0].lower()
                for f in list(files)[:2]
            ]

        unique = list(dict.fromkeys(keywords))[:5]
        if not unique:
            return "update project files"

        subject = " ".join(unique)

        if commit_type == "fix" and len(subject) > 3:
            subject = "handle " + subject

        if len(subject) > 45:
            subject = subject[:42] + "…"

        return subject
