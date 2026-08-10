<p align="center">
  <img src="https://raw.githubusercontent.com/prior-lang/prior/main/assets/logo.png" width="140" alt="PRIOR logo">
</p>

<h1 align="center">PRIOR</h1>

<p align="center"><strong>Your trading hypothesis, written down.</strong></p>

<p align="center">A complete, backtestable strategy in a few readable lines that compile to Python. Lookahead bias is impossible to write.</p>

<p align="center">
  <a href="https://pypi.org/project/prior-lang/"><img src="https://img.shields.io/pypi/v/prior-lang" alt="PyPI"></a>
  <a href="https://pepy.tech/project/prior-lang"><img src="https://static.pepy.tech/badge/prior-lang" alt="Downloads"></a>
  <a href="https://github.com/prior-lang/prior/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT"></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/prior-lang/prior/main/assets/prior-backtest.gif" width="780" alt="Write a trading strategy in a few lines, run a real backtest in one command">
</p>

PRIOR is a tiny declarative language for expressing trading strategies as testable hypotheses. A complete strategy fits in a few lines that read like the idea in your head:

```prior
when $NVDA crosses above [supertrend] and [rsi] < 40
  buy [10% portfolio]

sell when $NVDA crosses below [supertrend]
  or [trailing 8%]
```

Buy when the SuperTrend flips up and momentum is still washed out, trail the winner, and get out the moment the trend flips back. `[supertrend]` is a stateful ATR trailing stop, roughly thirty lines of careful, easy-to-miscode Python, that here is one word the compiler expands correctly and without lookahead.

The name is Bayesian: a prior is your belief before you see the data. A `.prior` file is exactly that, your trading thesis, committed to writing, before the backtest runs.

## Quickstart

Install it. The `[backtest]` extra pulls in pandas for the backtester:

```bash
pip install 'prior-lang[backtest]'
```

Write a strategy. A whole strategy is a few lines. This one buys dips inside a confirmed uptrend and trails the winners. Save it as `dip.prior`:

```
when $AVGO above [sma 200] and [rsi] crosses above 35
  buy [10% portfolio]

sell when [rsi] > 70
  or [trailing 8%]
```

Grab free sample data (no account, no API keys) and backtest it, all in under a minute:

```bash
prior sample stocks
prior backtest dip.prior --data prior-samples/stocks_1d.csv.gz --trades
```

On the five years of sample data that is a 1.12 Sharpe at a 79% win rate, and the same four untuned lines stay green on 16 of the 20 sample names. The backtest always prints buy-and-hold right next to your return, so you can see exactly when simply holding would have won. Since 0.12.1 the report also states its own assumptions: the Sharpe convention, the cost model in force (zero is the default, and the report says so rather than staying quiet), and how often every rule actually fired, with a loud flag on any rule that never fired at all. A rule that never fires produces the same equity curve as no rule, so the report is the only place that class of bug can become visible.

See exactly what it compiles to: the plain-English readback, the interchange JSON, and the generated Python.

```bash
prior explain dip.prior
```

That is the whole loop. Point `prior backtest` at any OHLCV file (`date,open,high,low,close,volume`, CSV / Parquet / JSON) to test your own ideas, and see [The toolchain](#the-toolchain) below for every command.

## Why a language this small

PRIOR is deliberately not a programming language. No variables, no loops, no user functions, no arithmetic. The vocabulary is a set of bracket tags, and each tag is a semantic macro that bundles what a competent quant means by the phrase:

`[lower_bollinger]` means the 20-period, 2-standard-deviation Bollinger band, *touched or crossed this bar*, with NaN warmup handled and the entry firing once on the touch rather than every bar price sits there. That is ~15 lines of careful pandas, invisible.

Because the language has no way to reference a future bar, **you cannot write a lookahead bug in PRIOR**. The most common way retail backtests lie is unrepresentable.

## Setups that unfold over several bars

Conditions joined with `and` all have to be true on the same bar. Plenty of setups aren't like that: something arms, and you watch a few later bars for a confirmation. That is what `then within N bars` is for.

```prior
when [new_low 20] then within 5 bars [macd_cross_up]
  buy [risk 1%]
```

The flush to a new low only arms the idea. Momentum has to turn within five bars or the window closes and nothing happens. The confirmation has to land on a *later* bar (same-bar is what `and` means), a fresh arm restarts the window, and an expired window leaves no state behind.

Normally this is a little state machine you maintain by hand, and it is exactly the kind of bookkeeping that quietly grows a lookahead bug. Here the window counts *backwards* from the current bar, asking whether the setup armed in the last five bars, never whether a confirmation is coming. So the guarantee above still holds: nothing reads a bar that hasn't closed.

## What PRIOR catches, and what it doesn't

PRIOR makes one guarantee, and it is worth being precise about its edges. A backtest can lie to you in three different ways, and only one of them is a language problem.

**Your code reaching into the future.** A signal that reads a bar it should not have seen yet, an indicator computed over the whole series at once, a fill at a price that had not printed. This is the class PRIOR closes. There is no token in the grammar that can reference a future bar, so the entire category is unrepresentable. You cannot write it, correctly or otherwise. This is the guarantee.

**Data that was not knowable at the time.** Companies restate earnings. A figure carries a date that looks perfectly innocent while holding a number nobody actually had on that date. PRIOR runs on the data you give it and has no way to know a value was revised after the fact. That is a data provenance problem, not a language one. The fix lives in your source. Use point-in-time data that stores what was actually reported at the time.

**A universe you picked because you already know how it turned out.** Backtest on ten mega-caps that survived, with no delisted names, and PRIOR will faithfully test a biased sample and never complain. The bias is in which data you chose, not in what your strategy does with it, so no language feature can catch it. The fix is a survivorship-free dataset that includes the names that died.

PRIOR owns the first one completely and does not pretend to own the other two. That is deliberate. A tool that claimed to solve all three would be making exactly the kind of quiet overstatement PRIOR exists to prevent.

Before you invest an evening, it is worth knowing what the language *cannot* say: no arithmetic between tags, nothing learned or fitted, one strategy form per file, options single-ticker, sequences two steps. The full inventory, with the exact error you get for each, is in [`spec/LIMITS.md`](https://github.com/prior-lang/prior/blob/main/spec/LIMITS.md). The complete tag vocabulary is in [`spec/TAGS.md`](https://github.com/prior-lang/prior/blob/main/spec/TAGS.md) — if a concept is not in there, you cannot express it. Close the hole you can close by construction, and be honest about the two that belong to your data.

## The same strategy, in Python

Take the strategy from the top of this page:

```prior
when $NVDA crosses above [supertrend] and [rsi] < 40
  buy [10% portfolio]

sell when $NVDA crosses below [supertrend]
  or [trailing 8%]
```

Four lines. Here is a faithful, correct Python version of the same idea, and it still leaves the trailing stop out:

```python
import numpy as np
import pandas as pd

def supertrend_direction(df, period=10, mult=3.0):
    prev_close = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - prev_close).abs(),
                    (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    hl2 = (df["high"] + df["low"]) / 2
    upper = (hl2 + mult * atr).to_numpy().copy()
    lower = (hl2 - mult * atr).to_numpy().copy()
    close = df["close"].to_numpy()
    direction = np.ones(len(close))
    for i in range(1, len(close)):
        if close[i] > upper[i - 1]:
            direction[i] = 1
        elif close[i] < lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
            if direction[i] > 0 and lower[i] < lower[i - 1]:
                lower[i] = lower[i - 1]
            if direction[i] < 0 and upper[i] > upper[i - 1]:
                upper[i] = upper[i - 1]
    return pd.Series(direction, index=df.index).where(atr.notna())

def rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))

def generate_signals(df):
    d = supertrend_direction(df)
    flip_up = (d > 0) & (d.shift(1) < 0)
    flip_down = (d < 0) & (d.shift(1) > 0)
    entry = (flip_up & (rsi(df["close"]) < 40)).fillna(False).to_numpy()
    exit_ = flip_down.fillna(False).to_numpy()
    position = np.zeros(len(df))
    holding = False
    for i in range(len(df)):
        if not holding and entry[i]:
            holding = True
        elif holding and exit_[i]:
            holding = False
        position[i] = 1.0 if holding else 0.0
    # trade the next bar, so a signal built from today's close is never
    # acted on before today's close actually exists:
    return pd.Series(position, index=df.index).shift(1).fillna(0)
```

Every line of that is somewhere a bug can hide. The SuperTrend band has to lock against the prior bar without peeking at the next one. Entries have to fire once on the flip, not every bar the trend is up. The whole thing has to trade on the following bar, or a signal built from a bar's close gets acted on before that close exists. Miss any of these and the backtest looks better than the strategy is.

PRIOR writes all of it for you, from one vetted definition, and the language has no way to express the lookahead version in the first place. Four lines, or forty. Both run the same idea; only one of them can lie to you.

## How it runs

```
strategy.prior  →  JSON strategy object  →  generated Python  →  backtest / paper / live
```

PRIOR compiles to an open JSON interchange format, then to plain Python you can read, audit, and run. `prior explain` shows every layer, plus an English readback of what your strategy does. Nothing is magic.

<p align="center">
  <img src="https://raw.githubusercontent.com/prior-lang/prior/main/assets/prior-compile.gif" width="760" alt="prior explain: English readback, interchange JSON, and the generated Python">
</p>

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

**One file, one ticker, unless you say otherwise.** A bars file with a `ticker` column is treated as a universe: the strategy runs independently on every symbol in it and the results are reported per ticker, not as one blended curve. That is worth knowing before you point it at a panel, because it changes what the numbers mean. Universe runs also print a reminder that a constituent list is today's constituents, so long backtests over one inherit survivorship bias.

Strategies are accepted as `.prior` text or as the interchange `.json`. Every verb takes either, and `prior fmt strategy.json` converts JSON back into readable PRIOR text.

Generating strategies from a pipeline rather than writing them by hand? [`spec/strategy.schema.json`](https://github.com/prior-lang/prior/blob/main/spec/strategy.schema.json) is a JSON Schema for the interchange, bundled in the package so you can validate structure before the compiler sees it:

```python
import jsonschema, prior_lang

jsonschema.Draft202012Validator(prior_lang.load_schema()).validate(obj)
```

It is a fast structural gate, not the language. `prior validate` remains the authority on whether a strategy is real. See [SPEC.md §11](https://github.com/prior-lang/prior/blob/main/spec/SPEC.md) for the format.

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

A backtest with `--trades` prints the metrics plus a full per-trade log. You see every entry and exit, bars held, return, and which exit actually fired (stop, target, or time), so no number is a black box.

There is deliberately no options sample: real chain data cannot be redistributed under any free license. Options strategies (the wheel, cash-secured puts, covered calls, and multi-leg structures like put/call spreads, iron condors, straddles, strangles) backtest locally on chains YOU bring (`prior backtest wheel.prior --data f.csv --chains chains.csv`, one row per contract per day: date, expiry, strike, right, delta, mid), or in AutoQuant where licensed chain data is built in. A bundled synthetic universe also ships in `examples/data/` for fully offline use.

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

The [VS Code extension](https://github.com/prior-lang/prior/tree/main/editors/vscode) gives you syntax highlighting, tag completions with parameter docs, hovers that show what every tag expands to, live compiler diagnostics with quick fixes, and `prior fmt` as the document formatter.

Install it from the [Marketplace](https://marketplace.visualstudio.com/items?itemName=autoquant.prior-lang). Search "PRIOR" in the Extensions panel, or:

```
code --install-extension autoquant.prior-lang
```

Highlighting, completions, and hovers work immediately. Diagnostics and formatting shell out to the CLI so the editor reports exactly what the compiler will say. Install it with `pip install prior-lang`, or point the `prior.command` setting at any environment that has it.

## Documentation

- **Guides and tutorials:** [autoquant.ai/prior](https://autoquant.ai/prior)
- **Language specification:** [`spec/SPEC.md`](https://github.com/prior-lang/prior/blob/main/spec/SPEC.md): the source of truth for implementers
- **Tag reference:** [`spec/TAGS.md`](https://github.com/prior-lang/prior/blob/main/spec/TAGS.md): every tag, its defaults, and exactly what it expands to
- **Receipts:** `prior backtest --receipt` binds a result to a strategy digest, a data digest and the cost assumptions
- **Limits:** [`spec/LIMITS.md`](https://github.com/prior-lang/prior/blob/main/spec/LIMITS.md): what the language cannot express, and which backtest biases it does not close
- **Writing your own tags:** [`spec/PLUGINS.md`](https://github.com/prior-lang/prior/blob/main/spec/PLUGINS.md): add namespaced condition tags without touching the grammar

## Repository layout

```
spec/SPEC.md         language specification (grammar, semantics, error contract)
spec/TAGS.md         every tag: params, defaults, exact semantics, readback strings
examples/*.prior     complete strategies, from one-liners to pairs trades, the executable spec
python/prior_lang/   the reference implementation (zero-dependency parser + CLI)
editors/vscode/      VS Code extension: highlighting, completions, hovers, live diagnostics
```

## Acknowledgments

The sequence operator (`then within`, v0.9) and the `[sweep]` / `[sweep_high]` tags (v0.12) came out of field testing by **Precious Ukaegbu**, who reduced a lexer crash to a single line (now a regression test), found the gap in the grammar, and specified the sweep primitive precisely enough to build: a wick below a swing low that closes back above it.

The rule activity table, the Sharpe convention label, the stated cost model (all v0.12.1), the `[after_losses N]` outcome gate (v0.15), the divergence tags at confirmed fractal pivots (v0.16), and the gate's printed decomposition plus the equity report's stated fill convention (v0.18.1) came from a review by **Sunil Kumar**, who read the spec with his own scars attached and then put 35 rejected hypotheses through the grammar as an expressiveness benchmark. He specified the gate's hardest requirement himself: the loss streak must be counted on a shadow book that takes every signal, including the trades the gate declines. He later ran the gate on ten years of NSE data through his own independent engine and reproduced the admitted bucket within nine percent — the first cross-engine replication of a PRIOR result, and the reason the report now prints the decomposition instead of leaving it to arithmetic.

Fractal levels (`[fractal_high N]` / `[fractal_low N]`, v0.14) were specified in review by **Gabriel Guevara Muradas**, including the reveal delay that makes marking a fractal on its own bar unwritable.

## License

MIT, see [LICENSE](https://github.com/prior-lang/prior/blob/main/LICENSE). Use it, fork it, build your own runner on the open interchange format.

---

Built and stewarded by [AutoQuant](https://autoquant.ai).
