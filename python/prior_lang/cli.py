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
    _load_program(args.file)
    print(f"ok — {args.file} is a valid PRIOR strategy")
    return 0


def _cmd_fmt(args) -> int:
    # For .json input this converts: interchange JSON in, .prior text out.
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
        load_bars, run_backtest, run_ranking_backtest, run_universe_backtest,
    )

    strategy = _load_program(args.file).to_json()
    if strategy.get("options"):
        raise SystemExit(
            "options backtests need real chain data, which cannot be bundled or "
            "synthesized honestly.\nThis strategy validates, formats, and explains "
            "here; backtest it in AutoQuant desktop, or prior backtest --cloud (coming soon)."
        )
    df = load_bars(args.data)
    name = strategy.get("name") or Path(args.file).stem

    if strategy.get("ranking"):
        if "ticker" not in df.columns:
            raise SystemExit(
                "ranking strategies decide across a universe — the data file "
                "needs a ticker column (one stacked set of rows per ticker)"
            )
        res = run_ranking_backtest(strategy, df)
        print(f"{name} — portfolio of {res['tickers']} tickers, {res['bars']} bars from {args.data}")
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
        # Multi-ticker file: independent per-ticker runs across the universe.
        res = run_universe_backtest(strategy, df)
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
        return 0

    if (strategy.get("universe") or {}).get("type") == "dynamic":
        raise SystemExit(
            "a dynamic universe like [top_volume] ranks tickers against each other — "
            "it needs a multi-ticker data file (add a ticker column, one stacked set "
            "of rows per ticker)"
        )

    result = run_backtest(strategy, df)
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
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {label:<{width}}  {value}")
    print()
    print("Full-history + intraday data across whole universes: prior backtest --cloud (coming soon)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="prior",
        description="PRIOR — strategies that read like the idea. Your hypothesis, written down.",
    )
    parser.add_argument("--version", action="version", version=f"prior {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check a .prior file, print errors or ok")
    p.add_argument("file")
    p.set_defaults(fn=_cmd_validate)

    p = sub.add_parser("fmt", help="print (or rewrite) the canonical formatting")
    p.add_argument("file")
    p.add_argument("--write", action="store_true", help="rewrite the file in place")
    p.set_defaults(fn=_cmd_fmt)

    p = sub.add_parser("compile", help="emit runnable Python (or --json for the interchange format)")
    p.add_argument("file")
    p.add_argument("--json", action="store_true", help="emit strategy JSON instead of Python")
    p.add_argument("--out", help="write to a file instead of stdout")
    p.set_defaults(fn=_cmd_compile)

    p = sub.add_parser("explain", help="show every layer: English, JSON, generated Python")
    p.add_argument("file")
    p.set_defaults(fn=_cmd_explain)

    p = sub.add_parser("backtest", help="run the strategy over a bars file and print metrics")
    p.add_argument("file")
    p.add_argument("--data", help="bars as CSV, Parquet, JSON, or JSONL (date,open,high,low,close,volume); add a ticker column to run a whole universe from one file")
    p.add_argument("--cloud", action="store_true", help="run against hosted full-history data (coming soon)")
    p.set_defaults(fn=_cmd_backtest)

    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except PriorError as e:
        print(e.render(), file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
