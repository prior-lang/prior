"""Generate editors/vscode/data/tags.json from the tag registry.

The registry (prior_lang.tags.TAGS) is the machine truth for params and
defaults; DESCRIPTIONS below is the human truth for hovers. A test keeps
both complete: adding a tag without a description fails the suite, so
editor tooling can never lag the language.

Run from python/:  python -m tools.gen_editor_tags
"""

from __future__ import annotations

import json
from pathlib import Path

from prior_lang.tags import TAGS, UNIVERSE_TICKERS

# One-line hover documentation per tag: (description, example).
DESCRIPTIONS: dict[str, tuple[str, str]] = {
    # ── operand conditions ────────────────────────────────────────
    "lower_bollinger": ("The lower Bollinger band — touch it with `at` for mean-reversion entries. NaN warmup handled; `at` fires once on the touch, not every bar below.", "when price at [lower_bollinger 20 2.5]"),
    "middle_bollinger": ("The middle Bollinger band (the moving average of the band pair) — the classic mean-reversion exit target.", "sell when price at [middle_bollinger]"),
    "upper_bollinger": ("The upper Bollinger band — touch it with `at` to fade strength or confirm breakouts.", "when price at [upper_bollinger 20]"),
    "rsi": ("Wilder's RSI, 0–100. Compare with `<` `>` or `crosses above/below` a threshold.", "when [rsi 2] < 10"),
    "sma": ("Simple moving average of closes. Compare price or a faster average against it.", "when price above [sma 200]"),
    "ema": ("Exponential moving average of closes. In crosses, the faster average goes on the left.", "when [ema 50] crosses above [ema 200]"),
    "vwap": ("Rolling volume-weighted average price. Needs volume — unavailable on spreads.", "when price above [vwap 20]"),
    "adx": ("Average Directional Index, 0–100 — trend strength regardless of direction. Above ~25 is trending.", "when [adx] > 25"),
    "stoch": ("Stochastic %K (smoothed), 0–100. Compare or cross a threshold for overbought/oversold timing.", "when [stoch] crosses above 20"),
    "ivrank": ("Implied-volatility rank over the lookback (cloud data). Parses and explains everywhere; evaluation needs hosted chain history.", "when [ivrank] > 50"),
    "short_interest": ("Short interest as % of float (cloud data). Evaluation needs hosted data.", "when [short_interest] > 20"),
    # ── predicate conditions ──────────────────────────────────────
    "macd_cross_up": ("MACD line crosses above its signal line — the classic momentum go signal.", "when [macd_cross_up]"),
    "macd_cross_down": ("MACD line crosses below its signal line.", "sell when [macd_cross_down]"),
    "volume_spike": ("This bar's volume is at least `multiplier`× its rolling average.", "when [volume_spike 2x]"),
    "heavy_volume": ("Volume in the top N% of the lookback window — quieter cousin of a spike.", "when [heavy_volume top 10%]"),
    "volatile": ("Rolling volatility (ATR%) is above the threshold — regime filter for hot tape.", "when [volatile 3%]"),
    "quiet": ("Rolling volatility (ATR%) is below the threshold — regime filter for calm tape.", "when [quiet 1.5%]"),
    "new_high": ("Close is the highest of the lookback (default 252 bars — a 52-week high on dailies).", "when [new_high]"),
    "new_low": ("Close is the lowest of the lookback.", "when [new_low 63]"),
    "gap_up": ("Today opened at least `gap` above yesterday's close.", "when [gap_up 3%]"),
    "gap_down": ("Today opened at least `gap` below yesterday's close.", "when [gap_down 3%]"),
    "up_days": ("The last N bars all closed higher than the bar before.", "when [up_days 3]"),
    "down_days": ("The last N bars all closed lower than the bar before.", "when [down_days 5]"),
    "squeeze": ("Bollinger bandwidth in the tightest `pct`% of the lookback — coiled-spring compression before expansion.", "when [squeeze]"),
    "obv_rising": ("On-balance volume above its own moving average — accumulation confirmation. Needs volume.", "when [obv_rising]"),
    "earnings_within": ("An earnings report falls within N days (cloud calendar data).", "when [earnings_within 7 days]"),
    "no_earnings_within": ("No earnings report within N days — skip the binary-event lottery (cloud calendar data).", "when [no_earnings_within 14 days]"),
    # ── exits ─────────────────────────────────────────────────────
    "stop": ("Stop loss: exit when the position moves against you by a percent or an ATR multiple.", "sell when [stop 2%]  ·  [stop 2 atr]"),
    "target": ("Profit target: exit on a favorable move of a percent or an ATR multiple.", "sell when [target 5%]"),
    "trailing": ("Trailing stop from the high-water mark, percent or ATR multiple.", "sell when [trailing 3%]"),
    "after": ("Time exit: close after N bars, no questions asked.", "sell when [after 10 bars]"),
    "breakeven": ("Once up `trigger`, the stop moves to the entry price — the trade can no longer lose.", "sell when [breakeven after 2%] or [stop 3%]"),
    # ── sizing / risk ─────────────────────────────────────────────
    "risk": ("Risk-based sizing: size the position so the stop distance costs this % of the portfolio. Requires a stop in the exit.", "buy [risk 1%]"),
    "max_positions": ("Cap on simultaneous open positions across the universe.", "risk [max_positions 3]"),
    "max_position": ("Cap any single position at this % of the portfolio.", "risk [max_position 20%]"),
    "daily_loss": ("Halt new entries after losing this many dollars in a day.", "risk [daily_loss $500]"),
    "cooldown": ("After an exit, ignore new entry signals for N bars.", "risk [cooldown 5]"),
    "reverse": ("Stop-and-reverse: an opposite-direction entry signal flips the position instead of standing aside. Needs both long and short rules.", "risk [reverse]"),
    "contracts": ("Options position size: number of contracts per trade.", "risk [contracts 2]"),
    "collateral": ("Options cash-secured-put collateral cap as % of portfolio.", "risk [collateral 30%]"),
    # ── ranking metrics ───────────────────────────────────────────
    "momentum": ("N-bar total return; `skip` recent bars to dodge short-term reversal (12-1 momentum = [momentum 252 skip=21]).", "hold top 5 by [momentum 126]"),
    "volatility": ("Annualized close-to-close volatility — rank `bottom` for low-vol portfolios.", "hold bottom 5 by [volatility 60]"),
    "inverse_volatility": ("1/volatility — as a `weighted by` metric it risk-balances the book.", "weighted by [inverse_volatility]"),
    "relative_strength": ("N-bar return minus the equal-weight universe's N-bar return.", "hold top 3 by [relative_strength 63]"),
    "dollar_volume": ("Average close × volume — a liquidity rank.", "hold top 10 by [dollar_volume]"),
    # ── options ───────────────────────────────────────────────────
    "csp": ("Cash-secured put at ~`delta`, ~`dte` days out.", "write [csp delta=20 dte=30]"),
    "covered_call": ("Covered call against held shares at ~`delta`, ~`dte` days out.", "write [covered_call delta=25 dte=45]"),
    "profit": ("Options management: close at this % of max profit.", "close at [profit 50%]"),
    "loss": ("Options management: close at this % loss of credit received.", "close at [loss 200%]"),
    "dte": ("Options management: act when this many days to expiry remain.", "roll at [dte 21]"),
    # ── universes ─────────────────────────────────────────────────
    "sp_top_30": ("Prebuilt list: the 30 largest S&P names by market cap.", "universe [sp_top_30]"),
    "mega_tech": ("Prebuilt list: 15 mega-cap tech names.", "universe [mega_tech]"),
    "etf_sectors": ("Prebuilt list: the 11 SPDR sector ETFs.", "universe [etf_sectors]"),
    "big_banks": ("Prebuilt list: 10 money-center and super-regional banks.", "universe [big_banks]"),
    "semis": ("Prebuilt list: 14 semiconductor leaders.", "universe [semis]"),
    "crypto_majors": ("Prebuilt list: 8 deepest-liquidity crypto pairs (BTC-USD, ETH-USD, …).", "universe [crypto_majors]"),
    "top_volume": ("Dynamic universe: the N highest trailing-dollar-volume tickers in your data, membership recomputed monthly on closed bars only (no mid-month repaint).", "universe [top_volume 50]"),
}


def build() -> dict:
    tags = []
    missing = []
    for name, spec in sorted(TAGS.items()):
        if "." in name:
            continue  # plugin tags are not core vocabulary
        doc = DESCRIPTIONS.get(name)
        if doc is None:
            missing.append(name)
            continue
        seen_positional = {p.name for p in spec.positional}
        tags.append({
            "name": name,
            "kind": spec.kind,
            "usage": spec.usage,
            "cloudOnly": spec.cloud_only,
            "description": doc[0],
            "example": doc[1],
            "params": [
                {"name": p.name, "kind": p.kind, "default": p.default, "required": p.required}
                for p in spec.positional
            ] + [
                {"name": k, "kind": p.kind, "default": p.default, "required": p.required, "named": True}
                for k, p in spec.named.items() if k not in seen_positional
            ],
        })
    if missing:
        raise SystemExit(
            "tags missing an editor description (add them to DESCRIPTIONS in "
            f"tools/gen_editor_tags.py): {', '.join(missing)}"
        )
    return {
        "tags": tags,
        "universes": {k: v for k, v in UNIVERSE_TICKERS.items()},
    }


def main() -> int:
    out = Path(__file__).resolve().parents[2] / "editors" / "vscode" / "data" / "tags.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {out} ({len(build()['tags'])} tags)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
