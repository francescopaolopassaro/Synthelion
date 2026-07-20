# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from synthelion.devtools.review_service import ReviewService

_SOURCE_EXTENSIONS = frozenset({
    ".cs", ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".rs",
    ".go", ".rb", ".php", ".swift", ".kt", ".scala", ".cpp", ".c", ".h",
})

_CLASS_RE = re.compile(r"\b(class|interface|struct|enum|record)\s+(\w+)")
_METHOD_RE = re.compile(
    r"(?:public|private|protected|internal|static|virtual|override|async|unsafe|\s)+"
    r"\s+(\w+(?:<[^>]+>)?)\s+(\w+)\s*\("
)
_DEF_RE = re.compile(r"^(func|def|function|sub)\s+(\w+)")
_PROP_RE = re.compile(
    r"(?:public|private|protected|internal|static|readonly)?\s*(\w+(?:<[^>]+>)?)\s+(\w+)\s*\{\s*(?:get|set)"
)
_RESERVED_NAMES = frozenset({"if", "while", "for", "foreach", "using"})

_SEVERITY_ICON = {"critical": "🔴", "bug": "🐛", "warning": "⚠️", "perf": "⚡"}


@dataclass
class CavecrewSymbol:
    name: str
    kind: str
    line: int


@dataclass
class CavecrewFileMap:
    file_path: str
    file_type: str
    symbols: list[CavecrewSymbol] = field(default_factory=list)


@dataclass
class CavecrewResult:
    agent: str = ""
    summary: str = ""
    details: list[str] = field(default_factory=list)


def _extract_symbols(content: str) -> list[CavecrewSymbol]:
    symbols: list[CavecrewSymbol] = []
    for i, raw_line in enumerate(content.split("\n")):
        line = raw_line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        line_num = i + 1

        m = _CLASS_RE.search(line)
        if m:
            symbols.append(CavecrewSymbol(name=m.group(2), kind=m.group(1), line=line_num))
            continue

        m = _METHOD_RE.search(line)
        if m and "class " not in line:
            name = m.group(2)
            if name not in _RESERVED_NAMES:
                symbols.append(CavecrewSymbol(name=name, kind="method", line=line_num))
                continue

        m = _DEF_RE.match(line)
        if m:
            symbols.append(CavecrewSymbol(name=m.group(2), kind=m.group(1), line=line_num))
            continue

        m = _PROP_RE.search(line)
        if m and len(m.group(2)) > 1:
            symbols.append(CavecrewSymbol(name=m.group(2), kind="property", line=line_num))

    return symbols


class CavecrewService:
    """Cavecrew micro-agents (investigator, builder, reviewer) for delegated code tasks.

    Ported from C# CavecrewService. Lightweight, regex-based symbol extraction and
    diff review — no LLM call, no external dependency.
    """

    def investigate(self, path: str) -> CavecrewResult:
        result = CavecrewResult(agent="cavecrew-investigator")

        if not os.path.isdir(path) and not os.path.isfile(path):
            result.summary = "Path not found"
            return result

        if os.path.isdir(path):
            files = []
            for root, _dirs, filenames in os.walk(path):
                for fname in filenames:
                    if os.path.splitext(fname)[1].lower() in _SOURCE_EXTENSIONS:
                        files.append(os.path.join(root, fname))
                    if len(files) >= 50:
                        break
                if len(files) >= 50:
                    break
        else:
            files = [path]

        file_maps: list[CavecrewFileMap] = []
        for file in files:
            try:
                with open(file, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except OSError:
                continue
            symbols = _extract_symbols(content)
            if symbols:
                file_maps.append(CavecrewFileMap(
                    file_path=file,
                    file_type=os.path.splitext(file)[1].lstrip("."),
                    symbols=symbols,
                ))

        total_symbols = sum(len(m.symbols) for m in file_maps)
        result.summary = f"Mapped {len(file_maps)} files, {total_symbols} symbols across {os.path.basename(path)}"

        result.details.append("Files:")
        for entry in sorted(file_maps, key=lambda m: m.file_path):
            kinds: dict[str, int] = {}
            for s in entry.symbols:
                kinds[s.kind] = kinds.get(s.kind, 0) + 1
            kinds_str = ", ".join(f"{count} {kind}" for kind, count in kinds.items())
            result.details.append(f"  {entry.file_path} [{kinds_str}]")
            for sym in entry.symbols[:5]:
                result.details.append(f"    L{sym.line:>5} {sym.kind:<10} {sym.name}")
            if len(entry.symbols) > 5:
                result.details.append(f"    ... +{len(entry.symbols) - 5} more")

        return result

    def build(self, description: str, files: list[str]) -> CavecrewResult:
        result = CavecrewResult(
            agent="cavecrew-builder",
            summary=f"Surgical change: {description}",
            details=[f"Files ({len(files)}):"],
        )

        keywords = {w.lower() for w in description.split() if len(w) > 3}

        for file in files:
            result.details.append(f"  {file}")
            if not os.path.isfile(file):
                result.details.append("    ⚠ File not found")
                continue

            try:
                with open(file, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except OSError as exc:
                result.details.append(f"    ⚠ Error: {exc}")
                continue

            symbols = _extract_symbols(content)
            if not symbols:
                continue

            relevant = [s for s in symbols if not keywords or any(k in s.name.lower() for k in keywords)]

            if relevant:
                result.details.append("    Related symbols:")
                for s in relevant:
                    result.details.append(f"      L{s.line} {s.kind} {s.name}")
            else:
                names = ", ".join(s.name for s in symbols[:3])
                result.details.append(f"    Symbols available: {names}")

        result.details.append(f"Suggested scope: {len(files)} file(s), {description}")
        return result

    def review(self, diff_text: str) -> CavecrewResult:
        result = CavecrewResult(agent="cavecrew-reviewer")

        if not diff_text or not diff_text.strip():
            result.summary = "No diff to analyze"
            result.details.append("Provide a git diff or patch text for analysis")
            return result

        review = ReviewService().review_diff(diff_text)

        result.summary = f"Reviewed diff: {review.changed_files} files, {review.total_issues} issues"
        result.details.append(f"Changes: +{review.additions} / -{review.deletions} across {review.changed_files} file(s)")
        result.details.append(f"Issues found: {review.total_issues}")

        for comment in review.comments[:20]:
            icon = _SEVERITY_ICON.get(comment.severity, "ℹ️")
            result.details.append(f"  {icon} {comment}")

        if review.total_issues > 20:
            result.details.append(f"  ... +{review.total_issues - 20} more issues")

        if review.total_issues == 0:
            result.details.append("  ✅ No issues detected")

        return result
