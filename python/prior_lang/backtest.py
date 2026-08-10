"""Reference backtester: strategy JSON + one instrument's bars → metrics.

Deliberately small and readable — this is the conformance runner, not a
research platform. Bar-close fills: a signal at bar i earns bar i+1's
return. Metrics assume daily bars for annualization (252).

pandas/numpy are imported lazily so the core package stays dependency-free
for parse/validate/fmt/explain; `prior backtest` tells you what to install
if they're missing.
"""

from __future__ import annotations

import math
from .codegen import compile_strategy


# The reporting convention, stated wherever the number goes. Two Sharpe
# conventions circulate (daily curve vs per trade returns) and an
# unlabeled number lets a reader assume the flattering one.
SHARPE_NOTE = "daily returns, annualized by sqrt(252)"


def _require_pandas():
    try:
        import numpy as np
        import pandas as pd
        return pd, np
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "prior backtest needs pandas and numpy: pip install 'prior-lang[backtest]'"
        ) from e


def load_bars(path: str):
    """Load OHLCV bars from CSV, Parquet, JSON (array of bar records), or
    JSONL (one bar object per line). Column names are matched
    case-insensitively; a date/time column becomes the index if present.

    A `ticker` (or `symbol`) column marks a multi-instrument file — one
    stacked set of rows per ticker — and is preserved for the universe
    runner to group on."""
    pd, _np = _require_pandas()
    import os
    if not os.path.exists(path):
        raise SystemExit(
            f"no such data file: {path}\n"
            "(need bars fast? prior sample lists free downloads)"
        )
    if path.endswith((".parquet", ".pq")):
        df = pd.read_parquet(path)
    elif path.endswith(".jsonl"):
        df = pd.read_json(path, lines=True)
    elif path.endswith(".json"):
        df = pd.read_json(path, orient="records")
    else:
        df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "symbol" in df.columns and "ticker" not in df.columns:
        df = df.rename(columns={"symbol": "ticker"})
    for date_col in ("date", "time", "timestamp", "datetime"):
        if date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col])
            df = df.set_index(date_col)
            break
    missing = [c for c in ("close",) if c not in df.columns]
    if missing:
        raise SystemExit(f"data file is missing column(s): {', '.join(missing)}")
    for col in ("open", "high", "low"):
        if col not in df.columns:
            df[col] = df["close"]
    if "volume" not in df.columns:
        df["volume"] = 0
    _check_chronological(df)
    return df


def _check_chronological(df) -> None:
    """Refuse bars that are out of order or duplicated.

    The grammar guarantees no expression reads a bar that has not closed,
    but that guarantee is stated in terms of row order. Hand the runner a
    file whose rows are shuffled and `close.shift(1)` faithfully returns
    whatever row happens to sit above — which can be a later date. The
    lookahead then arrives through the data door instead of the grammar,
    and the run still prints a plausible-looking result.

    So this is checked rather than assumed. It is not sorted silently:
    a file in the wrong order means something upstream is broken, and
    quietly repairing it would hide the actual bug. Duplicated timestamps
    are refused for the same reason.
    """
    pd, _ = _require_pandas()
    if not isinstance(df.index, pd.DatetimeIndex) or len(df) < 2:
        return

    def _fail(kind: str, where: str, hint: str):
        raise SystemExit(
            f"bars are {kind}{where}.\n"
            "PRIOR guarantees no strategy reads a bar that hasn't closed, and that "
            "guarantee is\nstated in row order. Out-of-order bars break it silently "
            f"and still produce a result.\n{hint}"
        )

    groups = df.groupby(df["ticker"]) if "ticker" in df.columns else [("", df)]
    for name, part in groups:
        where = f" for {name}" if name else ""
        idx = part.index
        if idx.has_duplicates:
            dupe = idx[idx.duplicated()][0]
            _fail("duplicated", f"{where} (first repeat: {dupe.date()})",
                  "Drop or merge the repeated timestamps before backtesting.")
        if not idx.is_monotonic_increasing:
            bad = next(
                (idx[i + 1] for i in range(len(idx) - 1) if idx[i + 1] < idx[i]), None
            )
            at = f" (first at {bad.date()})" if bad is not None else ""
            _fail("not in chronological order", f"{where}{at}",
                  "Sort by the date column and run again. If they arrived sorted as "
                  "text,\ncheck the dates parsed as dates rather than strings.")


def resolve_universe_tickers(strategy: dict) -> list[str] | None:
    """The tickers a strategy's universe declares, or None if unknown
    (manual lists without tickers, and dynamic universes — those resolve
    from the data itself via dynamic_membership)."""
    from .tags import UNIVERSE_TICKERS

    uni = strategy.get("universe", {}) or {}
    if uni.get("type") == "prebuilt":
        return UNIVERSE_TICKERS.get(uni.get("key"))
    if uni.get("type") == "dynamic":
        return None
    return uni.get("tickers")


def dynamic_membership(strategy: dict, df):
    """Membership mask (dates × tickers, bool) for a dynamic universe, or
    None if the universe isn't dynamic.

    top_volume semantics: on the first bar of each month, rank tickers by
    trailing `period`-bar average dollar volume as of the PRIOR bar (no
    same-bar lookahead) and keep the top `count` until the next recompute.
    Bars before the first recompute have no members — the strategy waits,
    exactly like a warmup period.
    """
    pd, _np = _require_pandas()
    uni = strategy.get("universe", {}) or {}
    if uni.get("type") != "dynamic":
        return None
    p = uni.get("params", {}) or {}
    count, period = int(p.get("count", 50)), int(p.get("period", 20))

    closes = df.pivot_table(index=df.index, columns="ticker", values="close")
    volumes = df.pivot_table(index=df.index, columns="ticker", values="volume")
    closes.columns = [str(c).upper() for c in closes.columns]
    volumes.columns = [str(c).upper() for c in volumes.columns]
    dollar = (closes * volumes).rolling(period, min_periods=period).mean().shift(1)

    member = pd.DataFrame(False, index=closes.index, columns=closes.columns)
    months = closes.index.to_period("M")
    recompute = pd.Series(True, index=closes.index).groupby(months).cumsum() == 1
    current: set[str] = set()
    started = False
    for i, ts in enumerate(closes.index):
        # Recompute on month-firsts; before the first successful ranking,
        # keep trying every bar so warmup ends as soon as data allows.
        if recompute.iloc[i] or not started:
            ranked = dollar.iloc[i].dropna().sort_values(ascending=False)
            if len(ranked):
                current = set(ranked.head(count).index)
                started = True
        if current:
            member.loc[ts, list(current)] = True
    return member


def run_universe_backtest(strategy: dict, df, capital: float | None = None,
                          cost_bps: float = 0.0, fill: str = "close") -> dict:
    """Run the strategy independently over each ticker in a multi-ticker
    frame, filtered to the strategy's universe.

    These are independent per-instrument runs — each ticker gets the full
    hypothetical allocation, and risk guards like max_positions have no
    cross-ticker meaning here. Portfolio-level simulation with shared
    capital is the reference runner's job (AutoQuant desktop).
    """
    universe = resolve_universe_tickers(strategy)
    in_file = [str(t).upper() for t in df["ticker"].unique()]
    membership = dynamic_membership(strategy, df)

    if universe is not None:
        wanted = [t for t in in_file if t in set(universe)]
        skipped = sorted(set(in_file) - set(universe))
        not_in_file = sorted(set(universe) - set(in_file))
    elif membership is not None:
        # Dynamic universe: every ticker with at least one membership
        # window runs; its signals are masked outside those windows.
        wanted = [t for t in in_file if t in membership.columns and bool(membership[t].any())]
        skipped = sorted(set(in_file) - set(wanted))
        not_in_file = []
    else:
        wanted, skipped, not_in_file = in_file, [], []

    per_ticker = []
    for ticker in wanted:
        bars = df[df["ticker"].str.upper() == ticker].drop(columns=["ticker"]).sort_index()
        mask = membership[ticker].reindex(bars.index).fillna(False) if membership is not None else None
        result = run_backtest(strategy, bars, mask=mask, capital=capital,
                              cost_bps=cost_bps, fill=fill)
        result["ticker"] = ticker
        per_ticker.append(result)

    returns = [r["total_return_pct"] for r in per_ticker]
    return {
        "per_ticker": per_ticker,
        "skipped_not_in_universe": skipped,
        "universe_not_in_file": not_in_file,
        "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
        "total_trades": sum(r["trades"] for r in per_ticker),
    }


def _rule_weight(sizing, capital: float, stop_pct) -> float:
    """One entry's position weight under a capital base. Weight is capped
    at 1.0 (the reference runner does not model leverage)."""
    if sizing is None:
        return 1.0
    m = sizing.get("method")
    v = float(sizing.get("value", 1.0))
    if m == "percent_of_portfolio":
        return min(1.0, v)
    if m == "fixed_dollar":
        return min(1.0, v / capital) if capital else 1.0
    if m == "risk_based":
        # size so the stop distance costs v of the portfolio
        if stop_pct:
            return min(1.0, v / (float(stop_pct) / 100.0))
        return 1.0
    return 1.0


def _weight_series(strategy: dict, df, signals, capital: float, namespace):
    """Per-bar position weight implied by the strategy's sizing tags.

    Fast path: every rule shares one sizing -> constant weight. Otherwise
    the traced run tells us which rule (or direction) opened each
    position, and that entry's weight holds until the position closes.
    """
    pd, _np = _require_pandas()
    exits = strategy.get("exits")
    long_stop = ((exits or {}).get("long") or strategy.get("exit") or {}).get("stop_loss_pct")
    short_stop = ((exits or {}).get("short") or strategy.get("exit") or {}).get("stop_loss_pct")

    rules = strategy.get("rules")
    if not rules:
        w = _rule_weight(strategy.get("position_sizing"), capital, long_stop)
        return pd.Series(w, index=df.index)

    weights = [
        _rule_weight(r.get("position_sizing") or strategy.get("position_sizing"),
                     capital,
                     short_stop if r.get("direction") == "short" else long_stop)
        for r in rules
    ]
    if len(set(weights)) == 1:
        return pd.Series(weights[0], index=df.index)

    # Differing per-rule sizes: replay the traced events.
    import numpy as np
    traced_ns = {"pd": pd, "np": np, "math": math}
    exec(compile_strategy(strategy, trace=True), traced_ns)
    _sig, events = traced_ns["generate_signals_traced"](df)
    long_w = next((w for w, r in zip(weights, rules) if r.get("direction", "long") == "long"), 1.0)
    short_w = next((w for w, r in zip(weights, rules) if r.get("direction") == "short"), 1.0)
    w_arr = [1.0] * len(df)
    current = 1.0
    ei = 0
    starts = {}
    for e in events:
        if e["event"] == "entry":
            if "rule" in e and e["rule"] is not None and e["rule"] < len(weights):
                starts[e["i"]] = weights[e["rule"]]
            else:
                starts[e["i"]] = long_w if e.get("dir", 1) > 0 else short_w
    for i in range(len(df)):
        if i in starts:
            current = starts[i]
        w_arr[i] = current
    return pd.Series(w_arr, index=df.index)


FILL_CONVENTIONS = ("close", "next-open")


def _check_fill(fill: str, frames) -> None:
    """Refuse an unknown fill convention, and refuse next-open when the
    data carries no open column — the price the convention needs."""
    from .errors import PriorError

    if fill not in FILL_CONVENTIONS:
        raise PriorError(
            f"fill must be one of {', '.join(FILL_CONVENTIONS)} — got {fill!r}")
    if fill == "next-open":
        for f in frames:
            if "open" not in f.columns:
                raise PriorError(
                    "fill next-open prices entries at the next bar's open, "
                    "but the data has no open column")


def _next_open_returns(pd, np, position, gap, intra, cc):
    """Per-bar returns when positions change at the NEXT bar's open.

    On a bar where the position changes, the old position carries the
    overnight gap and the new position the open-to-close move, compounded.
    On unchanged bars the full close-to-close return applies — identical
    to the close-fill accounting.
    """
    prev = position.shift(1).fillna(0.0)
    changed = position.ne(prev)
    split = (1.0 + prev * gap) * (1.0 + position * intra) - 1.0
    return pd.Series(np.where(changed, split, position * cc), index=position.index)


def run_backtest(strategy: dict, df, mask=None, capital: float | None = None,
                 cost_bps: float = 0.0, score_from=None, fill: str = "close") -> dict:
    """Execute the strategy over one instrument's bars; return metrics.

    `mask` (optional bool Series on df's index) zeroes signals outside a
    dynamic universe's membership windows. Signals stay float — partial
    exits emit fractional positions like 0.5.

    `capital` (optional dollars) makes the sizing tags REAL: [5%
    portfolio] takes a 5% position with the rest in cash, [$5000]
    becomes 5000/capital, [risk 1%] sizes off the stop distance. Without
    it the runner keeps its documented default: one fully-allocated
    position, sizing tags as metadata.

    `score_from` (optional timestamp) splits WARMUP from SCORING:
    signals are computed over all of `df`, metrics only over bars at or
    after `score_from`. This is how an out-of-sample window is scored
    honestly for strategies with long indicators — a 200-day average is
    NaN for the first 200 bars of any freshly sliced window, so scoring
    a bare holdout silently reports "never traded" for exactly the
    strategies with the longest memory. Warming up on earlier bars leaks
    nothing: live trading carries its indicator history in the same way.
    """
    pd, np = _require_pandas()
    _check_fill(fill, (df,))

    code = compile_strategy(strategy)
    namespace = {"pd": pd, "np": np, "math": math}
    exec(code, namespace)  # our own generated code
    raw_signals = namespace["generate_signals"](df)
    gate_stats = dict(raw_signals.attrs.get("after_losses") or {})
    signals = raw_signals.astype(float)
    if mask is not None:
        signals = signals.where(mask, 0.0)
    if capital:
        signals = signals * _weight_series(strategy, df, signals, capital, namespace)

    if score_from is not None:
        keep = df.index >= pd.Timestamp(score_from)
        df, signals = df[keep], signals[keep]

    close = df["close"].astype(float)
    # Signal at bar i → position over bar i+1 (no lookahead at the fill).
    position = signals.shift(1).fillna(0)
    bar_returns = close.pct_change().fillna(0)
    if fill == "next-open":
        opens = df["open"].astype(float)
        gap = (opens / close.shift(1) - 1).fillna(0.0)
        intra = (close / opens - 1).fillna(0.0)
        strat_returns = _next_open_returns(pd, np, position, gap, intra, bar_returns)
    else:
        strat_returns = position * bar_returns
    if cost_bps:
        # Cost charged on every unit of position change (entries, exits,
        # partials, flips all pay in proportion to size traded).
        turnover = position.diff().abs().fillna(position.abs())
        strat_returns = strat_returns - turnover * (cost_bps / 10_000.0)
    equity = (1 + strat_returns).cumprod()

    # Trades: edges of the signal's SIGN (fractional partials like 0.5 stay
    # inside one trade; a reverse-flip closes one trade and opens the next).
    # An open trade closes at the last bar. Short PnL is the mirrored move.
    # Trades are priced at the fill: the signal bar's close, or under
    # next-open the following bar's open — so a signal on the final bar
    # never fills there, and an exit that cannot fill marks at the last
    # close, matching the equity accounting.
    sig = signals.to_numpy()
    closes = close.to_numpy()
    if fill == "next-open":
        fillp = np.append(df["open"].astype(float).to_numpy()[1:], np.nan)
    else:
        fillp = closes
    trades = []
    entry_i = None
    entry_dir = 0
    prev = 0.0
    for i in range(len(sig)):
        s = sig[i]
        if s != 0 and prev == 0:
            if not math.isnan(fillp[i]):
                entry_i, entry_dir = i, (1 if s > 0 else -1)
        elif entry_i is not None and (s == 0 or (s > 0) != (prev > 0)):
            out = fillp[i] if not math.isnan(fillp[i]) else closes[-1]
            trades.append(entry_dir * (out / fillp[entry_i] - 1))
            if s != 0 and not math.isnan(fillp[i]):  # flipped straight into the other direction
                entry_i, entry_dir = i, (1 if s > 0 else -1)
            else:
                entry_i = None
        prev = s
    if entry_i is not None:
        trades.append(entry_dir * (closes[-1] / fillp[entry_i] - 1))

    total_return = float(equity.iloc[-1] - 1)
    years = max(len(df) / 252.0, 1e-9)
    cagr = float((1 + total_return) ** (1 / years) - 1) if total_return > -1 else -1.0
    vol = float(strat_returns.std() * (252 ** 0.5))
    sharpe = float(strat_returns.mean() / strat_returns.std() * (252 ** 0.5)) if strat_returns.std() > 0 else 0.0
    running_max = equity.cummax()
    max_dd = float((equity / running_max - 1).min())
    wins = [t for t in trades if t > 0]

    dollars = {}
    if capital:
        dollars = {
            "capital": round(float(capital), 2),
            "final_equity_usd": round(capital * float(equity.iloc[-1]), 2),
            "net_pnl_usd": round(capital * total_return, 2),
        }
    return {
        "bars": len(df),
        "equity": equity,
        "position": position,
        "fill": fill,
        **dollars,
        **({"after_losses": gate_stats} if gate_stats else {}),
        "total_return_pct": round(total_return * 100, 2),
        "buy_hold_return_pct": round(float(closes[-1] / closes[0] - 1) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "sharpe_note": SHARPE_NOTE,
        "cost_bps": float(cost_bps),
        "volatility_pct": round(vol * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else None,
        "avg_trade_pct": round(100 * sum(trades) / len(trades), 3) if trades else None,
    }


def _pair_events_into_trades(events, index, closes) -> list[dict]:
    """Pair up entry/exit events into trade records. `closes` is the
    series the strategy actually traded on (raw closes, or the spread)."""
    trades = []
    open_t = None
    for e in events:
        if e["event"] == "entry":
            open_t = {"i": e["i"], "dir": int(e.get("dir", 1)), "rule": e.get("rule")}
        elif e["event"] == "exit" and open_t is not None:
            i0, i1, d = open_t["i"], e["i"], open_t["dir"]
            trades.append({
                "entry_date": str(getattr(index[i0], "date", lambda: index[i0])()),
                "exit_date": str(getattr(index[i1], "date", lambda: index[i1])()),
                "direction": "long" if d > 0 else "short",
                "rule": open_t["rule"],
                "entry_price": round(float(closes[i0]), 4),
                "exit_price": round(float(closes[i1]), 4),
                "bars_held": i1 - i0,
                "return_pct": round(d * (float(closes[i1]) / float(closes[i0]) - 1) * 100, 2),
                "exit_reason": e["reason"],
            })
            open_t = None
    if open_t is not None:
        i0, i1, d = open_t["i"], len(closes) - 1, open_t["dir"]
        trades.append({
            "entry_date": str(getattr(index[i0], "date", lambda: index[i0])()),
            "exit_date": str(getattr(index[i1], "date", lambda: index[i1])()),
            "direction": "long" if d > 0 else "short",
            "rule": open_t["rule"],
            "entry_price": round(float(closes[i0]), 4),
            "exit_price": round(float(closes[i1]), 4),
            "bars_held": i1 - i0,
            "return_pct": round(d * (float(closes[i1]) / float(closes[i0]) - 1) * 100, 2),
            "exit_reason": "open",
        })
    return trades


def trade_log(strategy: dict, df) -> list[dict]:
    """Per-trade log for a rules/mixed strategy over one instrument's
    bars: entry/exit dates and prices, direction, bars held, return, and
    WHICH exit fired (knowable because exit precedence is deterministic).
    Partial exits scale the position mid-trade; the log reports the full
    entry-to-exit move per direction."""
    pd, np = _require_pandas()
    code = compile_strategy(strategy, trace=True)
    namespace = {"pd": pd, "np": np, "math": math}
    exec(code, namespace)  # our own generated code
    _sig, events = namespace["generate_signals_traced"](df)
    return _pair_events_into_trades(events, df.index, df["close"].astype(float).to_numpy())


def pair_trade_log(strategy: dict, df) -> list[dict]:
    """Trade log for a spread strategy: prices are SPREAD values."""
    pd, np = _require_pandas()
    a, b = [str(t).upper() for t in strategy["universe"]["tickers"]]
    form = strategy["universe"].get("form", "ratio")
    panel = {
        str(t).upper(): g.drop(columns=["ticker"]).sort_index()
        for t, g in df.groupby(df["ticker"].str.upper())
    }
    code = compile_strategy(strategy, trace=True)
    namespace = {"pd": pd, "np": np, "math": math}
    exec(code, namespace)  # our own generated code
    sig, events = namespace["generate_pair_signals_traced"](panel)
    close_a = panel[a]["close"].astype(float).reindex(sig.index)
    close_b = panel[b]["close"].astype(float).reindex(sig.index)
    spread = (close_a / close_b) if form == "ratio" else (close_a - close_b)
    return _pair_events_into_trades(events, sig.index, spread.to_numpy())


def run_pair_backtest(strategy: dict, df, cost_bps: float = 0.0,
                      fill: str = "close") -> dict:
    """Backtest a spread strategy over a multi-ticker frame containing
    both legs. Position accounting is equal dollar legs: a +1 spread
    signal is long leg A / short leg B, each at half the allocation, so
    the position return per bar is 0.5 * (ret_A - ret_B). Net market
    exposure is ~0 by construction; the P&L is the relative move."""
    pd, np = _require_pandas()

    a, b = [str(t).upper() for t in strategy["universe"]["tickers"]]
    form = strategy["universe"].get("form", "ratio")
    panel = {
        str(t).upper(): g.drop(columns=["ticker"]).sort_index()
        for t, g in df.groupby(df["ticker"].str.upper())
    }
    missing = [t for t in (a, b) if t not in panel]
    if missing:
        raise SystemExit(
            f"the data file has no rows for {', '.join(missing)} — a spread "
            f"backtest needs both legs ({a} and {b})"
        )
    _check_fill(fill, (panel[a], panel[b]))

    code = compile_strategy(strategy)
    namespace = {"pd": pd, "np": np, "math": math}
    exec(code, namespace)  # our own generated code
    signals = namespace["generate_pair_signals"](panel).astype(float)

    close_a = panel[a]["close"].astype(float).reindex(signals.index)
    close_b = panel[b]["close"].astype(float).reindex(signals.index)
    spread = (close_a / close_b) if form == "ratio" else (close_a - close_b)

    position = signals.shift(1).fillna(0)
    ret_a = close_a.pct_change().fillna(0)
    ret_b = close_b.pct_change().fillna(0)
    pair_cc = 0.5 * (ret_a - ret_b)
    if fill == "next-open":
        open_a = panel[a]["open"].astype(float).reindex(signals.index)
        open_b = panel[b]["open"].astype(float).reindex(signals.index)
        gap = 0.5 * ((open_a / close_a.shift(1) - 1).fillna(0.0)
                     - (open_b / close_b.shift(1) - 1).fillna(0.0))
        intra = 0.5 * ((close_a / open_a - 1).fillna(0.0)
                       - (close_b / open_b - 1).fillna(0.0))
        strat_returns = _next_open_returns(pd, np, position, gap, intra, pair_cc)
    else:
        strat_returns = position * pair_cc
    if cost_bps:
        turnover = position.diff().abs().fillna(position.abs())
        strat_returns = strat_returns - turnover * (cost_bps / 10_000.0)  # both legs, half-sized each
    equity = (1 + strat_returns).cumprod()

    # Trades on the spread signal's sign, same accounting as run_backtest
    # but P&L measured on the dollar-neutral pair return.
    sig = signals.to_numpy()
    trades = []
    entry_i = None
    entry_dir = 0
    prev = 0.0
    cum = (1 + strat_returns).cumprod().to_numpy()
    for i in range(len(sig)):
        s = sig[i]
        if s != 0 and prev == 0:
            entry_i, entry_dir = i, (1 if s > 0 else -1)
        elif entry_i is not None and (s == 0 or (s > 0) != (prev > 0)):
            trades.append(cum[i] / cum[entry_i] - 1)
            entry_i = None if s == 0 else i
            entry_dir = 0 if s == 0 else (1 if s > 0 else -1)
        prev = s
    if entry_i is not None:
        trades.append(cum[-1] / cum[entry_i] - 1)

    total_return = float(equity.iloc[-1] - 1)
    years = max(len(signals) / 252.0, 1e-9)
    cagr = float((1 + total_return) ** (1 / years) - 1) if total_return > -1 else -1.0
    sharpe = float(strat_returns.mean() / strat_returns.std() * (252 ** 0.5)) if strat_returns.std() > 0 else 0.0
    running_max = equity.cummax()
    max_dd = float((equity / running_max - 1).min())
    wins = [t for t in trades if t > 0]

    return {
        "pair": f"{a}/{b}",
        "equity": equity,
        "position": position,
        "form": form,
        "fill": fill,
        "bars": len(signals),
        "total_return_pct": round(total_return * 100, 2),
        "spread_start": round(float(spread.iloc[0]), 4),
        "spread_end": round(float(spread.iloc[-1]), 4),
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "sharpe_note": SHARPE_NOTE,
        "cost_bps": float(cost_bps),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else None,
        "avg_trade_pct": round(100 * sum(trades) / len(trades), 3) if trades else None,
    }


def run_ranking_backtest(strategy: dict, df, cost_bps: float = 0.0,
                         fill: str = "close") -> dict:
    """Portfolio backtest for a ranking (hold) strategy over a multi-ticker
    frame. Joint semantics: weights come from generate_weights, equity is
    the weighted sum of per-ticker returns, and turnover (mean |weight
    change| per rebalance) stands in for cost-awareness until cost
    modeling exists."""
    pd, np = _require_pandas()
    from .codegen import compile_strategy

    panel = {
        str(t).upper(): g.drop(columns=["ticker"]).sort_index()
        for t, g in df.groupby(df["ticker"].str.upper())
    }
    universe = resolve_universe_tickers(strategy)
    membership = dynamic_membership(strategy, df)
    skipped, missing = [], []
    if universe is not None:
        skipped = sorted(set(panel) - set(universe))
        missing = sorted(set(universe) - set(panel))
        panel = {t: v for t, v in panel.items() if t in set(universe)}
    if not panel:
        raise SystemExit("no tickers in the data file match the strategy's universe")

    code = compile_strategy(strategy)
    namespace = {"pd": pd, "np": np, "math": math}
    exec(code, namespace)  # our own generated code
    weights = namespace["generate_weights"](panel)
    if membership is not None:
        # Dynamic universe: zero out non-members (the freed weight sits in
        # cash rather than renormalizing — honest about reduced exposure).
        mask = membership.reindex(index=weights.index, columns=weights.columns, fill_value=False)
        weights = weights.where(mask, 0.0)

    closes = pd.DataFrame({t: p["close"] for t, p in panel.items()}).sort_index()
    rets = closes.pct_change().fillna(0)
    w_eff = weights.shift(1).fillna(0)
    if fill == "next-open":
        _check_fill(fill, panel.values())
        opens = pd.DataFrame({t: p["open"] for t, p in panel.items()}).sort_index()
        opens = opens.reindex(index=closes.index, columns=closes.columns)
        gap = (opens / closes.shift(1) - 1).fillna(0.0)
        intra = (closes / opens - 1).fillna(0.0)
        # Weights decided at bar i-1's close trade at bar i's open: the
        # book holds the PREVIOUS weights overnight and the new weights
        # intraday, compounded, on every bar the weights changed.
        w_prev = weights.shift(2).fillna(0)
        changed = w_eff.ne(w_prev).any(axis=1)
        split = ((1.0 + (w_prev * gap).sum(axis=1))
                 * (1.0 + (w_eff * intra).sum(axis=1)) - 1.0)
        port_rets = (w_eff * rets).sum(axis=1).where(~changed, split)
    else:
        _check_fill(fill, ())
        port_rets = (w_eff * rets).sum(axis=1)
    if cost_bps:
        daily_turnover = weights.diff().abs().sum(axis=1).fillna(0)
        port_rets = port_rets - daily_turnover * (cost_bps / 10_000.0)
    equity = (1 + port_rets).cumprod()

    turnover = weights.diff().abs().sum(axis=1)
    reb_turnover = turnover[turnover > 1e-12]

    total_return = float(equity.iloc[-1] - 1)
    years = max(len(closes) / 252.0, 1e-9)
    cagr = float((1 + total_return) ** (1 / years) - 1) if total_return > -1 else -1.0
    sharpe = float(port_rets.mean() / port_rets.std() * (252 ** 0.5)) if port_rets.std() > 0 else 0.0
    running_max = equity.cummax()
    max_dd = float((equity / running_max - 1).min())
    bench = rets.mean(axis=1)
    bench_total = float((1 + bench).cumprod().iloc[-1] - 1)

    final = weights.iloc[-1]
    holdings = sorted(
        ((t, float(w)) for t, w in final.items() if w > 1e-9),
        key=lambda kv: -kv[1],
    )

    return {
        "bars": len(closes),
        "equity": equity,
        "weights": weights,
        "fill": fill,
        "tickers": len(panel),
        "total_return_pct": round(total_return * 100, 2),
        "equal_weight_universe_pct": round(bench_total * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "sharpe_note": SHARPE_NOTE,
        "cost_bps": float(cost_bps),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "rebalances": int(len(reb_turnover)),
        "avg_turnover_pct": round(float(reb_turnover.mean()) * 100, 2) if len(reb_turnover) else 0.0,
        "holdings": holdings,
        "skipped_not_in_universe": skipped,
        "universe_not_in_file": missing,
    }


# ── Portfolio of strategies (sleeves) ──────────────────────────────

def _rebalance_dates(index, policy: str) -> set:
    pd, _np = _require_pandas()
    """Last bar of each calendar period — the same convention the
    ranking code generator emits (%Y-%m monthly, ISO %G-%V weekly).
    'never' (or a non-datetime index) rebalances nothing."""
    if policy == "never" or not isinstance(index, pd.DatetimeIndex):
        return set()
    fmt = "%G-%V" if policy == "weekly" else "%Y-%m"
    series = index.to_series()
    key = series.dt.strftime(fmt)
    return set(series.groupby(key).tail(1))


def _sleeve_run(strategy: dict, df, chains, cost_bps: float, contract_fee: float,
                fill: str = "close"):
    """Run one sleeve through its existing runner, unchanged. Returns
    (kind, result, daily_returns, exposure) where exposure maps ticker →
    per-bar direction Series (+1 long / -1 short / 0 flat), or None when
    a sleeve type cannot expose it honestly (options, v1)."""
    from .errors import PriorError

    name = strategy.get("name")
    if strategy.get("options"):
        if fill != "close":
            raise PriorError(
                f"sleeve {name!r} is an options strategy — options fill at "
                "chain marks, so fill next-open is not available for books "
                "with options sleeves")
        from .options_backtest import run_options_backtest
        tickers = (strategy.get("universe") or {}).get("tickers") or []
        bars = df[df["ticker"] == tickers[0]].drop(columns=["ticker"]) \
            if "ticker" in df.columns else df
        res = run_options_backtest(strategy, bars, chains, contract_fee=contract_fee)
        base = res.get("capital_base")
        if not base:
            raise PriorError(
                f"sleeve {name!r} reports no capital base, so it has no "
                "percent-return stream to compose")
        rets = res["equity"].diff().fillna(res["equity"].iloc[0]) / float(base)
        return "options", res, rets, None
    if (strategy.get("universe") or {}).get("type") == "pair":
        res = run_pair_backtest(strategy, df, cost_bps=cost_bps, fill=fill)
        pos = res["position"]
        a, b = [t.upper() for t in strategy["universe"]["tickers"]]
        sign = pos.apply(lambda x: 0 if x == 0 else (1 if x > 0 else -1))
        return "pair", res, _equity_rets(res["equity"]), {a: sign, b: -sign}
    if strategy.get("ranking"):
        res = run_ranking_backtest(strategy, df, cost_bps=cost_bps, fill=fill)
        w = res["weights"]
        expo = {t: (w[t] > 1e-9).astype(int) for t in w.columns}
        return "ranking", res, _equity_rets(res["equity"]), expo
    tickers = (strategy.get("universe") or {}).get("tickers") or []
    bars = df[df["ticker"] == tickers[0]].drop(columns=["ticker"]) \
        if "ticker" in df.columns else df
    if not len(bars):
        raise PriorError(f"no rows for {tickers[0]} in the data file "
                         f"(sleeve {name!r})")
    res = run_backtest(strategy, bars, cost_bps=cost_bps, fill=fill)
    pos = res["position"]
    sign = pos.apply(lambda x: 0 if x == 0 else (1 if x > 0 else -1))
    return "rules", res, _equity_rets(res["equity"]), {tickers[0]: sign}


def _equity_rets(equity):
    r = equity.pct_change()
    if len(r):
        r.iloc[0] = float(equity.iloc[0]) - 1.0
    return r.fillna(0.0)


def run_portfolio_backtest(doc: dict, df, chains=None, capital=None,
                           cost_bps: float = 0.0,
                           contract_fee: float = 0.0,
                           fill: str = "close") -> dict:
    """Compose sleeves as return streams into one book.

    Each sleeve runs its existing runner unchanged on its own slice of
    the data. Between rebalances sleeve values drift; at each boundary
    close they true up to target weights and that day is charged
    cost_bps on the true-up turnover — the same convention the ranking
    backtest uses. The combined window is the intersection of sleeve
    windows, and every convention here is printed by the report rather
    than assumed silently.
    """
    from .errors import PriorError
    pd, _np = _require_pandas()
    _check_fill(fill, ())

    port = doc["portfolio"]
    policy = port["rebalance"]
    specs = port["sleeves"]

    names, weights, kinds, results, rets_by, expo_by = [], [], [], [], {}, {}
    for s in specs:
        strat = s["strategy"]
        name = strat.get("name")
        kind, res, rets, expo = _sleeve_run(strat, df, chains, cost_bps,
                                            contract_fee, fill=fill)
        names.append(name)
        weights.append(float(s["weight_pct"]) / 100.0)
        kinds.append(kind)
        results.append(res)
        rets_by[name] = rets
        expo_by[name] = expo

    common = None
    for r in rets_by.values():
        common = r.index if common is None else common.intersection(r.index)
    common = common.sort_values()
    if len(common) < 40:
        raise PriorError(
            f"sleeves share only {len(common)} bars — a combined curve over "
            "fewer than 40 is noise wearing a number")

    reb = _rebalance_dates(common, policy)
    v = list(weights)                      # book starts at 1.0
    book_vals = []
    trueups = []
    aligned = {n: rets_by[n].reindex(common).fillna(0.0) for n in names}
    for t in common:
        for i, n in enumerate(names):
            v[i] *= (1.0 + float(aligned[n].loc[t]))
        book = sum(v)
        if t in reb:
            turnover = sum(abs(weights[i] * book - v[i]) for i in range(len(v))) / book
            if turnover > 1e-12:
                book *= (1.0 - turnover * (cost_bps / 10_000.0))
                trueups.append(turnover)
            v = [weights[i] * book for i in range(len(v))]
        book_vals.append(book)
    equity = pd.Series(book_vals, index=common)
    book_rets = _equity_rets(equity)

    total_return = float(equity.iloc[-1] - 1)
    years = max(len(common) / 252.0, 1e-9)
    cagr = float((1 + total_return) ** (1 / years) - 1) if total_return > -1 else -1.0
    vol = float(book_rets.std() * (252 ** 0.5))
    sharpe = float(book_rets.mean() / book_rets.std() * (252 ** 0.5)) \
        if book_rets.std() > 0 else 0.0
    running_max = equity.cummax()
    max_dd = float((equity / running_max - 1).min())

    correlations = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            ra, rb = aligned[names[i]], aligned[names[j]]
            # A constant return stream has no correlation to report —
            # guard rather than let numpy warn its way to the same NaN.
            if float(ra.std()) == 0.0 or float(rb.std()) == 0.0:
                c = None
            else:
                c = ra.corr(rb)
            correlations.append({"a": names[i], "b": names[j],
                                 "corr": round(float(c), 3)
                                 if c is not None and pd.notna(c) else None})

    overlap = []
    overlap_unavailable = [n for n in names if expo_by[n] is None]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            ea, eb = expo_by[names[i]], expo_by[names[j]]
            if ea is None or eb is None:
                continue
            for tk in set(ea) & set(eb):
                a = ea[tk].reindex(common).fillna(0)
                b = eb[tk].reindex(common).fillna(0)
                both = (a != 0) & (b != 0)
                if not both.any():
                    continue
                opposed = both & ((a * b) < 0)
                overlap.append({
                    "a": names[i], "b": names[j], "ticker": tk,
                    "both_pct": round(float(both.mean() * 100), 1),
                    "opposed_pct": round(float(opposed.mean() * 100), 1),
                })

    sleeves_out = []
    for i, n in enumerate(names):
        res = results[i]
        sleeves_out.append({
            "name": n,
            "weight_pct": round(weights[i] * 100, 2),
            "kind": kinds[i],
            "total_return_pct": res.get("total_return_pct"),
            "sharpe": res.get("sharpe"),
            "max_drawdown_pct": res.get("max_drawdown_pct"),
        })

    dollars = {}
    if capital:
        dollars = {
            "capital": round(float(capital), 2),
            "final_equity_usd": round(capital * float(equity.iloc[-1]), 2),
            "net_pnl_usd": round(capital * total_return, 2),
        }
    return {
        "bars": len(common),
        "equity": equity,
        **dollars,
        "window": {"from": str(common[0])[:10], "to": str(common[-1])[:10]},
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "sharpe_note": SHARPE_NOTE,
        "volatility_pct": round(vol * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "cost_bps": float(cost_bps),
        "rebalance": policy,
        "fill": fill,
        "rebalances": len(trueups),
        "avg_trueup_turnover_pct": round(100 * sum(trueups) / len(trueups), 2)
            if trueups else 0.0,
        "sleeves": sleeves_out,
        "correlations": correlations,
        "overlap": overlap,
        "overlap_unavailable": overlap_unavailable,
    }
