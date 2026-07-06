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
```

Strategies are accepted as `.prior` text or as the interchange `.json` — every verb takes either, and `prior fmt strategy.json` converts JSON back into readable PRIOR text.

Try it immediately with the bundled (synthetic) sample universe:

```
prior backtest examples/mega_tech_capitulation.prior --data examples/data/sample_universe.csv
```

Install: `pip install prior-lang` (add `[backtest]` for the backtester's pandas dependency).

## Status

Pre-1.0; syntax may change. Working today: the spec, the parser, the canonical
formatter, the reference code generator, the English readback, and a local
reference backtester (bring your own CSV/Parquet bars). Coming: bundled sample
data, hosted full-history backtests (`--cloud`).

## Documentation

- **Guides and tutorials:** [autoquant.ai/prior](https://autoquant.ai/prior)
- **Language specification:** [`spec/SPEC.md`](spec/SPEC.md) — the source of truth for implementers
- **Tag reference:** [`spec/TAGS.md`](spec/TAGS.md) — every tag, its defaults, and exactly what it expands to

## Repository layout

```
spec/SPEC.md         language specification (grammar, semantics, error contract)
spec/TAGS.md         every tag: params, defaults, exact semantics, readback strings
examples/*.prior     five complete strategies — the executable spec
python/prior_lang/   the reference implementation (zero-dependency parser + CLI)
```

## License

MIT.

---

PRIOR is built and stewarded by [AutoQuant](https://autoquant.ai), the local-first desktop platform for researching, backtesting, and deploying trading strategies.
