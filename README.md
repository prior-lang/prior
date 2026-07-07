# PRIOR

**Your hypothesis, written down.**

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

There is deliberately no options sample: real chain data cannot be redistributed under any free license, and the local CLI does not backtest options — that runs in AutoQuant. A bundled synthetic universe also ships in `examples/data/` for fully offline use.

Install: `pip install prior-lang` (add `[backtest]` for the backtester's pandas dependency).

## Status

Pre-1.0; syntax may change. Working today: the spec, the parser, the canonical
formatter, the reference code generator, the English readback, and a local
reference backtester (bring your own CSV/Parquet bars). Coming: bundled sample
data, hosted full-history backtests (`--cloud`).

## Editor support

The [VS Code extension](editors/vscode/) gives you syntax highlighting, tag completions with parameter docs, hovers that show what every tag expands to, live compiler diagnostics with quick fixes, and `prior fmt` as the document formatter.

Until the Marketplace listing lands, install it from the repo:

```
cd editors/vscode
npx @vscode/vsce package
code --install-extension prior-lang-*.vsix
```

(If `code` isn't on your PATH: VS Code → ⌘⇧P → "Shell Command: Install 'code' command in PATH", or drag the `.vsix` onto the Extensions panel.)

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
