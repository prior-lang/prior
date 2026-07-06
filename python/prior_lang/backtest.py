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
    """Load OHLCV bars from CSV or Parquet. Column names are matched
    case-insensitively; a date/time column becomes the index if present.

    A `ticker` (or `symbol`) column marks a multi-instrument file — one
    stacked set of rows per ticker — and is preserved for the universe
    runner to group on."""
    pd, _np = _require_pandas()
    if path.endswith((".parquet", ".pq")):
        df = pd.read_parquet(path)
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
    """The tickers a strategy's universe declares, or None if unknown."""
    from .tags import UNIVERSE_TICKERS

    uni = strategy.get("universe", {}) or {}
    if uni.get("type") == "prebuilt":
        return UNIVERSE_TICKERS.get(uni.get("key"))
    return uni.get("tickers")


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

    if universe is not None:
        wanted = [t for t in in_file if t in set(universe)]
        skipped = sorted(set(in_file) - set(universe))
        not_in_file = sorted(set(universe) - set(in_file))
    else:
        wanted, skipped, not_in_file = in_file, [], []

    per_ticker = []
    for ticker in wanted:
        bars = df[df["ticker"].str.upper() == ticker].drop(columns=["ticker"]).sort_index()
        result = run_backtest(strategy, bars)
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


def run_backtest(strategy: dict, df) -> dict:
    """Execute the strategy over one instrument's bars; return metrics."""
    pd, np = _require_pandas()

    code = compile_strategy(strategy)
    namespace = {"pd": pd, "np": np, "math": math}
    exec(code, namespace)  # our own generated code
    signals = namespace["generate_signals"](df).astype(int)

    close = df["close"].astype(float)
    # Signal at bar i → position over bar i+1 (no lookahead at the fill).
    position = signals.shift(1).fillna(0)
    bar_returns = close.pct_change().fillna(0)
    strat_returns = position * bar_returns
    equity = (1 + strat_returns).cumprod()

    # Trades: rising/falling edges of the signal; open trade closes at end.
    sig = signals.to_numpy()
    closes = close.to_numpy()
    trades = []
    entry_i = None
    for i in range(len(sig)):
        if sig[i] == 1 and (i == 0 or sig[i - 1] == 0):
            entry_i = i
        elif sig[i] == 0 and i > 0 and sig[i - 1] == 1 and entry_i is not None:
            trades.append(closes[i] / closes[entry_i] - 1)
            entry_i = None
    if entry_i is not None:
        trades.append(closes[-1] / closes[entry_i] - 1)

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
