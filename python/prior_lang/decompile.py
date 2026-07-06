"""Decompiler: strategy JSON → .prior source.

The inverse of the parser's desugaring, so anything that produces the
interchange JSON (a scanner, a GUI builder, another tool) can render its
strategy as readable PRIOR text. Output is canonical (it round-trips
through parse → format unchanged) and omits parameters that equal their
defaults, so the text stays as short as what a person would write.
"""

from __future__ import annotations

from .errors import PriorError
from .formatter import format_program
from .parser import Comparison, Predicate, Program, TagNode


def _tag(name: str, pos=None, named=None, params=None) -> TagNode:
    return TagNode(
        name,
        params or {},
        pos_raw=list(pos or []),
        named_raw=dict(named or {}),
    )


def _n(v) -> float:
    return float(v)


def _condition_to_term(cond: dict):
    name = cond["condition"]
    p = cond.get("params", {}) or {}

    if name == "price_at_bollinger_band":
        band = p.get("band", "upper")
        pos, named = [], {}
        if _n(p.get("period", 20)) != 20:
            pos.append(("number", _n(p["period"])))
        if _n(p.get("num_std", 2.0)) != 2.0:
            named["std"] = ("number", _n(p["num_std"]))
        return Comparison(("price",), "at", _tag(f"{band}_bollinger", pos, named))

    if name in ("price_above_sma", "price_below_sma", "price_above_ema", "price_below_ema"):
        side = "above" if "above" in name else "below"
        ma = name[-3:]
        return Comparison(("price",), side, _tag(ma, [("number", _n(p["period"]))]))

    if name in ("rsi_less_than", "rsi_greater_than", "rsi_crosses_above", "rsi_crosses_below"):
        pos = []
        if _n(p.get("period", 14)) != 14:
            pos.append(("number", _n(p["period"])))
        cmp = {"rsi_less_than": "<", "rsi_greater_than": ">",
               "rsi_crosses_above": "crosses_above", "rsi_crosses_below": "crosses_below"}[name]
        return Comparison(_tag("rsi", pos), cmp, ("number", _n(p["threshold"])))

    if name in ("macd_crosses_above_signal", "macd_crosses_below_signal"):
        direction = "up" if "above" in name else "down"
        pos = []
        fast, slow, sig = _n(p.get("fast", 12)), _n(p.get("slow", 26)), _n(p.get("signal", 9))
        if (fast, slow, sig) != (12.0, 26.0, 9.0):
            pos = [("number", fast), ("number", slow), ("number", sig)]
        return Predicate(_tag(f"macd_cross_{direction}", pos))

    if name in ("ema_crosses_above", "ema_crosses_below", "sma_crosses_above", "sma_crosses_below"):
        ma = name[:3]
        cmp = "crosses_above" if name.endswith("above") else "crosses_below"
        return Comparison(
            _tag(ma, [("number", _n(p["fast"]))]), cmp, _tag(ma, [("number", _n(p["slow"]))])
        )

    if name in ("atr_greater_than_pct", "atr_less_than_pct"):
        surface = "volatile" if "greater" in name else "quiet"
        named = {}
        if _n(p.get("period", 14)) != 14:
            named["period"] = ("number", _n(p["period"]))
        return Predicate(_tag(surface, [("percent", _n(p["threshold_pct"]))], named))

    if name == "volume_greater_than_avg":
        pos, named = [], {}
        if _n(p.get("multiplier", 1.5)) != 1.5:
            pos.append(("mult", _n(p["multiplier"])))
        if _n(p.get("period", 20)) != 20:
            named["period"] = ("number", _n(p["period"]))
        return Predicate(_tag("volume_spike", pos, named))

    if name == "volume_in_top_pct":
        pos, named = [("word", "top"), ("percent", _n(p.get("top_pct", 10.0)))], {}
        if _n(p.get("period", 60)) != 60:
            named["period"] = ("number", _n(p["period"]))
        return Predicate(_tag("heavy_volume", pos, named))

    raise PriorError(f"no PRIOR surface syntax for condition '{name}'")


def strategy_to_source(strategy: dict) -> str:
    """Render strategy JSON as canonical .prior text."""
    prog = Program()
    prog.name = strategy.get("name")

    uni = strategy.get("universe", {}) or {}
    if uni.get("type") == "prebuilt":
        prog.universe_tag = _tag(uni["key"])
    elif uni.get("tickers"):
        prog.universe_tickers = [str(t).upper() for t in uni["tickers"]]

    tf = strategy.get("timeframe")
    if tf and tf != "1d":
        prog.timeframe = tf
    elif tf == "1d":
        prog.timeframe = "1d"

    entry = strategy.get("entry", {}) or {}
    prog.entry_logic = entry.get("match_logic", "all")
    prog.entry_terms = [_condition_to_term(c) for c in entry.get("conditions", [])]

    sizing = strategy.get("position_sizing")
    if sizing:
        method = sizing.get("method")
        v = _n(sizing.get("value", 0))
        if method == "percent_of_portfolio":
            prog.sizing = _tag("__pct_portfolio__", params={"value": v * 100})
        elif method == "fixed_dollar":
            prog.sizing = _tag("__dollar__", params={"value": v})
        elif method == "risk_based":
            prog.sizing = _tag("risk", [("percent", v * 100)])

    ex = strategy.get("exit", {}) or {}
    exit_terms: list = [_condition_to_term(c) for c in ex.get("conditions") or []]
    if ex.get("stop_loss_pct") is not None:
        exit_terms.append(_tag("stop", [("percent", _n(ex["stop_loss_pct"]))]))
    if ex.get("profit_target_pct") is not None:
        exit_terms.append(_tag("target", [("percent", _n(ex["profit_target_pct"]))]))
    if ex.get("trailing_stop_pct") is not None:
        exit_terms.append(_tag("trailing", [("percent", _n(ex["trailing_stop_pct"]))]))
    if ex.get("hold_bars") is not None:
        exit_terms.append(_tag("after", [("number", _n(ex["hold_bars"])), ("word", "bars")]))
    prog.exit_terms = exit_terms

    risk = strategy.get("risk") or {}
    if "max_positions" in risk:
        prog.risk_tags.append(_tag("max_positions", [("number", _n(risk["max_positions"]))]))
    if "max_position_pct" in risk:
        prog.risk_tags.append(_tag("max_position", [("percent", _n(risk["max_position_pct"]) * 100)]))
    if "daily_loss_limit_usd" in risk:
        prog.risk_tags.append(_tag("daily_loss", [("dollar", _n(risk["daily_loss_limit_usd"]))]))

    return format_program(prog)
