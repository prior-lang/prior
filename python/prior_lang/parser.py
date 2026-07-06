"""Parser: logical lines → Program → strategy JSON.

Recursive descent over the token stream from lexer.py. Parsing keeps the
surface AST (tags as written, comparisons as written) so the formatter can
round-trip; desugaring to registry conditions happens in to_json().

The v0.1 restriction on expressions: one rule combines its terms with all
`and` or all `or` — mixing requires parentheses semantics we deliberately
don't ship yet. Parenthesized groups parse, then flatten if homogeneous.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from .errors import PriorError
from .lexer import LogicalLine, Token, tokenize
from .tags import DOLLAR, MULT, NUMBER, PERCENT, TAGS, WORD, TagSpec

VERSION = "0.1"

_BOLLINGER = {"lower_bollinger": "lower", "middle_bollinger": "middle", "upper_bollinger": "upper"}
_PREDICATE_MAP = {
    "macd_cross_up": "macd_crosses_above_signal",
    "macd_cross_down": "macd_crosses_below_signal",
    "volatile": "atr_greater_than_pct",
    "quiet": "atr_less_than_pct",
    "volume_spike": "volume_greater_than_avg",
    "heavy_volume": "volume_in_top_pct",
}


# ── AST ────────────────────────────────────────────────────────────

@dataclass
class TagNode:
    name: str                      # spec name, or __pct_portfolio__ / __dollar__
    params: dict                   # resolved params (defaults filled)
    pos_raw: list = field(default_factory=list)    # surface positional (kind, value)
    named_raw: dict = field(default_factory=dict)  # surface named name → (kind, value)
    line: int = 0
    col: int = 0

    @property
    def spec(self) -> TagSpec | None:
        return TAGS.get(self.name)


@dataclass
class Comparison:
    left: object       # ('price',) ('volume',) ('ticker', sym) TagNode
    cmp: str           # at | above | below | crosses_above | crosses_below | < | > | <= | >=
    right: object      # TagNode | ('number', v)
    line: int = 0


@dataclass
class Predicate:
    tag: TagNode
    line: int = 0


@dataclass
class Program:
    name: str | None = None
    universe_tag: TagNode | None = None
    universe_tickers: list[str] = field(default_factory=list)
    timeframe: str | None = None
    entry_logic: str = "all"
    entry_terms: list = field(default_factory=list)
    sizing: TagNode | None = None
    exit_terms: list = field(default_factory=list)   # Comparison/Predicate/TagNode(exit)
    risk_tags: list[TagNode] = field(default_factory=list)
    scoped_ticker: str | None = None
    source_name: str = "<string>"

    def to_json(self) -> dict:
        entry_conditions = [_desugar(t) for t in self.entry_terms]

        exit_conditions = []
        stop = target = trailing = hold = None
        for t in self.exit_terms:
            if isinstance(t, TagNode):
                if t.name == "stop":
                    stop = t.params["value"]
                elif t.name == "target":
                    target = t.params["value"]
                elif t.name == "trailing":
                    trailing = t.params["value"]
                elif t.name == "after":
                    hold = int(t.params["bars"])
            else:
                exit_conditions.append(_desugar(t))

        if self.universe_tag is not None:
            universe = {"type": "prebuilt", "key": self.universe_tag.name}
        elif self.universe_tickers:
            universe = {"type": "manual", "tickers": list(self.universe_tickers)}
        else:
            universe = {"type": "manual", "tickers": [self.scoped_ticker]}

        sizing = None
        if self.sizing is not None:
            if self.sizing.name == "__pct_portfolio__":
                sizing = {"method": "percent_of_portfolio", "value": self.sizing.params["value"] / 100.0}
            elif self.sizing.name == "__dollar__":
                sizing = {"method": "fixed_dollar", "value": self.sizing.params["value"]}
            elif self.sizing.name == "risk":
                sizing = {"method": "risk_based", "value": self.sizing.params["value"] / 100.0}

        risk = {}
        for t in self.risk_tags:
            if t.name == "max_positions":
                risk["max_positions"] = int(t.params["value"])
            elif t.name == "max_position":
                risk["max_position_pct"] = t.params["value"] / 100.0
            elif t.name == "daily_loss":
                risk["daily_loss_limit_usd"] = t.params["value"]

        out = {
            "version": VERSION,
            "name": self.name,
            "universe": universe,
            "timeframe": self.timeframe or "1d",
            "entry": {"match_logic": self.entry_logic, "conditions": entry_conditions},
            "exit": {
                "conditions": exit_conditions,
                "stop_loss_pct": stop,
                "profit_target_pct": target,
                "trailing_stop_pct": trailing,
                "hold_bars": hold,
            },
            "position_sizing": sizing,
        }
        if risk:
            out["risk"] = risk
        return out


# ── Desugar: surface term → registry condition ────────────────────

def _operand_desc(op) -> str:
    if isinstance(op, TagNode):
        return f"[{op.name}]"
    if isinstance(op, tuple):
        if op[0] == "ticker":
            return f"${op[1]}"
        if op[0] == "number":
            return f"{op[1]:g}"
        return op[0]
    return str(op)


def _desugar(term) -> dict:
    if isinstance(term, Predicate):
        tag = term.tag
        name = _PREDICATE_MAP.get(tag.name)
        if name is None:
            spec = tag.spec
            if spec is not None and spec.usage == "operand":
                raise PriorError(
                    f"[{tag.name}] needs a comparison to become a rule",
                    line=tag.line,
                    suggestion=_operand_hint(tag.name),
                )
            raise PriorError(f"[{tag.name}] cannot be used as a condition", line=tag.line)
        p = tag.params
        if tag.name in ("volatile", "quiet"):
            return {"condition": name, "params": {"threshold_pct": p["threshold"], "period": int(p["period"])}}
        if tag.name == "volume_spike":
            return {"condition": name, "params": {"multiplier": p["multiplier"], "period": int(p["period"])}}
        if tag.name == "heavy_volume":
            return {"condition": name, "params": {"top_pct": p["top_pct"], "period": int(p["period"])}}
        # MACD crosses
        return {"condition": name, "params": {"fast": int(p["fast"]), "slow": int(p["slow"]), "signal": int(p["signal"])}}

    assert isinstance(term, Comparison)
    left, cmp, right = term.left, term.cmp, term.right

    left_is_price = isinstance(left, tuple) and left[0] in ("price", "ticker")

    if left_is_price and isinstance(right, TagNode):
        if right.name in _BOLLINGER:
            if cmp != "at":
                raise PriorError(
                    f"Bollinger bands use touch semantics: price at [{right.name}]",
                    line=term.line,
                )
            p = right.params
            return {
                "condition": "price_at_bollinger_band",
                "params": {"period": int(p["period"]), "num_std": float(p["std"]), "band": _BOLLINGER[right.name]},
            }
        if right.name in ("sma", "ema"):
            if cmp not in ("above", "below"):
                raise PriorError(
                    f"price compares to a moving average with above/below, not '{_cmp_text(cmp)}'",
                    line=term.line,
                    suggestion=f"price above [{right.name} {int(right.params['period'])}]",
                )
            return {
                "condition": f"price_{cmp}_{right.name}",
                "params": {"period": int(right.params["period"])},
            }
        raise PriorError(
            f"price cannot be compared to [{right.name}]",
            line=term.line,
        )

    if isinstance(left, TagNode) and left.name == "rsi":
        if not (isinstance(right, tuple) and right[0] == "number"):
            raise PriorError("[rsi] compares against a number from 0 to 100", line=term.line)
        threshold = float(right[1])
        if not (0 <= threshold <= 100):
            raise PriorError(f"RSI threshold {threshold:g} is out of range — RSI lives between 0 and 100", line=term.line)
        period = int(left.params["period"])
        table = {
            "<": "rsi_less_than",
            ">": "rsi_greater_than",
            "crosses_above": "rsi_crosses_above",
            "crosses_below": "rsi_crosses_below",
        }
        name = table.get(cmp)
        if name is None:
            raise PriorError(
                f"[rsi] supports <, >, crosses above, crosses below — not '{_cmp_text(cmp)}'",
                line=term.line,
            )
        return {"condition": name, "params": {"period": period, "threshold": threshold}}

    if isinstance(left, TagNode) and left.name in ("sma", "ema") and isinstance(right, TagNode):
        if right.name != left.name:
            raise PriorError(
                f"moving-average crosses compare like with like: [{left.name}] with [{left.name}]",
                line=term.line,
            )
        if cmp not in ("crosses_above", "crosses_below"):
            raise PriorError(
                f"two moving averages combine with crosses above / crosses below, not '{_cmp_text(cmp)}'",
                line=term.line,
            )
        fast = int(left.params["period"])
        slow = int(right.params["period"])
        if fast >= slow:
            raise PriorError(
                f"the faster average goes on the left: [{left.name} {min(fast, slow)}] "
                f"crosses {'above' if cmp == 'crosses_above' else 'below'} [{left.name} {max(fast, slow)}]",
                line=term.line,
            )
        direction = "above" if cmp == "crosses_above" else "below"
        return {"condition": f"{left.name}_crosses_{direction}", "params": {"fast": fast, "slow": slow}}

    if isinstance(left, tuple) and left[0] == "volume":
        raise PriorError(
            "raw volume comparisons aren't in v0.1 — the volume tags carry the semantics",
            line=term.line,
            suggestion="use [volume_spike 1.5x] or [heavy_volume top 10%]",
        )

    raise PriorError(
        f"cannot make a rule from: {_operand_desc(left)} {_cmp_text(cmp)} {_operand_desc(right)}",
        line=term.line,
    )


def _operand_hint(tag_name: str) -> str:
    hints = {
        "rsi": "[rsi] < 30",
        "sma": "price above [sma 50]",
        "ema": "price above [ema 20]",
        "lower_bollinger": "price at [lower_bollinger]",
        "middle_bollinger": "price at [middle_bollinger]",
        "upper_bollinger": "price at [upper_bollinger]",
    }
    return hints.get(tag_name, "")


def _cmp_text(cmp: str) -> str:
    return cmp.replace("_", " ")


# ── Parser ─────────────────────────────────────────────────────────

class _Cursor:
    def __init__(self, ll: LogicalLine):
        self.tokens = ll.tokens
        self.i = 0
        self.ll = ll

    def at_end(self) -> bool:
        return self.i >= len(self.tokens)

    def peek(self) -> Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def next(self) -> Token:
        tok = self.peek()
        if tok is None:
            last = self.tokens[-1]
            raise PriorError(
                "the line ends before the statement is complete",
                line=last.line, col=last.col + len(last.raw),
                source_line=self.ll.sources.get(last.line, self.ll.source),
            )
        self.i += 1
        return tok

    def err(self, message: str, tok: Token | None = None, suggestion: str | None = None):
        tok = tok or self.peek() or self.tokens[-1]
        raise PriorError(
            message, line=tok.line, col=tok.col,
            source_line=self.ll.sources.get(tok.line, self.ll.source),
            suggestion=suggestion,
        )


def _did_you_mean(name: str, candidates) -> str | None:
    close = difflib.get_close_matches(name, list(candidates), n=1, cutoff=0.6)
    return f"Did you mean [{close[0]}]?" if close else None


def _parse_tag(cur: _Cursor) -> TagNode:
    lb = cur.next()  # lbrack consumed by caller check
    assert lb.kind == "lbrack"
    tok = cur.peek()
    if tok is None:
        cur.err("unclosed '['")

    # Special sizing forms: [5% portfolio] and [$10000]
    if tok.kind == "percent":
        pct = cur.next()
        follow = cur.peek()
        if follow is not None and follow.kind in ("word", "keyword") and follow.value == "portfolio":
            cur.next()
            _expect_rbrack(cur)
            return TagNode("__pct_portfolio__", {"value": pct.value},
                           pos_raw=[("percent", pct.value)], line=pct.line, col=pct.col)
        cur.err("a percent inside a bare tag needs context", tok=pct,
                suggestion="sizing is [5% portfolio]; stops are [stop 1.5%]")
    if tok.kind == "dollar":
        dol = cur.next()
        _expect_rbrack(cur)
        return TagNode("__dollar__", {"value": dol.value},
                       pos_raw=[("dollar", dol.value)], line=dol.line, col=dol.col)

    if tok.kind not in ("word", "keyword"):
        cur.err("a tag starts with its name, like [lower_bollinger]")
    name_tok = cur.next()
    name = str(name_tok.value)
    if name == "risk":
        # `risk` is a keyword but also a sizing tag name
        pass
    spec = TAGS.get(name)
    if spec is None:
        cur.err(f"[{name_tok.raw}] is not a known tag", tok=name_tok,
                suggestion=_did_you_mean(name, TAGS.keys()))

    pos_raw: list = []
    named_raw: dict = {}
    while True:
        tok = cur.peek()
        if tok is None:
            cur.err("unclosed '[' — missing ']'", tok=name_tok)
        if tok.kind == "rbrack":
            cur.next()
            break
        if tok.kind in ("word", "keyword"):
            nxt = cur.tokens[cur.i + 1] if cur.i + 1 < len(cur.tokens) else None
            if nxt is not None and nxt.kind == "eq":
                key_tok = cur.next()
                cur.next()  # '='
                val_tok = cur.next()
                if val_tok.kind not in ("number", "percent", "dollar", "mult", "word"):
                    cur.err(f"'{key_tok.raw}=' needs a value", tok=val_tok)
                key = str(key_tok.value)
                if key not in spec.named:
                    cur.err(f"[{name}] has no parameter '{key}'", tok=key_tok,
                            suggestion=_did_you_mean(key, spec.named.keys()))
                named_raw[key] = (val_tok.kind, val_tok.value)
                continue
            pos_raw.append(("word", tok.value))
            cur.next()
            continue
        if tok.kind in ("number", "percent", "dollar", "mult"):
            pos_raw.append((tok.kind, tok.value))
            cur.next()
            continue
        cur.err(f"unexpected {tok.raw!r} inside [{name}]")

    # heavy_volume convenience: allow [heavy_volume 10%] without the 'top'
    if name == "heavy_volume" and pos_raw and pos_raw[0][0] == "percent":
        pos_raw.insert(0, ("word", "top"))

    params = _resolve_params(cur, name_tok, spec, pos_raw, named_raw)
    return TagNode(name, params, pos_raw=pos_raw, named_raw=named_raw,
                   line=name_tok.line, col=name_tok.col)


def _expect_rbrack(cur: _Cursor):
    tok = cur.peek()
    if tok is None or tok.kind != "rbrack":
        cur.err("missing ']'")
    cur.next()


def _resolve_params(cur: _Cursor, name_tok: Token, spec: TagSpec, pos_raw, named_raw) -> dict:
    params: dict = {}
    if len(pos_raw) > len(spec.positional):
        cur.err(f"[{spec.name}] takes at most {len(spec.positional)} positional value(s)", tok=name_tok)
    for i, p in enumerate(spec.positional):
        if i < len(pos_raw):
            kind, value = pos_raw[i]
            if kind != p.kind:
                cur.err(
                    f"[{spec.name}] expects a {p.kind} for '{p.name}', got {_kind_example(kind, value)}",
                    tok=name_tok,
                    suggestion=_kind_suggestion(spec.name, p),
                )
            params[p.name] = value
        elif p.required:
            cur.err(f"[{spec.name}] needs '{p.name}'", tok=name_tok,
                    suggestion=_kind_suggestion(spec.name, p))
        else:
            params[p.name] = p.default
    for key, p in spec.named.items():
        if key in named_raw:
            kind, value = named_raw[key]
            if kind != p.kind:
                cur.err(f"[{spec.name}] expects a {p.kind} for '{key}'", tok=name_tok)
            params[key] = value
        elif key not in params:
            params[key] = p.default
    if spec.name == "after":
        unit = params.get("unit", "bars")
        if unit not in ("bar", "bars"):
            cur.err(f"[after] counts bars: [after 5 bars], not '{unit}'", tok=name_tok)
    return params


def _kind_example(kind: str, value) -> str:
    return {"number": f"number {value:g}", "percent": f"percent {value:g}%",
            "dollar": f"dollar ${value:g}", "mult": f"multiplier {value:g}x",
            "word": f"word '{value}'"}.get(kind, kind)


def _kind_suggestion(tag: str, p) -> str:
    examples = {NUMBER: "20", PERCENT: "1.5%", DOLLAR: "$10000", MULT: "1.5x", WORD: "top"}
    return f"e.g. [{tag} {examples.get(p.kind, '')}]"


def _parse_operand(cur: _Cursor):
    tok = cur.peek()
    if tok is None:
        cur.err("expected a value here")
    if tok.kind == "keyword" and tok.value in ("price", "volume"):
        cur.next()
        return (tok.value,)
    if tok.kind == "ticker":
        cur.next()
        return ("ticker", tok.value)
    if tok.kind == "lbrack":
        return _parse_tag(cur)
    if tok.kind == "number":
        cur.next()
        return ("number", tok.value)
    if tok.kind == "keyword" and tok.value == "on":
        cur.err("multi-timeframe rules ('on 4h') are coming in a later version", tok=tok)
    cur.err(f"expected price, volume, a $TICKER, a [tag], or a number — got {tok.raw!r}")


def _parse_cmp(cur: _Cursor) -> str | None:
    tok = cur.peek()
    if tok is None:
        return None
    if tok.kind == "op":
        cur.next()
        return tok.value
    if tok.kind == "keyword" and tok.value in ("at", "above", "below"):
        cur.next()
        return tok.value
    if tok.kind == "keyword" and tok.value == "crosses":
        cur.next()
        nxt = cur.peek()
        if nxt is None or not (nxt.kind == "keyword" and nxt.value in ("above", "below")):
            cur.err("'crosses' is followed by above or below", tok=tok)
        cur.next()
        return f"crosses_{nxt.value}"
    return None


def _parse_term(cur: _Cursor):
    tok = cur.peek()
    if tok is not None and tok.kind == "lparen":
        cur.next()
        node = _parse_expr(cur)
        close = cur.peek()
        if close is None or close.kind != "rparen":
            cur.err("missing ')'")
        cur.next()
        return node
    start = cur.peek()
    left = _parse_operand(cur)
    cmp = _parse_cmp(cur)
    if cmp is None:
        if isinstance(left, TagNode):
            return Predicate(tag=left, line=left.line)
        cur.err("this needs a comparison to become a rule", tok=start)
    right = _parse_operand(cur)
    line = start.line if start else 0
    return Comparison(left=left, cmp=cmp, right=right, line=line)


def _parse_expr(cur: _Cursor, stop_at_buy: bool = False):
    """Parse an and/or expression into ('all'|'any'|None, [terms])."""
    def and_chain():
        items = [term_node()]
        while True:
            tok = cur.peek()
            if tok is not None and tok.kind == "keyword" and tok.value == "and":
                cur.next()
                items.append(term_node())
            else:
                return ("all", items) if len(items) > 1 else (None, items)

    def term_node():
        return _parse_term(cur)

    logic, items = and_chain()
    while True:
        tok = cur.peek()
        if stop_at_buy and tok is not None and tok.kind == "keyword" and tok.value == "buy":
            break
        if tok is not None and tok.kind == "keyword" and tok.value == "or":
            cur.next()
            logic2, items2 = and_chain()
            if logic == "all" or logic2 == "all":
                cur.err("one rule combines with all 'and' or all 'or' — mixing needs a later version", tok=tok)
            logic = "any"
            items = items + items2
        else:
            break
    return (logic, items)


def _flatten(node, cur: _Cursor):
    """Flatten nested (logic, items) trees; reject mixed logic."""
    logic, items = node
    flat = []
    child_logics = set()
    for it in items:
        if isinstance(it, tuple) and len(it) == 2 and isinstance(it[1], list):
            sub_logic, sub_items = _flatten(it, cur)
            if sub_logic is not None:
                child_logics.add(sub_logic)
            flat.extend(sub_items)
        else:
            flat.append(it)
    if logic is not None:
        child_logics.add(logic)
    if len(child_logics) > 1:
        cur.err("one rule combines with all 'and' or all 'or' — mixing needs a later version")
    return (child_logics.pop() if child_logics else None, flat)


# ── Statements ─────────────────────────────────────────────────────

def parse_source(source: str, filename: str = "<string>") -> Program:
    prog = Program(source_name=filename)
    seen: set[str] = set()

    for ll in tokenize(source):
        cur = _Cursor(ll)
        head = cur.next()

        if head.kind == "word" and head.value in ("short", "cover"):
            cur.err("short entries are coming in v1.1 — the syntax is reserved", tok=head)

        if head.kind != "keyword":
            cur.err(
                f"a statement starts with strategy, universe, timeframe, when, sell, or risk — got {head.raw!r}",
                tok=head,
            )

        kw = head.value
        if kw in seen and kw in ("strategy", "universe", "timeframe", "when", "if", "sell", "risk"):
            label = "entry (when)" if kw in ("when", "if") else kw
            cur.err(f"more than one {label} statement — multiple rules are coming in v1.1", tok=head)

        if kw == "strategy":
            tok = cur.next()
            if tok.kind != "string":
                cur.err('strategy takes a quoted name: strategy "My Strategy"', tok=tok)
            prog.name = tok.value
            seen.add("strategy")

        elif kw == "universe":
            tok = cur.peek()
            if tok is not None and tok.kind == "lbrack":
                tag = _parse_tag(cur)
                if tag.spec is None or tag.spec.kind != "universe":
                    cur.err(f"[{tag.name}] is not a universe", tok=head,
                            suggestion=_did_you_mean(tag.name, [n for n, s in TAGS.items() if s.kind == "universe"]))
                prog.universe_tag = tag
            else:
                while not cur.at_end():
                    t = cur.next()
                    if t.kind != "ticker":
                        cur.err("universe lists tickers ($AAPL $MSFT) or one prebuilt tag", tok=t)
                    prog.universe_tickers.append(t.value)
                if not prog.universe_tickers:
                    cur.err("universe needs a prebuilt tag or at least one $TICKER", tok=head)
            seen.add("universe")

        elif kw == "timeframe":
            tok = cur.next()
            if tok.kind != "timeframe":
                cur.err("timeframe looks like 1d, 4h, 15m, 1w", tok=tok)
            prog.timeframe = tok.value
            seen.add("timeframe")

        elif kw in ("when", "if"):
            node = _parse_expr(cur, stop_at_buy=True)
            logic, terms = _flatten(node, cur)
            prog.entry_logic = logic or "all"
            prog.entry_terms = terms
            buy = cur.peek()
            if buy is None or not (buy.kind == "keyword" and buy.value == "buy"):
                cur.err("the entry rule ends with: buy [sizing]",
                        suggestion="e.g. buy [10% portfolio]")
            cur.next()
            size_tok = cur.peek()
            if size_tok is None or size_tok.kind != "lbrack":
                cur.err("buy needs a sizing tag", tok=buy,
                        suggestion="e.g. buy [10% portfolio], buy [$10000], buy [risk 1%]")
            tag = _parse_tag(cur)
            if tag.name not in ("__pct_portfolio__", "__dollar__", "risk"):
                kindname = tag.spec.kind if tag.spec else "unknown"
                cur.err(f"[{tag.name}] is a {kindname} tag; buy takes a sizing tag", tok=buy,
                        suggestion="e.g. buy [10% portfolio], buy [$10000], buy [risk 1%]")
            prog.sizing = tag
            if not cur.at_end():
                cur.err("nothing may follow the sizing tag on the entry rule")
            seen.add("when")
            seen.add("if")

        elif kw == "sell":
            tok = cur.peek()
            if tok is not None and tok.kind == "keyword" and tok.value == "when":
                cur.next()
            node = _parse_expr(cur)
            logic, terms = _flatten(node, cur)
            if logic == "all" and len(terms) > 1:
                cur.err("exit rules combine with 'or' — the position closes on the first that fires", tok=head)
            counts: dict[str, int] = {}
            for t in terms:
                if isinstance(t, Predicate) and t.tag.spec is not None and t.tag.spec.kind == "exit":
                    terms[terms.index(t)] = t.tag  # unwrap exit tags
                    t = t.tag
                if isinstance(t, TagNode):
                    counts[t.name] = counts.get(t.name, 0) + 1
                    if counts[t.name] > 1:
                        cur.err(f"[{t.name}] appears twice in the exit rule", tok=head)
            prog.exit_terms = terms
            if not cur.at_end():
                cur.err("unexpected trailing tokens after the exit rule")
            seen.add("sell")

        elif kw == "risk":
            while not cur.at_end():
                tok = cur.peek()
                if tok.kind != "lbrack":
                    cur.err("risk takes tags: risk [max_positions 5] [daily_loss $500]", tok=tok)
                tag = _parse_tag(cur)
                if tag.spec is None or tag.spec.kind != "risk":
                    cur.err(f"[{tag.name}] is not a risk tag", tok=head,
                            suggestion=_did_you_mean(tag.name, [n for n, s in TAGS.items() if s.kind == "risk"]))
                prog.risk_tags.append(tag)
            if not prog.risk_tags:
                cur.err("risk needs at least one tag", tok=head)
            seen.add("risk")

        else:
            cur.err(f"'{head.raw}' cannot start a statement", tok=head)

    _validate(prog)
    return prog


def _validate(prog: Program):
    if not prog.entry_terms:
        raise PriorError("the strategy has no entry rule — add: when <condition> buy [sizing]")
    if not prog.exit_terms:
        raise PriorError("the strategy has no exit rule — add: sell when <condition or exit tags>")

    # Inline ticker scoping vs universe statement
    tickers = set()
    for t in prog.entry_terms + prog.exit_terms:
        if isinstance(t, Comparison) and isinstance(t.left, tuple) and t.left[0] == "ticker":
            tickers.add(t.left[1])
    if len(tickers) > 1:
        raise PriorError(
            f"v0.1 supports one inline ticker per strategy — found {', '.join('$' + s for s in sorted(tickers))}"
        )
    if tickers:
        if prog.universe_tag is not None or prog.universe_tickers:
            raise PriorError(
                "use either a universe statement or an inline $TICKER, not both — "
                "per-ticker overrides inside a universe are coming later"
            )
        prog.scoped_ticker = tickers.pop()
    elif prog.universe_tag is None and not prog.universe_tickers:
        raise PriorError(
            "the strategy needs a universe — add: universe [sp_top_30] (or scope it inline: when $NVDA at ...)"
        )

    # Risk-based sizing requires a stop to size against
    if prog.sizing is not None and prog.sizing.name == "risk":
        has_stop = any(isinstance(t, TagNode) and t.name == "stop" for t in prog.exit_terms)
        if not has_stop:
            raise PriorError(
                "risk-based sizing needs a stop to size against — add [stop x%] to the sell rule"
            )

    # Desugar everything once so condition-level errors surface at compile time
    for t in prog.entry_terms:
        _desugar(t)
    for t in prog.exit_terms:
        if not isinstance(t, TagNode):
            _desugar(t)
