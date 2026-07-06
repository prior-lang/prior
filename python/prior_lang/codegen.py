"""Reference code generator: strategy JSON → runnable Python.

Emits a `generate_signals(df) -> pd.Series` (0/1 long/flat) from the
compiled strategy JSON. The emitted code references only pd/np/math —
no imports — so it runs in restricted execution environments.

Semantics (normative, see spec/SPEC.md §6):
  - entries fire on the rising edge of the combined entry condition
  - indicator warmup (NaN) evaluates false
  - bar-close evaluation throughout
  - exit precedence within a bar: stop → target → trailing → condition
    exits → time ([after N bars])

When the only exit is time-based, the emitted code is a pure vectorized
form; priced/conditional exits are path-dependent (entry price, high-water
mark), so those strategies emit a single explicit walk over the bars.

Conforming runners must produce identical signals for identical inputs.
"""

from __future__ import annotations

from typing import Any, Dict, List

DEFAULT_HOLD_BARS = 5


def _hcode(condition: Dict[str, Any]) -> str:
    """Emit the boolean Series expression for one condition. Returns a
    Python source snippet that assigns to `cond` and is safe to inline."""
    ctype = condition["type"]
    p = condition.get("params", {}) or {}

    if ctype == "price_above_ema":
        n = int(p["period"])
        return (
            f"ema = close.ewm(span={n}, adjust=False, min_periods={n}).mean()\n"
            f"    cond = (close > ema).fillna(False)"
        )
    if ctype == "price_below_ema":
        n = int(p["period"])
        return (
            f"ema = close.ewm(span={n}, adjust=False, min_periods={n}).mean()\n"
            f"    cond = (close < ema).fillna(False)"
        )
    if ctype == "price_above_sma":
        n = int(p["period"])
        return (
            f"sma = close.rolling({n}, min_periods={n}).mean()\n"
            f"    cond = (close > sma).fillna(False)"
        )
    if ctype == "price_below_sma":
        n = int(p["period"])
        return (
            f"sma = close.rolling({n}, min_periods={n}).mean()\n"
            f"    cond = (close < sma).fillna(False)"
        )
    if ctype == "rsi_less_than":
        n = int(p.get("period", 14))
        t = float(p["threshold"])
        return (
            f"delta = close.diff()\n"
            f"    gain = delta.clip(lower=0).rolling({n}, min_periods={n}).mean()\n"
            f"    loss = (-delta.clip(upper=0)).rolling({n}, min_periods={n}).mean()\n"
            f"    rs = gain / loss.replace(0, np.nan)\n"
            f"    rsi = 100 - (100 / (1 + rs))\n"
            f"    cond = (rsi < {t}).fillna(False)"
        )
    if ctype == "rsi_greater_than":
        n = int(p.get("period", 14))
        t = float(p["threshold"])
        return (
            f"delta = close.diff()\n"
            f"    gain = delta.clip(lower=0).rolling({n}, min_periods={n}).mean()\n"
            f"    loss = (-delta.clip(upper=0)).rolling({n}, min_periods={n}).mean()\n"
            f"    rs = gain / loss.replace(0, np.nan)\n"
            f"    rsi = 100 - (100 / (1 + rs))\n"
            f"    cond = (rsi > {t}).fillna(False)"
        )
    if ctype == "rsi_crosses_above":
        n = int(p.get("period", 14))
        t = float(p["threshold"])
        return (
            f"delta = close.diff()\n"
            f"    gain = delta.clip(lower=0).rolling({n}, min_periods={n}).mean()\n"
            f"    loss = (-delta.clip(upper=0)).rolling({n}, min_periods={n}).mean()\n"
            f"    rs = gain / loss.replace(0, np.nan)\n"
            f"    rsi = 100 - (100 / (1 + rs))\n"
            f"    prev = rsi.shift(1)\n"
            f"    cond = ((prev <= {t}) & (rsi > {t})).fillna(False)"
        )
    if ctype == "rsi_crosses_below":
        n = int(p.get("period", 14))
        t = float(p["threshold"])
        return (
            f"delta = close.diff()\n"
            f"    gain = delta.clip(lower=0).rolling({n}, min_periods={n}).mean()\n"
            f"    loss = (-delta.clip(upper=0)).rolling({n}, min_periods={n}).mean()\n"
            f"    rs = gain / loss.replace(0, np.nan)\n"
            f"    rsi = 100 - (100 / (1 + rs))\n"
            f"    prev = rsi.shift(1)\n"
            f"    cond = ((prev >= {t}) & (rsi < {t})).fillna(False)"
        )
    if ctype == "macd_crosses_above_signal":
        fast = int(p.get("fast", 12))
        slow = int(p.get("slow", 26))
        sig = int(p.get("signal", 9))
        return (
            f"ema_fast = close.ewm(span={fast}, adjust=False, min_periods={fast}).mean()\n"
            f"    ema_slow = close.ewm(span={slow}, adjust=False, min_periods={slow}).mean()\n"
            f"    macd_line = ema_fast - ema_slow\n"
            f"    signal_line = macd_line.ewm(span={sig}, adjust=False, min_periods={sig}).mean()\n"
            f"    diff = macd_line - signal_line\n"
            f"    cond = ((diff.shift(1) <= 0) & (diff > 0)).fillna(False)"
        )
    if ctype == "macd_crosses_below_signal":
        fast = int(p.get("fast", 12))
        slow = int(p.get("slow", 26))
        sig = int(p.get("signal", 9))
        return (
            f"ema_fast = close.ewm(span={fast}, adjust=False, min_periods={fast}).mean()\n"
            f"    ema_slow = close.ewm(span={slow}, adjust=False, min_periods={slow}).mean()\n"
            f"    macd_line = ema_fast - ema_slow\n"
            f"    signal_line = macd_line.ewm(span={sig}, adjust=False, min_periods={sig}).mean()\n"
            f"    diff = macd_line - signal_line\n"
            f"    cond = ((diff.shift(1) >= 0) & (diff < 0)).fillna(False)"
        )
    if ctype == "ema_crosses_above":
        fast = int(p.get("fast", 50))
        slow = int(p.get("slow", 200))
        return (
            f"ema_fast = close.ewm(span={fast}, adjust=False, min_periods={fast}).mean()\n"
            f"    ema_slow = close.ewm(span={slow}, adjust=False, min_periods={slow}).mean()\n"
            f"    diff = ema_fast - ema_slow\n"
            f"    cond = ((diff.shift(1) <= 0) & (diff > 0)).fillna(False)"
        )
    if ctype == "ema_crosses_below":
        fast = int(p.get("fast", 50))
        slow = int(p.get("slow", 200))
        return (
            f"ema_fast = close.ewm(span={fast}, adjust=False, min_periods={fast}).mean()\n"
            f"    ema_slow = close.ewm(span={slow}, adjust=False, min_periods={slow}).mean()\n"
            f"    diff = ema_fast - ema_slow\n"
            f"    cond = ((diff.shift(1) >= 0) & (diff < 0)).fillna(False)"
        )
    if ctype == "sma_crosses_above":
        fast = int(p.get("fast", 50))
        slow = int(p.get("slow", 200))
        return (
            f"sma_fast = close.rolling({fast}, min_periods={fast}).mean()\n"
            f"    sma_slow = close.rolling({slow}, min_periods={slow}).mean()\n"
            f"    diff = sma_fast - sma_slow\n"
            f"    cond = ((diff.shift(1) <= 0) & (diff > 0)).fillna(False)"
        )
    if ctype == "sma_crosses_below":
        fast = int(p.get("fast", 50))
        slow = int(p.get("slow", 200))
        return (
            f"sma_fast = close.rolling({fast}, min_periods={fast}).mean()\n"
            f"    sma_slow = close.rolling({slow}, min_periods={slow}).mean()\n"
            f"    diff = sma_fast - sma_slow\n"
            f"    cond = ((diff.shift(1) >= 0) & (diff < 0)).fillna(False)"
        )
    if ctype == "price_at_bollinger_band":
        n = int(p.get("period", 20))
        num_std = float(p.get("num_std", 2.0))
        which = p.get("band", "upper")
        expr = ""
        if which == "upper":
            expr = "cond = (close >= upper).fillna(False)"
        elif which == "lower":
            expr = "cond = (close <= lower).fillna(False)"
        else:  # middle
            expr = "cond = ((close - mid).abs() / mid < 0.005).fillna(False)"
        return (
            f"mid = close.rolling({n}, min_periods={n}).mean()\n"
            f"    std = close.rolling({n}, min_periods={n}).std()\n"
            f"    upper = mid + {num_std} * std\n"
            f"    lower = mid - {num_std} * std\n"
            f"    {expr}"
        )
    if ctype == "atr_greater_than_pct":
        n = int(p.get("period", 14))
        t = float(p["threshold_pct"])
        return (
            f"prev_close = close.shift(1)\n"
            f"    tr = pd.concat([(df['high'] - df['low']),\n"
            f"                    (df['high'] - prev_close).abs(),\n"
            f"                    (df['low'] - prev_close).abs()], axis=1).max(axis=1)\n"
            f"    atr = tr.rolling({n}, min_periods={n}).mean()\n"
            f"    atr_pct = (atr / close.replace(0, np.nan)) * 100\n"
            f"    cond = (atr_pct > {t}).fillna(False)"
        )
    if ctype == "atr_less_than_pct":
        n = int(p.get("period", 14))
        t = float(p["threshold_pct"])
        return (
            f"prev_close = close.shift(1)\n"
            f"    tr = pd.concat([(df['high'] - df['low']),\n"
            f"                    (df['high'] - prev_close).abs(),\n"
            f"                    (df['low'] - prev_close).abs()], axis=1).max(axis=1)\n"
            f"    atr = tr.rolling({n}, min_periods={n}).mean()\n"
            f"    atr_pct = (atr / close.replace(0, np.nan)) * 100\n"
            f"    cond = (atr_pct < {t}).fillna(False)"
        )
    if ctype == "volume_greater_than_avg":
        n = int(p.get("period", 20))
        m = float(p.get("multiplier", 1.5))
        return (
            f"vol = df['volume']\n"
            f"    avg = vol.rolling({n}, min_periods={n}).mean()\n"
            f"    cond = (vol > avg * {m}).fillna(False)"
        )
    if ctype == "volume_in_top_pct":
        n = int(p.get("period", 60))
        top_pct = float(p.get("top_pct", 10.0))
        q = 1.0 - top_pct / 100.0
        return (
            f"vol = df['volume']\n"
            f"    thr = vol.rolling({n}, min_periods={n}).quantile({q})\n"
            f"    cond = (vol >= thr).fillna(False)"
        )

    if ctype == "price_new_high":
        n = int(p.get("period", 252))
        return (
            f"prior_max = close.shift(1).rolling({n}, min_periods={n}).max()\n"
            f"    cond = (close >= prior_max).fillna(False)"
        )
    if ctype == "price_new_low":
        n = int(p.get("period", 252))
        return (
            f"prior_min = close.shift(1).rolling({n}, min_periods={n}).min()\n"
            f"    cond = (close <= prior_min).fillna(False)"
        )
    if ctype == "gap_up":
        g = float(p.get("min_gap_pct", 2.0))
        return (
            f"gap_pct = (df['open'] / close.shift(1) - 1) * 100\n"
            f"    cond = (gap_pct >= {g}).fillna(False)"
        )
    if ctype == "gap_down":
        g = float(p.get("min_gap_pct", 2.0))
        return (
            f"gap_pct = (df['open'] / close.shift(1) - 1) * 100\n"
            f"    cond = (gap_pct <= -{g}).fillna(False)"
        )
    if ctype == "up_days":
        n = int(p["count"])
        return (
            f"ups = (close.diff() > 0).rolling({n}, min_periods={n}).sum()\n"
            f"    cond = (ups == {n}).fillna(False)"
        )
    if ctype == "down_days":
        n = int(p["count"])
        return (
            f"downs = (close.diff() < 0).rolling({n}, min_periods={n}).sum()\n"
            f"    cond = (downs == {n}).fillna(False)"
        )
    if ctype == "price_above_level":
        lvl = float(p["level"])
        return f"cond = (close > {lvl}).fillna(False)"
    if ctype == "price_below_level":
        lvl = float(p["level"])
        return f"cond = (close < {lvl}).fillna(False)"
    if ctype in ("adx_greater_than", "adx_less_than"):
        n = int(p.get("period", 14))
        t = float(p["threshold"])
        op = ">" if ctype == "adx_greater_than" else "<"
        return (
            f"prev_close = close.shift(1)\n"
            f"    tr = pd.concat([(df['high'] - df['low']),\n"
            f"                    (df['high'] - prev_close).abs(),\n"
            f"                    (df['low'] - prev_close).abs()], axis=1).max(axis=1)\n"
            f"    up_move = df['high'].diff()\n"
            f"    down_move = -df['low'].diff()\n"
            f"    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)\n"
            f"    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)\n"
            f"    atr = tr.ewm(alpha=1 / {n}, adjust=False, min_periods={n}).mean()\n"
            f"    plus_di = 100 * plus_dm.ewm(alpha=1 / {n}, adjust=False, min_periods={n}).mean() / atr\n"
            f"    minus_di = 100 * minus_dm.ewm(alpha=1 / {n}, adjust=False, min_periods={n}).mean() / atr\n"
            f"    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)\n"
            f"    adx = dx.ewm(alpha=1 / {n}, adjust=False, min_periods={n}).mean()\n"
            f"    cond = (adx {op} {t}).fillna(False)"
        )
    if ctype in ("stoch_less_than", "stoch_greater_than"):
        n = int(p.get("period", 14))
        s = int(p.get("smooth", 3))
        t = float(p["threshold"])
        op = "<" if ctype == "stoch_less_than" else ">"
        return (
            f"low_min = df['low'].rolling({n}, min_periods={n}).min()\n"
            f"    high_max = df['high'].rolling({n}, min_periods={n}).max()\n"
            f"    k_fast = 100 * (close - low_min) / (high_max - low_min).replace(0, np.nan)\n"
            f"    k = k_fast.rolling({s}, min_periods={s}).mean()\n"
            f"    cond = (k {op} {t}).fillna(False)"
        )
    if ctype in ("stoch_crosses_above", "stoch_crosses_below"):
        n = int(p.get("period", 14))
        s = int(p.get("smooth", 3))
        t = float(p["threshold"])
        if ctype == "stoch_crosses_above":
            expr = f"cond = ((prev <= {t}) & (k > {t})).fillna(False)"
        else:
            expr = f"cond = ((prev >= {t}) & (k < {t})).fillna(False)"
        return (
            f"low_min = df['low'].rolling({n}, min_periods={n}).min()\n"
            f"    high_max = df['high'].rolling({n}, min_periods={n}).max()\n"
            f"    k_fast = 100 * (close - low_min) / (high_max - low_min).replace(0, np.nan)\n"
            f"    k = k_fast.rolling({s}, min_periods={s}).mean()\n"
            f"    prev = k.shift(1)\n"
            f"    {expr}"
        )

    if ctype in ("price_above_vwap", "price_below_vwap"):
        n = int(p.get("period", 20))
        op = ">" if ctype == "price_above_vwap" else "<"
        return (
            f"tp = (df['high'] + df['low'] + close) / 3\n"
            f"    pv = (tp * df['volume']).rolling({n}, min_periods={n}).sum()\n"
            f"    v = df['volume'].rolling({n}, min_periods={n}).sum()\n"
            f"    vwap = pv / v.replace(0, np.nan)\n"
            f"    cond = (close {op} vwap).fillna(False)"
        )
    if ctype == "bollinger_squeeze":
        n = int(p.get("period", 20))
        num_std = float(p.get("num_std", 2.0))
        lookback = int(p.get("lookback", 126))
        pct = float(p.get("pct", 10.0))
        q = pct / 100.0
        return (
            f"mid = close.rolling({n}, min_periods={n}).mean()\n"
            f"    std = close.rolling({n}, min_periods={n}).std()\n"
            f"    width = (2 * {num_std} * std) / mid.replace(0, np.nan)\n"
            f"    thr = width.rolling({lookback}, min_periods={lookback}).quantile({q})\n"
            f"    cond = (width <= thr).fillna(False)"
        )
    if ctype == "obv_rising":
        n = int(p.get("period", 20))
        return (
            f"direction = np.sign(close.diff()).fillna(0)\n"
            f"    obv = (direction * df['volume']).cumsum()\n"
            f"    obv_avg = obv.rolling({n}, min_periods={n}).mean()\n"
            f"    cond = (obv > obv_avg).fillna(False)"
        )

    raise ValueError(f"Unknown condition type: {ctype}")


def _condition_blocks(
    conditions: List[Dict[str, Any]], match_logic: str, var_prefix: str = "cond"
) -> tuple[str, str]:
    op = "&" if match_logic == "all" else "|"
    identity = "True" if match_logic == "all" else "False"

    blocks: List[str] = []
    combine_names: List[str] = []
    for i, cond in enumerate(conditions):
        snippet = _hcode(cond)
        snippet = snippet.replace("cond =", f"{var_prefix}_{i} =")
        blocks.append(f"    # {var_prefix} {i + 1}: {cond['type']}\n    {snippet}")
        combine_names.append(f"{var_prefix}_{i}")

    combined_expr = f" {op} ".join(combine_names) if combine_names else identity
    return "\n\n".join(blocks), combined_expr


def generate_strategy_code(
    conditions: List[Dict[str, Any]],
    match_logic: str = "all",
    hold_bars: int = DEFAULT_HOLD_BARS,
    exit_conditions: List[Dict[str, Any]] | None = None,
    stop_loss_pct: float | None = None,
    profit_target_pct: float | None = None,
    trailing_stop_pct: float | None = None,
    stop_loss_atr: float | None = None,
    profit_target_atr: float | None = None,
    trailing_stop_atr: float | None = None,
    breakeven_trigger_pct: float | None = None,
    direction: str = "long",
    position_sizing: Dict[str, Any] | None = None,
    risk: Dict[str, Any] | None = None,
) -> str:
    """Build the strategy code string.

    Exit rules: each of stop/target/trailing takes EITHER a percent or an
    ATR multiple (both set is an error). Percent exits measure from the
    entry close; ATR stops/targets freeze the 14-period ATR at entry, and
    the ATR trailing stop is a chandelier (current ATR off the watermark).
    breakeven_trigger_pct arms once price moves N% in the trade's favor,
    after which a return to the entry price exits.

    Exit precedence within a bar: stop -> breakeven -> target -> trailing
    -> condition exits -> hold_bars. Bar-close evaluation; entries fire on
    the rising edge. direction="short" emits 0/-1 signals with all exits
    mirrored. Long-only, hold-only strategies emit the original vectorized
    form, byte-stable with pre-Phase-B output.
    """
    if not conditions:
        raise ValueError("At least one condition is required")
    if direction not in ("long", "short"):
        raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")
    for pct_v, atr_v, label in (
        (stop_loss_pct, stop_loss_atr, "stop"),
        (profit_target_pct, profit_target_atr, "target"),
        (trailing_stop_pct, trailing_stop_atr, "trailing"),
    ):
        if pct_v is not None and atr_v is not None:
            raise ValueError(f"{label}: give a percent or an ATR multiple, not both")

    entry_body, entry_expr = _condition_blocks(conditions, match_logic, "cond")
    hold = int(max(1, hold_bars))
    is_short = direction == "short"

    has_priced_exits = any(
        v is not None
        for v in (stop_loss_pct, profit_target_pct, trailing_stop_pct,
                  stop_loss_atr, profit_target_atr, trailing_stop_atr,
                  breakeven_trigger_pct)
    )
    has_cond_exits = bool(exit_conditions)

    metadata = ""
    if position_sizing:
        metadata += f"POSITION_SIZING = {position_sizing!r}\n"
    if risk:
        metadata += f"RISK = {risk!r}\n"
    if metadata:
        metadata += "\n\n"

    if not has_priced_exits and not has_cond_exits:
        hold_phrase = f"stays short for {hold} bars" if is_short else f"holds for {hold} bars"
        signals_expr = (
            "entries.astype(int).rolling(%d, min_periods=1).max().fillna(0).astype(int)" % hold
        )
        if is_short:
            signals_expr = "(%s * -1)" % signals_expr
        return f'''{metadata}def generate_signals(df):
    """Auto-generated strategy. Mirrors {len(conditions)} condition(s)
    combined with {match_logic.upper()}. Enters on the rising edge of the
    combined match and {hold_phrase}."""
    close = df["close"]

{entry_body}

    combined = ({entry_expr}).fillna(False)
    entries = combined & ~combined.shift(1).fillna(False)
    signals = {signals_expr}
    return signals
'''

    exit_body = ""
    exit_expr = "False"
    if has_cond_exits:
        exit_body, exit_expr = _condition_blocks(exit_conditions, "any", "xcond")
        exit_body = "\n" + exit_body + "\n"
        exit_series = f"    exit_cond = ({exit_expr}).fillna(False)\n"
    else:
        exit_series = "    exit_cond = pd.Series(False, index=df.index)\n"

    stop = float(stop_loss_pct) if stop_loss_pct is not None else 0.0
    target = float(profit_target_pct) if profit_target_pct is not None else 0.0
    trail = float(trailing_stop_pct) if trailing_stop_pct is not None else 0.0
    stop_a = float(stop_loss_atr) if stop_loss_atr is not None else 0.0
    target_a = float(profit_target_atr) if profit_target_atr is not None else 0.0
    trail_a = float(trailing_stop_atr) if trailing_stop_atr is not None else 0.0
    be = float(breakeven_trigger_pct) if breakeven_trigger_pct is not None else 0.0

    needs_atr = bool(stop_a or target_a or trail_a)

    exit_desc_parts = []
    if stop:
        exit_desc_parts.append(f"stop {stop}%")
    if stop_a:
        exit_desc_parts.append(f"stop {stop_a} ATR")
    if be:
        exit_desc_parts.append(f"breakeven at {be}%")
    if target:
        exit_desc_parts.append(f"target {target}%")
    if target_a:
        exit_desc_parts.append(f"target {target_a} ATR")
    if trail:
        exit_desc_parts.append(f"trailing {trail}%")
    if trail_a:
        exit_desc_parts.append(f"trailing {trail_a} ATR (chandelier)")
    if has_cond_exits:
        exit_desc_parts.append(f"{len(exit_conditions)} exit condition(s)")
    exit_desc_parts.append(f"max {hold} bars")
    exit_desc = ", ".join(exit_desc_parts)

    if is_short:
        sig_val = "-1"
        wm_cmp = "<"
        enter_phrase = "Enters short on the rising edge"
        stop_chk = f"px >= entry_px * (1 + {stop} / 100.0)"
        target_chk = f"px <= entry_px * (1 - {target} / 100.0)"
        trail_chk = f"px >= hwm * (1 + {trail} / 100.0)"
        stop_a_chk = f"not np.isnan(entry_atr) and px >= entry_px + {stop_a} * entry_atr"
        target_a_chk = f"not np.isnan(entry_atr) and px <= entry_px - {target_a} * entry_atr"
        trail_a_chk = f"not np.isnan(atr_arr[i]) and px >= hwm + {trail_a} * atr_arr[i]"
        be_arm_chk = f"px <= entry_px * (1 - {be} / 100.0)"
        be_exit_chk = "px >= entry_px"
    else:
        sig_val = "1"
        wm_cmp = ">"
        enter_phrase = "Enters on the rising edge"
        stop_chk = f"px <= entry_px * (1 - {stop} / 100.0)"
        target_chk = f"px >= entry_px * (1 + {target} / 100.0)"
        trail_chk = f"px <= hwm * (1 - {trail} / 100.0)"
        stop_a_chk = f"not np.isnan(entry_atr) and px <= entry_px - {stop_a} * entry_atr"
        target_a_chk = f"not np.isnan(entry_atr) and px >= entry_px + {target_a} * entry_atr"
        trail_a_chk = f"not np.isnan(atr_arr[i]) and px <= hwm - {trail_a} * atr_arr[i]"
        be_arm_chk = f"px >= entry_px * (1 + {be} / 100.0)"
        be_exit_chk = "px <= entry_px"

    atr_block = ""
    atr_init = ""
    entry_atr_line = ""
    if needs_atr:
        atr_block = (
            "\n    prev_close_x = close.shift(1)\n"
            "    tr_x = pd.concat([(df['high'] - df['low']),\n"
            "                    (df['high'] - prev_close_x).abs(),\n"
            "                    (df['low'] - prev_close_x).abs()], axis=1).max(axis=1)\n"
            "    atr_x = tr_x.rolling(14, min_periods=14).mean()\n"
            "    atr_arr = atr_x.to_numpy()\n"
        )
        atr_init = "\n    entry_atr = float('nan')"
        entry_atr_line = "\n                entry_atr = atr_arr[i]"

    be_init = ""
    be_reset_line = ""
    be_arm_line = ""
    if be:
        be_init = "\n    be_armed = False"
        be_reset_line = "\n                be_armed = False"
        be_arm_line = f"\n        if not be_armed and {be_arm_chk}:\n            be_armed = True"

    checks = []
    if stop:
        checks.append(stop_chk)
    if stop_a:
        checks.append(stop_a_chk)
    if be:
        checks.append(f"be_armed and {be_exit_chk}")
    if target:
        checks.append(target_chk)
    if target_a:
        checks.append(target_a_chk)
    if trail:
        checks.append(trail_chk)
    if trail_a:
        checks.append(trail_a_chk)
    checks.append("exit_arr[i]")
    checks.append(f"bars_held >= {hold}")

    chain_lines = []
    for idx, chk in enumerate(checks):
        kw = "if" if idx == 0 else "elif"
        chain_lines.append(f"        {kw} {chk}:")
        chain_lines.append("            exit_now = True")
    exit_chain = "\n".join(chain_lines)

    return f'''{metadata}def generate_signals(df):
    """Auto-generated strategy. Mirrors {len(conditions)} entry
    condition(s) combined with {match_logic.upper()}. {enter_phrase};
    exits on first of: {exit_desc}. Bar-close evaluation; exit precedence
    stop -> breakeven -> target -> trailing -> conditions -> time."""
    close = df["close"]

{entry_body}

    combined = ({entry_expr}).fillna(False)
    entries = combined & ~combined.shift(1).fillna(False)
{exit_body}
{exit_series}{atr_block}
    entries_arr = entries.to_numpy()
    exit_arr = exit_cond.to_numpy()
    close_arr = close.to_numpy()
    n = len(df)
    sig = np.zeros(n, dtype=int)
    in_pos = False
    entry_px = 0.0
    hwm = 0.0
    bars_held = 0{atr_init}{be_init}
    for i in range(n):
        if not in_pos:
            if entries_arr[i]:
                in_pos = True
                entry_px = close_arr[i]
                hwm = close_arr[i]
                bars_held = 0{entry_atr_line}{be_reset_line}
                sig[i] = {sig_val}
            continue
        bars_held += 1
        px = close_arr[i]
        if px {wm_cmp} hwm:
            hwm = px{be_arm_line}
        exit_now = False
{exit_chain}
        if exit_now:
            in_pos = False
            sig[i] = 0
        else:
            sig[i] = {sig_val}
    return pd.Series(sig, index=df.index)
'''



def _metric_code(metric: Dict[str, Any]) -> str:
    """Emit the body of a per-ticker metric function: df -> pd.Series."""
    name = metric["name"]
    p = metric.get("params", {}) or {}

    if name == "momentum":
        n = int(p["period"])
        skip = int(p.get("skip", 0))
        if skip:
            return f"    return close.shift({skip}) / close.shift({n}) - 1"
        return f"    return close / close.shift({n}) - 1"
    if name == "volatility":
        n = int(p.get("period", 20))
        return f"    return close.pct_change().rolling({n}, min_periods={n}).std() * (252 ** 0.5)"
    if name == "inverse_volatility":
        n = int(p.get("period", 20))
        return (
            f"    vol = close.pct_change().rolling({n}, min_periods={n}).std() * (252 ** 0.5)\n"
            f"    return 1.0 / vol.replace(0, np.nan)"
        )
    if name == "relative_strength":
        n = int(p.get("period", 63))
        # Cross-sectional demeaning happens in generate_weights.
        return f"    return close / close.shift({n}) - 1"
    if name == "dollar_volume":
        n = int(p.get("period", 20))
        return f"    return (close * df['volume']).rolling({n}, min_periods={n}).mean()"
    if name == "rsi":
        n = int(p.get("period", 14))
        return (
            f"    delta = close.diff()\n"
            f"    gain = delta.clip(lower=0).rolling({n}, min_periods={n}).mean()\n"
            f"    loss = (-delta.clip(upper=0)).rolling({n}, min_periods={n}).mean()\n"
            f"    rs = gain / loss.replace(0, np.nan)\n"
            f"    return 100 - (100 / (1 + rs))"
        )
    if name == "adx":
        n = int(p.get("period", 14))
        return (
            f"    prev_close = close.shift(1)\n"
            f"    tr = pd.concat([(df['high'] - df['low']),\n"
            f"                    (df['high'] - prev_close).abs(),\n"
            f"                    (df['low'] - prev_close).abs()], axis=1).max(axis=1)\n"
            f"    up_move = df['high'].diff()\n"
            f"    down_move = -df['low'].diff()\n"
            f"    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)\n"
            f"    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)\n"
            f"    atr = tr.ewm(alpha=1 / {n}, adjust=False, min_periods={n}).mean()\n"
            f"    plus_di = 100 * plus_dm.ewm(alpha=1 / {n}, adjust=False, min_periods={n}).mean() / atr\n"
            f"    minus_di = 100 * minus_dm.ewm(alpha=1 / {n}, adjust=False, min_periods={n}).mean() / atr\n"
            f"    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)\n"
            f"    return dx.ewm(alpha=1 / {n}, adjust=False, min_periods={n}).mean()"
        )
    if name == "stoch":
        n = int(p.get("period", 14))
        s = int(p.get("smooth", 3))
        return (
            f"    low_min = df['low'].rolling({n}, min_periods={n}).min()\n"
            f"    high_max = df['high'].rolling({n}, min_periods={n}).max()\n"
            f"    k_fast = 100 * (close - low_min) / (high_max - low_min).replace(0, np.nan)\n"
            f"    return k_fast.rolling({s}, min_periods={s}).mean()"
        )
    raise ValueError(f"Unknown rank metric: {name}")


def generate_ranking_code(
    metric: Dict[str, Any],
    select: str = "top",
    count: int = 5,
    rebalance: str = "monthly",
    where_conditions: List[Dict[str, Any]] | None = None,
    where_logic: str = "all",
    weighting: Dict[str, Any] | None = None,
    max_position_pct: float | None = None,
) -> str:
    """Emit generate_weights(panel) for a ranking (hold) strategy.

    panel: dict[ticker -> OHLCV DataFrame]. Returns DataFrame [date x
    ticker] of portfolio weights; rows sum to <= 1 (shortfall is cash).
    Rebalance decisions at the close of the last bar of each period;
    ties break alphabetically; NaN metric or a failed where-filter means
    ineligible. Universes are today's constituents — long histories
    inherit survivorship bias (documented in the spec).
    """
    if select not in ("top", "bottom"):
        raise ValueError(f"select must be 'top' or 'bottom', got {select!r}")
    if rebalance not in ("daily", "weekly", "monthly"):
        raise ValueError(f"rebalance must be daily/weekly/monthly, got {rebalance!r}")
    count = int(count)
    if count < 1:
        raise ValueError("count must be >= 1")

    metric_body = _metric_code(metric)
    is_relative = metric["name"] == "relative_strength"

    where_fn = ""
    where_call = "elig[t] = close.notna()"
    if where_conditions:
        body, expr = _condition_blocks(where_conditions, where_logic, "wcond")
        where_fn = (
            "def _prior_where(df):\n"
            '    close = df["close"]\n'
            "\n"
            f"{body}\n"
            "\n"
            f"    return ({expr}).fillna(False)\n"
            "\n"
            "\n"
        )
        where_call = "elig[t] = _prior_where(panel[t]).reindex(closes.index, fill_value=False)"

    weight_fn = ""
    weighting = weighting or {"method": "equal"}
    by_metric = weighting.get("method") == "by_metric"
    if by_metric:
        weight_fn = (
            "def _prior_weight_metric(df):\n"
            '    close = df["close"]\n'
            f"{_metric_code(weighting['metric'])}\n"
            "\n"
            "\n"
        )

    sort_key = "(-kv[1], kv[0])" if select == "top" else "(kv[1], kv[0])"
    cap = float(max_position_pct) if max_position_pct is not None else 0.0

    if rebalance == "daily":
        reb_lines = "    reb_dates = list(closes.index)"
    else:
        fmt = "%G-%V" if rebalance == "weekly" else "%Y-%m"
        reb_lines = (
            "    if isinstance(closes.index, pd.DatetimeIndex):\n"
            f"        period_key = closes.index.to_series().dt.strftime({fmt!r})\n"
            "        reb_dates = list(closes.index.to_series().groupby(period_key).tail(1))\n"
            "    else:\n"
            "        reb_dates = list(closes.index)"
        )

    if by_metric:
        weight_lines = (
            "        wm_row = wmetric.loc[d]\n"
            "        wvals = {}\n"
            "        for t in chosen:\n"
            "            wv = wm_row.get(t, float('nan'))\n"
            "            wvals[t] = float(wv) if wv == wv and wv > 0 else 0.0\n"
            "        total = sum(wvals.values())\n"
            "        if total <= 0:\n"
            "            row = {t: 1.0 / len(chosen) for t in chosen}\n"
            "        else:\n"
            "            row = {t: v / total for t, v in wvals.items()}"
        )
        wmetric_line = (
            "\n    wmetric = pd.DataFrame({t: _prior_weight_metric(panel[t]) for t in tickers})"
            ".sort_index().reindex(closes.index)"
        )
    else:
        weight_lines = "        row = {t: 1.0 / len(chosen) for t in chosen}"
        wmetric_line = ""

    cap_lines = ""
    if cap:
        cap_lines = (
            "\n"
            "        # Cap per-name weight; redistribute the excess pro-rata once,\n"
            "        # then cap again — anything still over stays in cash.\n"
            f"        excess = sum(max(0.0, w - {cap}) for w in row.values())\n"
            f"        row = {{t: min(w, {cap}) for t, w in row.items()}}\n"
            "        if excess > 0:\n"
            f"            headroom = {{t: {cap} - w for t, w in row.items() if w < {cap}}}\n"
            "            total_head = sum(headroom.values())\n"
            "            if total_head > 0:\n"
            "                for t, h in headroom.items():\n"
            f"                    row[t] = min({cap}, row[t] + excess * (h / total_head))"
        )

    relative_line = ""
    if is_relative:
        relative_line = "\n    metric = metric.sub(metric.mean(axis=1), axis=0)"

    header = (
        f'    """Auto-generated ranking strategy: hold {select} {count} by '
        f'{metric["name"]},\n'
        f"    rebalanced {rebalance}. Ties break alphabetically; NaN metric or a\n"
        f"    failed filter means ineligible; fewer qualifiers than {count} leaves\n"
        f'    the remainder in cash."""'
    )

    return (
        where_fn
        + weight_fn
        + "def _prior_metric(df):\n"
        + '    close = df["close"]\n'
        + metric_body
        + "\n\n\n"
        + "def generate_weights(panel):\n"
        + header
        + "\n"
        + "    tickers = sorted(panel.keys())\n"
        + '    closes = pd.DataFrame({t: panel[t]["close"] for t in tickers}).sort_index()\n'
        + "    metric = pd.DataFrame({t: _prior_metric(panel[t]) for t in tickers}).sort_index()\n"
        + "    metric = metric.reindex(closes.index)"
        + relative_line
        + wmetric_line
        + "\n"
        + "    elig = {}\n"
        + "    for t in tickers:\n"
        + "        close = closes[t]\n"
        + f"        {where_call}\n"
        + "\n"
        + reb_lines
        + "\n"
        + "\n"
        + "    weights = pd.DataFrame(0.0, index=closes.index, columns=tickers)\n"
        + "    reb_set = set(reb_dates)\n"
        + "    for d in reb_dates:\n"
        + "        candidates = []\n"
        + "        for t in tickers:\n"
        + "            v = metric.at[d, t]\n"
        + "            if v == v and bool(elig[t].loc[d]):\n"
        + "                candidates.append((t, float(v)))\n"
        + "        if not candidates:\n"
        + "            continue\n"
        + f"        candidates.sort(key=lambda kv: {sort_key})\n"
        + f"        chosen = [t for t, _ in candidates[:{count}]]\n"
        + weight_lines
        + cap_lines
        + "\n"
        + "        for t, w in row.items():\n"
        + "            weights.at[d, t] = w\n"
        + "\n"
        + "    # Hold weights between rebalances: rows at non-rebalance dates\n"
        + "    # forward-fill from the last rebalance.\n"
        + "    mask = pd.Series([d in reb_set for d in weights.index], index=weights.index)\n"
        + "    weights = weights.where(mask).ffill().fillna(0.0)\n"
        + "    return weights\n"
    )


def compile_strategy(strategy: Dict[str, Any]) -> str:
    """Strategy JSON (the parser's output) → Python source string."""
    ranking = strategy.get("ranking")
    if ranking:
        where = ranking.get("where") or {}
        risk = strategy.get("risk") or {}
        return generate_ranking_code(
            metric=ranking["metric"],
            select=ranking.get("select", "top"),
            count=ranking.get("count", 5),
            rebalance=strategy.get("rebalance", "monthly"),
            where_conditions=[
                {"type": c["condition"], "params": c.get("params", {})}
                for c in where.get("conditions") or []
            ] or None,
            where_logic=where.get("match_logic", "all"),
            weighting=ranking.get("weighting"),
            max_position_pct=risk.get("max_position_pct"),
        )

    entry = strategy["entry"]
    exit_rule = strategy.get("exit", {}) or {}
    return generate_strategy_code(
        conditions=[{"type": c["condition"], "params": c.get("params", {})} for c in entry["conditions"]],
        match_logic=entry.get("match_logic", "all"),
        direction=strategy.get("direction", "long"),
        hold_bars=exit_rule.get("hold_bars") or DEFAULT_HOLD_BARS,
        exit_conditions=[
            {"type": c["condition"], "params": c.get("params", {})}
            for c in (exit_rule.get("conditions") or [])
        ] or None,
        stop_loss_pct=exit_rule.get("stop_loss_pct"),
        profit_target_pct=exit_rule.get("profit_target_pct"),
        trailing_stop_pct=exit_rule.get("trailing_stop_pct"),
        stop_loss_atr=exit_rule.get("stop_loss_atr"),
        profit_target_atr=exit_rule.get("profit_target_atr"),
        trailing_stop_atr=exit_rule.get("trailing_stop_atr"),
        breakeven_trigger_pct=exit_rule.get("breakeven_trigger_pct"),
        position_sizing=strategy.get("position_sizing"),
        risk=strategy.get("risk"),
    )
