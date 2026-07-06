# PRIOR Language Specification — v0.3 (draft)

**PRIOR** — Portable Rules for Indicators, Orders & Risk. A declarative language for expressing trading strategies as testable hypotheses. This spec is the source of truth for the parser, formatter, and compiler. Pre-1.0, breakable with notice.

Status: draft. v0.3 (2026-07-06) adds the vocabulary sweep (new highs/lows, gaps, streaks, price levels, ADX, stochastic, VWAP, squeeze, OBV) and richer exits (ATR-unit stops/targets, chandelier trailing, breakeven). v0.2 (2026-07-06) added short strategies. v0.1 drafted 2026-07-05. Companion documents: `TAGS.md` (tag reference), `../examples/*.prior` (the executable spec — every example must parse, format canonically, and compile).

---

## 1. Design invariants

These are not stylistic preferences. Violating any of them is a spec bug.

1. **Not Turing-complete.** No variables, loops, user-defined functions, imports, or arithmetic on tag values. When the language feels too small, the answer is a new tag, not new syntax.
2. **No expressible lookahead.** There is no token, tag, or construct that references a future bar. This is a property of the vocabulary, enforced by construction.
3. **Tags are semantic macros.** A tag bundles indicator defaults, tolerance/touch semantics, NaN-warmup policy, and edge-trigger behavior. Tag semantics are defined once (in the scanner condition registry) and never forked.
4. **Compile-time is the only error time.** A `.prior` file that compiles, runs. All validation — unknown tags, bad params, kind mismatches, missing exits — happens at compile with line-precise messages.
5. **Round-trip stability.** parse → JSON → format must reproduce the canonical form of the input exactly. The JSON interchange (the AutoQuant strategy format, `STRATEGY_FORMAT_PLAN.md` in the AutoQuant repo) is the AST.

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
| TAGNAME / WORD | `[a-z_][a-z0-9_]*` | `lower_bollinger`, `top` | dotted names (`acme.momo_score`) are reserved for namespaced third-party tags in a future version; v0.1 rejects them with a "coming later" error |

### Keywords

`strategy` `universe` `timeframe` `when` `if` `buy` `short` `sell` `cover` `risk` `and` `or` `at` `above` `below` `crosses` `price` `volume`

Reserved for future versions: `on` (multi-timeframe).

---

## 3. Grammar (EBNF)

```ebnf
program        = { line } ;
line           = [ statement ] , [ comment ] , NEWLINE ;

statement      = strategy_stmt | universe_stmt | timeframe_stmt
               | entry_stmt | exit_stmt | risk_stmt ;

strategy_stmt  = "strategy" , STRING ;
universe_stmt  = "universe" , ( tag | TICKER , { TICKER } ) ;
timeframe_stmt = "timeframe" , TIMEFRAME ;

entry_stmt     = ( "when" | "if" ) , expr , action ;
action         = ( "buy" | "short" ) , tag ;        (* sizing tag, required *)

exit_stmt      = ( "sell" | "cover" ) , [ "when" ] , expr ;

risk_stmt      = "risk" , tag , { tag } ;

expr           = and_expr , { "or" , and_expr } ;
and_expr       = term , { "and" , term } ;
term           = comparison | tag | "(" , expr , ")" ;
comparison     = operand , comparator , operand ;
comparator     = "at" | "above" | "below"
               | "crosses" , ( "above" | "below" )
               | "<" | ">" | "<=" | ">=" ;
operand        = "price" | "volume" | tag | NUMBER | PERCENT | TICKER ;

tag            = "[" , tag_body , "]" ;
tag_body       = TAGNAME , { tag_arg }        (* [lower_bollinger std=1], [stop 1.5%] *)
               | PERCENT , "portfolio"        (* [5% portfolio] — sizing special form *)
               | DOLLAR ;                     (* [$10000] — sizing special form *)
tag_arg        = tag_value | TAGNAME , "=" , tag_value ;
tag_value      = NUMBER | PERCENT | DOLLAR | MULTIPLIER | WORD ;
```

The two sizing special forms exist because `buy [5% portfolio]` and `buy [$10000]` read the way traders talk; they are the only tags whose body doesn't start with a name. `[risk 1%]` uses the normal name-first form.

Precedence: `and` binds tighter than `or`. Parentheses override.

The grammar is deliberately permissive; **kind checking** (section 5) rejects nonsense like `buy [stop 1.5%]` or `risk [rsi]` with targeted messages. This keeps parse errors rare and semantic errors specific.

---

## 4. Statements

A v0.1 program has at most one of each: `strategy`, `universe`, `timeframe`, entry (`when`), exit (`sell`), `risk`. A second entry or exit statement is a compile error ("multiple entry rules are coming in v1.1"). Statement order is free; `prior fmt` canonicalizes to the order above.

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

An inline `$TICKER` operand scopes the whole strategy to that instrument, and `price`/`volume` refer to it. v0.1 restriction: a program uses **either** a `universe` statement with universe-wide rules, **or** inline single-ticker scoping — mixing the two is a compile error ("per-ticker overrides inside a universe are coming in a later version"). All inline tickers in one program must be the same symbol in v0.1.

---

## 5. Kinds

Every tag has exactly one kind. The kind table lives in `TAGS.md` and is machine-derived from the registry mapping.

| Kind | Where legal | Examples |
|---|---|---|
| `condition` | entry expr, exit expr | `[lower_bollinger]`, `[rsi]`, `[macd_cross_up]` |
| `sizing` | after `buy`, exactly one | `[5% portfolio]`, `[$10000]`, `[risk 1%]` |
| `exit` | exit expr, `or`-combined | `[stop 1.5%]`, `[after 5 bars]` |
| `risk` | `risk` statement | `[max_positions 5]`, `[daily_loss $500]` |
| `universe` | `universe` statement | `[sp_top_30]`, `[semis]` |

Kind-check errors name both the tag's kind and the expected kind: *"line 7: [stop 1.5%] is an exit tag; the entry rule takes condition tags. Did you mean to put it in the sell rule?"*

Cross-statement checks:
- `buy [risk N%]` **requires** a `[stop]` tag in the exit. Missing stop = compile error: *"risk-based sizing needs a stop to size against; add [stop x%] to the sell rule."* No synthetic fallback.
- `[trailing]` and `[stop]` may coexist (trailing tightens, stop is the floor). Two `[stop]` tags = error.

---

## 6. Evaluation semantics

- **Direction.** A strategy is long (`buy` … `sell`) or short (`short` … `cover`), one direction per strategy in v0.2; the pairing is enforced (`buy` with `cover` is a compile error that teaches the vocabulary). Short signals are 0/-1. Exit tags are direction-relative: a short's `[stop]` sits above entry, its `[target]` below, and `[trailing]` trails the low-water mark. Condition tags are direction-neutral predicates and never change meaning.
- **Bar-close evaluation.** All conditions are evaluated on completed bars. There is no intrabar evaluation in v0.1 backtests. (Live/paper runners may place broker-side bracket orders for stops/targets that fill intrabar; this backtest-vs-live divergence is documented behavior, not a bug — backtests are conservative.)
- **Edge-triggered entry.** The entry fires on the bar where the combined condition transitions false→true, matching the scanner/codegen pattern (`entries = cond & ~cond.shift(1)`). A condition that stays true for 10 bars produces one entry, not ten.
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

## 9. Registry gaps found while drafting (feed into Phase B)

The vocabulary maps 1:1 onto the AutoQuant scanner condition registry (`engine/scanner/conditions.py` in the AutoQuant repo, 16 conditions in production). Writing the examples surfaced gaps to fill in Phase B — additions to the registry, used by both scanner and PRIOR:

1. `ema_crosses_below` — registry has `ema_crosses_above` only. Needed for symmetric MA-cross exits (death cross).
2. `sma_crosses_above` / `sma_crosses_below` — classic golden cross is SMA 50/200; registry only crosses EMAs today.
3. Middle-band tolerance (0.5%) is hardcoded in `price_at_bollinger_band` — consider exposing as an optional param (`[middle_bollinger tol=0.5%]`) but keep the default.

Until these land, `[ema N] crosses below [ema M]` and SMA crosses are compile errors with the message "not yet supported by the condition registry (planned)".

---

## 10. Versioning

The spec carries a version (`v0.1`). A `.prior` file may optionally declare `# prior: 0.1` as its first comment line; absent, the compiler assumes its own version. Pre-1.0: breaking changes allowed with a formatter migration (`prior fmt --upgrade`) whenever mechanically possible. Post-1.0: the LEAN/Terraform bar — files keep compiling.
