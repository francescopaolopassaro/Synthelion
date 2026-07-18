# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re

import regex

_LINE_COMMENT = re.compile(r"(//|#)[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_HASH_BANG = re.compile(r"^#!")

# Matches a plausible function/method signature ending in an opening brace, capturing
# everything up to and including that brace so the body (found by brace-depth counting
# below, not regex — nesting can go arbitrarily deep) can be replaced with a placeholder.
# Intentionally conservative: control-flow blocks (if/for/while/switch/try) are excluded,
# since collapsing "if (x) { ... }" would remove branching logic, not implementation
# detail — this only targets declarations. Ported from Caveman C# 1.4.1.
_CSTYLE_SIGNATURE = regex.compile(
    r"^([ \t]*(?:public|private|protected|internal|static|async|virtual|override|abstract|"
    r"sealed|final|export|default|fn|func|pub)?[\w<>\[\],.?\s]*?\b"
    r"(?!if|for|while|switch|catch|using|lock|foreach)(\w+)\s*\(([^;{}]*)\)\s*"
    r"(?:where[^{]*)?\{)",
    regex.MULTILINE,
)

# "class" is deliberately excluded: it's a container, not implementation to hide (the
# C-style regex has the same property for free, since a class declaration has no
# parentheses to match) — only leaf "def" bodies get collapsed, so a class with several
# methods keeps every method signature instead of vanishing into a single "...".
_PYTHON_DEF_LINE = re.compile(r"^([ \t]*)(?:async\s+)?def\s+\w", re.MULTILINE)
_PYTHON_INDENT = re.compile(r"^([ \t]*)")


class CodeCompressor:
    """Strips comments and blank lines from source code.

    Ported from C# CavemanCodeCompressor. Detects language by syntax heuristics.
    Preserves shebangs. Does NOT strip string literals (safety).
    """

    def compress(self, code: str, skeletonize: bool = False) -> tuple[str, str, bool, int]:
        """Return (compressed, detected_language, was_compressed, functions_skeletonized).

        `skeletonize` (ported from Caveman C# 1.4.1, default off): an additional pass
        that replaces function/method bodies with a placeholder, keeping only
        signatures. Unlike the default comment-stripping pass (always a valid subset
        of the input), skeletonization is lossy by design and off by default — opt in
        when you want structure/signatures but not implementations.
        """
        if not code or not code.strip():
            return code, "", False, 0

        lang = _detect_lang(code)
        lines = code.splitlines()
        out: list[str] = []
        comments_removed = 0
        blanks_removed = 0

        if lang in ("python",):
            # Python: remove # comments (but not shebangs), remove blank lines
            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    blanks_removed += 1
                    continue
                if i == 0 and _HASH_BANG.match(line):
                    out.append(line)
                    continue
                # Remove inline # comments (naive — doesn't parse strings)
                clean = _LINE_COMMENT.sub("", line).rstrip()
                if not clean.strip():
                    comments_removed += 1
                    continue
                out.append(clean)
        else:
            # C-family, JS, TS, Java, etc.: remove // and /* */ comments
            # First pass: strip block comments
            code_no_blocks = _BLOCK_COMMENT.sub("", code)
            comments_removed += code.count("/*")
            for line in code_no_blocks.splitlines():
                stripped = line.strip()
                if not stripped:
                    blanks_removed += 1
                    continue
                clean = _LINE_COMMENT.sub("", line).rstrip()
                if not clean.strip():
                    comments_removed += 1
                    continue
                out.append(clean)

        result = "\n".join(out)
        functions_skeletonized = 0

        if skeletonize:
            if lang == "python":
                result, functions_skeletonized = _skeletonize_python(result)
            else:
                result, functions_skeletonized = _skeletonize_cstyle(result)

        return result, lang, result != code, functions_skeletonized

    @staticmethod
    def detect_language(code: str) -> str:
        return _detect_lang(code)


# ------------------------------------------------------------------
# Skeletonization (ported from Caveman C# 1.4.1)
# ------------------------------------------------------------------

def _find_matching_brace(s: str, open_idx: int) -> int:
    """Real brace-depth counting (not regex) — nesting can go arbitrarily deep, and a
    regex can't balance that. String/char literals are tracked so a brace inside a
    string (e.g. "{") is never mistaken for real code structure."""
    depth = 0
    in_string = in_char = False
    i = open_idx
    n = len(s)
    while i < n:
        c = s[i]
        if in_string:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_string = False
        elif in_char:
            if c == "\\":
                i += 2
                continue
            if c == "'":
                in_char = False
        elif c == '"':
            in_string = True
        elif c == "'":
            in_char = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _skeletonize_cstyle(code: str) -> tuple[str, int]:
    parts: list[str] = []
    pos = 0
    count = 0

    for m in _CSTYLE_SIGNATURE.finditer(code):
        if m.start() < pos:
            continue  # inside a body already collapsed above — skip
        open_idx = m.end() - 1  # the signature match ends in '{'
        close_idx = _find_matching_brace(code, open_idx)
        if close_idx < 0:
            continue  # unbalanced (or a false-positive match) — leave as-is
        if close_idx - open_idx - 1 < 40:
            continue  # trivial/near-empty body — nothing meaningful to collapse

        parts.append(code[pos:open_idx + 1])  # up to and including the opening '{'
        parts.append(" /* ... */ ")
        parts.append("}")
        pos = close_idx + 1
        count += 1

    parts.append(code[pos:])
    return "".join(parts), count


def _skeletonize_python(code: str) -> tuple[str, int]:
    lines = code.split("\n")
    result: list[str] = []
    count = 0
    i = 0
    n = len(lines)

    while i < n:
        if not _PYTHON_DEF_LINE.match(lines[i]):
            result.append(lines[i])
            i += 1
            continue

        def_indent = _PYTHON_INDENT.match(lines[i]).group(1)
        result.append(lines[i])
        j = i + 1
        body: list[str] = []
        while j < n:
            if not lines[j].strip():
                body.append(lines[j])
                j += 1
                continue
            line_indent = _PYTHON_INDENT.match(lines[j]).group(1)
            if len(line_indent) <= len(def_indent):
                break
            body.append(lines[j])
            j += 1

        # Only collapse a real multi-statement body — a one-liner isn't worth it.
        if sum(1 for line in body if line.strip()) >= 2:
            result.append(def_indent + "    ...")
            count += 1
        else:
            result.extend(body)
        i = j

    return "\n".join(result), count


def _detect_lang(code: str) -> str:
    lower = code[:500].lower()
    if "def " in lower or "import " in lower or "class " in lower and ":" in lower:
        if "public class" not in lower and "function " not in lower:
            return "python"
    if "public class" in lower or "private void" in lower or "namespace " in lower:
        return "csharp"
    if "function " in lower or "const " in lower or "=>" in lower:
        return "javascript"
    if "#include" in lower:
        return "cpp"
    if "package " in lower and "func " in lower:
        return "go"
    return "unknown"
