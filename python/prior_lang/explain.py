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
    name = cond["condition"]
    p = cond.get("params", {}) or {}

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


def explain_strategy(strategy: dict) -> str:
    lines: list[str] = []

    if strategy.get("name"):
        lines.append(f"{strategy['name']}.")

    uni = strategy.get("universe", {})
    if uni.get("type") == "prebuilt":
        label = _UNIVERSE_LABELS.get(uni.get("key"), uni.get("key"))
        lines.append(f"Trades {label} on {strategy.get('timeframe', '1d')} bars.")
    else:
        tickers = ", ".join(uni.get("tickers", []))
        lines.append(f"Trades {tickers} on {strategy.get('timeframe', '1d')} bars.")

    direction = strategy.get("direction", "long")
    entry = strategy["entry"]
    joiner = " and " if entry.get("match_logic", "all") == "all" else " or "
    conds = joiner.join(_condition_text(c) for c in entry["conditions"])
    lines.append(f"{_sizing_text(strategy.get('position_sizing'), direction)} when {conds}. "
                 "Entries trigger once per signal, on the bar the condition becomes true.")

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
    if risk_parts:
        lines.append("Risk guards: " + "; ".join(risk_parts) + ".")

    return "\n".join(lines)
