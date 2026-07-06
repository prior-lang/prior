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
    term = _condition_to_term_inner(cond)
    tf = cond.get("timeframe")
    if tf:
        if isinstance(term, Predicate):
            term.tag.timeframe = tf
        else:
            for side in (term.right, term.left):
                if isinstance(side, TagNode):
                    side.timeframe = tf
                    break
    return term


def _condition_to_term_inner(cond: dict):
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

    if name in ("price_new_high", "price_new_low"):
        surface = "new_high" if name.endswith("high") else "new_low"
        pos = []
        if _n(p.get("period", 252)) != 252:
            pos.append(("number", _n(p["period"])))
        return Predicate(_tag(surface, pos))

    if name in ("gap_up", "gap_down"):
        pos = []
        if _n(p.get("min_gap_pct", 2.0)) != 2.0:
            pos.append(("percent", _n(p["min_gap_pct"])))
        return Predicate(_tag(name, pos))

    if name in ("up_days", "down_days"):
        return Predicate(_tag(name, [("number", _n(p["count"]))]))

    if name in ("price_above_level", "price_below_level"):
        side = "above" if "above" in name else "below"
        return Comparison(("price",), side, ("number", _n(p["level"])))

    if name in ("price_above_vwap", "price_below_vwap"):
        side = "above" if "above" in name else "below"
        pos = []
        if _n(p.get("period", 20)) != 20:
            pos.append(("number", _n(p["period"])))
        return Comparison(("price",), side, _tag("vwap", pos))

    if name == "bollinger_squeeze":
        pos, named = [], {}
        if _n(p.get("lookback", 126)) != 126:
            pos.append(("number", _n(p["lookback"])))
        if _n(p.get("pct", 10.0)) != 10.0:
            named["pct"] = ("number", _n(p["pct"]))
        if _n(p.get("period", 20)) != 20:
            named["period"] = ("number", _n(p["period"]))
        if _n(p.get("num_std", 2.0)) != 2.0:
            named["std"] = ("number", _n(p["num_std"]))
        return Predicate(_tag("squeeze", pos, named))

    if name == "obv_rising":
        pos = []
        if _n(p.get("period", 20)) != 20:
            pos.append(("number", _n(p["period"])))
        return Predicate(_tag("obv_rising", pos))

    if name in ("adx_greater_than", "adx_less_than"):
        pos = []
        if _n(p.get("period", 14)) != 14:
            pos.append(("number", _n(p["period"])))
        cmp = ">" if name.endswith("greater_than") else "<"
        return Comparison(_tag("adx", pos), cmp, ("number", _n(p["threshold"])))

    if name in ("stoch_less_than", "stoch_greater_than", "stoch_crosses_above", "stoch_crosses_below"):
        pos, named = [], {}
        if _n(p.get("period", 14)) != 14:
            pos.append(("number", _n(p["period"])))
        if _n(p.get("smooth", 3)) != 3:
            named["smooth"] = ("number", _n(p["smooth"]))
        cmp = {"stoch_less_than": "<", "stoch_greater_than": ">",
               "stoch_crosses_above": "crosses_above", "stoch_crosses_below": "crosses_below"}[name]
        return Comparison(_tag("stoch", pos, named), cmp, ("number", _n(p["threshold"])))

    raise PriorError(f"no PRIOR surface syntax for condition '{name}'")


def _metric_tag(m: dict) -> TagNode:
    from .tags import TAGS
    name = m["name"]
    p = m.get("params", {}) or {}
    spec = TAGS.get(name)
    pos, named = [], {}
    if spec is not None:
        for i, param in enumerate(spec.positional):
            v = p.get(param.name)
            if v is None:
                continue
            if param.required or _n(v) != _n(param.default if param.default is not None else v):
                pos.append((param.kind, _n(v)))
        for key, param in spec.named.items():
            if key in [q.name for q in spec.positional]:
                continue
            v = p.get(key)
            if v is not None and _n(v) != _n(param.default):
                named[key] = (param.kind, _n(v))
    return TagNode(name, dict(p), pos_raw=pos, named_raw=named)


def strategy_to_source(strategy: dict) -> str:
    """Render strategy JSON as canonical .prior text."""
    prog = Program()
    prog.name = strategy.get("name")
    prog.direction = strategy.get("direction", "long")
    prog.exit_keyword = "cover" if prog.direction == "short" else "sell"

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

    options = strategy.get("options")
    if options:
        opt = options.get("option", {})
        prog.opt_form = options.get("form", "wheel")
        entry = options.get("entry") or {}
        prog.opt_entry_logic = entry.get("match_logic", "all")
        prog.opt_entry_terms = [_condition_to_term(c) for c in entry.get("conditions") or []]
        if prog.opt_form == "wheel":
            prog.opt_params = {"delta": _n(opt.get("delta", 25)), "dte": _n(opt.get("dte", 45))}
        else:
            named = {}
            if _n(opt.get("delta", 25)) != 25:
                named["delta"] = ("number", _n(opt["delta"]))
            if _n(opt.get("dte", 45)) != 45:
                named["dte"] = ("number", _n(opt["dte"]))
            prog.opt_option = _tag(opt["type"], named=named,
                                   params={"delta": _n(opt.get("delta", 25)), "dte": _n(opt.get("dte", 45))})
        mgmt = options.get("management") or {}
        if mgmt.get("profit_pct") is not None:
            prog.mgmt_close_terms.append(_tag("profit", [("percent", _n(mgmt["profit_pct"]))], params={"value": _n(mgmt["profit_pct"])}))
        if mgmt.get("loss_pct") is not None:
            prog.mgmt_close_terms.append(_tag("loss", [("percent", _n(mgmt["loss_pct"]))], params={"value": _n(mgmt["loss_pct"])}))
        if mgmt.get("close_dte") is not None:
            prog.mgmt_close_terms.append(_tag("dte", [("number", _n(mgmt["close_dte"]))], params={"days": mgmt["close_dte"]}))
        if mgmt.get("roll_dte") is not None:
            prog.mgmt_roll_terms.append(_tag("dte", [("number", _n(mgmt["roll_dte"]))], params={"days": mgmt["roll_dte"]}))
        risk = strategy.get("risk") or {}
        if "contracts" in risk:
            prog.risk_tags.append(_tag("contracts", [("number", _n(risk["contracts"]))], params={"count": risk["contracts"]}))
        if "collateral_pct" in risk:
            prog.risk_tags.append(_tag("collateral", [("percent", _n(risk["collateral_pct"]) * 100)], params={"value": _n(risk["collateral_pct"]) * 100}))
        if "cooldown_bars" in risk:
            prog.risk_tags.append(_tag("cooldown", [("number", _n(risk["cooldown_bars"]))], params={"bars": risk["cooldown_bars"]}))
        return format_program(prog)

    ranking = strategy.get("ranking")
    if ranking:
        prog.rebalance = strategy.get("rebalance", "monthly")
        prog.rank_select = ranking.get("select", "top")
        prog.rank_count = int(ranking.get("count", 1))
        prog.rank_metric = _metric_tag(ranking["metric"])
        where = ranking.get("where") or {}
        prog.rank_where_logic = where.get("match_logic", "all")
        prog.rank_where_terms = [_condition_to_term(c) for c in where.get("conditions") or []]
        weighting = ranking.get("weighting") or {}
        if weighting.get("method") == "by_metric":
            prog.rank_weight_metric = _metric_tag(weighting["metric"])
        risk = strategy.get("risk") or {}
        if "max_positions" in risk:
            prog.risk_tags.append(_tag("max_positions", [("number", _n(risk["max_positions"]))]))
        if "max_position_pct" in risk:
            prog.risk_tags.append(_tag("max_position", [("percent", _n(risk["max_position_pct"]) * 100)]))
        if "daily_loss_limit_usd" in risk:
            prog.risk_tags.append(_tag("daily_loss", [("dollar", _n(risk["daily_loss_limit_usd"]))]))
        return format_program(prog)

    entry = strategy.get("entry", {}) or {}
    prog.entry_logic = entry.get("match_logic", "all")
    prog.entry_terms = [_condition_to_term(c) for c in entry.get("conditions", [])]

    def _sizing_tag(sizing):
        if not sizing:
            return None
        method = sizing.get("method")
        v = _n(sizing.get("value", 0))
        if method == "percent_of_portfolio":
            return _tag("__pct_portfolio__", params={"value": v * 100})
        if method == "fixed_dollar":
            return _tag("__dollar__", params={"value": v})
        if method == "risk_based":
            return _tag("risk", [("percent", v * 100)])
        return None

    prog.sizing = _sizing_tag(strategy.get("position_sizing"))
    if strategy.get("rules"):
        prog.rules = [
            {
                "logic": r.get("match_logic", "all"),
                "terms": [_condition_to_term(c) for c in r["conditions"]],
                "sizing": _sizing_tag(r.get("position_sizing")),
                "direction": r.get("direction", strategy.get("direction", "long")),
            }
            for r in strategy["rules"]
        ]
    p = strategy.get("partial_exit")
    if p:
        pterms: list = [_condition_to_term(c) for c in p.get("conditions") or []]
        if p.get("profit_target_pct") is not None:
            pterms.append(_tag("target", [("percent", _n(p["profit_target_pct"]))],
                               params={"value": _n(p["profit_target_pct"]), "unit": "pct"}))
        if p.get("hold_bars") is not None:
            pterms.append(_tag("after", [("number", _n(p["hold_bars"])), ("word", "bars")]))
        prog.partial_terms = pterms

    def _exit_terms_from_spec(ex):
        terms: list = [_condition_to_term(c) for c in ex.get("conditions") or []]
        if ex.get("stop_loss_pct") is not None:
            terms.append(_tag("stop", [("percent", _n(ex["stop_loss_pct"]))], params={"value": _n(ex["stop_loss_pct"]), "unit": "pct"}))
        if ex.get("stop_loss_atr") is not None:
            terms.append(_tag("stop", [("number", _n(ex["stop_loss_atr"])), ("word", "atr")], params={"value": _n(ex["stop_loss_atr"]), "unit": "atr"}))
        if ex.get("breakeven_trigger_pct") is not None:
            terms.append(_tag("breakeven", [("word", "after"), ("percent", _n(ex["breakeven_trigger_pct"]))], params={"trigger": _n(ex["breakeven_trigger_pct"])}))
        if ex.get("profit_target_pct") is not None:
            terms.append(_tag("target", [("percent", _n(ex["profit_target_pct"]))], params={"value": _n(ex["profit_target_pct"]), "unit": "pct"}))
        if ex.get("profit_target_atr") is not None:
            terms.append(_tag("target", [("number", _n(ex["profit_target_atr"])), ("word", "atr")], params={"value": _n(ex["profit_target_atr"]), "unit": "atr"}))
        if ex.get("trailing_stop_pct") is not None:
            terms.append(_tag("trailing", [("percent", _n(ex["trailing_stop_pct"]))], params={"value": _n(ex["trailing_stop_pct"]), "unit": "pct"}))
        if ex.get("trailing_stop_atr") is not None:
            terms.append(_tag("trailing", [("number", _n(ex["trailing_stop_atr"])), ("word", "atr")], params={"value": _n(ex["trailing_stop_atr"]), "unit": "atr"}))
        if ex.get("hold_bars") is not None:
            terms.append(_tag("after", [("number", _n(ex["hold_bars"])), ("word", "bars")]))
        return terms

    if strategy.get("exits"):
        prog.exit_terms = _exit_terms_from_spec(strategy["exits"]["long"])
        prog.exit_short_terms = _exit_terms_from_spec(strategy["exits"]["short"])
        risk = strategy.get("risk") or {}
        if "max_positions" in risk:
            prog.risk_tags.append(_tag("max_positions", [("number", _n(risk["max_positions"]))]))
        if "max_position_pct" in risk:
            prog.risk_tags.append(_tag("max_position", [("percent", _n(risk["max_position_pct"]) * 100)]))
        if "daily_loss_limit_usd" in risk:
            prog.risk_tags.append(_tag("daily_loss", [("dollar", _n(risk["daily_loss_limit_usd"]))]))
        if "cooldown_bars" in risk:
            prog.risk_tags.append(_tag("cooldown", [("number", _n(risk["cooldown_bars"]))], params={"bars": risk["cooldown_bars"]}))
        return format_program(prog)

    ex = strategy.get("exit", {}) or {}
    exit_terms: list = [_condition_to_term(c) for c in ex.get("conditions") or []]
    if ex.get("stop_loss_pct") is not None:
        exit_terms.append(_tag("stop", [("percent", _n(ex["stop_loss_pct"]))], params={"value": _n(ex["stop_loss_pct"]), "unit": "pct"}))
    if ex.get("stop_loss_atr") is not None:
        exit_terms.append(_tag("stop", [("number", _n(ex["stop_loss_atr"])), ("word", "atr")], params={"value": _n(ex["stop_loss_atr"]), "unit": "atr"}))
    if ex.get("breakeven_trigger_pct") is not None:
        exit_terms.append(_tag("breakeven", [("word", "after"), ("percent", _n(ex["breakeven_trigger_pct"]))], params={"trigger": _n(ex["breakeven_trigger_pct"])}))
    if ex.get("profit_target_pct") is not None:
        exit_terms.append(_tag("target", [("percent", _n(ex["profit_target_pct"]))], params={"value": _n(ex["profit_target_pct"]), "unit": "pct"}))
    if ex.get("profit_target_atr") is not None:
        exit_terms.append(_tag("target", [("number", _n(ex["profit_target_atr"])), ("word", "atr")], params={"value": _n(ex["profit_target_atr"]), "unit": "atr"}))
    if ex.get("trailing_stop_pct") is not None:
        exit_terms.append(_tag("trailing", [("percent", _n(ex["trailing_stop_pct"]))], params={"value": _n(ex["trailing_stop_pct"]), "unit": "pct"}))
    if ex.get("trailing_stop_atr") is not None:
        exit_terms.append(_tag("trailing", [("number", _n(ex["trailing_stop_atr"])), ("word", "atr")], params={"value": _n(ex["trailing_stop_atr"]), "unit": "atr"}))
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
    if "cooldown_bars" in risk:
        prog.risk_tags.append(_tag("cooldown", [("number", _n(risk["cooldown_bars"]))], params={"bars": risk["cooldown_bars"]}))

    return format_program(prog)
