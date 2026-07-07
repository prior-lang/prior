"""English readback: strategy JSON → plain sentences.

The templates here are the normative readback strings from spec/TAGS.md.
`prior explain` prints this alongside the JSON and the generated Python so
every layer of the compile is inspectable.
"""

from __future__ import annotations

from .tags import UNIVERSE_KEYS

_UNIVERSE_LABELS = {
    "sp_top_30": "the S&P Top 30",
    "mega_tech": "the mega-cap tech basket",
    "etf_sectors": "the SPDR sector ETFs",
    "big_banks": "the big banks",
    "semis": "the semiconductor leaders",
    "crypto_majors": "the major crypto pairs",
}


def _num(v) -> str:
    if v is None:
        return "?"
    return str(int(v)) if float(v) == int(v) else f"{float(v):g}"


def _plural(v, word: str) -> str:
    return f"{_num(v)} {word}{'' if float(v) == 1 else 's'}"


def _condition_text(cond: dict) -> str:
    text = _condition_text_inner(cond)
    tf = cond.get("timeframe")
    if tf:
        text += f", judged on closed {tf} bars"
    return text


def _condition_text_inner(cond: dict) -> str:
    name = cond["condition"]
    p = cond.get("params", {}) or {}

    if "." in name:
        from .plugins import PLUGIN_TAGS
        plug = PLUGIN_TAGS.get(name)
        if plug is not None and plug.readback is not None:
            return plug.readback(dict(p))
        return f"{name}({', '.join(f'{k}={v}' for k, v in p.items())})"

    if name == "price_at_bollinger_band":
        return (
            f"price touches or crosses the {p.get('band', 'upper')} Bollinger band "
            f"({_num(p.get('period', 20))}-period, {_plural(p.get('num_std', 2.0), 'standard deviation')})"
        )
    if name in ("price_above_sma", "price_below_sma", "price_above_ema", "price_below_ema"):
        side = "above" if "above" in name else "below"
        ma = name[-3:].upper()
        return f"price is {side} the {_num(p.get('period'))}-period {ma}"
    if name == "rsi_less_than":
        return f"RSI({_num(p.get('period', 14))}) is below {_num(p.get('threshold'))}"
    if name == "rsi_greater_than":
        return f"RSI({_num(p.get('period', 14))}) is above {_num(p.get('threshold'))}"
    if name in ("rsi_crosses_above", "rsi_crosses_below"):
        d = "above" if name.endswith("above") else "below"
        return f"RSI({_num(p.get('period', 14))}) crosses {d} {_num(p.get('threshold'))}"
    if name in ("macd_crosses_above_signal", "macd_crosses_below_signal"):
        d = "above" if "above" in name else "below"
        return (
            f"MACD({_num(p.get('fast', 12))},{_num(p.get('slow', 26))},{_num(p.get('signal', 9))}) "
            f"crosses {d} its signal line"
        )
    if name in ("ema_crosses_above", "ema_crosses_below", "sma_crosses_above", "sma_crosses_below"):
        ma = name[:3].upper()
        d = "above" if name.endswith("above") else "below"
        return f"the {_num(p.get('fast'))}-period {ma} crosses {d} the {_num(p.get('slow'))}-period {ma}"
    if name == "atr_greater_than_pct":
        return f"ATR({_num(p.get('period', 14))}) is above {_num(p.get('threshold_pct'))}% of price"
    if name == "atr_less_than_pct":
        return f"ATR({_num(p.get('period', 14))}) is below {_num(p.get('threshold_pct'))}% of price"
    if name == "volume_greater_than_avg":
        return (
            f"volume is more than {_num(p.get('multiplier', 1.5))}x its "
            f"{_num(p.get('period', 20))}-bar average"
        )
    if name == "volume_in_top_pct":
        return (
            f"volume is in the top {_num(p.get('top_pct', 10))}% of the last "
            f"{_plural(p.get('period', 60), 'bar')}"
        )
    if name in ("iv_rank_less_than", "iv_rank_greater_than"):
        side = "below" if "less" in name else "above"
        return f"IV rank is {side} {_num(p.get('threshold'))} (hosted data)"
    if name in ("short_interest_less_than", "short_interest_greater_than"):
        side = "below" if "less" in name else "above"
        return f"short interest is {side} {_num(p.get('threshold'))}% of float (hosted data)"
    if name in ("earnings_within", "no_earnings_within"):
        neg = "no " if name.startswith("no_") else ""
        return f"{neg}earnings within {_plural(p.get('days'), 'day')} (hosted data)"
    if name in ("price_new_high", "price_new_low"):
        side = "high" if name.endswith("high") else "low"
        return f"price makes a new {_num(p.get('period', 252))}-bar closing {side}"
    if name in ("gap_up", "gap_down"):
        d = "up" if name == "gap_up" else "down"
        return f"price gaps {d} at least {_num(p.get('min_gap_pct', 2))}% at the open"
    if name in ("up_days", "down_days"):
        d = "higher" if name == "up_days" else "lower"
        return f"the last {_plural(p.get('count'), 'close')} were each {d} than the one before"
    if name in ("price_above_level", "price_below_level"):
        side = "above" if "above" in name else "below"
        return f"price is {side} {_num(p.get('level'))}"
    if name in ("adx_greater_than", "adx_less_than"):
        side = "above" if "greater" in name else "below"
        return f"ADX({_num(p.get('period', 14))}) is {side} {_num(p.get('threshold'))}"
    if name in ("stoch_less_than", "stoch_greater_than"):
        side = "below" if "less" in name else "above"
        return f"stochastic %K({_num(p.get('period', 14))}) is {side} {_num(p.get('threshold'))}"
    if name in ("price_above_vwap", "price_below_vwap"):
        side = "above" if "above" in name else "below"
        return f"price is {side} the {_num(p.get('period', 20))}-bar VWAP"
    if name == "bollinger_squeeze":
        return (
            f"Bollinger band width is in its lowest {_num(p.get('pct', 10))}% "
            f"of the last {_plural(p.get('lookback', 126), 'bar')}"
        )
    if name == "obv_rising":
        return f"on-balance volume is above its {_num(p.get('period', 20))}-bar average"
    if name in ("stoch_crosses_above", "stoch_crosses_below"):
        d = "above" if name.endswith("above") else "below"
        return f"stochastic %K({_num(p.get('period', 14))}) crosses {d} {_num(p.get('threshold'))}"
    return name


def _sizing_text(sizing: dict | None, direction: str = "long") -> str:
    verb = "Sell short" if direction == "short" else "Buy"
    if not sizing:
        return verb
    method = sizing.get("method")
    v = sizing.get("value", 0)
    if method == "percent_of_portfolio":
        return f"{verb} {_num(v * 100)}% of the portfolio"
    if method == "fixed_dollar":
        return f"{verb} ${_num(v)} worth"
    if method == "risk_based":
        kind = "short" if direction == "short" else "position"
        return f"Size the {kind} to risk {_num(v * 100)}% of equity at the stop"
    return verb


def _exit_bits(ex: dict, is_short: bool) -> list:
    bits = []
    if ex.get("stop_loss_pct") is not None:
        bits.append(f"a stop loss {_num(ex['stop_loss_pct'])}% {'above' if is_short else 'below'} entry")
    if ex.get("stop_loss_atr") is not None:
        bits.append(f"a stop {_num(ex['stop_loss_atr'])} ATR {'above' if is_short else 'below'} entry")
    if ex.get("profit_target_pct") is not None:
        bits.append(f"a target {_num(ex['profit_target_pct'])}% {'below' if is_short else 'above'} entry")
    for c in ex.get("conditions") or []:
        bits.append(_condition_text(c))
    if ex.get("hold_bars") is not None:
        bits.append(f"a time exit after {_plural(ex['hold_bars'], 'bar')}")
    return bits


def explain_strategy(strategy: dict) -> str:
    lines: list[str] = []

    if strategy.get("name"):
        lines.append(f"{strategy['name']}.")

    uni = strategy.get("universe", {})
    if uni.get("type") == "prebuilt":
        label = _UNIVERSE_LABELS.get(uni.get("key"), uni.get("key"))
        lines.append(f"Trades {label} on {strategy.get('timeframe', '1d')} bars.")
    elif uni.get("type") == "pair":
        a, b = [str(t).upper() for t in uni.get("tickers", ["?", "?"])]
        form = (
            f"the price ratio {a}/{b}"
            if uni.get("form", "ratio") == "ratio"
            else f"the price difference {a} minus {b}"
        )
        lines.append(
            f"Trades the spread between {a} and {b} ({form}) on "
            f"{strategy.get('timeframe', '1d')} bars — a long position buys {a} and "
            f"shorts {b} outright (the underlyings themselves, not options) in equal "
            "dollar legs; a short position mirrors. Conditions and exits evaluate on "
            "the spread series itself."
        )
    elif uni.get("type") == "dynamic":
        p = uni.get("params", {}) or {}
        lines.append(
            f"Trades the {_num(p.get('count', 50))} highest-dollar-volume tickers in the data "
            f"({_num(p.get('period', 20))}-bar average, membership recomputed monthly on closed "
            f"bars only) on {strategy.get('timeframe', '1d')} bars."
        )
    else:
        tickers = ", ".join(uni.get("tickers", []))
        lines.append(f"Trades {tickers} on {strategy.get('timeframe', '1d')} bars.")

    options = strategy.get("options")
    if options:
        opt = options.get("option", {})
        mgmt = options.get("management") or {}
        risk = strategy.get("risk") or {}
        delta = _num(opt.get("delta", 25))
        dte = _num(opt.get("dte", 45))
        if options.get("form") == "wheel":
            line = (f"Run the wheel: sell the ~{delta}-delta cash-secured put ~{dte} days out; "
                    f"if assigned, sell the ~{delta}-delta covered call against the shares; "
                    "called away means back to selling puts.")
        else:
            otype = opt.get("type")
            width = _num(opt.get("width", 5))
            note = ""
            if otype == "covered_call":
                line = f"Write the ~{delta}-delta covered call ~{dte} days out"
            elif otype == "put_spread":
                line = (f"Sell the ~{delta}-delta put and buy a put {width} points lower "
                        f"(~{dte} days out)")
                note = ("A defined-risk credit put spread: max loss is capped at the "
                        "width minus the credit.")
            elif otype == "call_spread":
                line = (f"Sell the ~{delta}-delta call and buy a call {width} points higher "
                        f"(~{dte} days out)")
                note = ("A defined-risk credit call spread: max loss is capped at the "
                        "width minus the credit.")
            elif otype == "iron_condor":
                line = (f"Sell the ~{delta}-delta put and call, buy wings {width} points "
                        f"further out (~{dte} days out)")
                note = "An iron condor: max loss is capped by the wings."
            elif otype == "straddle":
                line = f"Sell the at-the-money straddle ~{dte} days out"
                note = "Undefined risk until closed."
            elif otype == "strangle":
                line = f"Sell the ~{delta}-delta strangle ~{dte} days out"
                note = "Undefined risk until closed."
            else:
                line = f"Write the ~{delta}-delta cash-secured put ~{dte} days out"
            conds = (options.get("entry") or {}).get("conditions") or []
            if conds:
                joiner = " and " if (options.get("entry") or {}).get("match_logic", "all") == "all" else " or "
                line += " when " + joiner.join(_condition_text(c) for c in conds)
            line += "."
            if note:
                line += " " + note
        lines.append(line)
        bits = []
        if mgmt.get("profit_pct") is not None:
            bits.append(f"close at {_num(mgmt['profit_pct'])}% of the credit captured")
        if mgmt.get("loss_pct") is not None:
            bits.append(f"close if the loss reaches {_num(mgmt['loss_pct'])}% of the credit")
        if mgmt.get("close_dte") is not None:
            bits.append(f"close at {_num(mgmt['close_dte'])} DTE")
        if mgmt.get("roll_dte") is not None:
            bits.append(f"roll at {_num(mgmt['roll_dte'])} DTE")
        if bits:
            lines.append("Management, checked daily: " + "; ".join(bits) + ". Otherwise positions run to expiry, where assignment is decided by moneyness.")
        if "contracts" in risk:
            lines.append(f"Size: {_plural(risk['contracts'], 'contract')} per position.")
        elif "collateral_pct" in risk:
            lines.append(f"Size: puts sized so collateral stays within {_num(risk['collateral_pct'] * 100)}% of equity.")
        return "\n".join(lines)

    ranking = strategy.get("ranking")
    if ranking:
        m = ranking["metric"]
        mp = m.get("params", {}) or {}
        metric_text = {
            "momentum": lambda: f"{_num(mp.get('period'))}-bar momentum" + (
                f" (skipping the last {_num(mp.get('skip'))} bars)" if mp.get("skip") else ""),
            "volatility": lambda: f"{_num(mp.get('period', 20))}-bar volatility",
            "inverse_volatility": lambda: f"inverse {_num(mp.get('period', 20))}-bar volatility",
            "relative_strength": lambda: f"{_num(mp.get('period', 63))}-bar strength relative to the universe",
            "dollar_volume": lambda: f"{_num(mp.get('period', 20))}-bar average dollar volume",
        }.get(m["name"], lambda: m["name"])()
        cadence = {"daily": "Each day", "weekly": "Each week", "monthly": "Each month"}[strategy.get("rebalance", "monthly")]
        pick = "strongest" if ranking.get("select", "top") == "top" else "lowest-ranked"
        line = (f"{cadence}, hold the {_num(ranking.get('count'))} names with the "
                f"{'highest' if ranking.get('select') == 'top' else 'lowest'} {metric_text}")
        where = (ranking.get("where") or {}).get("conditions") or []
        if where:
            joiner = " and " if (ranking.get("where") or {}).get("match_logic", "all") == "all" else " or "
            line += ", considering only names where " + joiner.join(_condition_text(c) for c in where)
        weighting = ranking.get("weighting") or {}
        if weighting.get("method") == "by_metric":
            wm = weighting["metric"]
            line += f", weighted by {wm['name'].replace('_', ' ')}"
        else:
            line += ", equally weighted"
        lines.append(line + ". Positions change only at rebalance closes; names that no longer qualify are sold.")
        risk = strategy.get("risk") or {}
        if "max_position_pct" in risk:
            lines.append(f"No single position above {_num(risk['max_position_pct'] * 100)}% of equity.")
        return "\n".join(lines)

    direction = strategy.get("direction", "long")
    rule_dicts = strategy.get("rules") or [
        {**strategy["entry"], "position_sizing": strategy.get("position_sizing")}
    ]
    rule_lines = []
    for r in rule_dicts:
        joiner = " and " if r.get("match_logic", "all") == "all" else " or "
        conds = joiner.join(_condition_text(c) for c in r["conditions"])
        rule_lines.append(f"{_sizing_text(r.get('position_sizing'), direction)} when {conds}")
    lines.append(". Or: ".join(rule_lines) +
                 ". Entries trigger once per signal, on the bar a rule becomes true; one position at a time.")
    p = strategy.get("partial_exit")
    if p:
        p_bits = []
        if p.get("profit_target_pct") is not None:
            side = "below" if direction == "short" else "above"
            p_bits.append(f"{_num(p['profit_target_pct'])}% {side} entry")
        for c in p.get("conditions") or []:
            p_bits.append(_condition_text(c))
        if p.get("hold_bars") is not None:
            p_bits.append(f"after {_plural(p['hold_bars'], 'bar')}")
        lines.append("Takes half off (once per position) at the first of: " + "; ".join(p_bits) + ".")

    if strategy.get("exits"):
        for label, exd, ishort in (("Longs exit", strategy["exits"]["long"], False),
                                   ("Shorts cover", strategy["exits"]["short"], True)):
            bits = _exit_bits(exd, ishort)
            if bits:
                lines.append(f"{label} on the first of: " + "; ".join(bits) + ".")
        risk = strategy.get("risk") or {}
        risk_parts: list[str] = []
        if "max_positions" in risk:
            risk_parts.append(f"at most {_plural(risk['max_positions'], 'open position')}")
        if "cooldown_bars" in risk:
            risk_parts.append(f"no re-entry for {_plural(risk['cooldown_bars'], 'bar')} after an exit")
        if risk.get("reverse"):
            risk_parts.append("an opposite signal closes the position and reverses the same bar")
        if risk_parts:
            lines.append("Risk guards: " + "; ".join(risk_parts) + ".")
        return "\n".join(lines)

    ex = strategy.get("exit", {}) or {}
    exits: list[str] = []
    is_short = direction == "short"
    if ex.get("stop_loss_pct") is not None:
        side = "above" if is_short else "below"
        exits.append(f"a stop loss {_num(ex['stop_loss_pct'])}% {side} entry")
    if ex.get("profit_target_pct") is not None:
        side = "below" if is_short else "above"
        exits.append(f"a profit target {_num(ex['profit_target_pct'])}% {side} entry")
    if ex.get("trailing_stop_pct") is not None:
        mark = "low" if is_short else "high"
        exits.append(f"a trailing stop {_num(ex['trailing_stop_pct'])}% off the {mark}")
    if ex.get("stop_loss_atr") is not None:
        side = "above" if is_short else "below"
        exits.append(f"a stop {_num(ex['stop_loss_atr'])} ATR {side} entry")
    if ex.get("profit_target_atr") is not None:
        side = "below" if is_short else "above"
        exits.append(f"a target {_num(ex['profit_target_atr'])} ATR {side} entry")
    if ex.get("trailing_stop_atr") is not None:
        mark = "low" if is_short else "high"
        exits.append(f"a chandelier stop {_num(ex['trailing_stop_atr'])} ATR off the {mark}")
    if ex.get("breakeven_trigger_pct") is not None:
        d = "in the trade's favor" if is_short else "up"
        exits.append(f"a breakeven stop armed once {_num(ex['breakeven_trigger_pct'])}% {d}")
    for c in ex.get("conditions") or []:
        exits.append(_condition_text(c))
    if ex.get("hold_bars") is not None:
        exits.append(f"a time exit after {_plural(ex['hold_bars'], 'bar')}")
    if exits:
        lines.append("Exits on the first of: " + "; ".join(exits) +
                     ". Checked at each bar close in that order.")

    risk = strategy.get("risk") or {}
    risk_parts: list[str] = []
    if "max_positions" in risk:
        risk_parts.append(f"at most {_plural(risk['max_positions'], 'open position')}")
    if "max_position_pct" in risk:
        risk_parts.append(f"no single position above {_num(risk['max_position_pct'] * 100)}% of equity")
    if "daily_loss_limit_usd" in risk:
        risk_parts.append(f"new entries halt after ${_num(risk['daily_loss_limit_usd'])} of daily losses")
    if "cooldown_bars" in risk:
        risk_parts.append(f"no re-entry for {_plural(risk['cooldown_bars'], 'bar')} after an exit")
    if risk.get("reverse"):
        risk_parts.append("an opposite signal closes the position and reverses the same bar")
    if risk_parts:
        lines.append("Risk guards: " + "; ".join(risk_parts) + ".")

    return "\n".join(lines)
