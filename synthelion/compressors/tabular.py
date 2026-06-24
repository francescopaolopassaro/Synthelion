# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import re

_ROW_SEP = re.compile(r"^\|[-: ]+\|[-| :]+$")


class TabularCompressor:
    """Prunes redundant columns from markdown tables.

    Ported from C# CavemanTabularCompressor. Drops columns where all data cells
    are identical or empty (zero information content).
    """

    def compress(self, table: str) -> tuple[str, bool]:
        """Return (compressed, was_compressed)."""
        if not table or "|" not in table:
            return table, False

        lines = [l for l in table.splitlines() if l.strip()]
        if len(lines) < 3:
            return table, False

        # Parse header, separator, rows
        header = _parse_row(lines[0])
        if not header:
            return table, False

        sep_idx = next((i for i, l in enumerate(lines[1:], 1) if _ROW_SEP.match(l.strip())), None)
        if sep_idx is None:
            return table, False

        data_lines = lines[sep_idx + 1 :]
        data_rows = [_parse_row(l) for l in data_lines]
        data_rows = [r for r in data_rows if r]

        if not data_rows:
            return table, False

        # Find columns with unique content
        n_cols = len(header)
        keep_cols = []
        for ci in range(n_cols):
            vals = {r[ci] if ci < len(r) else "" for r in data_rows}
            if len(vals) > 1 or (len(vals) == 1 and next(iter(vals)).strip()):
                keep_cols.append(ci)

        if len(keep_cols) == n_cols:
            return table, False

        def pick(row: list[str]) -> str:
            cells = [row[ci] if ci < len(row) else "" for ci in keep_cols]
            return "| " + " | ".join(cells) + " |"

        out_lines = [pick(header)]
        out_lines.append("| " + " | ".join("---" for _ in keep_cols) + " |")
        for row in data_rows:
            out_lines.append(pick(row))

        return "\n".join(out_lines), True


def _parse_row(line: str) -> list[str]:
    line = line.strip()
    if not line.startswith("|"):
        return []
    cells = line.split("|")[1:-1]
    return [c.strip() for c in cells]
