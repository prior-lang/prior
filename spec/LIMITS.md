# What PRIOR cannot express

PRIOR is deliberately small. This document is the honest inventory of what that costs you, so you can decide in five minutes whether the language fits your idea instead of discovering it an hour in.

Two rules make the rest of this page predictable:

- **Nothing fails silently.** Every limit below is a compile error with a line, a caret, and a message. A `.prior` file that compiles, runs. A tool that quietly ignores what it does not understand is how you end up backtesting a strategy you did not write.
- **The tag vocabulary is the ceiling.** [`TAGS.md`](TAGS.md) is the complete list of core tags. If a concept is not in there, you cannot express it, and the answer is a new tag rather than new syntax. You can add your own without touching the grammar — see [`PLUGINS.md`](PLUGINS.md).

---

## 1. The language is not a programming language

There are no variables, loops, functions, imports, or conditionals beyond the condition grammar. There is also no arithmetic on tag values, so you cannot subtract one indicator from another, scale one by a constant, or compare a tag against a computed expression.

```
when [rsi] - [rsi 5] > 10
```
```
line 4: unexpected character '-'
    when [rsi] - [rsi 5] > 10
               ^
```

If you need a derived quantity, it belongs in the registry as a tag with a name and defined semantics, not assembled inline in a strategy file. That is the trade: you lose arbitrary expression, and in exchange every strategy means exactly one thing and round-trips through JSON without ambiguity.

## 2. Nothing is learned or fitted

PRIOR states rules. It does not train, fit, or infer. There is no model, no weights, no regime classifier, no parameter search. If your idea is "the entry threshold is whatever the optimizer found" or "enter when the HMM says regime 2," the model itself lives outside PRIOR and always will.

This is a boundary, not a gap on a roadmap. The useful split is to keep the learned component in your own pipeline and express the rules around it here, so that the part which can be written down honestly, is.

## 3. A strategy is one form, never two

A file is **rules**, or **ranking**, or **options**. Mixing them is an error.

```
a strategy is rules (when/sell) or ranking (hold), not both — hold IS the entry, the exit, and the sizing
```
```
an options strategy stands alone — no buy/short rules, sell/cover exits, or hold alongside it
```

Within rules, direction pairing is enforced: `buy` exits with `sell`, `short` exits with `cover`. A file may hold both long and short rules, and when it does it needs both exits.

```
long strategies exit with sell — cover closes a short
```

## 4. Current limits, by feature

These are true as of v0.9 and are the ones most likely to stop you.

**Options** are single-ticker.

```
options strategies are single-ticker for now — universe $F, or an inline $TICKER
```

Multi-leg structures settle expiry as cash by net intrinsic, with no share-assignment modeling. Undefined-risk structures (straddle, strangle) report P&L without percent-return metrics, because there is no honest fixed collateral base to divide by. Options backtests need real chain data you supply with `--chains`; the reference runner will not fabricate it.

**Windowed sequences** (`A then within N bars B`) are two steps, in entry rules only.

```
line 4: chaining more than two steps is not supported yet
split the idea into one 'then within N bars' step
```
```
line 4: 'on <timeframe>' is not supported after 'then' yet
```

**Multi-timeframe** conditions only look coarser than the strategy timeframe, never finer.

```
'on 15m' is finer than the strategy timeframe (1d) — a coarser strategy cannot see intrabar data; 'on' is for higher-timeframe context (e.g. a daily regime gate on an hourly strategy)
```

Both sides of a comparison must share one timeframe, and `on` is not yet allowed inside a `hold` where-filter.

**Ranking** universes are today's constituents, so long ranking backtests inherit survivorship bias. Point-in-time membership is a data problem, covered in section 5.

**Positions** are one per ticker. While a position is open, further entries in that ticker are ignored, and an opposite-direction edge does not reverse you. Re-entry needs a fresh rising edge after the exit.

**Evaluation** happens on completed bars. There is no intrabar logic in backtests. Live runners may place broker-side bracket orders that fill intrabar, which makes backtests the conservative of the two. That divergence is documented behavior rather than a bug.

**Risk-based sizing** requires a stop to size against, with no synthetic fallback.

```
risk-based sizing needs a stop to size against — add [stop x%] to the sell rule
```

**Band tolerance** is not tunable. `price_at_bollinger_band` hardcodes a 0.5% touch, so `[middle_bollinger tol=0.5%]` is an error. Exposing it as an optional parameter would be additive and has simply not been done.

## 5. Which backtest lies PRIOR actually closes

A backtest can mislead you in several ways, and only some are a language problem. Being precise about which is the point of the project.

**Your code reaching into the future.** *Closed completely.* No token in the grammar references a bar that has not closed, so the category is unrepresentable rather than discouraged. Entries are edge-triggered on the false-to-true transition and fills land on the next bar, handled by the compiler instead of by you remembering.

**Statistics computed over the whole series.** *Structurally absent.* This is the subtle one: z-scoring an indicator or bucketing it into quantiles using the full history leaks the future distribution into every early bar, and a walk-forward harness wrapped around it will not save you. PRIOR has no normalization, standardization, or quantile-binning construct. Every tag is defined on a trailing window (`[momentum 252 skip=21]`, `[volatility 20]`, `[ivrank]` against its own trailing year), so there is nowhere for a full-sample statistic to enter.

**Data that was not knowable at the time.** *Yours.* Companies restate earnings. A figure can carry an innocent-looking date while holding a number nobody had on that date. PRIOR runs on the data you give it and cannot know a value was revised afterward. Use point-in-time data.

**A universe you chose knowing how it turned out.** *Yours.* Backtest ten mega-caps that survived and PRIOR will faithfully test a biased sample without complaint. The bias is in which data you picked, not in what the strategy does with it. Use a survivorship-free dataset that includes the names that died.

**Publishing a result nobody can tie to anything.** *Addressed.* `prior backtest --receipt` emits the metrics alongside a digest of the canonical strategy, a digest of the bars, and the cost assumptions, so a published number says what produced it. The strategy digest is taken over canonical source with comments stripped, which makes it identical whether the strategy arrived as `.prior` text or as JSON.

**A result you selected from many attempts.** *Yours.* Write a thousand strategies, backtest them all honestly, publish the best one, and you have produced a lie that contains no lookahead anywhere in it. Selection bias lives above the language, in which results you chose to believe, and no property of a single backtest can detect how many siblings it had. The mitigations are procedural: count your trials, deflate your Sharpe for them, and hold out data your search never touched.

PRIOR closes the first two by construction and gives you a receipt for the third. The last two belong to your data and your process, and it does not pretend otherwise. A tool claiming all of them would be making exactly the kind of quiet overstatement this language exists to prevent.

## 6. Asking for something that is not here

If the rule you want is not expressible, that is worth reporting. The most useful report names the actual setup rather than the syntax you tried, because the answer is often a tag that does not exist yet rather than a grammar change.

The windowed sequence operator in section 4 exists because someone described an arm-then-confirm setup they could not write, and the honest answer at the time was that PRIOR could not express it.
