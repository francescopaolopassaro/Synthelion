# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Minimal regex-shape random sampler — devtools only, not shipped at runtime.

`privacy_rules.yaml`'s patterns are all *regular* in the classical sense
(literals, character classes, repetition, non-capturing groups, alternation)
and never use backreferences or lookaround — every pattern in the file was
checked by hand before relying on that. That is exactly the subset a small
recursive-descent sampler can generate from directly, which is what this module
does: parse the pattern once into a tiny AST, then draw random strings that
match its *shape*. It generates candidates for the checksum-guarded rules; the
real validator (`privacy_validators.py`) still has the only say on whether a
candidate is actually valid — this module only needs to get close enough that
brute-force retries find one quickly.
"""
from __future__ import annotations

import random
import re

# ---------------------------------------------------------------------------
# AST nodes — tuples, not classes: this stays a private one-file tool.
# ---------------------------------------------------------------------------
# ("lit", char)
# ("class", [(lo, hi), ...], negate: bool)
# ("any",)
# ("seq", [node, ...])
# ("alt", [node, ...])
# ("rep", node, min, max)

_CLASS_SHORTHAND = {
    "d": [("0", "9")],
    "w": [("a", "z"), ("A", "Z"), ("0", "9"), ("_", "_")],
    "s": [(" ", " "), ("\t", "\t")],
}


class _Parser:
    def __init__(self, pattern: str) -> None:
        # Inline flags like (?-i) at the very start don't change the shape —
        # drop them rather than teaching the parser to skip them mid-stream.
        self.s = re.sub(r"^\(\?-?[aiLmsux]+\)", "", pattern)
        self.i = 0
        self.n = len(self.s)

    def parse(self):
        node = self._alt()
        return node

    def _alt(self):
        branches = [self._seq()]
        while self._peek() == "|":
            self.i += 1
            branches.append(self._seq())
        return branches[0] if len(branches) == 1 else ("alt", branches)

    def _seq(self):
        parts = []
        while self.i < self.n and self._peek() not in "|)":
            parts.append(self._rep())
        return ("seq", parts)

    def _rep(self):
        atom = self._atom()
        c = self._peek()
        if c == "*":
            self.i += 1
            return ("rep", atom, 0, 6)
        if c == "+":
            self.i += 1
            return ("rep", atom, 1, 6)
        if c == "?":
            self.i += 1
            return ("rep", atom, 0, 1)
        if c == "{":
            j = self.s.index("}", self.i)
            spec = self.s[self.i + 1:j]
            self.i = j + 1
            if "," in spec:
                lo, hi = spec.split(",")
                lo = int(lo) if lo else 0
                hi = int(hi) if hi else lo + 6
            else:
                lo = hi = int(spec)
            return ("rep", atom, lo, hi)
        return atom

    def _atom(self):
        c = self._peek()
        if c == "(":
            self.i += 1
            if self.s[self.i:self.i + 2] == "?:":
                self.i += 2
            node = self._alt()
            if self._peek() == ")":
                self.i += 1
            return node
        if c == "[":
            return self._char_class()
        if c == "\\":
            self.i += 1
            esc = self.s[self.i]
            self.i += 1
            if esc in _CLASS_SHORTHAND:
                return ("class", _CLASS_SHORTHAND[esc], False)
            if esc == "b":
                return ("seq", [])       # zero-width — nothing to draw
            return ("lit", esc)          # escaped literal (\., \+, \-, ...)
        if c == "^" or c == "$":
            self.i += 1
            return ("seq", [])
        if c == ".":
            self.i += 1
            return ("any",)
        self.i += 1
        return ("lit", c)

    def _char_class(self) -> tuple:
        self.i += 1  # consume '['
        negate = False
        if self._peek() == "^":
            negate = True
            self.i += 1
        ranges: list[tuple[str, str]] = []
        while self.i < self.n and self.s[self.i] != "]":
            ch = self.s[self.i]
            if ch == "\\":
                self.i += 1
                esc = self.s[self.i]
                self.i += 1
                if esc in _CLASS_SHORTHAND:
                    ranges.extend(_CLASS_SHORTHAND[esc])
                else:
                    ranges.append((esc, esc))
                continue
            self.i += 1
            if self._peek() == "-" and self.i + 1 < self.n and self.s[self.i + 1] != "]":
                self.i += 1
                hi = self.s[self.i]
                if hi == "\\":
                    self.i += 1
                    hi = self.s[self.i]
                self.i += 1
                ranges.append((ch, hi))
            else:
                ranges.append((ch, ch))
        if self._peek() == "]":
            self.i += 1
        return ("class", ranges, negate)

    def _peek(self) -> str:
        return self.s[self.i] if self.i < self.n else ""


_PRINTABLE = [chr(c) for c in range(0x21, 0x7F)]


def _draw(node, rng: random.Random) -> str:
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "any":
        return rng.choice(_PRINTABLE)
    if kind == "class":
        _, ranges, negate = node
        if not negate:
            lo, hi = rng.choice(ranges)
            return chr(rng.randint(ord(lo), ord(hi)))
        excluded = set()
        for lo, hi in ranges:
            excluded.update(chr(c) for c in range(ord(lo), ord(hi) + 1))
        pool = [c for c in _PRINTABLE if c not in excluded]
        return rng.choice(pool) if pool else "x"
    if kind == "seq":
        return "".join(_draw(p, rng) for p in node[1])
    if kind == "alt":
        return _draw(rng.choice(node[1]), rng)
    if kind == "rep":
        _, atom, lo, hi = node
        count = rng.randint(lo, hi)
        return "".join(_draw(atom, rng) for _ in range(count))
    raise ValueError(f"unhandled node {node!r}")


class PatternSampler:
    """Compile once, draw many — parsing a pattern is the expensive part."""

    def __init__(self, pattern: str) -> None:
        self._ast = _Parser(pattern).parse()

    def sample(self, rng: random.Random) -> str:
        return _draw(self._ast, rng)


def generate_matching(
    pattern: str,
    validator,
    rng: random.Random,
    max_tries: int = 20_000,
) -> str | None:
    """Draw candidates until one satisfies `validator`, or give up.

    `validator=None` returns the first shape-matching draw unconditionally —
    correct for patterns with no checksum, where shape alone is the format.
    """
    sampler = PatternSampler(pattern)
    if validator is None:
        return sampler.sample(rng)
    for _ in range(max_tries):
        candidate = sampler.sample(rng)
        try:
            if validator(candidate):
                return candidate
        except Exception:  # noqa: BLE001 — a validator quirk must not abort generation
            continue
    return None
