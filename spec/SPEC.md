# PRIOR Language Specification — v0.7 (draft)

**PRIOR** — Portable Rules for Indicators, Orders & Risk. A declarative language for expressing trading strategies as testable hypotheses. This spec is the source of truth for the parser, formatter, and compiler. Pre-1.0, breakable with notice.

Status: draft. v0.16 (2026-08-07) adds divergence: `[bullish_divergence rsi N]` / `[bearish_divergence rsi N]` compare price and RSI at the two most recent CONFIRMED fractal pivots (the same strict construction and reveal law as the fractal tags — wing N, each pivot revealed N bars after it forms). Bullish: price makes a lower confirmed low while RSI makes a higher low; bearish mirrors on highs. The RSI value is read at the pivot bar but becomes knowledge only at the reveal, so the condition changes value exactly at reveal bars and the classic repainting divergence (drawn through an unconfirmed pivot) is unrepresentable. Pivots further apart than `within` bars (default 60) are two unrelated swings, not a divergence; a pivot whose RSI is undefined (a one directional 14 bar run under the divide guard) is skipped rather than compared. RSI is the supported oscillator for now; other indicators need their own pivot semantics first and are refused readably. v0.15 (2026-08-07) adds outcome-conditioned entries: `risk [after_losses N]` admits an entry only when the strategy's own last N trades were consecutive losses. The streak is counted on a shadow book that takes every signal the strategy generates, including the trades the gate declines — otherwise the gate would feed back into its own input and the semantics would depend on the gate itself. An outcome is a realized close-to-close fill, known at its exit bar's close, so the entry decision reads only realized information and the no-lookahead law is untouched: yesterday's fill is knowledge, tomorrow's is not. A winning or flat trade resets the streak; the backtest report prints how many shadow trades the gate saw and how many it admitted, and a gate that admits nothing is flagged loudly. Stock strategies only for now — premium programs and ranking strategies refuse it with a pointed error. v0.14 (2026-08-07) adds fractal levels: `[fractal_high N]` and `[fractal_low N]` give the most recent confirmed strict fractal extreme as a price operand (price crosses above [fractal_high]). A fractal needs its `wing` bars on both sides, so it does not exist until the wing closes; the level is revealed exactly `wing` bars after the bar that made it, and the delay scales with the wing. This is the canonical accidental lookahead (marking the fractal on its own bar) made unwritable, and the reveal timing is regression tested. v0.13 (2026-08-06) fixes two options backtest defects and one is a semantics change: contract selection now converts trader delta units (delta=25) to the decimal deltas chain data carries, so a 25 delta request picks the 0.25 delta strike instead of the deepest in the money contract; and a cash secured put program that takes assignment sells the shares at the next close and resumes selling puts, rather than holding the stock silently for the rest of the test. Wheel and covered call forms are unchanged. v0.12 (2026-08-05) adds parenthesized groups — the one way to mix `and` with `or` (`(a or b) and c`), nesting to any depth, usable as sequence terms, flattening away when redundant so punctuation never changes a canonical hash; interchange gains the `group` condition (children under `params.conditions`, same nesting convention as `sequence`). Also adds `[sweep N]` / `[sweep_high N]` — the bar takes out the prior N-bar low/high intrabar and closes back through it, the stop-run-and-reclaim in one tag, both halves reading only this bar and the prior window. v0.12 limits: `on <timeframe>` conditions cannot sit inside parentheses. v0.10 (2026-08-03) adds `[jade_lizard]` (short put + short call + long call `width` above it — the asymmetric premium structure whose upside risk disappears once the credit exceeds the call-spread width, while the downside stays a naked put and therefore undefined; reported without percent-return metrics for the same reason straddles and strangles are). v0.9 (2026-07-27) adds the windowed sequence operator (`A then within N bars B` — arm-then-confirm setups, binding tighter than `and`, strictly ordered, window counted backwards so lookahead stays unrepresentable). v0.8 (2026-07-07) adds multi-leg option structures as write-rule tags ([put_spread], [call_spread], [iron_condor], [straddle], [strangle] — structures are always tags, never the spread() call form), partial exits inside mixed long+short files (sell half / cover half per direction), dynamic universes ([top_volume N], membership recomputed monthly on closed bars), pairs trading (spread($A, $B) as a first-class operand), and the observability toolchain (--trades per-trade log with exit reasons, trace per-bar condition verdicts). The reference backtester now runs options on user-provided chain data (--chains), applies sizing under --capital, models per-side costs (--fee-bps/--slippage-bps, --contract-fee), and windows by date (--from/--to). v0.7 (2026-07-06) also adds hosted-data condition tags ([ivrank], [short_interest], [earnings_within]) — syntax everywhere, evaluation in AutoQuant where the data exists. v0.7 adds options strategies: the wheel playbook (wheel [delta=25 dte=45]) and write-rules (when <cond> write [csp ...]), with close at / roll at management and single-ticker scope; options strategies validate, format, and explain everywhere but backtest only where real chain data exists. v0.6 (2026-07-06) adds rule plurality: multiple entry rules per strategy including long AND short in one file (sell closes longs, cover closes shorts, both required when mixed; simultaneous opposite edges stand aside), partial exits (sell half when; cover half when in mixed files since v0.8), and cooldown (risk [cooldown N]). v0.5 (2026-07-06) adds multi-timeframe conditions (on <tf> inside condition tags, closed-bar no-repaint semantics). v0.4 (2026-07-06) adds ranking strategies (hold top N by [metric], rebalance calendars, where-filters, weighting). v0.3 (2026-07-06) adds the vocabulary sweep (new highs/lows, gaps, streaks, price levels, ADX, stochastic, VWAP, squeeze, OBV) and richer exits (ATR-unit stops/targets, chandelier trailing, breakeven). v0.2 (2026-07-06) added short strategies. v0.1 drafted 2026-07-05. Companion documents: `TAGS.md` (tag reference), `../examples/*.prior` (the executable spec — every example must parse, format canonically, and compile).

---

## 1. Design invariants

These are not stylistic preferences. Violating any of them is a spec bug.

1. **Not Turing-complete.** No variables, loops, user-defined functions, imports, or arithmetic on tag values. When the language feels too small, the answer is a new tag, not new syntax.
2. **No expressible lookahead.** There is no token, tag, or construct that references a future bar. This is a property of the vocabulary, enforced by construction.
3. **Tags are semantic macros.** A tag bundles indicator defaults, tolerance/touch semantics, NaN-warmup policy, and edge-trigger behavior. Tag semantics are defined once (in the scanner condition registry) and never forked.
4. **Compile-time is the only error time.** A `.prior` file that compiles, runs. All validation — unknown tags, bad params, kind mismatches, missing exits — happens at compile with line-precise messages.
5. **Round-trip stability.** parse → JSON → format must reproduce the canonical form of the input exactly. The JSON interchange (§11) is the AST.

---

## 2. Lexical structure

- **Encoding:** UTF-8. Line-oriented.
- **Comments:** `#` to end of line. Preserved by `prior fmt` (attached to the following statement).
- **Logical lines:** A newline ends a statement, EXCEPT a line whose first token is `and`, `or`, `buy`, or `short` continues the previous logical line. Indentation is cosmetic; `prior fmt` indents continuations two spaces.
- **Case:** Keywords and tag names are case-insensitive on input. `prior fmt` normalizes both to lowercase. Ticker symbols are uppercased.

### Tokens

| Token | Form | Examples | Notes |
|---|---|---|---|
| STRING | double-quoted | `"Bollinger Reversal"` | strategy names only |
| NUMBER | int or decimal | `20`, `1.5` | |
| PERCENT | number + `%` | `5%`, `1.5%` | |
| DOLLAR | `$` + digits | `$10000`, `$500` | disambiguated from TICKER by first char after `$` |
| MULTIPLIER | number + `x` | `1.5x`, `2x` | |
| TICKER | `$` + letters (may contain `-`) | `$NVDA`, `$BTC-USD` | disambiguated from DOLLAR by first char after `$` |
| TIMEFRAME | int + unit | `1d`, `4h`, `15m`, `1w` | lexical form only; the compiler validates against the engine-supported set at compile time (engine is the source of truth) |
| TAGNAME / WORD | `[a-z_][a-z0-9_]*` | `lower_bollinger`, `top` | dotted names (`acme.momo`) are namespaced plugin tags — registered via prior_lang.plugins (see TAGS.md); unregistered dotted names error with a pointer |

### Keywords

`strategy` `universe` `timeframe` `when` `if` `buy` `short` `sell` `cover` `hold` `rebalance` `top` `bottom` `by` `where` `weighted` `equally` `risk` `and` `or` `at` `above` `below` `crosses` `price` `volume`

`on` is tag syntax (multi-timeframe suffix), not a statement keyword.

---

## 3. Grammar (EBNF)

```ebnf
program        = { line } ;
line           = [ statement ] , [ comment ] , NEWLINE ;

statement      = strategy_stmt | universe_stmt | timeframe_stmt
               | entry_stmt | exit_stmt | risk_stmt ;

strategy_stmt  = "strategy" , STRING ;
universe_stmt  = "universe" , ( tag | TICKER , { TICKER } ) ;
                 (* the tag is a prebuilt list ([sp_top_30]) or dynamic ([top_volume 50]) *)
timeframe_stmt = "timeframe" , TIMEFRAME ;

entry_stmt     = ( "when" | "if" ) , expr , action ;
action         = ( "buy" | "short" ) , tag ;        (* sizing tag, required *)

exit_stmt      = ( "sell" | "cover" ) , [ "half" ] , [ "when" ] , expr ;

risk_stmt      = "risk" , tag , { tag } ;

rebalance_stmt = "rebalance" , ( "daily" | "weekly" | "monthly" ) ;

wheel_stmt     = "wheel" , "[" , { ("delta"|"dte") , "=" , NUMBER } , "]" ,
                 [ "where" , expr ] ;
close_stmt     = "close" , "at" , mgmt_tag , { "or" , mgmt_tag } ;
roll_stmt      = "roll" , "at" , "[" , "dte" , NUMBER , "]" ;
hold_stmt      = "hold" , ( "top" | "bottom" ) , NUMBER , "by" , tag ,
                 [ "where" , expr ] ,
                 [ "weighted" , ( "equally" | "by" , tag ) ] ;

expr           = and_expr , { "or" , and_expr } ;
and_expr       = seq_term , { "and" , seq_term } ;
seq_term       = term , [ "then" , "within" , NUMBER , ( "bar" | "bars" ) , term ] ;
term           = comparison | tag | "(" , expr , ")" ;
comparison     = operand , comparator , operand ;
comparator     = "at" | "above" | "below"
               | "crosses" , ( "above" | "below" )
               | "<" | ">" | "<=" | ">=" ;
operand        = "price" | "volume" | tag | NUMBER | PERCENT | TICKER | spread ;
spread         = "spread" , "(" , TICKER , "," , TICKER , [ "," , ( "ratio" | "diff" ) ] , ")" ;

tag            = "[" , tag_body , "]" ;
tag_body       = TAGNAME , { tag_arg } , [ "on" , TIMEFRAME ]
                                              (* [rsi on 4h], [sma 200 on 1d] *)
               | PERCENT , "portfolio"        (* [5% portfolio] — sizing special form *)
               | DOLLAR ;                     (* [$10000] — sizing special form *)
tag_arg        = tag_value | TAGNAME , "=" , tag_value ;
tag_value      = NUMBER | PERCENT | DOLLAR | MULTIPLIER | WORD ;
```

The two sizing special forms exist because `buy [5% portfolio]` and `buy [$10000]` read the way traders talk; they are the only tags whose body doesn't start with a name. `[risk 1%]` uses the normal name-first form.

Combining: one chain is all `and` or all `or`. Mixing the two requires parentheses — `(a or b) and c` — which say which binds first, so there is no precedence table to remember and no silent misreading of a rule. Groups nest to any depth; redundant parentheses around a same-connector chain flatten away and do not change the strategy's canonical form.

The grammar is deliberately permissive; **kind checking** (section 5) rejects nonsense like `buy [stop 1.5%]` or `risk [rsi]` with targeted messages. This keeps parse errors rare and semantic errors specific.

---

## 4. Statements

A program has at most one of each: `strategy`, `universe`, `timeframe`, exit (`sell`/`cover`), partial exit (`sell half`), `risk` — and any number of entry rules (`when`, since v0.6). Statement order is free; `prior fmt` canonicalizes to the order above.

| Statement | Required | Default when omitted |
|---|---|---|
| `strategy "Name"` | no | filename, title-cased |
| `universe ...` | no* | *required unless the entry/exit rules use inline `$TICKER` scoping |
| `timeframe TF` | no | `1d` |
| `when <expr> buy|short <sizing-tag>` | **yes** | — |
| `sell|cover [when] <expr>` | **yes** | — |
| `risk [tag]...` | no | engine defaults |

### Entry (`when` / `if`)

`when` is canonical. `if` is accepted as a permanent alias (it was the original sketch) and rewritten to `when` by `prior fmt`.

**The sizing tag on `buy` is mandatory.** Omitting it is a compile error: *"buy needs a sizing tag, e.g. buy [10% portfolio]"*. Silent defaults on money decisions are not a feature. `prior fmt --fix` inserts `[10% portfolio]  # default, review me` when asked explicitly.

### Exit (`sell`)

The exit expression may mix **condition terms** (evaluated like entry conditions) and **exit tags** (`[stop 1.5%]`, `[target 3%]`, `[trailing 2%]`, `[after 5 bars]`), combined with `or`. Combining exit tags with `and` is a compile error (an `and` of a stop and a target has no coherent order semantics).

### Ticker scoping

An inline `$TICKER` operand scopes the whole strategy to that instrument, and `price`/`volume` refer to it.

### Spread scoping (pairs trading)

`spread($GLD, $GDX)` is a first-class operand — the ratio of the two legs' closes (`diff` as the optional third argument for the difference form). It behaves exactly like `price`: every price comparison works on it, and indicators compute ON the spread series. Using a spread scopes the whole strategy to that pair: one spread per file, no `universe` statement, no other inline tickers. Buying the spread is long the first leg / short the second in equal dollar legs; shorting mirrors; exits close both legs. Volume-based conditions are compile errors on spreads (a spread has no volume), and percent exits are rejected on `diff` spreads (a difference can cross zero, making percent moves undefined — use ATR units). v0.1 restriction: a program uses **either** a `universe` statement with universe-wide rules, **or** inline single-ticker scoping — mixing the two is a compile error ("per-ticker overrides inside a universe are coming in a later version"). All inline tickers in one program must be the same symbol in v0.1.

---

## 5. Kinds

Every tag has exactly one kind. The kind table lives in `TAGS.md` and is machine-derived from the registry mapping.

| Kind | Where legal | Examples |
|---|---|---|
| `condition` | entry expr, exit expr | `[lower_bollinger]`, `[rsi]`, `[macd_cross_up]` |
| `sizing` | after `buy`, exactly one | `[5% portfolio]`, `[$10000]`, `[risk 1%]` |
| `exit` | exit expr, `or`-combined | `[stop 1.5%]`, `[after 5 bars]` |
| `risk` | `risk` statement | `[max_positions 5]`, `[daily_loss $500]` |
| `universe` | `universe` statement | `[sp_top_30]`, `[semis]`, `[top_volume 50]` (dynamic: membership computed from data, monthly, closed bars only) |

Kind-check errors name both the tag's kind and the expected kind: *"line 7: [stop 1.5%] is an exit tag; the entry rule takes condition tags. Did you mean to put it in the sell rule?"*

Cross-statement checks:
- `buy [risk N%]` **requires** a `[stop]` tag in the exit. Missing stop = compile error: *"risk-based sizing needs a stop to size against; add [stop x%] to the sell rule."* No synthetic fallback.
- `[trailing]` and `[stop]` may coexist (trailing tightens, stop is the floor). Two `[stop]` tags = error.

---

## 6. Evaluation semantics

- **Options strategies (v0.7).** A strategy is equities-rules, ranking, OR options — never mixed. The `wheel` playbook runs the full lifecycle (cash → short put → assigned → covered call → called away → cash); `when <cond> write [csp delta=25 dte=45]` is the composable primitive (the whole condition grammar gates when premium is sold). Management (`close at [profit 50%]`/`[loss 200%]`/`[dte N]`, `roll at [dte N]`) is checked at each bar close before expiry settlement; assignment at expiry by moneyness; chain selection is the nearest expiry ≥ DTE, then nearest |delta| (deterministic ties). Delta is in trader units (25 = the 25-delta). Single-ticker only for now. Options strategies compile to a generate_option_orders(df, chains) contract; conforming runners need real chain data — the reference runner never fabricates it but runs on chains the user provides (--chains). Multi-leg structures (v0.8: [put_spread], [call_spread], [iron_condor] with width = wing distance in strike points; [straddle], [strangle]) emit one order row per leg with side and group columns; management works on the structure's NET mid vs its net credit; rolls rebuild the whole structure; expiry settles cash by net intrinsic (no share-assignment modeling on multi-leg). Undefined-risk structures (straddle/strangle) report P&L without percent-return metrics — there is no honest fixed collateral base.
- **Rule plurality (v0.6).** A strategy may have several entry rules (`when … buy [sizing]` blocks, each with its own logic and sizing). Any rule's rising edge opens the position in that rule's direction; one position at a time per ticker; while positioned, opposite-direction edges are ignored (no stop-and-reverse yet), and a bar where long and short edges fire together stands aside. Mixed files need both a sell rule (longs) and a cover rule (shorts), each a full exit spec. `sell half when …` (at most one) takes half off ONCE per position — its triggers are targets, conditions, or `[after N bars]`, never stops — and is checked after the full-exit chain. `risk [cooldown N]` blocks re-entry for N bars after any exit. Signals become fractional (±0.5) once a partial fires.
- **Multi-timeframe conditions.** A condition tag may carry `on <tf>` where `<tf>` is COARSER than the strategy timeframe (finer or equal is a compile error). The whole condition is judged on that timeframe's **closed** bars — the strategy's bars are resampled (weeks end Friday), the condition evaluates there, and its verdict forward-fills onto the strategy's bars. A higher-TF bar's verdict is visible only from its close onward: **the gate cannot repaint**, structurally. Both sides of a comparison must share one timeframe. Multi-timeframe strategies require datetime-indexed bars (a clear runtime error otherwise). Mixing frames inside one comparison (strategy-TF price against a higher-TF level) and `on` inside `hold` where-filters are future extensions.
- **Ranking strategies** (`hold`) are a third form, mutually exclusive with rules (`when`/`sell`): `hold` IS the entry, the exit, and the sizing. On each rebalance close (daily / weekly = last trading day of ISO week / monthly = last trading day of month, default monthly), eligible tickers (metric non-NaN, `where` conditions true) are ranked; ties break alphabetically; the top/bottom N are held equally weighted or `weighted by` a metric, capped by `risk [max_position N%]` (excess redistributes pro-rata once, remainder is cash); fewer qualifiers than N leaves the shortfall in cash; weights hold between rebalances. **Universes are today's constituents — long ranking backtests inherit survivorship bias.** Point-in-time constituents are a hosted-data concern.
- **Direction.** A strategy is long (`buy` … `sell`) or short (`short` … `cover`); since v0.6 both may appear in one file (see rule plurality above), and the pairing is enforced (`buy` with `cover` is a compile error that teaches the vocabulary). Short signals are 0/-1. Exit tags are direction-relative: a short's `[stop]` sits above entry, its `[target]` below, and `[trailing]` trails the low-water mark. Condition tags are direction-neutral predicates and never change meaning.
- **Bar-close evaluation.** All conditions are evaluated on completed bars. There is no intrabar evaluation in v0.1 backtests. (Live/paper runners may place broker-side bracket orders for stops/targets that fill intrabar; this backtest-vs-live divergence is documented behavior, not a bug — backtests are conservative.)
- **Edge-triggered entry.** The entry fires on the bar where the combined condition transitions false→true, matching the scanner/codegen pattern (`entries = cond & ~cond.shift(1)`). A condition that stays true for 10 bars produces one entry, not ten.
- **Windowed sequences (v0.9).** `A then within N bars B` expresses arm-then-confirm setups (a sweep, then a structure break inside N bars) that a single-bar conjunction cannot. `then` binds tighter than `and`, so `A then within N bars B and C` reads `(A then within N bars B) and C`. Semantics: **A arms on its rising edge**; **B must land on a strictly later bar** (same-bar B does not fire — that is what `and` is for); the window is the N bars following the arming bar; a fresh A inside an open window starts a new window; an expired window is silent and leaves no state. The result is an ordinary boolean condition, so it composes with `and`/`or` and feeds the usual edge-triggered entry. **The window counts backwards from the current bar** ("did A arm within the last N bars"), never forwards from the arm, so every term still reads closed bars only and lookahead remains unrepresentable. v0.9 limits: two steps (no chaining), no `on <timeframe>` inside a sequence, entry rules only.
- **Warmup.** Indicator NaN periods evaluate to false. Never an exception, never a fill.
- **One position per ticker.** While a position is open in a ticker, further entries in that ticker are ignored. Re-entry requires a new rising edge after the exit.
- **Exit precedence within a bar:** `[stop]` → `[breakeven]` → `[target]` → `[trailing]` → condition exits → `[after N bars]`. Deterministic and documented so backtests are reproducible.
- **`crosses above/below`** requires both the current and previous bar to be non-NaN; the crossing bar itself satisfies the condition (consistent with `rsi_crosses_above` in the registry).
- **`at`** is per-tag touch semantics, defined in `TAGS.md` (e.g. lower band: `close <= band`; middle band: within 0.5% of mid). `price == [tag]` is a parse-level error with the hint to use `at` — float equality never fires and the language refuses to let you write it.

---

## 7. Compile pipeline & errors

```
strategy.prior → parse → kind check → cross-checks → JSON (interchange schema) → Python codegen
```

Error message contract (every error MUST have all four):
1. Line and column.
2. The offending source line, quoted.
3. What's wrong, in trader language, not parser language.
4. A concrete suggestion — did-you-mean (Levenshtein ≤ 2 over the tag registry), an example fix, or a doc pointer.

Example: `line 4: [lower_bolinger] is not a known tag. Did you mean [lower_bollinger]?`

---

## 8. Canonical formatting (`prior fmt`)

- Statement order: `strategy`, `universe`, `timeframe`, blank line, entry, blank line, exit, blank line, `risk`.
- Two-space indent for continuation lines (`and`/`or`/`buy`).
- `if` → `when`. Lowercase keywords and tag names. Uppercase tickers.
- Positional params before named params inside tags; drop params equal to defaults? **No** — explicit params are kept even when equal to defaults (the author wrote them for a reason). fmt never deletes meaning.
- Idempotent: `fmt(fmt(x)) == fmt(x)`. Round-trip: `fmt(parse→json→print(x)) == fmt(x)`.

---

## 9. Known gaps

The tag vocabulary resolves onto a condition registry shared with AutoQuant's scanner, so a tag means the same thing in both. `TAGS.md` is the reference for what exists; this section records registry-level gaps. `LIMITS.md` is the user-facing inventory of what the language cannot express and which backtest biases it does not close.

- **Band tolerance is not tunable.** `price_at_bollinger_band` hardcodes a 0.5% touch tolerance, so `[middle_bollinger tol=0.5%]` is a compile error (`has no parameter 'tol'`). Exposing it as an optional param with the current value as default would be additive and backward compatible; it has not been done.

A tag or parameter that the registry does not implement is always a compile error with a line-precise message, never a silent no-op. Per §1.4 that is the only place such a failure can surface.

---

## 10. Versioning

The spec carries a version, currently `v0.7`, which is also the `version` field on the JSON interchange (§11). A `.prior` file may optionally declare `# prior: 0.7` as its first comment line; absent, the compiler assumes its own version. Pre-1.0: breaking changes allowed with a formatter migration (`prior fmt --upgrade`) whenever mechanically possible. Post-1.0: the LEAN/Terraform bar — files keep compiling.

---

## 11. JSON interchange

`prior compile --json` emits the strategy object; `prior fmt strategy.json` turns it back into canonical PRIOR text. Both directions run through the same parser and the same validation, so a `.json` strategy is not a back door: anything the grammar forbids is still rejected, and **§1.2 (no expressible lookahead) holds identically through the JSON path.**

This makes the JSON the integration surface. A generator, a database, or a pipeline can emit strategy objects without templating PRIOR text, and they inherit the safety properties.

### Round trip

```
source → compile_source() → dict → json.dumps → json.loads → strategy_to_source() → source
```

is stable: the resulting IR compares equal to the original, and the emitted source is canonical form (§8).

That stability is also how the door is guarded. `strategy_to_source` renders what it recognizes and ignores the rest, which is correct for a renderer and wrong for an entry point, so JSON arriving from outside goes through **`strategy_from_json`**: it renders, re-parses, re-emits, and rejects any key or parameter that did not survive the trip, naming the path it found. A parameter the grammar has no word for is therefore an error on both doors — `[rsi tol=0.5%]` is refused as text, and `{"condition": "rsi", "params": {"tol": "0.5%"}}` is refused as JSON, rather than being silently dropped. Numeric widening (`20` vs `20.0`) is not a difference.

### Canonical encoding (commitments)

`prior hash` prints the digest a proof system, audit log or registry commits to. The encoding is one rule applied uniformly: **every number scaled by 10^6 and rounded to an integer, keys sorted, no insignificant whitespace, UTF-8.**

Counts are scaled too — an RSI period of 14 encodes as `14000000` — so a verifier never needs a table of which fields are fractions and which are counts. `10^6` reaches below a basis point, so sizing finer than the language currently expresses will not invalidate commitments already minted. The digest is taken over the compiled IR, so it is identical whether the strategy arrived as `.prior` text or as JSON, and unaffected by comments or formatting.

A value the scale cannot represent exactly is an error rather than a silent rounding.

### Strategy object

Every strategy carries these four:

| key | type | notes |
|---|---|---|
| `version` | string | interchange version, currently `"0.7"`. Not the same as the file's `# prior:` pragma. |
| `name` | string | from the `strategy` statement |
| `universe` | object | see below |
| `timeframe` | string | `1d`, `1h`, `4h`, … Defaults to `1d` when the source omits it. |

The rest depend on the strategy's shape. A single-entry directional strategy carries `direction`, `entry`, `exit`, `position_sizing`, `risk`. Rotation strategies carry `rebalance` and `ranking` instead of `entry`. Options strategies carry `options`. Multi-rule strategies carry `rules` and `exits`. **Consumers should treat every key beyond the four above as optional and branch on presence, not assume a fixed shape.**

### `universe`

Four forms, discriminated by `type`:

```json
{"type": "prebuilt", "key": "mega_tech"}
{"type": "manual",   "tickers": ["BTC-USD"]}
{"type": "dynamic",  "key": "top_volume", "params": {"count": 50, "period": 20}}
{"type": "pair",     "tickers": ["GLD", "GDX"], "form": "ratio"}
```

### `entry`

```json
{"match_logic": "all", "conditions": [ <condition>, ... ]}
```

`match_logic` is `"all"` (from `and`) or `"any"` (from `or`).

### Condition nodes

Every condition is `{"condition": <name>, "params": {…}}`. The name is the resolved registry entry, not the surface tag: `[rsi] > 65` becomes `rsi_greater_than`, `[new_low 20]` becomes `price_new_low`. Params are fully defaulted at compile time, so a consumer never has to know a tag's defaults.

Conditions nest. The windowed sequence operator (§6) carries two of them:

```json
{
  "condition": "sequence",
  "params": {
    "window": 5,
    "first":  {"condition": "price_new_low", "params": {"period": 20}},
    "second": {"condition": "macd_crosses_above_signal",
               "params": {"fast": 12, "slow": 26, "signal": 9}}
  }
}
```

### `exit`

`conditions` is a list of condition nodes; the rest are scalar exits, `null` when unset. Exit precedence within a bar is fixed and documented in §6, not implied by key order here.

```
conditions, stop_loss_pct, profit_target_pct, trailing_stop_pct,
stop_loss_atr, profit_target_atr, trailing_stop_atr,
breakeven_trigger_pct, hold_bars
```

### `position_sizing` and `risk`

```json
{"method": "risk_based", "value": 0.01}
```

`method` is `fixed_dollar`, `percent_of_portfolio`, or `risk_based`. `risk` carries any of `max_positions`, `max_position_pct`, `daily_loss_limit_usd`, `cooldown_bars`, `contracts`.

### Stability

The interchange is versioned with the spec and is pre-1.0, so it moves under the same rule as the language (§10): breaking changes ship with a formatter migration where mechanically possible.

### Validating generated strategies

Two gates, and a pipeline that emits strategies wants both.

`spec/strategy.schema.json` is a JSON Schema (draft 2020-12) covering the structure: required keys, the four universe forms, condition nesting, enumerated values, sign constraints on stops and targets. It runs without importing PRIOR, so a generator can reject a malformed object at the point it is built. It is checked against every file in `examples/` on each release.

It ships in the wheel, so no repo checkout is needed:

```python
import json, jsonschema, prior_lang

jsonschema.Draft202012Validator(prior_lang.load_schema()).validate(obj)
# prior_lang.schema_path() if you want the file itself
```

It is deliberately **not** the language. It cannot tell you a tag exists, that its parameters are right, that kinds match, or that a strategy has the exits it needs. Nothing structural can. For that, `prior validate --stdin --json` returns `{"ok": bool, "errors": [{line, col, message, suggestion}]}` and is the authority.

Schema first for a fast local reject, compiler second for the real answer.
