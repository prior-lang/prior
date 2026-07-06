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

from . import __version__, format_source, parse_source
from .codegen import compile_strategy
from .errors import PriorError
from .explain import explain_strategy


def _read(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"no such file: {path}")
    return p.read_text()


def _cmd_validate(args) -> int:
    parse_source(_read(args.file), filename=args.file)
    print(f"ok — {args.file} is a valid PRIOR strategy")
    return 0


def _cmd_fmt(args) -> int:
    canonical = format_source(_read(args.file), filename=args.file)
    if args.write:
        Path(args.file).write_text(canonical)
        print(f"formatted {args.file}")
    else:
        sys.stdout.write(canonical)
    return 0


def _cmd_compile(args) -> int:
    strategy = parse_source(_read(args.file), filename=args.file).to_json()
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
    strategy = parse_source(_read(args.file), filename=args.file).to_json()
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
    from .backtest import load_bars, run_backtest  # lazy: needs pandas

    strategy = parse_source(_read(args.file), filename=args.file).to_json()
    df = load_bars(args.data)
    result = run_backtest(strategy, df)

    name = strategy.get("name") or Path(args.file).stem
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
    p.add_argument("--data", help="CSV or Parquet with date,open,high,low,close,volume")
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
