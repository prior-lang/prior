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
    direction: str = "long",
    position_sizing: Dict[str, Any] | None = None,
    risk: Dict[str, Any] | None = None,
) -> str:
    """Build the strategy code string.

    Args mirror the strategy JSON: entry conditions + match logic, exit
    rules (priced, conditional, time), direction ("long" emits 0/1
    signals, "short" emits 0/-1 with stop/target/trailing mirrored around
    entry and the trailing watermark tracking the low), and sizing/risk
    metadata embedded as module-level constants.

    Exit precedence within a bar (see prior/spec SPEC.md section 6):
    stop -> target -> trailing -> condition exits -> hold_bars. Bar-close
    evaluation; entries fire on the rising edge of the combined condition.

    When only hold_bars is used with direction="long" (the scanner's
    promote path), the emitted code is byte-stable with pre-Phase-B
    output so existing promoted strategies regenerate identically.
    """
    if not conditions:
        raise ValueError("At least one condition is required")
    if direction not in ("long", "short"):
        raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")

    entry_body, entry_expr = _condition_blocks(conditions, match_logic, "cond")
    hold = int(max(1, hold_bars))
    is_short = direction == "short"

    has_priced_exits = any(
        v is not None for v in (stop_loss_pct, profit_target_pct, trailing_stop_pct)
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

    exit_desc_parts = []
    if stop:
        exit_desc_parts.append(f"stop {stop}%")
    if target:
        exit_desc_parts.append(f"target {target}%")
    if trail:
        exit_desc_parts.append(f"trailing {trail}%")
    if has_cond_exits:
        exit_desc_parts.append(f"{len(exit_conditions)} exit condition(s)")
    exit_desc_parts.append(f"max {hold} bars")
    exit_desc = ", ".join(exit_desc_parts)

    if is_short:
        sig_val = "-1"
        wm_cmp = "<"
        stop_expr = f"px >= entry_px * (1 + {stop} / 100.0)"
        target_expr = f"px <= entry_px * (1 - {target} / 100.0)"
        trail_expr = f"px >= hwm * (1 + {trail} / 100.0)"
        enter_phrase = "Enters short on the rising edge"
    else:
        sig_val = "1"
        wm_cmp = ">"
        stop_expr = f"px <= entry_px * (1 - {stop} / 100.0)"
        target_expr = f"px >= entry_px * (1 + {target} / 100.0)"
        trail_expr = f"px <= hwm * (1 - {trail} / 100.0)"
        enter_phrase = "Enters on the rising edge"

    return f'''{metadata}def generate_signals(df):
    """Auto-generated strategy. Mirrors {len(conditions)} entry
    condition(s) combined with {match_logic.upper()}. {enter_phrase};
    exits on first of: {exit_desc}. Bar-close evaluation; exit precedence
    stop -> target -> trailing -> conditions -> time."""
    close = df["close"]

{entry_body}

    combined = ({entry_expr}).fillna(False)
    entries = combined & ~combined.shift(1).fillna(False)
{exit_body}
{exit_series}
    entries_arr = entries.to_numpy()
    exit_arr = exit_cond.to_numpy()
    close_arr = close.to_numpy()
    n = len(df)
    sig = np.zeros(n, dtype=int)
    in_pos = False
    entry_px = 0.0
    hwm = 0.0
    bars_held = 0
    for i in range(n):
        if not in_pos:
            if entries_arr[i]:
                in_pos = True
                entry_px = close_arr[i]
                hwm = close_arr[i]
                bars_held = 0
                sig[i] = {sig_val}
            continue
        bars_held += 1
        px = close_arr[i]
        if px {wm_cmp} hwm:
            hwm = px
        exit_now = False
        if {stop} > 0 and {stop_expr}:
            exit_now = True
        elif {target} > 0 and {target_expr}:
            exit_now = True
        elif {trail} > 0 and {trail_expr}:
            exit_now = True
        elif exit_arr[i]:
            exit_now = True
        elif bars_held >= {hold}:
            exit_now = True
        if exit_now:
            in_pos = False
            sig[i] = 0
        else:
            sig[i] = {sig_val}
    return pd.Series(sig, index=df.index)
'''

def compile_strategy(strategy: Dict[str, Any]) -> str:
    """Strategy JSON (the parser's output) → Python source string."""
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
        position_sizing=strategy.get("position_sizing"),
        risk=strategy.get("risk"),
    )
