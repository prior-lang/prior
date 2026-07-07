"""Reference options backtester: strategy JSON + underlying bars + the
USER'S OWN chain data → cash-ledger metrics.

The OSS toolchain never bundles or synthesizes chain data (it can't be
done honestly). It will happily run on chains you bring: one row per
contract per day with date, expiry, strike, right (P/C), delta, mid.

Accounting is deliberately simple and stated: fills at mid, one
position at a time, contracts × 100 multiplier, no commissions or
slippage, no early assignment (single legs settle by moneyness at
expiry; multi-leg structures settle cash by net intrinsic). This is a
conformance runner, not a research platform — AutoQuant's engine is
the research-grade path.
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
            "options backtests need pandas and numpy: pip install 'prior-lang[backtest]'"
        ) from e


def load_chains(path: str):
    """Load option chains: CSV, Parquet, JSON, or JSONL. Columns (case-
    insensitive): date, expiry, strike, right, delta, mid. right accepts
    P/C or put/call. delta may be signed or absolute."""
    pd, _np = _require_pandas()
    import os
    if not os.path.exists(path):
        raise SystemExit(f"no such chains file: {path}")
    if path.endswith((".parquet", ".pq")):
        df = pd.read_parquet(path)
    elif path.endswith(".jsonl"):
        df = pd.read_json(path, lines=True)
    elif path.endswith(".json"):
        df = pd.read_json(path, orient="records")
    else:
        df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in ("date", "expiry", "strike", "right", "delta", "mid")
               if c not in df.columns]
    if missing:
        raise SystemExit(
            f"chains file is missing column(s): {', '.join(missing)} "
            "(need date, expiry, strike, right, delta, mid)"
        )
    df["date"] = pd.to_datetime(df["date"])
    df["expiry"] = pd.to_datetime(df["expiry"])
    df["right"] = df["right"].astype(str).str.upper().str[0]  # put->P, call->C
    df["strike"] = df["strike"].astype(float)
    df["delta"] = df["delta"].astype(float).abs()
    df["mid"] = df["mid"].astype(float)
    return df


def run_options_backtest(strategy: dict, df, chains) -> dict:
    """Execute an options strategy; return a cash-ledger report."""
    pd, np = _require_pandas()

    contracts = int((strategy.get("risk") or {}).get("contracts", 1))
    mult = 100.0 * contracts

    code = compile_strategy(strategy)
    namespace = {"pd": pd, "np": np, "math": math}
    exec(code, namespace)  # our own generated code
    orders = namespace["generate_option_orders"](df, chains)

    if len(orders) == 0:
        # No entries ever fired (gate never true, or no viable contracts):
        # report an honest zero row, not a crash.
        return {"orders": orders, "cycles": 0, "wins": 0, "win_rate_pct": None,
                "net_pnl": 0.0, "option_pnl": 0.0, "stock_pnl": 0.0,
                "premium_collected": 0.0, "contracts": contracts,
                "final_shares": 0, "capital_base": None,
                "total_return_pct": None, "sharpe": None, "max_drawdown_pct": None,
                "equity": pd.Series(0.0, index=df.index)}

    is_structure = "group" in orders.columns

    cash = 0.0
    premium = 0.0
    shares = 0
    cycle_pnl: dict = {}

    if is_structure:
        for _, o in orders.iterrows():
            sign = 1.0 if o["side"] == "short" else -1.0
            if o["action"] in ("open", "roll_open"):
                flow = sign * o["price"]
                premium += flow * mult  # legs sum to the structure's net credit
            else:  # close, roll_close, settle
                flow = -sign * o["price"]
            cash += flow * mult
            cycle_pnl[o["group"]] = cycle_pnl.get(o["group"], 0.0) + flow * mult
    else:
        cycle = 0
        for _, o in orders.iterrows():
            a = o["action"]
            if a in ("sell_put", "sell_call", "roll_open"):
                cycle += 1
                cash += o["price"] * mult
                premium += o["price"] * mult
                cycle_pnl[cycle] = cycle_pnl.get(cycle, 0.0) + o["price"] * mult
            elif a in ("close", "roll_close"):
                cash -= o["price"] * mult
                cycle_pnl[cycle] = cycle_pnl.get(cycle, 0.0) - o["price"] * mult
            elif a == "assigned":
                cash -= o["strike"] * mult
                shares += contracts * 100
            elif a == "called_away":
                cash += o["strike"] * mult
                shares -= contracts * 100
            # expired: no cash flow

    last_px = float(df["close"].iloc[-1])
    stock_mark = shares * last_px
    option_pnl = sum(cycle_pnl.values())
    # Stock P&L = everything cash saw beyond the option cycles, plus the mark
    stock_pnl = (cash - option_pnl) + stock_mark

    equity, capital = _mark_daily(pd, df, chains, orders, mult, is_structure)

    total_return_pct = sharpe = max_dd_pct = None
    if capital and capital > 0:
        rets = equity.diff().fillna(0.0) / capital
        total_return_pct = round((cash + stock_mark) / capital * 100, 2)
        sd = rets.std()
        sharpe = round(float(rets.mean() / sd * (252 ** 0.5)), 3) if sd > 0 else 0.0
        curve = capital + equity
        running_max = curve.cummax()
        max_dd_pct = round(float((curve / running_max - 1).min()) * 100, 2)

    wins = [v for v in cycle_pnl.values() if v > 0]
    return {
        "orders": orders,
        "cycles": len(cycle_pnl),
        "wins": len(wins),
        "win_rate_pct": round(100 * len(wins) / len(cycle_pnl), 1) if cycle_pnl else None,
        "net_pnl": round(cash + stock_mark, 2),
        "option_pnl": round(option_pnl, 2),
        "stock_pnl": round(stock_pnl, 2),
        "premium_collected": round(premium, 2),
        "contracts": contracts,
        "final_shares": shares,
        "capital_base": round(capital, 2) if capital else None,
        "total_return_pct": total_return_pct,
        "sharpe": sharpe,
        "max_drawdown_pct": max_dd_pct,
        "equity": equity,
    }


def _requirement(legs, entry_px, mult) -> float | None:
    """Collateral proxy for one open position. None = undefined risk."""
    shorts = [l for l in legs if l["side"] == "short"]
    longs = [l for l in legs if l["side"] == "long"]
    if not shorts:
        return 0.0
    if not longs:
        if len(shorts) == 1:
            leg = shorts[0]
            # cash-secured put, or covered call backed by shares
            return leg["strike"] * mult if leg["right"] == "P" else entry_px * mult
        return None  # straddle / strangle: undefined risk
    req = 0.0
    for right in ("P", "C"):
        s = [l for l in shorts if l["right"] == right]
        w = [l for l in longs if l["right"] == right]
        if s and w:
            req = max(req, abs(s[0]["strike"] - w[0]["strike"]) * mult)
        elif s:
            return None
    return req


def _mark_daily(pd, df, chains, orders, mult, is_structure):
    """Daily mark-to-market equity (P&L in dollars, starts at 0) and the
    max collateral requirement observed (the capital base for returns)."""
    realized = 0.0
    shares = 0
    open_legs: list = []
    entry_px = 0.0
    capital = 0.0
    undefined_risk = False
    by_date: dict = {}
    for _, o in orders.iterrows():
        by_date.setdefault(o["date"], []).append(o)

    values = []
    for d in df.index:
        px = float(df.at[d, "close"])
        for o in by_date.get(d, []):
            a = o["action"]
            side = o.get("side", "short") if is_structure else "short"
            leg = {"strike": float(o["strike"] or 0.0), "right": o["right"],
                   "expiry": o["expiry"], "side": side}
            if a in ("open", "roll_open", "sell_put", "sell_call"):
                realized += (o["price"] if side == "short" else -o["price"]) * mult
                open_legs.append(leg)
                entry_px = px
            elif a in ("close", "roll_close"):
                realized -= (o["price"] if side == "short" else -o["price"]) * mult
                open_legs = [l for l in open_legs
                             if not (l["strike"] == leg["strike"] and l["right"] == leg["right"]
                                     and l["side"] == side)]
            elif a == "settle":
                realized -= (o["price"] if side == "short" else -o["price"]) * mult
                open_legs = []
            elif a == "expired":
                open_legs = []
            elif a == "assigned":
                realized -= leg["strike"] * mult
                shares += int(mult)
                open_legs = []
            elif a == "called_away":
                realized += leg["strike"] * mult
                shares -= int(mult)
                open_legs = []
        if open_legs:
            req = _requirement(open_legs, entry_px, mult)
            if req is None:
                undefined_risk = True
            else:
                capital = max(capital, req)
        liability = 0.0
        if open_legs:
            ch_d = chains[chains["date"] == d]
            for leg in open_legs:
                row = ch_d[(ch_d["expiry"] == leg["expiry"])
                           & (ch_d["strike"] == leg["strike"])
                           & (ch_d["right"] == leg["right"])]
                if len(row):
                    m = float(row.iloc[0]["mid"])
                    liability += m if leg["side"] == "short" else -m
        values.append(realized + shares * px - liability * mult)
    equity = pd.Series(values, index=df.index)
    return equity, (None if undefined_risk else capital)
