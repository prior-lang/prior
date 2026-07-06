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
    return df


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


def run_universe_backtest(strategy: dict, df) -> dict:
    """Run the strategy independently over each ticker in a multi-ticker
    frame, filtered to the strategy's universe.

    These are independent per-instrument runs — each ticker gets the full
    hypothetical allocation, and risk guards like max_positions have no
    cross-ticker meaning here. Portfolio-level simulation with shared
    capital is the reference runner's job (AutoQuant desktop / --cloud).
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
        result = run_backtest(strategy, bars, mask=mask)
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


def run_backtest(strategy: dict, df, mask=None) -> dict:
    """Execute the strategy over one instrument's bars; return metrics.

    `mask` (optional bool Series on df's index) zeroes signals outside a
    dynamic universe's membership windows. Signals stay float — partial
    exits emit fractional positions like 0.5.
    """
    pd, np = _require_pandas()

    code = compile_strategy(strategy)
    namespace = {"pd": pd, "np": np, "math": math}
    exec(code, namespace)  # our own generated code
    signals = namespace["generate_signals"](df).astype(float)
    if mask is not None:
        signals = signals.where(mask, 0.0)

    close = df["close"].astype(float)
    # Signal at bar i → position over bar i+1 (no lookahead at the fill).
    position = signals.shift(1).fillna(0)
    bar_returns = close.pct_change().fillna(0)
    strat_returns = position * bar_returns
    equity = (1 + strat_returns).cumprod()

    # Trades: edges of the signal's SIGN (fractional partials like 0.5 stay
    # inside one trade; a reverse-flip closes one trade and opens the next).
    # An open trade closes at the last bar. Short PnL is the mirrored move.
    sig = signals.to_numpy()
    closes = close.to_numpy()
    trades = []
    entry_i = None
    entry_dir = 0
    prev = 0.0
    for i in range(len(sig)):
        s = sig[i]
        if s != 0 and prev == 0:
            entry_i, entry_dir = i, (1 if s > 0 else -1)
        elif entry_i is not None and (s == 0 or (s > 0) != (prev > 0)):
            trades.append(entry_dir * (closes[i] / closes[entry_i] - 1))
            if s != 0:  # flipped straight into the other direction
                entry_i, entry_dir = i, (1 if s > 0 else -1)
            else:
                entry_i = None
        prev = s
    if entry_i is not None:
        trades.append(entry_dir * (closes[-1] / closes[entry_i] - 1))

    total_return = float(equity.iloc[-1] - 1)
    years = max(len(df) / 252.0, 1e-9)
    cagr = float((1 + total_return) ** (1 / years) - 1) if total_return > -1 else -1.0
    vol = float(strat_returns.std() * (252 ** 0.5))
    sharpe = float(strat_returns.mean() / strat_returns.std() * (252 ** 0.5)) if strat_returns.std() > 0 else 0.0
    running_max = equity.cummax()
    max_dd = float((equity / running_max - 1).min())
    wins = [t for t in trades if t > 0]

    return {
        "bars": len(df),
        "total_return_pct": round(total_return * 100, 2),
        "buy_hold_return_pct": round(float(closes[-1] / closes[0] - 1) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "volatility_pct": round(vol * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else None,
        "avg_trade_pct": round(100 * sum(trades) / len(trades), 3) if trades else None,
    }


def run_pair_backtest(strategy: dict, df) -> dict:
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
    strat_returns = position * 0.5 * (ret_a - ret_b)
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
        "form": form,
        "bars": len(signals),
        "total_return_pct": round(total_return * 100, 2),
        "spread_start": round(float(spread.iloc[0]), 4),
        "spread_end": round(float(spread.iloc[-1]), 4),
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else None,
        "avg_trade_pct": round(100 * sum(trades) / len(trades), 3) if trades else None,
    }


def run_ranking_backtest(strategy: dict, df) -> dict:
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
    port_rets = (weights.shift(1).fillna(0) * rets).sum(axis=1)
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
        "tickers": len(panel),
        "total_return_pct": round(total_return * 100, 2),
        "equal_weight_universe_pct": round(bench_total * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "rebalances": int(len(reb_turnover)),
        "avg_turnover_pct": round(float(reb_turnover.mean()) * 100, 2) if len(reb_turnover) else 0.0,
        "holdings": holdings,
        "skipped_not_in_universe": skipped,
        "universe_not_in_file": missing,
    }
