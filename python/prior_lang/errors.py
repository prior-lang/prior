"""Compile errors with the line-precise, suggestion-bearing contract from SPEC.md §7.

Every PriorError carries: the line/column, the offending source line, a
message in trader language, and (where we can) a concrete suggestion.
"""

from __future__ import annotations


class PriorError(Exception):
    def __init__(
        self,
        message: str,
        line: int | None = None,
        col: int | None = None,
        source_line: str | None = None,
        suggestion: str | None = None,
    ):
        self.message = message
        self.line = line
        self.col = col
        self.source_line = source_line
        self.suggestion = suggestion
        super().__init__(self.render())

    def render(self) -> str:
        parts = []
        loc = f"line {self.line}: " if self.line is not None else ""
        parts.append(f"{loc}{self.message}")
        if self.source_line is not None:
            parts.append(f"    {self.source_line.rstrip()}")
            if self.col is not None:
                parts.append("    " + " " * self.col + "^")
        if self.suggestion:
            parts.append(self.suggestion)
        return "\n".join(parts)

    def __str__(self) -> str:  # pragma: no cover - render tested directly
        return self.render()
