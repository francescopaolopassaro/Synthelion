# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re

_LINE_COMMENT = re.compile(r"(//|#)[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_HASH_BANG = re.compile(r"^#!")


class CodeCompressor:
    """Strips comments and blank lines from source code.

    Ported from C# CavemanCodeCompressor. Detects language by syntax heuristics.
    Preserves shebangs. Does NOT strip string literals (safety).
    """

    def compress(self, code: str) -> tuple[str, str, bool]:
        """Return (compressed, detected_language, was_compressed)."""
        if not code or not code.strip():
            return code, "", False

        lang = _detect_lang(code)
        lines = code.splitlines()
        out: list[str] = []
        in_block = False
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
        return result, lang, result != code

    @staticmethod
    def detect_language(code: str) -> str:
        return _detect_lang(code)


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
