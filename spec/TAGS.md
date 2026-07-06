# PRIOR Tag Reference — v0.7 (draft)

Every tag in the language, its parameters, defaults, exact semantics, and what it compiles to. This file is the source of truth for the compiler's tag registry, the editor's autocomplete, and the `prior explain` readback strings.

Tags come in five kinds (see `SPEC.md` §5): **condition**, **sizing**, **exit**, **risk**, **universe**. Condition tags subdivide by usage into **predicate tags** (complete conditions, used bare: `when [macd_cross_up]`) and **operand tags** (values compared with `at` / `above` / `below` / `crosses` / `<` / `>`: `when price at [lower_bollinger]`, `when [rsi] < 30`).

Any condition tag accepts an `on <timeframe>` suffix (`[rsi on 4h]`, `[sma 200 on 1d]`): the condition is judged on that timeframe's closed bars and forward-filled — see SPEC §4 for the no-repaint contract.

Registry targets refer to the AutoQuant scanner condition registry (`engine/scanner/conditions.py`), which is the single implementation shared by StratScanner and PRIOR. Tags never fork registry semantics.

---

## Condition tags

### `[lower_bollinger]` · `[upper_bollinger]` · `[middle_bollinger]` — operand

| Param | Position | Default | Meaning |
|---|---|---|---|
| `period` | 1 | `20` | SMA/std window |
| `std` | 2 (or named) | `2.0` | band width in standard deviations |

Use: `price at [lower_bollinger]` · `price at [middle_bollinger]` · `price at [upper_bollinger std=1]`

Compiles to `price_at_bollinger_band` with `band: lower|middle|upper`.

**Exact `at` semantics (per registry):**
- lower: `close <= lower_band` (touched or crossed this bar)
- upper: `close >= upper_band`
- middle: `|close − mid| / mid < 0.5%` (tolerance hardcoded in v0.1; may become a param later)

Warmup: first `period` bars → false. Readback: *"price touches or crosses the {lower|middle|upper} Bollinger band ({period}-period, {std} standard deviation{s})"*.

### `[rsi]` — operand

| Param | Position | Default |
|---|---|---|
| `period` | 1 | `14` |

Use, and the registry condition each comparator selects:

| Written | Compiles to |
|---|---|
| `[rsi] < 30` | `rsi_less_than {period, threshold: 30}` |
| `[rsi] > 70` | `rsi_greater_than` |
| `[rsi] crosses above 55` | `rsi_crosses_above` (prev bar ≤ 55, this bar > 55) |
| `[rsi] crosses below 45` | `rsi_crosses_below` |

The right-hand side must be a number 0–100. Readback: *"RSI({period}) {is below|is above|crosses above|crosses below} {threshold}"*.

### `[sma N]` · `[ema N]` — operand

| Param | Position | Default |
|---|---|---|
| `period` | 1 | required |

| Written | Compiles to |
|---|---|
| `price above [sma 50]` | `price_above_sma {period: 50}` |
| `price below [sma 50]` | `price_below_sma` |
| `price above [ema 20]` | `price_above_ema` |
| `price below [ema 20]` | `price_below_ema` |
| `[ema 50] crosses above [ema 200]` | `ema_crosses_above {fast: 50, slow: 200}` |
| `[ema 50] crosses below [ema 200]` | **registry gap** — compile error "planned" (SPEC §9) |
| `[sma N] crosses above/below [sma M]` | **registry gap** — compile error "planned" (SPEC §9) |

In an MA-cross comparison, the left tag is `fast` and the right is `slow`; `fast >= slow` is a compile error (*"the faster average goes on the left: [ema 50] crosses above [ema 200]"*).

### `[macd_cross_up]` · `[macd_cross_down]` — predicate

| Param | Position | Default |
|---|---|---|
| `fast` | 1 | `12` |
| `slow` | 2 | `26` |
| `signal` | 3 | `9` |

Use bare: `when [macd_cross_up]`. Compiles to `macd_crosses_above_signal` / `macd_crosses_below_signal`. The MACD line crossed its signal line on this bar (prev-bar diff ≤ 0 and this-bar diff > 0, or the mirror). Readback: *"MACD({fast},{slow},{signal}) crosses {above|below} its signal line"*.

### `[volatile N%]` · `[quiet N%]` — predicate

| Param | Position | Default |
|---|---|---|
| `threshold` | 1 (percent) | required |
| `period` | named | `14` |

`[volatile 2%]` → `atr_greater_than_pct {threshold_pct: 2.0, period: 14}`: ATR as a percent of price is above 2%. `[quiet 1%]` → `atr_less_than_pct`: below 1%. Readback: *"ATR({period}) is {above|below} {threshold}% of price"*.

### `[volume_spike Nx]` — predicate

| Param | Position | Default |
|---|---|---|
| `multiplier` | 1 (multiplier) | `1.5x` |
| `period` | named | `20` |

`[volume_spike 1.5x]` → `volume_greater_than_avg {multiplier: 1.5, period: 20}`: this bar's volume exceeds the 20-bar average × 1.5. Readback: *"volume is more than {multiplier}× its {period}-bar average"*.

### `[heavy_volume top N%]` — predicate

| Param | Position | Default |
|---|---|---|
| `top` | 1 (word + percent) | `top 10%` |
| `period` | named | `60` |

`[heavy_volume top 10%]` → `volume_in_top_pct {top_pct: 10, period: 60}`: this bar's volume is in the top 10% of the trailing 60-bar distribution. Readback: *"volume is in the top {N}% of the last {period} bars"*.

### v0.3 additions — breakouts, gaps, streaks, levels, regime, stochastic

| Tag / form | Kind | Params (defaults) | Compiles to |
|---|---|---|---|
| `[new_high]` / `[new_low]` | predicate | period (252) | `price_new_high` / `price_new_low` — close at/beyond the highest/lowest close of the prior N bars |
| `[gap_up 2%]` / `[gap_down 2%]` | predicate | gap (2%) | `gap_up` / `gap_down` — open at least N% above/below the prior close |
| `[up_days 3]` / `[down_days 3]` | predicate | count (required) | `up_days` / `down_days` — N consecutive higher/lower closes |
| `price above 250` / `price below 10` | comparison | level | `price_above_level` / `price_below_level` — absolute price levels |
| `[adx] > 25` / `[adx] < 15` | operand | period (14) | `adx_greater_than` / `adx_less_than` — Wilder ADX trend-regime filter (threshold 0-100) |
| `[stoch] < 20`, `> 80`, `crosses above/below N` | operand | period (14), smooth (3) | `stoch_*` family — slow %K vs threshold (0-100) |
| `price above [vwap]` / `below [vwap 30]` | operand | period (20) | `price_above_vwap` / `price_below_vwap` — rolling volume-weighted typical price |
| `[squeeze]` | predicate | lookback (126), pct (10), period (20), std (2.0) | `bollinger_squeeze` — band width in its lowest N% of the lookback |
| `[obv_rising]` | predicate | period (20) | `obv_rising` — on-balance volume above its N-bar average |

Readbacks: *"price makes a new {period}-bar closing {high|low}"* · *"price gaps {up|down} at least {N}% at the open"* · *"the last {N} closes were each {higher|lower} than the one before"* · *"price is {above|below} {level}"* · *"ADX({period}) is {above|below} {threshold}"* · *"stochastic %K({period}) {is below|is above|crosses above|crosses below} {threshold}"*.

---

## Metric tags (rank/weight metrics in `hold` strategies)

| Tag | Params (defaults) | Definition |
|---|---|---|
| `[momentum N]` | period (required), `skip` (0) | return over the window from N bars ago to `skip` bars ago — classic 12-1 is `[momentum 252 skip=21]` |
| `[volatility N]` | period (20) | annualized stdev of daily returns |
| `[inverse_volatility N]` | period (20) | 1 / volatility — for `weighted by` and low-vol ranks |
| `[relative_strength N]` | period (63) | N-bar return minus the equal-weight universe's N-bar return |
| `[dollar_volume N]` | period (20) | mean of close × volume — liquidity rank |

Numeric operand tags double as metrics: `hold top 5 by [rsi]` ranks by RSI(14); `[adx]` and `[stoch]` work the same way. The reverse does not hold — `[momentum]` is not a condition.

---

## Sizing tags (exactly one, after `buy`)

### `[N% portfolio]`

Special form (percent-first, see SPEC §3). Position size = N% of current portfolio equity. → `{method: percent_of_portfolio, value: N/100}`. Readback: *"buy {N}% of the portfolio"*.

### `[$N]`

Special form. Fixed dollar amount per position. → `{method: fixed_dollar, value: N}`. Readback: *"buy ${N} worth"*.

### `[risk N%]`

Position sized so that if the stop is hit, the loss equals N% of equity: `size = (equity × N%) / stop_distance`. **Requires a `[stop x%]` tag in the exit rule** — compile error otherwise (SPEC §5). → `{method: risk_based, value: N/100}`. Readback: *"size the position to risk {N}% of equity at the stop"*.

---

## Exit tags (`or`-combinable in the `sell` rule)

| Tag | Param | Semantics | Readback |
|---|---|---|---|
| `[stop 1.5%]` or `[stop 2 atr]` | percent OR ATR multiple | exit at N% adverse move from entry, or N× the entry-bar ATR(14). Max one per strategy. | *"stop loss {N}% below entry"* / *"a stop {N} ATR below entry"* |
| `[target 3%]` or `[target 4 atr]` | percent OR ATR multiple | exit at N% favorable move, or N× entry ATR | *"take profit {N}% above entry"* |
| `[trailing 2%]` or `[trailing 3 atr]` | percent OR ATR multiple | percent trails the watermark; the ATR form is a chandelier (current ATR off the watermark) | *"trailing stop {N}% off the high"* / *"a chandelier stop {N} ATR off the high"* |
| `[breakeven after 2%]` | percent, required | once price moves N% in the trade's favor, a return to the entry price exits | *"a breakeven stop armed once {N}% up"* |
| `[after N bars]` | number + `bars`, required | exit at the close of the Nth bar after entry | *"exit after {N} bars"* |

Evaluation is bar-close (SPEC §6); precedence within a bar: stop → breakeven → target → trailing → condition exits → after. ATR stops/targets freeze the entry-bar ATR(14); the ATR trailing form uses the current bar's ATR (chandelier). Exit tags are direction-relative: in a short strategy, `[stop]` is the price rising N% above entry, `[target]` is it falling N% below, and `[trailing]` trails the low-water mark upward.

---

## Option & management tags (v0.7)

| Tag | Kind | Params (defaults) | Meaning |
|---|---|---|---|
| `[csp delta=25 dte=45]` | option | delta (25, trader units), dte (45) | the cash-secured put nearest those coordinates |
| `[covered_call delta=25 dte=45]` | option | same | the call written against held shares |
| `[profit 50%]` | management | percent of credit | close when half the credit is captured |
| `[loss 200%]` | management | percent of credit | close when the loss reaches 2x the credit |
| `[dte 21]` | management | days | close (in `close at`) or roll (in `roll at`) at N days to expiry |
| `[contracts 1]` / `[collateral 50%]` | risk | count / percent | option position sizing |

---

## Risk tags (in the `risk` statement)

| Tag | Param | Semantics |
|---|---|---|
| `[max_positions N]` | number | never hold more than N open positions across the strategy |
| `[max_position N%]` | percent | no single position may exceed N% of equity at entry |
| `[daily_loss $N]` | dollar | halt new entries for the day after realized losses reach $N |
| `[cooldown N]` | number | no re-entry for N bars after any exit — unlike other risk tags, this one shapes generate_signals directly |

Risk tags attach as strategy-level metadata for the runner; they do not alter `generate_signals`.

---

## Universe tags (in the `universe` statement)

Shared 1:1 with the AutoQuant engine's prebuilt universes (`engine/loop/universes.py`) and the StratScanner dropdown. Re-expanded from their definition on every run.

| Tag | Contents (2026-07-05) |
|---|---|
| `[sp_top_30]` | 30 largest S&P names by market cap. ORCL fills the BRK-B slot (Berkshire's ticker formats inconsistently across data providers). |
| `[mega_tech]` | 15 mega-cap tech: AAPL MSFT GOOGL AMZN META NVDA TSLA AVGO ORCL CRM ADBE NFLX AMD INTC QCOM |
| `[etf_sectors]` | 11 SPDR sector ETFs: XLK XLF XLE XLV XLI XLY XLP XLB XLRE XLU XLC |
| `[big_banks]` | 10 money-center + super-regional banks: JPM BAC WFC C GS MS USB PNC TFC SCHW |
| `[semis]` | 14 semiconductor leaders: NVDA AVGO AMD QCOM TXN INTC MU AMAT LRCX KLAC MRVL ADI NXPI MCHP |
| `[crypto_majors]` | 8 deepest-liquidity crypto pairs: BTC-USD ETH-USD SOL-USD DOGE-USD AVAX-USD LINK-USD LTC-USD BCH-USD |

Manual universes skip the tag: `universe $AAPL $MSFT $NVDA` or, for one ticker, inline scoping (`when $NVDA at [lower_bollinger]`).

---

## Adding a tag (the process, so we never fork semantics)

1. The condition lands in the scanner registry first (`conditions.py`), with params and defaults.
2. This file gets the tag entry: name, kind, params table, registry mapping, readback string.
3. The compiler's tag table is regenerated from this file (Phase C makes this mechanical).
4. An example or test exercises the tag through compile + backtest.

Tags are the human names; registry keys are the stable API. Registry keys never rename for the language's sake.
