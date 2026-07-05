# PRIOR

**Your hypothesis, written down.**

PRIOR is a tiny declarative language for expressing trading strategies as testable hypotheses. A complete strategy fits in a few lines that read like the idea in your head:

```prior
universe [sp_top_30]

when price at [lower_bollinger std=1]
  buy [5% portfolio]

sell when price at [middle_bollinger]
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

The reference runner is [AutoQuant](https://autoquant.ai), where PRIOR strategies backtest and deploy against real market data. The format is open; nothing prevents other runners.

## Status

Phase A: specification draft. The spec (`spec/SPEC.md`), tag reference (`spec/TAGS.md`), and examples (`examples/*.prior`) are written; the compiler is next. Pre-1.0, syntax may change.

## Repository layout

```
spec/SPEC.md       language specification (grammar, semantics, error contract)
spec/TAGS.md       every tag: params, defaults, exact semantics, readback strings
examples/*.prior   five complete strategies — the executable spec
```

## License

MIT.
