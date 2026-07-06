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
    if tag.timeframe:
        parts.append(f"on {tag.timeframe}")
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

    if prog.rank_select is not None:
        if prog.rebalance:
            setup.append(f"rebalance {prog.rebalance}")
            blocks[-1] = "\n".join(setup)  # setup was already appended; refresh
        hold = f"hold {prog.rank_select} {int(prog.rank_count)} by {_tag(prog.rank_metric)}"
        if prog.rank_where_terms:
            joiner = " and " if prog.rank_where_logic == "all" else " or "
            hold += "\n  where " + joiner.join(_term(t) for t in prog.rank_where_terms)
        if prog.rank_weight_metric is not None:
            hold += f"\n  weighted by {_tag(prog.rank_weight_metric)}"
        blocks.append(hold)
        if prog.risk_tags:
            blocks.append("risk " + " ".join(_tag(t) for t in prog.risk_tags))
        return "\n\n".join(blocks) + "\n"

    default_action = "short" if prog.direction == "short" else "buy"
    rules = prog.rules or [{"logic": prog.entry_logic, "terms": prog.entry_terms,
                            "sizing": prog.sizing, "direction": prog.direction}]
    for rule in rules:
        action = "short" if rule.get("direction") == "short" else (
            default_action if prog.direction != "mixed" else "buy")
        joiner = " and " if rule["logic"] == "all" else " or "
        entry = "when " + joiner.join(_term(t) for t in rule["terms"])
        if rule["sizing"] is not None:
            entry += f"\n  {action} {_tag(rule['sizing'])}"
        blocks.append(entry)

    exit_kw = "cover" if prog.direction == "short" else "sell"
    if prog.partial_terms:
        p_lines = [f"{exit_kw} half when {_term(prog.partial_terms[0])}"]
        for t in prog.partial_terms[1:]:
            p_lines.append(f"  or {_term(t)}")
        blocks.append("\n".join(p_lines))
    if prog.exit_terms:
        kw = "sell" if prog.direction == "mixed" else exit_kw
        exit_lines = [f"{kw} when {_term(prog.exit_terms[0])}"]
        for t in prog.exit_terms[1:]:
            exit_lines.append(f"  or {_term(t)}")
        blocks.append("\n".join(exit_lines))
    if prog.exit_short_terms:
        exit_lines = [f"cover when {_term(prog.exit_short_terms[0])}"]
        for t in prog.exit_short_terms[1:]:
            exit_lines.append(f"  or {_term(t)}")
        blocks.append("\n".join(exit_lines))

    if prog.risk_tags:
        blocks.append("risk " + " ".join(_tag(t) for t in prog.risk_tags))

    return "\n\n".join(blocks) + "\n"
