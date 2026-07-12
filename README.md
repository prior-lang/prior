<p align="center">
  <img src="assets/logo.png" width="140" alt="PRIOR logo">
</p>

<h1 align="center">PRIOR</h1>

<p align="center"><strong>Your hypothesis, written down.</strong></p>

<p align="center">
  <a href="https://pypi.org/project/prior-lang/"><img src="https://img.shields.io/pypi/v/prior-lang" alt="PyPI"></a>
  <a href="https://pepy.tech/project/prior-lang"><img src="https://static.pepy.tech/badge/prior-lang" alt="Downloads"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT"></a>
</p>

PRIOR is a tiny declarative language for expressing trading strategies as testable hypotheses. A complete strategy fits in a few lines that read like the idea in your head:

```prior
when $NVDA at [lower_bollinger std=1]
  buy [5% portfolio]

sell when $NVDA at [middle_bollinger]
  or [stop 1.5%]
  or [after 5 bars]
```

The name is Bayesian: a prior is your belief before you see the data. A `.prior` file is exactly that — your trading thesis, committed to writing, before the backtest runs.

## Why a language this small

PRIOR is deliberately not a programming language. No variables, no loops, no user functions, no arithmetic. The vocabulary is a set of bracket tags, and each tag is a semantic macro that bundles what a competent quant means by the phrase:

`[lower_bollinger]` means the 20-period, 2-standard-deviation Bollinger band, *touched or crossed this bar*, with NaN warmup handled and the entry firing once on the touch rather than every bar price sits there. That is ~15 lines of careful pandas, invisible.

Because the language has no way to reference a future bar, **you cannot write a lookahead bug in PRIOR**. The most common way retail backtests lie is unrepresentable.

## How it runs

```
strategy.prior  →  JSON strategy object  →  generated Python  →  backtest / paper / live
```

PRIOR compiles to an open JSON interchange format, then to plain Python you can read, audit, and run. `prior explain` shows every layer, plus an English readback of what your strategy does. Nothing is magic.

The reference runner is [AutoQuant](https://autoquant.ai), where PRIOR strategies scan live markets, backtest against full market history, and deploy to paper or live trading. The format is open; nothing prevents other runners.

## The toolchain

```
prior validate strategy.prior          errors (with line numbers and suggestions) or ok
prior fmt strategy.prior               canonical formatting (--write rewrites in place)
prior compile strategy.prior           emit runnable Python (--json for the interchange format)
prior explain strategy.prior           every layer: English readback, JSON, generated Python
prior backtest strategy.prior --data bars.csv    metrics over your own OHLCV data
                                                 (CSV, Parquet, JSON, or JSONL; add a ticker
                                                 column to run a whole universe from one file)
prior backtest ... --trades            the per-trade log: entry/exit, bars held, return,
                                                 and WHICH exit fired (stop? target? time?)
prior backtest ... --capital 25000     apply the sizing tags and report dollars
prior backtest ... --fee-bps 5 --slippage-bps 5    trading costs per side
prior backtest ... --contract-fee 0.65 options commission per contract per fill
prior backtest ... --json              metrics as JSON for scripting
prior backtest ... --from 2024-01-01 --to 2025-12-31    backtest a date window
prior backtest ... --equity out.csv     export the daily equity curve for charting
prior trace strategy.prior --data bars.csv --date 2026-03-14
                                                 why did/didn't it fire: every condition's
                                                 verdict on any bar
```

Strategies are accepted as `.prior` text or as the interchange `.json` — every verb takes either, and `prior fmt strategy.json` converts JSON back into readable PRIOR text.

Try it immediately with real sample data (free, no account, no API keys):

```
prior sample                 list what's available
prior sample crypto          5 years of daily bars for the [crypto_majors] pairs
prior sample stocks          5 years of daily bars for 20 US large caps
prior sample forex           5 years of daily closes for 7 majors
prior sample crypto --timeframe 1h    2 years of hourly bars (multi-timeframe ready)

Every category also comes in 15m, 5m, and 1m flavors (--timeframe 15m and so on);
window sizes shrink with bar size because that is what the free sources allow.

prior backtest examples/eth_oversold_recovery.prior --data prior-samples/crypto_1d.csv.gz
```

There is deliberately no options sample: real chain data cannot be redistributed under any free license. Options strategies — the wheel, cash-secured puts, covered calls, and multi-leg structures (put/call spreads, iron condors, straddles, strangles) — backtest locally on chains YOU bring (`prior backtest wheel.prior --data f.csv --chains chains.csv` — one row per contract per day: date, expiry, strike, right, delta, mid), or in AutoQuant where licensed chain data is built in. A bundled synthetic universe also ships in `examples/data/` for fully offline use.

Install: `pip install prior-lang` (add `[backtest]` for the backtester's pandas dependency).

## Deploy to live trading

The CLI validates, formats, explains, and backtests. To run a strategy live on
paper or real money, deploy it through AutoQuant, which executes locally on your
own machine and broker keys, so your strategy and keys never touch anyone's
servers:

```
prior deploy strategy.prior
```

Every account includes a 14-day trial with live paper trading. See
[autoquant.ai/prior/deploy](https://autoquant.ai/prior/deploy).

## Status

Pre-1.0; syntax may change. Working today: the spec, the parser, the canonical
formatter, the reference code generator, the English readback, a local
reference backtester (bring your own CSV/Parquet bars), free sample data
via `prior sample`, and a deploy handoff to AutoQuant for live trading.

## Editor support

The [VS Code extension](editors/vscode/) gives you syntax highlighting, tag completions with parameter docs, hovers that show what every tag expands to, live compiler diagnostics with quick fixes, and `prior fmt` as the document formatter.

Install it from the [Marketplace](https://marketplace.visualstudio.com/items?itemName=autoquant.prior-lang) — search "PRIOR" in the Extensions panel, or:

```
code --install-extension autoquant.prior-lang
```

Highlighting, completions, and hovers work immediately. Diagnostics and formatting shell out to the CLI so the editor reports exactly what the compiler will say — `pip install prior-lang`, or point the `prior.command` setting at any environment that has it.

## Documentation

- **Guides and tutorials:** [autoquant.ai/prior](https://autoquant.ai/prior)
- **Language specification:** [`spec/SPEC.md`](spec/SPEC.md) — the source of truth for implementers
- **Tag reference:** [`spec/TAGS.md`](spec/TAGS.md) — every tag, its defaults, and exactly what it expands to

## Repository layout

```
spec/SPEC.md         language specification (grammar, semantics, error contract)
spec/TAGS.md         every tag: params, defaults, exact semantics, readback strings
examples/*.prior     complete strategies, from one-liners to pairs trades — the executable spec
python/prior_lang/   the reference implementation (zero-dependency parser + CLI)
editors/vscode/      VS Code extension: highlighting, completions, hovers, live diagnostics
```

## License

MIT.

---

PRIOR is built and stewarded by [AutoQuant](https://autoquant.ai), the local-first desktop platform for researching, backtesting, and deploying trading strategies.
