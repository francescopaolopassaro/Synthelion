# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Advisory command-rewrite: for a small registry of known commands, suggests a less
verbose variant — same semantics and exit code, just less decorative output (banners,
pagers, audit/fund nags) — that a calling agent may choose to run instead.

Synthelion never executes anything itself anywhere in this codebase; this module is
no exception; `rewrite_command()` only ever returns a suggested string, never runs it.

Deliberately conservative like the rest of Synthelion's advisory tools: refuses to
rewrite anything that isn't a single, plain command — a composite shell expression
(`&&`, `|`, `;`, `` ` ``, `$()`, redirects, embedded newlines) could change meaning in
ways this module has no way to reason about, so those are left untouched.
"""
from __future__ import annotations

import re

_UNSAFE_RE = re.compile(r"\$\(|`|\||&&|;|>|<|\n")

# (prefix, flag to add, placement) — only flags that reduce decorative output
# without changing what the command does or its exit code.
#
# placement="after_git": `--no-pager` is a top-level git option, not a `log`/`show`/
# `diff` subcommand option — `git log --no-pager` is a *different, broken* command
# (git would treat it as an unknown option to `log`), so it must be inserted right
# after `git`, not appended at the end of the matched prefix.
# placement="after_prefix": npm/pip accept these flags anywhere after the
# subcommand, so appending right after the matched prefix is safe.
_REWRITE_RULES: tuple[tuple[str, str, str], ...] = (
    ("git log", "--no-pager", "after_git"),
    ("git show", "--no-pager", "after_git"),
    ("git diff", "--no-pager", "after_git"),
    ("npm install", "--no-fund --no-audit", "after_prefix"),
    ("npm ci", "--no-fund --no-audit", "after_prefix"),
    ("pip install", "--quiet", "after_prefix"),
)


def rewrite_command(command: str) -> tuple[str, bool]:
    """Returns (possibly rewritten command, whether it changed). Never rewrites a
    composite/non-attestable command (guard above) or one that already carries the
    flag; falls back to the input unchanged for anything not in the registry."""
    if not command:
        return command, False

    trimmed = command.strip()
    if _UNSAFE_RE.search(trimmed):
        return command, False

    for prefix, flag, placement in _REWRITE_RULES:
        if trimmed == prefix or trimmed.startswith(prefix + " "):
            if flag in trimmed:
                return command, False
            if placement == "after_git":
                rest = trimmed[len("git"):]  # keeps the leading space before the subcommand
                return f"git {flag}{rest}", True
            rest = trimmed[len(prefix):]
            return f"{prefix} {flag}{rest}", True

    return command, False
