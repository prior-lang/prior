"""The prior CLI.

    prior validate strategy.prior
    prior fmt strategy.prior [--write]
    prior compile strategy.prior [--json] [--out FILE]
    prior explain strategy.prior
    prior backtest strategy.prior --data bars.csv [--cloud]

Compile errors print with line numbers and suggestions and exit 1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, parse_source
from .codegen import compile_strategy
from .decompile import strategy_to_source
from .errors import PriorError
from .explain import explain_strategy
from .formatter import format_program


def _read(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"no such file: {path}")
    return p.read_text()


def _load_program(path: str):
    """Load a strategy from .prior source or interchange .json.

    JSON goes through the decompiler first, so both formats flow through
    the same parser and validation — a .json strategy that compiles is
    guaranteed expressible as .prior text, and vice versa.
    """
    src = _read(path)
    if path.endswith(".json"):
        try:
            src = strategy_to_source(json.loads(src))
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path}: not valid JSON ({e})")
    return parse_source(src, filename=path)


def _cmd_validate(args) -> int:
    # --stdin + --json is the editor-tooling contract: source on stdin,
    # machine-readable diagnostics on stdout, exit 1 on errors.
    try:
        if args.stdin:
            src = sys.stdin.read()
            if (args.file or "").endswith(".json"):
                src = strategy_to_source(json.loads(src))
            parse_source(src, filename=args.file or "<stdin>")
        else:
            if not args.file:
                raise SystemExit("prior validate needs a file (or --stdin)")
            _load_program(args.file)
    except PriorError as e:
        if args.json:
            print(json.dumps({"ok": False, "errors": [{
                "line": e.line, "col": e.col, "message": e.message,
                "suggestion": e.suggestion,
            }]}))
            return 1
        raise
    if args.json:
        print(json.dumps({"ok": True, "errors": []}))
    else:
        print(f"ok — {args.file or '<stdin>'} is a valid PRIOR strategy")
    return 0


def _cmd_fmt(args) -> int:
    # For .json input this converts: interchange JSON in, .prior text out.
    if args.stdin:
        src = sys.stdin.read()
        if (args.file or "").endswith(".json"):
            src = strategy_to_source(json.loads(src))
        sys.stdout.write(format_program(parse_source(src, filename=args.file or "<stdin>")))
        return 0
    if not args.file:
        raise SystemExit("prior fmt needs a file (or --stdin)")
    canonical = format_program(_load_program(args.file))
    if args.write:
        Path(args.file).write_text(canonical)
        print(f"formatted {args.file}")
    else:
        sys.stdout.write(canonical)
    return 0


def _cmd_compile(args) -> int:
    strategy = _load_program(args.file).to_json()
    output = (
        json.dumps(strategy, indent=2) + "\n" if args.json else compile_strategy(strategy)
    )
    if args.out:
        Path(args.out).write_text(output)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(output)
    return 0


def _cmd_explain(args) -> int:
    strategy = _load_program(args.file).to_json()
    print("── What it does ──────────────────────────────────────────")
    print(explain_strategy(strategy))
    print()
    print("── Strategy JSON (the interchange format) ────────────────")
    print(json.dumps(strategy, indent=2))
    print()
    print("── Generated Python (what actually runs) ─────────────────")
    sys.stdout.write(compile_strategy(strategy))
    return 0


def _cmd_backtest(args) -> int:
    if args.cloud:
        print(
            "Cloud backtests (full history, intraday, full universes) are coming soon.\n"
            "Local backtests run on your own data: prior backtest strategy.prior --data bars.csv"
        )
        return 0
    if not args.data:
        raise SystemExit(
            "prior backtest needs bars: --data bars.csv (columns: date,open,high,low,close,volume)"
        )
    from .backtest import (  # lazy: needs pandas
        load_bars, pair_trade_log, run_backtest, run_pair_backtest,
        run_ranking_backtest, run_universe_backtest, trade_log,
    )

    def _print_trades(trades):
        if not trades:
            print("  no trades")
            return
        print(f"  {'ENTRY':<12} {'EXIT':<12} {'DIR':<6} {'IN':>10} {'OUT':>10} {'BARS':>5} {'RET%':>8}  EXIT")
        for t in trades:
            print(
                f"  {t['entry_date']:<12} {t['exit_date']:<12} {t['direction']:<6}"
                f" {t['entry_price']:>10} {t['exit_price']:>10} {t['bars_held']:>5}"
                f" {t['return_pct']:>8.2f}  {t['exit_reason']}"
            )

    strategy = _load_program(args.file).to_json()
    if strategy.get("options") and not args.chains:
        raise SystemExit(
            "options backtests need real chain data, which cannot be bundled or "
            "synthesized honestly.\nBring your own: --chains chains.csv (one row per "
            "contract per day: date, expiry,\nstrike, right, delta, mid) — or backtest "
            "in AutoQuant desktop, where licensed\nchain data is built in."
        )
    df = load_bars(args.data)
    if args.date_from or args.date_to:
        import pandas as pd
        n_before = len(df)
        if args.date_from:
            df = df[df.index >= pd.Timestamp(args.date_from)]
        if args.date_to:
            df = df[df.index <= pd.Timestamp(args.date_to)]
        if df.empty:
            raise SystemExit(
                f"no bars between {args.date_from or 'the start'} and "
                f"{args.date_to or 'the end'} — the file covers a different range"
            )
        print(f"date range: {df.index.min().date()} to {df.index.max().date()} "
              f"({len(df)} of {n_before} rows)")
    name = strategy.get("name") or Path(args.file).stem
    cost_bps = float(args.fee_bps or 0.0) + float(args.slippage_bps or 0.0)

    # Timeframe sanity: a 1h strategy fed daily bars silently means
    # nonsense ([after 24 bars] = 24 days). Warn on a clear mismatch.
    tf_secs = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400,
               "1d": 86400, "1w": 604800}.get(strategy.get("timeframe", "1d"))
    if tf_secs and len(df) > 3:
        import pandas as pd
        spacing = df.index.to_series().diff().dropna().median().total_seconds()
        # business-daily data has weekend gaps; accept up to ~3.5x
        if spacing > tf_secs * 3.6 or spacing < tf_secs / 3.6:
            print(f"WARNING: strategy timeframe is {strategy.get('timeframe', '1d')} "
                  f"but the data's bar spacing looks like ~{int(spacing)}s — "
                  "bar-count tags like [after N bars] count DATA bars", file=sys.stderr)

    def _emit_json(payload: dict) -> int:
        clean = {k: v for k, v in payload.items()
                 if k not in ("equity", "orders", "per_ticker") and not hasattr(v, "iloc")}
        if "per_ticker" in payload:
            clean["per_ticker"] = [
                {k: v for k, v in r.items() if k != "equity" and not hasattr(v, "iloc")}
                for r in payload["per_ticker"]
            ]
        print(json.dumps(clean, indent=2, default=str))
        return 0

    if strategy.get("options"):
        from .options_backtest import load_chains, run_options_backtest

        if "ticker" in df.columns:
            uni_tickers = (strategy.get("universe") or {}).get("tickers") or []
            want = (args.ticker or (uni_tickers[0] if uni_tickers else "")).upper()
            if not want:
                raise SystemExit("multi-ticker data file — pick the underlying: --ticker F")
            df = df[df["ticker"].str.upper() == want].drop(columns=["ticker"]).sort_index()
            if df.empty:
                raise SystemExit(f"no rows for {want} in the data file")
        chains = load_chains(args.chains)
        res = run_options_backtest(strategy, df, chains, contract_fee=args.contract_fee)
        if args.as_json:
            return _emit_json(res)
        print(f"{name} — options on your chains, {len(df)} bars, {res['contracts']} contract(s)")
        rows = [
            ("Cycles (positions opened)", res["cycles"]),
            ("Win rate", f"{res['win_rate_pct']}%" if res.get("win_rate_pct") is not None else "n/a"),
            ("Premium collected", f"${res['premium_collected']:,.2f}"),
            *([("Fees paid", f"${res['fees_paid']:,.2f}")] if args.contract_fee else []),
            ("Option P&L", f"${res['option_pnl']:,.2f}"),
            ("Stock P&L", f"${res['stock_pnl']:,.2f} ({res['final_shares']} shares held at end)"),
            ("Net P&L", f"${res['net_pnl']:,.2f}"),
        ]
        if res.get("capital_base"):
            rows += [
                ("Capital base (max collateral)", f"${res['capital_base']:,.2f}"),
                ("Total return on collateral", f"{res['total_return_pct']}%"),
                ("Sharpe", res["sharpe"]),
                ("Max drawdown", f"{res['max_drawdown_pct']}%"),
            ]
        else:
            rows.append(("Return / Sharpe / drawdown", "n/a — undefined-risk structure has no fixed collateral base"))
        if args.capital:
            rows.append(("Return on capital", f"{res['net_pnl'] / args.capital * 100:.2f}% of ${args.capital:,.0f}"))
        if args.equity:
            res["equity"].rename("equity_pnl").to_csv(args.equity, header=True, index_label="date")
            rows.append(("Equity curve written to", args.equity))
        width = max(len(k) for k, _ in rows)
        for k, v in rows:
            print(f"  {k:<{width}}  {v}")
        if args.trades:
            orders = res["orders"]
            print(f"\nOrder log ({len(orders)} rows):")
            with_rows = orders if len(orders) <= 60 else orders.tail(60)
            if len(orders) > 60:
                print("  (showing the last 60)")
            print(with_rows.to_string(index=False))
        print(
            "\nNote: fills at mid, one position at a time, no commissions or "
            "slippage, no early\nassignment. Multi-leg structures settle cash by "
            "net intrinsic at expiry."
        )
        return 0

    if args.trades and strategy.get("ranking"):
        raise SystemExit(
            "ranking strategies don't have trades to log — holdings turn over "
            "at rebalances (a rebalance log is planned)"
        )
    if args.trades and (strategy.get("universe") or {}).get("type") == "dynamic":
        raise SystemExit(
            "--trades with a dynamic universe isn't wired up yet — membership "
            "masking would make the log lie; scope to a ticker to inspect trades"
        )

    if (strategy.get("universe") or {}).get("type") == "pair":
        if "ticker" not in df.columns:
            raise SystemExit(
                "a spread backtest needs both legs — the data file needs a "
                "ticker column (one stacked set of rows per ticker)"
            )
        res = run_pair_backtest(strategy, df, cost_bps=cost_bps)
        if args.as_json:
            return _emit_json(res)
        if args.equity:
            res["equity"].rename("equity").to_csv(args.equity, header=True, index_label="date")
        print(f"{name} — {res['pair']} spread (price {res['form']}), {res['bars']} bars from {args.data}")
        if args.capital:
            end = args.capital * (1 + res["total_return_pct"] / 100.0)
            print(f"  {'Starting capital':<20} ${args.capital:,.2f}")
            print(f"  {'Final equity':<20} ${end:,.2f}")
        rows = [
            ("Total return", f"{res['total_return_pct']}%"),
            ("CAGR", f"{res['cagr_pct']}%"),
            ("Sharpe", res["sharpe"]),
            ("Max drawdown", f"{res['max_drawdown_pct']}%"),
            ("Spread start → end", f"{res['spread_start']} → {res['spread_end']}"),
            ("Trades", res["trades"]),
            ("Win rate", f"{res['win_rate_pct']}%" if res["win_rate_pct"] is not None else "n/a"),
            ("Avg trade", f"{res['avg_trade_pct']}%" if res["avg_trade_pct"] is not None else "n/a"),
        ]
        width = max(len(k) for k, _ in rows)
        for k, v in rows:
            print(f"  {k:<{width}}  {v}")
        print(
            "\nNote: equal dollar legs (+1 spread = long "
            f"{res['pair'].split('/')[0]} / short {res['pair'].split('/')[1]}, "
            "each at half the allocation). Borrow costs and leg slippage are not modeled."
        )
        if args.trades:
            print("\nTrades (IN/OUT are spread values):")
            _print_trades(pair_trade_log(strategy, df))
        return 0

    if strategy.get("ranking"):
        if "ticker" not in df.columns:
            raise SystemExit(
                "ranking strategies decide across a universe — the data file "
                "needs a ticker column (one stacked set of rows per ticker)"
            )
        res = run_ranking_backtest(strategy, df, cost_bps=cost_bps)
        if args.as_json:
            return _emit_json(res)
        if args.equity:
            res["equity"].rename("equity").to_csv(args.equity, header=True, index_label="date")
        print(f"{name} — portfolio of {res['tickers']} tickers, {res['bars']} bars from {args.data}")
        if args.capital:
            end = args.capital * (1 + res["total_return_pct"] / 100.0)
            print(f"  {'Starting capital':<22} ${args.capital:,.2f}")
            print(f"  {'Final equity':<22} ${end:,.2f}")
        rows = [
            ("Total return", f"{res['total_return_pct']}%"),
            ("Equal-weight universe", f"{res['equal_weight_universe_pct']}%"),
            ("CAGR", f"{res['cagr_pct']}%"),
            ("Sharpe", res["sharpe"]),
            ("Max drawdown", f"{res['max_drawdown_pct']}%"),
            ("Rebalances", res["rebalances"]),
            ("Avg turnover", f"{res['avg_turnover_pct']}%"),
        ]
        width = max(len(label) for label, _ in rows)
        for label, value in rows:
            print(f"  {label:<{width}}  {value}")
        if res["holdings"]:
            pretty = ", ".join(f"{t} {w * 100:.0f}%" for t, w in res["holdings"])
            print(f"  {'Current holdings':<{width}}  {pretty}")
        if res["skipped_not_in_universe"]:
            sk = res["skipped_not_in_universe"]
            shown = ", ".join(sk[:8]) + (f" (+{len(sk) - 8} more)" if len(sk) > 8 else "")
            print(f"\n  skipped (in file, not in universe): {shown}")
        if res["universe_not_in_file"]:
            print(f"  no data provided for: {', '.join(res['universe_not_in_file'])}")
        print(
            "\nNote: universes are today's constituents — long backtests inherit "
            "survivorship bias.\nPoint-in-time universes and full history: "
            "prior backtest --cloud (coming soon)"
        )
        return 0

    if "ticker" in df.columns:
        if args.equity:
            raise SystemExit(
                "--equity writes one curve — universe runs are independent per-ticker; "
                "scope to one instrument for the export"
            )
        # Multi-ticker file: independent per-ticker runs across the universe.
        res = run_universe_backtest(strategy, df, capital=args.capital, cost_bps=cost_bps)
        if args.as_json:
            return _emit_json(res)
        rows = res["per_ticker"]
        if not rows:
            raise SystemExit(
                "no tickers in the data file match the strategy's universe"
            )
        print(f"{name} — {len(rows)} tickers from {args.data} (independent runs)")
        header = f"  {'TICKER':<9} {'RETURN':>8} {'B&H':>8} {'SHARPE':>7} {'MAXDD':>7} {'TRADES':>6} {'WIN%':>6}"
        print(header)
        for r in sorted(rows, key=lambda x: x["total_return_pct"], reverse=True):
            win = f"{r['win_rate_pct']:.0f}" if r["win_rate_pct"] is not None else "–"
            print(
                f"  {r['ticker']:<9} {r['total_return_pct']:>7.2f}% {r['buy_hold_return_pct']:>7.2f}%"
                f" {r['sharpe']:>7.3f} {r['max_drawdown_pct']:>6.2f}% {r['trades']:>6} {win:>6}"
            )
        print(f"  {'':<9} {'-------':>8}")
        print(f"  {'average':<9} {res['avg_return_pct']:>7.2f}%{'':<17} total trades: {res['total_trades']}")
        if res["skipped_not_in_universe"]:
            print(f"\n  skipped (in file, not in universe): {', '.join(res['skipped_not_in_universe'])}")
        if res["universe_not_in_file"]:
            print(f"  no data provided for: {', '.join(res['universe_not_in_file'])}")
        print(
            "\nNote: independent per-ticker runs (each gets the full allocation; "
            "max_positions does not apply across tickers).\n"
            "Portfolio-level simulation on full-history data: prior backtest --cloud (coming soon)"
        )
        if args.trades:
            for r in sorted(rows, key=lambda x: x["ticker"]):
                bars = df[df["ticker"].str.upper() == r["ticker"]].drop(columns=["ticker"]).sort_index()
                print(f"\nTrades — {r['ticker']}:")
                _print_trades(trade_log(strategy, bars))
        return 0

    if (strategy.get("universe") or {}).get("type") == "dynamic":
        raise SystemExit(
            "a dynamic universe like [top_volume] ranks tickers against each other — "
            "it needs a multi-ticker data file (add a ticker column, one stacked set "
            "of rows per ticker)"
        )

    result = run_backtest(strategy, df, capital=args.capital, cost_bps=cost_bps)
    if args.as_json:
        return _emit_json(result)
    sizing_used = strategy.get("position_sizing") or any(
        r.get("position_sizing") for r in (strategy.get("rules") or []))
    if sizing_used and not args.capital:
        print("(sizing shown as metadata — one fully-allocated position; add --capital 25000 to apply the sizing tags and see dollars)")
    if args.equity:
        result["equity"].rename("equity").to_csv(args.equity, header=True, index_label="date")
    print(f"{name} — {result['bars']} bars from {args.data}")
    rows = [
        ("Total return", f"{result['total_return_pct']}%"),
        ("Buy & hold", f"{result['buy_hold_return_pct']}%"),
        ("CAGR", f"{result['cagr_pct']}%"),
        ("Sharpe", result["sharpe"]),
        ("Volatility", f"{result['volatility_pct']}%"),
        ("Max drawdown", f"{result['max_drawdown_pct']}%"),
        ("Trades", result["trades"]),
        ("Win rate", f"{result['win_rate_pct']}%" if result["win_rate_pct"] is not None else "n/a"),
        ("Avg trade", f"{result['avg_trade_pct']}%" if result["avg_trade_pct"] is not None else "n/a"),
    ]
    if args.capital:
        rows = [
            ("Starting capital", f"${result['capital']:,.2f}"),
            ("Final equity", f"${result['final_equity_usd']:,.2f}"),
            ("Net P&L", f"${result['net_pnl_usd']:,.2f}"),
        ] + rows
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {label:<{width}}  {value}")
    if args.trades:
        print("\nTrades:")
        _print_trades(trade_log(strategy, df))
    print()
    print("Full-history + intraday data across whole universes: prior backtest --cloud (coming soon)")
    return 0


def _cmd_sample(args) -> int:
    from .samples import CATALOG, categories, download, timeframes

    if not args.category:
        print("Free sample data (real, redistributable bars):\n")
        width = max(len(f"{c} --timeframe {t}") for c, t in CATALOG)
        for (cat, tf), entry in CATALOG.items():
            cmd = f"{cat} --timeframe {tf}" if timeframes(cat)[0] != tf else cat
            print(f"  prior sample {cmd:<{width}}  {entry['desc']}")
        print(
            "\nDownloads land in ./prior-samples/. Options has no free sample:\n"
            "real chain data cannot be redistributed, and options backtests run\n"
            "in AutoQuant, not the local CLI."
        )
        return 0

    path = download(args.category, args.timeframe)
    entry_tf = args.timeframe or timeframes(args.category.lower())[0]
    entry = CATALOG[(args.category.lower(), entry_tf)]
    print(f"downloaded {path}")
    print(f"  {entry['desc']}")
    print(f"  works well with: {entry['try']}")
    print(f"\nTry it:\n  prior backtest your_strategy.prior --data {path}")
    return 0


def _cmd_trace(args) -> int:
    from .backtest import load_bars  # lazy: needs pandas
    from .trace import trace_report

    strategy = _load_program(args.file).to_json()
    df = load_bars(args.data)
    name = strategy.get("name") or Path(args.file).stem

    uni = strategy.get("universe") or {}
    if uni.get("type") == "pair":
        import pandas as pd
        if "ticker" not in df.columns:
            raise SystemExit("a spread trace needs both legs — the data file needs a ticker column")
        a, b = [str(t).upper() for t in uni["tickers"]]
        panel = {
            str(t).upper(): g.drop(columns=["ticker"]).sort_index()
            for t, g in df.groupby(df["ticker"].str.upper())
        }
        missing = [t for t in (a, b) if t not in panel]
        if missing:
            raise SystemExit(f"the data file has no rows for {', '.join(missing)}")
        leg_a = panel[a]["close"].astype(float)
        leg_b = panel[b]["close"].astype(float)
        leg_a, leg_b = leg_a.align(leg_b, join="inner")
        spread = (leg_a / leg_b if uni.get("form", "ratio") == "ratio" else leg_a - leg_b).dropna()
        df = pd.DataFrame({"open": spread, "high": spread, "low": spread,
                           "close": spread, "volume": 0.0})
        name += f" ({a}/{b} spread)"
    elif "ticker" in df.columns:
        if not args.ticker:
            raise SystemExit("multi-ticker data file — pick one instrument: --ticker NVDA")
        df = df[df["ticker"].str.upper() == args.ticker.upper()].drop(columns=["ticker"]).sort_index()
        if df.empty:
            raise SystemExit(f"no rows for {args.ticker.upper()} in the data file")
        name += f" — {args.ticker.upper()}"

    report = trace_report(strategy, df, date=args.date, last=args.last)
    for d in report["dates"]:
        sig = d["signal"]
        state = "flat" if sig == 0 else ("long" if sig > 0 else "short")
        if sig != 0 and abs(sig) != 1.0:
            state += f" (partial {abs(sig):g})"
        print(f"{name} — {d['date']} (bar {d['bar'] + 1} of {report['bars']})   signal {sig:g}, {state}")
        for r in d["rules"]:
            action = "buy" if r["direction"] == "long" else "short"
            print(f"  when ({r['match_logic']}) → {action}:")
            for c in r["conditions"]:
                print(f"    {'✓' if c['verdict'] else '✗'} {c['text']}")
        for e in d["exits"]:
            if e["conditions"]:
                print(f"  {e['keyword']} (any):")
                for c in e["conditions"]:
                    print(f"    {'✓' if c['verdict'] else '✗'} {c['text']}")
        print()
    print(
        "Priced exits (stop/target/trailing/time) evaluate against the open "
        "position — see prior backtest --trades for which one fired."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="prior",
        description="PRIOR — strategies that read like the idea. Your hypothesis, written down.",
    )
    parser.add_argument("--version", action="version", version=f"prior {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check a .prior file, print errors or ok")
    p.add_argument("--json", action="store_true", help="machine-readable diagnostics (for editor integrations)")
    p.add_argument("--stdin", action="store_true", help="read source from stdin instead of a file")
    p.add_argument("file", nargs="?", help="path (optional with --stdin; still names the file in errors)")
    p.set_defaults(fn=_cmd_validate)

    p = sub.add_parser("fmt", help="print (or rewrite) the canonical formatting")
    p.add_argument("file", nargs="?", help="path (optional with --stdin)")
    p.add_argument("--write", action="store_true", help="rewrite the file in place")
    p.add_argument("--stdin", action="store_true", help="read source from stdin, print canonical text")
    p.set_defaults(fn=_cmd_fmt)

    p = sub.add_parser("compile", help="emit runnable Python (or --json for the interchange format)")
    p.add_argument("file")
    p.add_argument("--json", action="store_true", help="emit strategy JSON instead of Python")
    p.add_argument("--out", help="write to a file instead of stdout")
    p.set_defaults(fn=_cmd_compile)

    p = sub.add_parser("explain", help="show every layer: English, JSON, generated Python")
    p.add_argument("file")
    p.set_defaults(fn=_cmd_explain)

    p = sub.add_parser("sample", help="download free sample data (stocks, crypto, forex) to get started instantly")
    p.add_argument("category", nargs="?", help="stocks | crypto | forex (omit to list the catalog)")
    p.add_argument("--timeframe", help="bar size where the category offers more than one (e.g. crypto --timeframe 1h)")
    p.set_defaults(fn=_cmd_sample)

    p = sub.add_parser("trace", help="why did/didn't it fire — every condition's verdict on a bar")
    p.add_argument("file")
    p.add_argument("--data", required=True, help="bars file (same formats as backtest)")
    p.add_argument("--date", help="bar to inspect (default: the last bar)")
    p.add_argument("--last", type=int, default=1, help="inspect the last N bars ending at --date (max 10)")
    p.add_argument("--ticker", help="which instrument to trace in a multi-ticker file")
    p.set_defaults(fn=_cmd_trace)

    p = sub.add_parser("backtest", help="run the strategy over a bars file and print metrics")
    p.add_argument("file")
    p.add_argument("--data", help="bars as CSV, Parquet, JSON, or JSONL (date,open,high,low,close,volume); add a ticker column to run a whole universe from one file")
    p.add_argument("--cloud", action="store_true", help="run against hosted full-history data (coming soon)")
    p.add_argument("--trades", action="store_true", help="print the per-trade log: entry/exit, direction, bars held, return, and which exit fired")
    p.add_argument("--chains", help="your own option chain data for options strategies (date, expiry, strike, right, delta, mid)")
    p.add_argument("--equity", help="write the daily equity curve to this CSV (chart it with anything)")
    p.add_argument("--capital", type=float, metavar="DOLLARS", help="account size: makes sizing tags real ([5%% portfolio], [$5000], [risk 1%%]) and reports dollar P&L")
    p.add_argument("--fee-bps", dest="fee_bps", type=float, default=0.0, metavar="BPS", help="commission per side in basis points (5 = 0.05%%)")
    p.add_argument("--slippage-bps", dest="slippage_bps", type=float, default=0.0, metavar="BPS", help="slippage per side in basis points, added to fees")
    p.add_argument("--contract-fee", dest="contract_fee", type=float, default=0.0, metavar="USD", help="options commission per contract per fill (e.g. 0.65)")
    p.add_argument("--json", dest="as_json", action="store_true", help="print the metrics as JSON instead of the table")
    p.add_argument("--from", dest="date_from", metavar="DATE", help="backtest from this date (indicators warm up INSIDE the range — include lead-in for long lookbacks)")
    p.add_argument("--to", dest="date_to", metavar="DATE", help="backtest up to this date")
    p.add_argument("--ticker", help="which underlying to use when the data file is multi-ticker (options strategies)")
    p.set_defaults(fn=_cmd_backtest)

    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except PriorError as e:
        print(e.render(), file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
