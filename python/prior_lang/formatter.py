"""Canonical formatter: Program → .prior text.

Prints from the surface AST (what the author wrote, normalized) — never
from the desugared JSON, which would lose the human-facing forms. The
canon per SPEC.md §8: statement order strategy/universe/timeframe, blank
line, entry, blank line, exit, blank line, risk; two-space continuations;
lowercase keywords and tags; `if` becomes `when`; explicit params are
kept even when they equal defaults.
"""

from __future__ import annotations

from .parser import Comparison, Predicate, Program, TagNode


def _num(v: float) -> str:
    return str(int(v)) if float(v) == int(v) else f"{v:g}"


def _value(kind: str, v) -> str:
    if kind == "number":
        return _num(v)
    if kind == "percent":
        return f"{_num(v)}%"
    if kind == "dollar":
        return f"${_num(v)}"
    if kind == "mult":
        return f"{_num(v)}x"
    return str(v)


def _tag(tag: TagNode) -> str:
    if tag.name == "__pct_portfolio__":
        return f"[{_num(tag.params['value'])}% portfolio]"
    if tag.name == "__dollar__":
        return f"[${_num(tag.params['value'])}]"
    parts = [tag.name]
    for kind, v in tag.pos_raw:
        parts.append(_value(kind, v))
    for key, (kind, v) in tag.named_raw.items():
        parts.append(f"{key}={_value(kind, v)}")
    return "[" + " ".join(parts) + "]"


def _operand(op) -> str:
    if isinstance(op, TagNode):
        return _tag(op)
    if isinstance(op, tuple):
        if op[0] == "ticker":
            return f"${op[1]}"
        if op[0] == "number":
            return _num(op[1])
        return op[0]  # price | volume
    return str(op)


def _term(t) -> str:
    if isinstance(t, Predicate):
        return _tag(t.tag)
    if isinstance(t, TagNode):
        return _tag(t)
    assert isinstance(t, Comparison)
    cmp = t.cmp.replace("crosses_", "crosses ")
    return f"{_operand(t.left)} {cmp} {_operand(t.right)}"


def format_program(prog: Program) -> str:
    blocks: list[str] = []

    header: list[str] = []
    if prog.name:
        header.append(f'strategy "{prog.name}"')
    if header:
        blocks.append("\n".join(header))

    setup: list[str] = []
    if prog.universe_tag is not None:
        setup.append(f"universe {_tag(prog.universe_tag)}")
    elif prog.universe_tickers:
        setup.append("universe " + " ".join(f"${t}" for t in prog.universe_tickers))
    if prog.timeframe:
        setup.append(f"timeframe {prog.timeframe}")
    if setup:
        blocks.append("\n".join(setup))

    joiner = " and " if prog.entry_logic == "all" else " or "
    entry = "when " + joiner.join(_term(t) for t in prog.entry_terms)
    entry += f"\n  buy {_tag(prog.sizing)}" if prog.sizing else ""
    blocks.append(entry)

    exit_lines = [f"sell when {_term(prog.exit_terms[0])}"]
    for t in prog.exit_terms[1:]:
        exit_lines.append(f"  or {_term(t)}")
    blocks.append("\n".join(exit_lines))

    if prog.risk_tags:
        blocks.append("risk " + " ".join(_tag(t) for t in prog.risk_tags))

    return "\n\n".join(blocks) + "\n"
