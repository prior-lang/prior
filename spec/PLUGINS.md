# Writing your own tags

`TAGS.md` is the complete core vocabulary, and `LIMITS.md` says plainly that
if a concept is not in there you cannot express it. That is true of the
core, and it is not the end of the story: you can add your own tags without
touching the grammar or forking anything.

A plugin tag is namespaced (`[acme.below_vwap 20]`) and behaves like any
other condition tag. It composes with `and`/`or`, carries `on <timeframe>`,
works inside `where` filters, and appears in `prior explain` in your own
words. The grammar never grows, so none of the language's guarantees move.

## A complete example

Two files. The first registers the tag:

```python
# myrules.py
from prior_lang.plugins import PluginTag, register

register(PluginTag(
    name="acme.below_vwap",
    params=[("period", "number", 20)],
    emit=lambda p: (
        f"tp = (df['high'] + df['low'] + df['close']) / 3\n"
        f"    vol = df['volume']\n"
        f"    vw = (tp * vol).rolling({int(p['period'])}).sum() / vol.rolling({int(p['period'])}).sum()\n"
        f"    cond = (close < vw).fillna(False)"
    ),
    readback=lambda p: f"price is below its {int(p['period'])}-bar VWAP",
))
```

The second uses it, like any other tag:

```
strategy "Plugin Gate"

universe $SPY
timeframe 1d

when [rsi] < 30 and [acme.below_vwap 20]
  buy [risk 1%]

sell when [rsi] > 55
  or [stop 3%]
```

Point PRIOR at the module and run it:

```
export PRIOR_PLUGINS=myrules
prior backtest strategy.prior --data bars.csv --capital 100000 --fee-bps 5
```

`prior explain` picks up your readback with no extra work:

> Size the position to risk 1% of equity at the stop when RSI(14) is below
> 30 **and price is below its 20-bar VWAP**.

## The emitter contract

`emit` returns Python source that will be spliced into the generated
`generate_signals(df)` function, so a few things matter.

**Assign to `cond`.** That name is what the compiler reads back out.

**Indent continuation lines by four spaces.** The snippet is inserted inside
a function body; the first line is already indented for you, and every
following line needs its own indentation, as in the example above.

**Only `close`, `df` and `np` are in scope.** The preamble binds `close =
df["close"]` and nothing else. Every other series comes off the frame:
`df["high"]`, `df["low"]`, `df["volume"]`. Reaching for a bare `high` is
the most common mistake and raises `NameError: name 'high' is not defined`
at backtest time rather than at compile time.

**Read closed bars only.** Nothing enforces this inside your emitter. The
core language cannot express lookahead, but a plugin is your own Python, so
the guarantee is yours to keep here. `df["close"].shift(-1)` will not be
caught. If you want the property PRIOR exists for, do not write that.

## Parameters

`params` is a list of `(name, kind, default)`. `kind` is `"number"` or
`"word"`. Positional arguments fill in order, so `[acme.below_vwap 20]`
sets `period` to `20`, and `[acme.below_vwap]` uses the default.

## Distribution and scope

`PRIOR_PLUGINS` takes a comma-separated list of module names, imported at
package load; importing should call `register()`. You can also call
`prior_lang.plugins.register(...)` directly before compiling.

Un-dotted names stay reserved for the core vocabulary, so your tags can
never collide with a future core tag. A strategy using a plugin tag compiles
only where that plugin is registered — if it is missing you get a clear
error rather than a wrong answer:

```
line 6: [acme.below_vwap] is a namespaced (plugin) tag, but no plugin has registered it
    when [rsi] < 30 and [acme.below_vwap 20]
                         ^
set PRIOR_PLUGINS=your_module or call prior_lang.plugins.register() first
```

That is worth thinking about before you share a strategy. A `.prior` file
using core tags alone is portable to anyone; one using your tags travels
only with your module.

## Current scope

Predicate tags only — a plugin tag is a complete condition, used bare in
`when`, `where` and `sell` expressions. Operand plugins that take a
comparison (`[acme.x] < 5`) are not supported yet. Sizing, exit, risk and
universe tags remain core-only.
