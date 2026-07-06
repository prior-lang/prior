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

    if "." in ctype:
        from .plugins import PLUGIN_TAGS
        plug = PLUGIN_TAGS.get(ctype)
        if plug is None:
            raise ValueError(
                f"plugin condition {ctype!r} is not registered in this runtime "
                "(set PRIOR_PLUGINS or call prior_lang.plugins.register())"
            )
        return plug.emit(dict(p))

    if ctype in ("iv_rank_less_than", "iv_rank_greater_than",
                 "short_interest_less_than", "short_interest_greater_than",
                 "earnings_within", "no_earnings_within"):
        # Hosted-data condition: the cloud runtime injects _prior_cloud into
        # the execution namespace; local runners never reach this emission
        # (compile_strategy refuses without allow_cloud).
        return f"cond = _prior_cloud(df, {ctype!r}, {dict(p)!r})"

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




def _tf_freq(tf: str) -> str:
    """PRIOR timeframe token → pandas resample rule. Weeks end Friday."""
    n = int(tf[:-1])
    unit = tf[-1]
    return {"m": f"{n}min", "h": f"{n}h", "d": f"{n}D", "w": f"{n}W-FRI"}[unit]


def _split_condition_blocks(
    conditions: List[Dict[str, Any]], match_logic: str, var_prefix: str = "cond"
) -> tuple[str, str, str, list]:
    """Like _condition_blocks, but conditions carrying a 'timeframe' are
    emitted as module-level helpers evaluated on a resampled frame of
    CLOSED higher-TF bars, then forward-filled onto the strategy index —
    the no-repaint contract (see prior spec §6).

    Returns (module_helpers_src, inline_body, combined_expr, tf_tokens).
    """
    op = "&" if match_logic == "all" else "|"
    identity = "True" if match_logic == "all" else "False"

    helpers: List[str] = []
    blocks: List[str] = []
    combine_names: List[str] = []
    tfs: List[str] = []
    for i, cond in enumerate(conditions):
        name = f"{var_prefix}_{i}"
        tf = cond.get("timeframe")
        if tf:
            if tf not in tfs:
                tfs.append(tf)
            snippet = _hcode(cond)
            helpers.append(
                f"def _prior_htf_{name}(df):\n"
                f'    close = df["close"]\n'
                f"    {snippet}\n"
                f"    return cond\n"
                f"\n"
                f"\n"
            )
            blocks.append(
                f"    # {var_prefix} {i + 1}: {cond['type']} on {tf} (closed bars, no repaint)\n"
                f'    {name} = _prior_htf_{name}(htf_{tf}).reindex(df.index, method="ffill").fillna(False).astype(bool)'
            )
        else:
            snippet = _hcode(cond)
            snippet = snippet.replace("cond =", f"{name} =")
            blocks.append(f"    # {var_prefix} {i + 1}: {cond['type']}\n    {snippet}")
        combine_names.append(name)

    combined_expr = f" {op} ".join(combine_names) if combine_names else identity
    return "".join(helpers), "\n\n".join(blocks), combined_expr, tfs


def _htf_preamble(tfs: list) -> str:
    """Emit the closed-bar resample frames for every timeframe in use."""
    if not tfs:
        return ""
    lines = [
        "",
        "    if not isinstance(df.index, pd.DatetimeIndex):",
        '        raise ValueError("multi-timeframe strategies need datetime-indexed bars")',
    ]
    for tf in tfs:
        freq = _tf_freq(tf)
        lines.append(f"    htf_{tf} = pd.DataFrame({{")
        for col, agg in (
            ("open", "first()"), ("high", "max()"), ("low", "min()"),
            ("close", "last()"), ("volume", "sum()"),
        ):
            lines.append(
                f'        "{col}": df["{col}"].resample("{freq}", label="right", closed="right").{agg},'
            )
        lines.append(f'    }}).dropna(subset=["close"])')
    return "\n".join(lines) + "\n"


def generate_strategy_code(
    conditions: List[Dict[str, Any]] | None = None,
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
    rules: List[Dict[str, Any]] | None = None,
    partial_exit: Dict[str, Any] | None = None,
    cooldown_bars: int = 0,
    position_sizing: Dict[str, Any] | None = None,
    risk: Dict[str, Any] | None = None,
) -> str:
    """Build the strategy code string.

    Entry: either `conditions`+`match_logic` (one rule) or `rules` (a list
    of {conditions, match_logic} — any rule's rising edge enters; one
    position at a time). Exits: percent or ATR-unit stop/target/trailing,
    breakeven, condition exits, time. `partial_exit` takes half off once
    per position (its own target/conditions/hold). `cooldown_bars` blocks
    re-entry for N bars after any exit. direction="short" mirrors
    everything. Signals: 0/±1, or fractional (±0.5) once a partial fires.

    Long-only, single-rule, hold-only strategies emit the original
    vectorized form, byte-stable with pre-Phase-B output.
    """
    rule_list = rules if rules else (
        [{"conditions": conditions, "match_logic": match_logic}] if conditions else []
    )
    if not rule_list or not rule_list[0].get("conditions"):
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

    hold = int(max(1, hold_bars))
    is_short = direction == "short"
    cooldown = int(max(0, cooldown_bars))
    multi_rule = len(rule_list) > 1

    has_priced_exits = any(
        v is not None
        for v in (stop_loss_pct, profit_target_pct, trailing_stop_pct,
                  stop_loss_atr, profit_target_atr, trailing_stop_atr,
                  breakeven_trigger_pct)
    )
    has_cond_exits = bool(exit_conditions)
    has_v06 = multi_rule or bool(partial_exit) or cooldown > 0

    metadata = ""
    if position_sizing:
        metadata += f"POSITION_SIZING = {position_sizing!r}\n"
    if multi_rule:
        sizings = [r.get("position_sizing") for r in rule_list]
        if any(s for s in sizings):
            metadata += f"RULE_SIZING = {sizings!r}\n"
    if risk:
        metadata += f"RISK = {risk!r}\n"
    if metadata:
        metadata += "\n\n"

    # ── Per-rule entry blocks ──────────────────────────────────────
    all_helpers = ""
    entry_bodies: List[str] = []
    edge_names: List[str] = []
    entry_tfs: List[str] = []
    for r, rule in enumerate(rule_list):
        prefix = "cond" if not multi_rule else f"cond_r{r}"
        helpers, body, expr, tfs = _split_condition_blocks(
            rule["conditions"], rule.get("match_logic", "all"), prefix
        )
        all_helpers += helpers
        for tf in tfs:
            if tf not in entry_tfs:
                entry_tfs.append(tf)
        combined_name = "combined" if not multi_rule else f"combined_r{r}"
        entries_name = "entries" if not multi_rule else f"entries_r{r}"
        body += (
            f"\n\n    {combined_name} = ({expr}).fillna(False)\n"
            f"    {entries_name} = {combined_name} & ~{combined_name}.shift(1, fill_value=False)"
        )
        entry_bodies.append(body)
        edge_names.append(entries_name)
    entry_body = "\n\n".join(entry_bodies)
    if multi_rule:
        entry_body += "\n\n    entries = " + " | ".join(edge_names)

    if not has_priced_exits and not has_cond_exits and not has_v06:
        hold_phrase = f"stays short for {hold} bars" if is_short else f"holds for {hold} bars"
        signals_expr = (
            "entries.astype(int).rolling(%d, min_periods=1).max().fillna(0).astype(int)" % hold
        )
        if is_short:
            signals_expr = "(%s * -1)" % signals_expr
        htf = _htf_preamble(entry_tfs)
        return f'''{metadata}{all_helpers}def generate_signals(df):
    """Auto-generated strategy. Mirrors {len(rule_list[0]["conditions"])} condition(s)
    combined with {rule_list[0].get("match_logic", "all").upper()}. Enters on the rising edge of the
    combined match and {hold_phrase}."""
    close = df["close"]
{htf}
{entry_body}

    signals = {signals_expr}
    return signals
'''

    # ── Exit machinery ─────────────────────────────────────────────
    exit_body = ""
    exit_expr = "False"
    exit_tfs: list = []
    if has_cond_exits:
        ehelpers, exit_body, exit_expr, exit_tfs = _split_condition_blocks(exit_conditions, "any", "xcond")
        all_helpers += ehelpers
        exit_body = "\n" + exit_body + "\n"
        exit_series = f"    exit_cond = ({exit_expr}).fillna(False)\n"
    else:
        exit_series = "    exit_cond = pd.Series(False, index=df.index)\n"

    partial = partial_exit or {}
    p_frac = float(partial.get("fraction", 0.5)) if partial else 0.0
    p_target = partial.get("profit_target_pct")
    p_hold = partial.get("hold_bars")
    p_conds = partial.get("conditions") or []
    partial_body = ""
    partial_series = ""
    if partial:
        if p_conds:
            phelpers, partial_body, p_expr, p_tfs = _split_condition_blocks(p_conds, "any", "pcond")
            all_helpers += phelpers
            for tf in p_tfs:
                if tf not in exit_tfs:
                    exit_tfs.append(tf)
            partial_body = "\n" + partial_body + "\n"
            partial_series = f"    partial_cond = ({p_expr}).fillna(False)\n"
        else:
            partial_series = "    partial_cond = pd.Series(False, index=df.index)\n"

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
    if partial:
        exit_desc_parts.append(f"partial ({p_frac:g}) once")
    exit_desc_parts.append(f"max {hold} bars")
    if cooldown:
        exit_desc_parts.append(f"{cooldown}-bar cooldown")
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
        p_target_chk = f"px <= entry_px * (1 - {p_target if p_target else 0.0} / 100.0)"
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
        p_target_chk = f"px >= entry_px * (1 + {p_target if p_target else 0.0} / 100.0)"

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

    # partial state
    frac_dtype = "float" if partial else "int"
    frac_init = ""
    frac_reset = ""
    partial_arr_line = ""
    partial_chain = ""
    sig_assign_pos = f"            sig[i] = {sig_val}"
    sig_assign_enter = f"                sig[i] = {sig_val}"
    if partial:
        frac_init = "\n    frac = 0.0\n    partial_done = False"
        frac_reset = "\n                frac = 1.0\n                partial_done = False"
        partial_arr_line = "    partial_arr = partial_cond.to_numpy()\n"
        p_checks = []
        if p_target is not None:
            p_checks.append(p_target_chk)
        if p_conds:
            p_checks.append("partial_arr[i]")
        if p_hold is not None:
            p_checks.append(f"bars_held >= {int(p_hold)}")
        p_cond_expr = " or ".join(p_checks) if p_checks else "False"
        partial_chain = (
            "        if not exit_now and not partial_done and (" + p_cond_expr + "):\n"
            f"            frac = {p_frac}\n"
            "            partial_done = True\n"
        )
        sig_assign_pos = f"            sig[i] = {sig_val} * frac"
        sig_assign_enter = f"                sig[i] = {sig_val} * frac"

    # cooldown state
    cd_init = ""
    cd_set = ""
    flat_prefix = "            if entries_arr[i]:"
    if cooldown:
        cd_init = "\n    cd = 0"
        cd_set = f"\n            cd = {cooldown}"
        flat_prefix = (
            "            if cd > 0:\n"
            "                cd -= 1\n"
            "            elif entries_arr[i]:"
        )

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

    all_tfs = entry_tfs + [t for t in exit_tfs if t not in entry_tfs]
    htf = _htf_preamble(all_tfs)
    n_conds = sum(len(r["conditions"]) for r in rule_list)
    rule_phrase = f"{len(rule_list)} rule(s), {n_conds} condition(s)"

    return f'''{metadata}{all_helpers}def generate_signals(df):
    """Auto-generated strategy: {rule_phrase}. {enter_phrase}
    of any rule; exits on first of: {exit_desc}. Bar-close evaluation;
    exit precedence stop -> breakeven -> target -> trailing -> conditions
    -> time; partial exits fire once, after the full-exit checks."""
    close = df["close"]
{htf}
{entry_body}
{exit_body}
{exit_series}{partial_body}{partial_series}{atr_block}
    entries_arr = entries.to_numpy()
    exit_arr = exit_cond.to_numpy()
{partial_arr_line}    close_arr = close.to_numpy()
    n = len(df)
    sig = np.zeros(n, dtype={frac_dtype})
    in_pos = False
    entry_px = 0.0
    hwm = 0.0
    bars_held = 0{atr_init}{be_init}{frac_init}{cd_init}
    for i in range(n):
        if not in_pos:
{flat_prefix}
                in_pos = True
                entry_px = close_arr[i]
                hwm = close_arr[i]
                bars_held = 0{entry_atr_line}{be_reset_line}{frac_reset}
{sig_assign_enter}
            continue
        bars_held += 1
        px = close_arr[i]
        if px {wm_cmp} hwm:
            hwm = px{be_arm_line}
        exit_now = False
{exit_chain}
{partial_chain}        if exit_now:
            in_pos = False
            sig[i] = 0{cd_set}
        else:
{sig_assign_pos}
    return pd.Series(sig, index=df.index)
'''




def _dir_check_exprs(ex: Dict[str, Any], is_short: bool) -> Dict[str, str]:
    """Per-direction exit-check expressions for one exit spec."""
    stop = float(ex.get("stop_loss_pct") or 0.0)
    target = float(ex.get("profit_target_pct") or 0.0)
    trail = float(ex.get("trailing_stop_pct") or 0.0)
    stop_a = float(ex.get("stop_loss_atr") or 0.0)
    target_a = float(ex.get("profit_target_atr") or 0.0)
    trail_a = float(ex.get("trailing_stop_atr") or 0.0)
    be = float(ex.get("breakeven_trigger_pct") or 0.0)
    hold = int(ex.get("hold_bars") or DEFAULT_HOLD_BARS)

    if is_short:
        out = {
            "stop": f"px >= entry_px * (1 + {stop} / 100.0)" if stop else "",
            "stop_a": f"not np.isnan(entry_atr) and px >= entry_px + {stop_a} * entry_atr" if stop_a else "",
            "target": f"px <= entry_px * (1 - {target} / 100.0)" if target else "",
            "target_a": f"not np.isnan(entry_atr) and px <= entry_px - {target_a} * entry_atr" if target_a else "",
            "trail": f"px >= hwm * (1 + {trail} / 100.0)" if trail else "",
            "trail_a": f"not np.isnan(atr_arr[i]) and px >= hwm + {trail_a} * atr_arr[i]" if trail_a else "",
            "be_arm": f"px <= entry_px * (1 - {be} / 100.0)" if be else "",
            "be_exit": "px >= entry_px" if be else "",
        }
    else:
        out = {
            "stop": f"px <= entry_px * (1 - {stop} / 100.0)" if stop else "",
            "stop_a": f"not np.isnan(entry_atr) and px <= entry_px - {stop_a} * entry_atr" if stop_a else "",
            "target": f"px >= entry_px * (1 + {target} / 100.0)" if target else "",
            "target_a": f"not np.isnan(entry_atr) and px >= entry_px + {target_a} * entry_atr" if target_a else "",
            "trail": f"px <= hwm * (1 - {trail} / 100.0)" if trail else "",
            "trail_a": f"not np.isnan(atr_arr[i]) and px <= hwm - {trail_a} * atr_arr[i]" if trail_a else "",
            "be_arm": f"px >= entry_px * (1 + {be} / 100.0)" if be else "",
            "be_exit": "px <= entry_px" if be else "",
        }
    out["hold"] = str(hold)
    out["needs_atr"] = bool(stop_a or target_a or trail_a)
    out["has_be"] = bool(be)
    return out


def _dir_chain(exprs: Dict[str, str], cond_arr: str, indent: str) -> str:
    checks = []
    for key in ("stop", "stop_a"):
        if exprs[key]:
            checks.append(exprs[key])
    if exprs["has_be"]:
        checks.append(f"be_armed and {exprs['be_exit']}")
    for key in ("target", "target_a", "trail", "trail_a"):
        if exprs[key]:
            checks.append(exprs[key])
    checks.append(f"{cond_arr}[i]")
    checks.append(f"bars_held >= {exprs['hold']}")
    lines = []
    for idx, chk in enumerate(checks):
        kw = "if" if idx == 0 else "elif"
        lines.append(f"{indent}{kw} {chk}:")
        lines.append(f"{indent}    exit_now = True")
    return "\n".join(lines)


def generate_mixed_code(
    rules: List[Dict[str, Any]],
    exit_long: Dict[str, Any],
    exit_short: Dict[str, Any],
    cooldown_bars: int = 0,
    reverse: bool = False,
    partial_long: Dict[str, Any] | None = None,
    partial_short: Dict[str, Any] | None = None,
    position_sizing: Dict[str, Any] | None = None,
    risk: Dict[str, Any] | None = None,
) -> str:
    """Emit generate_signals for a long+short strategy.

    Long rules' edges enter +1 (closed by the sell spec), short rules'
    edges enter -1 (closed by the cover spec). One position at a time;
    while positioned, opposite edges are ignored. A bar where a long edge
    and a short edge fire together stands aside — deterministic honesty
    over arbitrary priority. Cooldown applies to all entries.
    """
    long_rules = [r for r in rules if r.get("direction", "long") == "long"]
    short_rules = [r for r in rules if r.get("direction") == "short"]
    if not long_rules or not short_rules:
        raise ValueError("generate_mixed_code needs both long and short rules")

    metadata = ""
    if position_sizing:
        metadata += f"POSITION_SIZING = {position_sizing!r}\n"
    sizings = [r.get("position_sizing") for r in rules]
    if any(s for s in sizings):
        metadata += f"RULE_SIZING = {sizings!r}\n"
    if risk:
        metadata += f"RISK = {risk!r}\n"
    if metadata:
        metadata += "\n\n"

    all_helpers = ""
    tfs: List[str] = []

    def _rules_block(rule_list, tag_prefix, entries_name):
        nonlocal all_helpers
        bodies = []
        edges = []
        for r, rule in enumerate(rule_list):
            prefix = f"{tag_prefix}{r}"
            helpers, body, expr, rtfs = _split_condition_blocks(
                rule["conditions"], rule.get("match_logic", "all"), prefix
            )
            all_helpers += helpers
            for tf in rtfs:
                if tf not in tfs:
                    tfs.append(tf)
            body += (
                f"\n\n    combined_{prefix} = ({expr}).fillna(False)\n"
                f"    edge_{prefix} = combined_{prefix} & ~combined_{prefix}.shift(1, fill_value=False)"
            )
            bodies.append(body)
            edges.append(f"edge_{prefix}")
        return "\n\n".join(bodies) + f"\n\n    {entries_name} = " + " | ".join(edges)

    long_body = _rules_block(long_rules, "lcond_r", "long_entries")
    short_body = _rules_block(short_rules, "scond_r", "short_entries")

    def _exit_series(ex, prefix, series_name):
        nonlocal all_helpers
        conds = ex.get("conditions") or []
        if conds:
            helpers, body, expr, etfs = _split_condition_blocks(conds, "any", prefix)
            all_helpers += helpers
            for tf in etfs:
                if tf not in tfs:
                    tfs.append(tf)
            return "\n" + body + "\n", f"    {series_name} = ({expr}).fillna(False)\n"
        return "", f"    {series_name} = pd.Series(False, index=df.index)\n"

    lx_body, lx_series = _exit_series(exit_long, "xlcond", "exit_long_cond")
    sx_body, sx_series = _exit_series(exit_short, "xscond", "exit_short_cond")

    lex = _dir_check_exprs(exit_long, is_short=False)
    sex = _dir_check_exprs(exit_short, is_short=True)
    long_chain = _dir_chain(lex, "exit_long_arr", "            ")
    short_chain = _dir_chain(sex, "exit_short_arr", "            ")

    needs_atr = lex["needs_atr"] or sex["needs_atr"]
    has_be = lex["has_be"] or sex["has_be"]

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
    be_reset = ""
    be_arm_block = ""
    if has_be:
        be_init = "\n    be_armed = False"
        be_reset = "\n                be_armed = False"
        arm_long = lex["be_arm"] or "False"
        arm_short = sex["be_arm"] or "False"
        be_arm_block = (
            "\n        if not be_armed:\n"
            f"            if dir > 0 and ({arm_long}):\n"
            "                be_armed = True\n"
            f"            elif dir < 0 and ({arm_short}):\n"
            "                be_armed = True"
        )

    # ── Per-direction partial exits (sell half / cover half) ──────
    any_partial = bool(partial_long) or bool(partial_short)

    def _partial_pieces(spec, prefix, is_short_dir):
        nonlocal all_helpers
        if not spec:
            return "", "", "False"
        conds = spec.get("conditions") or []
        body = ""
        series = ""
        arr = f"{prefix}_arr"
        checks = []
        t = spec.get("profit_target_pct")
        if t is not None:
            if is_short_dir:
                checks.append(f"px <= entry_px * (1 - {float(t)} / 100.0)")
            else:
                checks.append(f"px >= entry_px * (1 + {float(t)} / 100.0)")
        if conds:
            cdicts = [{"type": c["condition"], "params": c.get("params", {}),
                       **({"timeframe": c["timeframe"]} if c.get("timeframe") else {})}
                      for c in conds]
            helpers, cbody, cexpr, ctfs = _split_condition_blocks(cdicts, "any", prefix)
            all_helpers += helpers
            for tf in ctfs:
                if tf not in tfs:
                    tfs.append(tf)
            body = "\n" + cbody + "\n"
            series = f"    {prefix}_cond = ({cexpr}).fillna(False)\n    {arr} = {prefix}_cond.to_numpy()\n"
            checks.append(f"{arr}[i]")
        h = spec.get("hold_bars")
        if h is not None:
            checks.append(f"bars_held >= {int(h)}")
        return body, series, (" or ".join(checks) if checks else "False")

    pl_body, pl_series, pl_expr = _partial_pieces(partial_long, "plcond", False)
    ps_body, ps_series, ps_expr = _partial_pieces(partial_short, "pscond", True)

    frac_dtype = "float" if any_partial else "int"
    frac_init = "\n    frac = 0.0\n    partial_done = False" if any_partial else ""
    frac_reset = "\n                frac = 1.0\n                partial_done = False" if any_partial else ""
    frac_flip_reset = "\n            frac = 1.0\n            partial_done = False" if any_partial else ""
    sig_enter = "                sig[i] = dir * frac" if any_partial else "                sig[i] = dir"
    sig_hold = "            sig[i] = dir * frac" if any_partial else "            sig[i] = dir"
    sig_flip = "\n            sig[i] = dir * frac" if any_partial else "\n            sig[i] = dir"
    partial_chain = ""
    if any_partial:
        partial_chain = (
            "        if not exit_now and not partial_done:\n"
            f"            if dir > 0 and ({pl_expr}):\n"
            "                frac = 0.5\n"
            "                partial_done = True\n"
            f"            elif dir < 0 and ({ps_expr}):\n"
            "                frac = 0.5\n"
            "                partial_done = True\n"
        )

    reverse_block = ""
    if reverse:
        reverse_block = (
            "\n        # risk [reverse]: an opposite signal closes and flips the same bar"
            "\n        if dir > 0 and bool(short_arr[i]) and not bool(long_arr[i]):"
            "\n            dir = -1"
            "\n            entry_px = px"
            "\n            hwm = px"
            "\n            bars_held = 0" + entry_atr_line.replace("                ", "            ") + be_reset.replace("                ", "            ") + frac_flip_reset + sig_flip +
            "\n            continue"
            "\n        if dir < 0 and bool(long_arr[i]) and not bool(short_arr[i]):"
            "\n            dir = 1"
            "\n            entry_px = px"
            "\n            hwm = px"
            "\n            bars_held = 0" + entry_atr_line.replace("                ", "            ") + be_reset.replace("                ", "            ") + frac_flip_reset + sig_flip +
            "\n            continue"
        )

    cooldown = int(max(0, cooldown_bars))
    cd_init = "\n    cd = 0" if cooldown else ""
    cd_set = f"\n            cd = {cooldown}" if cooldown else ""
    cd_gate = (
        "            if cd > 0:\n"
        "                cd -= 1\n"
        "                continue\n"
        if cooldown else ""
    )

    htf = _htf_preamble(tfs)
    n_l = sum(len(r["conditions"]) for r in long_rules)
    n_s = sum(len(r["conditions"]) for r in short_rules)

    return f'''{metadata}{all_helpers}def generate_signals(df):
    """Auto-generated long+short strategy: {len(long_rules)} long rule(s)
    ({n_l} condition(s)) closed by the sell spec, {len(short_rules)} short
    rule(s) ({n_s} condition(s)) closed by the cover spec. One position at
    a time; opposite edges while positioned are ignored; simultaneous long
    and short edges stand aside. Bar-close evaluation throughout."""
    close = df["close"]
{htf}
{long_body}

{short_body}
{lx_body}
{lx_series}{sx_body}
{sx_series}{pl_body}{pl_series}{ps_body}{ps_series}{atr_block}
    long_arr = long_entries.to_numpy()
    short_arr = short_entries.to_numpy()
    exit_long_arr = exit_long_cond.to_numpy()
    exit_short_arr = exit_short_cond.to_numpy()
    close_arr = close.to_numpy()
    n = len(df)
    sig = np.zeros(n, dtype={frac_dtype})
    in_pos = False
    dir = 0
    entry_px = 0.0
    hwm = 0.0
    bars_held = 0{atr_init}{be_init}{cd_init}{frac_init}
    for i in range(n):
        if not in_pos:
{cd_gate}            le = bool(long_arr[i])
            se = bool(short_arr[i])
            if le and se:
                pass  # conflicting signals this bar: stand aside
            elif le or se:
                in_pos = True
                dir = 1 if le else -1
                entry_px = close_arr[i]
                hwm = close_arr[i]
                bars_held = 0{entry_atr_line}{be_reset}{frac_reset}
{sig_enter}
            continue
        bars_held += 1
        px = close_arr[i]{reverse_block}
        if dir > 0:
            if px > hwm:
                hwm = px
        else:
            if px < hwm:
                hwm = px{be_arm_block}
        exit_now = False
        if dir > 0:
{long_chain}
        else:
{short_chain}
{partial_chain}        if exit_now:
            in_pos = False
            sig[i] = 0{cd_set}
        else:
{sig_hold}
    return pd.Series(sig, index=df.index)
'''



def generate_options_code(options: Dict[str, Any], risk: Dict[str, Any] | None = None) -> str:
    """Emit generate_option_orders(df, chains) for an options strategy.

    df: underlying OHLCV, datetime-indexed. chains: long-form frame with
    columns [date, expiry, strike, right ('P'|'C'), delta, mid] — one row
    per contract per day (the engine's options data shape; the OSS runner
    never fabricates this, per the design doc).

    Returns an orders DataFrame [date, action, right, strike, expiry,
    price, state]. Actions: sell_put, sell_call, close, roll_close,
    roll_open, assigned, expired, called_away.

    Semantics: bar-close; management (profit/loss/close-dte/roll-dte)
    checked before expiry settlement; assignment at expiry by moneyness;
    entry (or wheel re-entry) attempted after management the same bar.
    Chain selection: nearest listed expiry at least DTE days out, then
    the strike whose |delta| is nearest the target (ties: lower strike
    for puts, higher for calls).
    """
    form = options.get("form", "wheel")
    opt = options.get("option", {})
    target_delta = float(opt.get("delta", 25))
    target_dte = int(opt.get("dte", 45))
    mgmt = options.get("management") or {}
    profit = float(mgmt.get("profit_pct") or 0.0)
    loss = float(mgmt.get("loss_pct") or 0.0)
    close_dte = int(mgmt.get("close_dte") or 0)
    roll_dte = int(mgmt.get("roll_dte") or 0)
    entry = options.get("entry") or {}
    conditions = entry.get("conditions") or []

    metadata = ""
    if risk:
        metadata += f"RISK = {risk!r}\n\n\n"

    gate_fn = ""
    gate_call = "    gate = pd.Series(True, index=df.index)\n"
    if conditions:
        conds = [
            {"type": c["condition"], "params": c.get("params", {})}
            for c in conditions
        ]
        body, expr = _condition_blocks(conds, entry.get("match_logic", "all"), "gcond")
        gate_fn = (
            "def _prior_gate(df):\n"
            '    close = df["close"]\n'
            "\n" + body + "\n\n"
            f"    return ({expr}).fillna(False)\n\n\n"
        )
        gate_call = "    gate = _prior_gate(df)\n"

    if form == "wheel":
        put_enabled = "True"
        call_enabled = "True"
        assigned_state = "'long_stock'"
        kind_desc = "the wheel"
    elif opt.get("type") == "csp":
        put_enabled = "True"
        call_enabled = "False"
        assigned_state = "'assigned_hold'"  # terminal: hold shares, no calls
        kind_desc = "cash-secured puts"
    else:  # covered_call
        put_enabled = "False"
        call_enabled = "True"
        assigned_state = "'long_stock'"
        kind_desc = "covered calls"

    start_state = "'long_stock'" if (form != "wheel" and opt.get("type") == "covered_call") else "'cash'"

    return f'''{metadata}{gate_fn}def _prior_pick(ch_d, right, target_delta, target_dte, d):
    """Nearest expiry >= DTE, then nearest |delta|; deterministic ties."""
    cands = ch_d[ch_d["right"] == right]
    if len(cands) == 0:
        return None
    days = (pd.to_datetime(cands["expiry"]) - d).dt.days
    cands = cands[days >= target_dte]
    if len(cands) == 0:
        return None
    days = (pd.to_datetime(cands["expiry"]) - d).dt.days
    best_exp = cands.loc[days.idxmin(), "expiry"]
    cands = cands[cands["expiry"] == best_exp].copy()
    cands["_dgap"] = (cands["delta"].abs() - target_delta).abs()
    cands = cands.sort_values(
        ["_dgap", "strike"], ascending=[True, right == "P"]
    )
    row = cands.iloc[0]
    return {{"expiry": row["expiry"], "strike": float(row["strike"]),
             "right": right, "credit": float(row["mid"])}}


def generate_option_orders(df, chains):
    """Auto-generated options strategy: {kind_desc}, ~{target_delta:g}-delta,
    ~{target_dte}-DTE. Management before expiry each bar; assignment by
    moneyness at expiry; entries gated by the strategy's conditions."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("options strategies need datetime-indexed bars")
{gate_call}
    orders = []
    state = {start_state}
    pos = None

    def emit(d, action, price, p=None, st=None):
        src = p if p is not None else pos
        orders.append({{
            "date": d, "action": action,
            "right": src["right"] if src else None,
            "strike": src["strike"] if src else None,
            "expiry": src["expiry"] if src else None,
            "price": price, "state": st if st is not None else state,
        }})

    for d in df.index:
        ch_d = chains[chains["date"] == d]
        px = float(df.at[d, "close"])

        if pos is not None:
            row = ch_d[(ch_d["expiry"] == pos["expiry"])
                       & (ch_d["strike"] == pos["strike"])
                       & (ch_d["right"] == pos["right"])]
            mid = float(row.iloc[0]["mid"]) if len(row) else None
            dte_left = (pd.to_datetime(pos["expiry"]) - d).days
            closed = False
            if mid is not None:
                if {profit} > 0 and mid <= pos["credit"] * (1 - {profit} / 100.0):
                    emit(d, "close", mid)
                    closed = True
                elif {loss} > 0 and mid >= pos["credit"] * (1 + {loss} / 100.0):
                    emit(d, "close", mid)
                    closed = True
                elif {close_dte} > 0 and dte_left <= {close_dte}:
                    emit(d, "close", mid)
                    closed = True
                elif {roll_dte} > 0 and dte_left <= {roll_dte}:
                    emit(d, "roll_close", mid)
                    new = _prior_pick(ch_d, pos["right"], {target_delta}, {target_dte}, d)
                    if new is not None:
                        pos = new
                        emit(d, "roll_open", new["credit"])
                        continue
                    closed = True
            if closed:
                state = "long_stock" if pos["right"] == "C" else "cash"
                pos = None
            elif dte_left <= 0:
                if pos["right"] == "P":
                    if px < pos["strike"]:
                        emit(d, "assigned", pos["strike"], st={assigned_state})
                        state = {assigned_state}
                    else:
                        emit(d, "expired", 0.0, st="cash")
                        state = "cash"
                else:
                    if px >= pos["strike"]:
                        emit(d, "called_away", pos["strike"], st="cash")
                        state = "cash"
                    else:
                        emit(d, "expired", 0.0, st="long_stock")
                        state = "long_stock"
                pos = None

        if pos is None and bool(gate.get(d, False)):
            if state == "cash" and {put_enabled}:
                new = _prior_pick(ch_d, "P", {target_delta}, {target_dte}, d)
                if new is not None:
                    pos = new
                    state = "short_put"
                    emit(d, "sell_put", new["credit"])
            elif state == "long_stock" and {call_enabled}:
                new = _prior_pick(ch_d, "C", {target_delta}, {target_dte}, d)
                if new is not None:
                    pos = new
                    state = "short_call"
                    emit(d, "sell_call", new["credit"])

    return pd.DataFrame(orders, columns=["date", "action", "right", "strike", "expiry", "price", "state"])
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
        helpers, body, expr, wtfs = _split_condition_blocks(where_conditions, where_logic, "wcond")
        htf = _htf_preamble(wtfs)
        where_fn = (
            helpers
            + "def _prior_where(df):\n"
            + '    close = df["close"]\n'
            + htf
            + "\n"
            + f"{body}\n"
            + "\n"
            + f"    return ({expr}).fillna(False)\n"
            + "\n"
            + "\n"
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


def _find_cloud_only(strategy: Dict[str, Any]) -> list:
    from .tags import CLOUD_ONLY_CONDITIONS
    found = []

    def scan(conds):
        for c in conds or []:
            if c.get("condition") in CLOUD_ONLY_CONDITIONS:
                found.append(c["condition"])

    scan((strategy.get("entry") or {}).get("conditions"))
    scan((strategy.get("exit") or {}).get("conditions"))
    for r in strategy.get("rules") or []:
        scan(r.get("conditions"))
    for side in (strategy.get("exits") or {}).values():
        scan(side.get("conditions"))
    scan(((strategy.get("ranking") or {}).get("where") or {}).get("conditions"))
    scan((strategy.get("partial_exit") or {}).get("conditions"))
    scan(((strategy.get("options") or {}).get("entry") or {}).get("conditions"))
    return found


def generate_pair_code(base_code: str, pair: Dict[str, Any]) -> str:
    """Wrap single-instrument strategy code for a two-legged spread.

    The base code's generate_signals(df) runs unchanged on a synthetic
    frame whose close IS the spread series (open/high/low mirror it,
    volume is 0), so every condition, exit, and partial works on the
    spread. PAIR carries leg metadata for runners to translate a spread
    position into two equal-dollar legs."""
    a, b = [str(t).upper() for t in pair["tickers"]]
    form = pair.get("form", "ratio")
    expr = "leg_a / leg_b" if form == "ratio" else "leg_a - leg_b"
    return base_code + f'''

PAIR = ({a!r}, {b!r}, {form!r})


def generate_pair_signals(panel):
    """Signals on the {form} spread {a}/{b}. A +1 spread position means
    long {a} / short {b} in equal dollar legs; -1 mirrors; 0 is flat
    both legs."""
    leg_a = panel[{a!r}]["close"].astype(float)
    leg_b = panel[{b!r}]["close"].astype(float)
    leg_a, leg_b = leg_a.align(leg_b, join="inner")
    spread = ({expr}).dropna()
    df = pd.DataFrame({{
        "open": spread, "high": spread, "low": spread,
        "close": spread, "volume": 0.0,
    }})
    return generate_signals(df)
'''


def compile_strategy(strategy: Dict[str, Any], allow_cloud: bool = False) -> str:
    """Strategy JSON (the parser's output) → Python source string.

    Cloud-only conditions (IV rank, earnings calendar, short interest)
    refuse local compilation unless allow_cloud=True — the hosted runner
    passes that after substituting its own evaluators."""
    if not allow_cloud:
        cloud = _find_cloud_only(strategy)
        if cloud:
            from .errors import PriorError
            names = ", ".join(sorted(set(cloud)))
            raise PriorError(
                f"this strategy uses hosted-data conditions ({names}) — it "
                "validates, formats, and explains here, but evaluation needs "
                "data that only exists hosted. Backtest with --cloud (coming "
                "soon) or in AutoQuant."
            )
    def _conds(lst):
        return [
            {"type": c["condition"], "params": c.get("params", {}),
             **({"timeframe": c["timeframe"]} if c.get("timeframe") else {})}
            for c in (lst or [])
        ]

    if strategy.get("options"):
        return generate_options_code(strategy["options"], risk=strategy.get("risk"))

    uni = strategy.get("universe") or {}
    pair = uni if uni.get("type") == "pair" else None

    def _wrap(code: str) -> str:
        return generate_pair_code(code, pair) if pair else code

    if strategy.get("exits"):  # long+short strategy
        ex_l = dict(strategy["exits"]["long"])
        ex_s = dict(strategy["exits"]["short"])
        ex_l["conditions"] = _conds(ex_l.get("conditions"))
        ex_s["conditions"] = _conds(ex_s.get("conditions"))
        return _wrap(generate_mixed_code(
            rules=[
                {
                    "direction": r.get("direction", "long"),
                    "conditions": _conds(r["conditions"]),
                    "match_logic": r.get("match_logic", "all"),
                    "position_sizing": r.get("position_sizing"),
                }
                for r in strategy["rules"]
            ],
            exit_long=ex_l,
            exit_short=ex_s,
            cooldown_bars=(strategy.get("risk") or {}).get("cooldown_bars", 0),
            reverse=bool((strategy.get("risk") or {}).get("reverse")),
            partial_long=strategy.get("partial_exit"),
            partial_short=strategy.get("partial_exit_short"),
            position_sizing=strategy.get("position_sizing"),
            risk=strategy.get("risk"),
        ))

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
                {"type": c["condition"], "params": c.get("params", {}),
                 **({"timeframe": c["timeframe"]} if c.get("timeframe") else {})}
                for c in where.get("conditions") or []
            ] or None,
            where_logic=where.get("match_logic", "all"),
            weighting=ranking.get("weighting"),
            max_position_pct=risk.get("max_position_pct"),
        )

    entry = strategy["entry"]
    exit_rule = strategy.get("exit", {}) or {}
    return _wrap(generate_strategy_code(
        conditions=[
            {"type": c["condition"], "params": c.get("params", {}),
             **({"timeframe": c["timeframe"]} if c.get("timeframe") else {})}
            for c in entry["conditions"]
        ],
        match_logic=entry.get("match_logic", "all"),
        direction=strategy.get("direction", "long"),
        hold_bars=exit_rule.get("hold_bars") or DEFAULT_HOLD_BARS,
        exit_conditions=[
            {"type": c["condition"], "params": c.get("params", {}),
             **({"timeframe": c["timeframe"]} if c.get("timeframe") else {})}
            for c in (exit_rule.get("conditions") or [])
        ] or None,
        stop_loss_pct=exit_rule.get("stop_loss_pct"),
        profit_target_pct=exit_rule.get("profit_target_pct"),
        trailing_stop_pct=exit_rule.get("trailing_stop_pct"),
        stop_loss_atr=exit_rule.get("stop_loss_atr"),
        profit_target_atr=exit_rule.get("profit_target_atr"),
        trailing_stop_atr=exit_rule.get("trailing_stop_atr"),
        breakeven_trigger_pct=exit_rule.get("breakeven_trigger_pct"),
        rules=[
            {
                "conditions": [
                    {"type": c["condition"], "params": c.get("params", {}),
                     **({"timeframe": c["timeframe"]} if c.get("timeframe") else {})}
                    for c in r["conditions"]
                ],
                "match_logic": r.get("match_logic", "all"),
                "position_sizing": r.get("position_sizing"),
            }
            for r in strategy["rules"]
        ] if strategy.get("rules") else None,
        partial_exit=(
            {
                **strategy["partial_exit"],
                "conditions": [
                    {"type": c["condition"], "params": c.get("params", {}),
                     **({"timeframe": c["timeframe"]} if c.get("timeframe") else {})}
                    for c in (strategy["partial_exit"].get("conditions") or [])
                ],
            }
            if strategy.get("partial_exit") else None
        ),
        cooldown_bars=(strategy.get("risk") or {}).get("cooldown_bars", 0),
        position_sizing=strategy.get("position_sizing"),
        risk=strategy.get("risk"),
    ))
