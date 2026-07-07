"""The tag registry — the machine-readable mirror of spec/TAGS.md.

Each tag surface name maps to its kind, its parameter schema, and (for
condition tags) how it desugars into a registry condition. The parser
validates tag arguments against this table and the formatter uses it to
print canonical forms, so spec/TAGS.md and this file must move together.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Value kinds produced by the lexer for tag arguments.
NUMBER = "number"
PERCENT = "percent"
DOLLAR = "dollar"
MULT = "mult"
WORD = "word"


@dataclass
class Param:
    name: str
    kind: str
    default: object = None
    required: bool = False


@dataclass
class TagSpec:
    name: str
    kind: str  # condition | sizing | exit | risk | universe | metric | option | management
    usage: str  # operand | predicate | n/a
    positional: list[Param] = field(default_factory=list)
    named: dict[str, Param] = field(default_factory=dict)
    cloud_only: bool = False   # parses/explains everywhere; evaluates only on hosted data


def _p(name, kind, default=None, required=False):
    return Param(name=name, kind=kind, default=default, required=required)


UNIVERSE_KEYS = ["sp_top_30", "mega_tech", "etf_sectors", "big_banks", "semis", "crypto_majors"]

# Dynamic universes: membership computed from data at run time instead of
# a fixed list. No-lookahead law: membership recomputes on the first bar
# of each month from trailing average dollar volume as of the PRIOR bar,
# and holds until the next recompute.
DYNAMIC_UNIVERSE_KEYS = {"top_volume"}

# Prebuilt universe contents, mirroring the reference runner's lists (and
# the table in spec/TAGS.md — the three must move together). Used by the
# local backtester to filter multi-ticker data files.
UNIVERSE_TICKERS: dict[str, list[str]] = {
    "sp_top_30": [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "ORCL",
        "LLY", "AVGO", "JPM", "V", "UNH", "XOM", "MA", "JNJ", "PG", "HD",
        "COST", "ABBV", "MRK", "WMT", "NFLX", "CRM", "ADBE", "KO", "PEP",
        "BAC", "TMO", "CSCO",
    ],
    "mega_tech": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO",
        "ORCL", "CRM", "ADBE", "NFLX", "AMD", "INTC", "QCOM",
    ],
    "etf_sectors": [
        "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLB", "XLRE",
        "XLU", "XLC",
    ],
    "big_banks": [
        "JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "TFC", "SCHW",
    ],
    "semis": [
        "NVDA", "AVGO", "AMD", "QCOM", "TXN", "INTC", "MU", "AMAT", "LRCX",
        "KLAC", "MRVL", "ADI", "NXPI", "MCHP",
    ],
    "crypto_majors": [
        "BTC-USD", "ETH-USD", "SOL-USD", "DOGE-USD", "AVAX-USD", "LINK-USD",
        "LTC-USD", "BCH-USD",
    ],
}


TAGS: dict[str, TagSpec] = {}


def _register(spec: TagSpec):
    TAGS[spec.name] = spec


# ── Condition tags ─────────────────────────────────────────────────

for band in ("lower", "middle", "upper"):
    _register(TagSpec(
        name=f"{band}_bollinger",
        kind="condition",
        usage="operand",
        positional=[_p("period", NUMBER, 20), _p("std", NUMBER, 2.0)],
        named={"period": _p("period", NUMBER, 20), "std": _p("std", NUMBER, 2.0)},
    ))

_register(TagSpec(
    name="rsi", kind="condition", usage="operand",
    positional=[_p("period", NUMBER, 14)],
    named={"period": _p("period", NUMBER, 14)},
))

for ma in ("sma", "ema"):
    _register(TagSpec(
        name=ma, kind="condition", usage="operand",
        positional=[_p("period", NUMBER, required=True)],
        named={},
    ))

for direction in ("up", "down"):
    _register(TagSpec(
        name=f"macd_cross_{direction}", kind="condition", usage="predicate",
        positional=[_p("fast", NUMBER, 12), _p("slow", NUMBER, 26), _p("signal", NUMBER, 9)],
        named={k: _p(k, NUMBER, d) for k, d in (("fast", 12), ("slow", 26), ("signal", 9))},
    ))

_register(TagSpec(
    name="volatile", kind="condition", usage="predicate",
    positional=[_p("threshold", PERCENT, required=True)],
    named={"period": _p("period", NUMBER, 14)},
))
_register(TagSpec(
    name="quiet", kind="condition", usage="predicate",
    positional=[_p("threshold", PERCENT, required=True)],
    named={"period": _p("period", NUMBER, 14)},
))
_register(TagSpec(
    name="volume_spike", kind="condition", usage="predicate",
    positional=[_p("multiplier", MULT, 1.5)],
    named={"period": _p("period", NUMBER, 20)},
))
_register(TagSpec(
    name="heavy_volume", kind="condition", usage="predicate",
    positional=[_p("top", WORD, "top"), _p("top_pct", PERCENT, 10.0)],
    named={"period": _p("period", NUMBER, 60)},
))

_register(TagSpec(
    name="new_high", kind="condition", usage="predicate",
    positional=[_p("period", NUMBER, 252)],
    named={"period": _p("period", NUMBER, 252)},
))
_register(TagSpec(
    name="new_low", kind="condition", usage="predicate",
    positional=[_p("period", NUMBER, 252)],
    named={"period": _p("period", NUMBER, 252)},
))
_register(TagSpec(
    name="gap_up", kind="condition", usage="predicate",
    positional=[_p("gap", PERCENT, 2.0)],
))
_register(TagSpec(
    name="gap_down", kind="condition", usage="predicate",
    positional=[_p("gap", PERCENT, 2.0)],
))
_register(TagSpec(
    name="up_days", kind="condition", usage="predicate",
    positional=[_p("count", NUMBER, required=True)],
))
_register(TagSpec(
    name="down_days", kind="condition", usage="predicate",
    positional=[_p("count", NUMBER, required=True)],
))
_register(TagSpec(
    name="vwap", kind="condition", usage="operand",
    positional=[_p("period", NUMBER, 20)],
    named={"period": _p("period", NUMBER, 20)},
))
_register(TagSpec(
    name="squeeze", kind="condition", usage="predicate",
    positional=[_p("lookback", NUMBER, 126)],
    named={"pct": _p("pct", NUMBER, 10.0), "period": _p("period", NUMBER, 20), "std": _p("std", NUMBER, 2.0)},
))
_register(TagSpec(
    name="obv_rising", kind="condition", usage="predicate",
    positional=[_p("period", NUMBER, 20)],
))
_register(TagSpec(
    name="adx", kind="condition", usage="operand",
    positional=[_p("period", NUMBER, 14)],
    named={"period": _p("period", NUMBER, 14)},
))
_register(TagSpec(
    name="stoch", kind="condition", usage="operand",
    positional=[_p("period", NUMBER, 14)],
    named={"period": _p("period", NUMBER, 14), "smooth": _p("smooth", NUMBER, 3)},
))

# ── Cloud-only condition tags ──────────────────────────────────────
# These parse, validate, format, and explain everywhere. Evaluation needs
# data that only exists hosted (chain history, earnings calendars, short
# interest), so local compilation refuses with a pointer to --cloud.

_register(TagSpec(
    name="ivrank", kind="condition", usage="operand",
    named={"lookback": _p("lookback", NUMBER, 252)},
    cloud_only=True,
))
_register(TagSpec(
    name="short_interest", kind="condition", usage="operand",
    cloud_only=True,
))
_register(TagSpec(
    name="earnings_within", kind="condition", usage="predicate",
    positional=[_p("days", NUMBER, required=True), _p("unit", WORD, "days")],
    cloud_only=True,
))
_register(TagSpec(
    name="no_earnings_within", kind="condition", usage="predicate",
    positional=[_p("days", NUMBER, required=True), _p("unit", WORD, "days")],
    cloud_only=True,
))

CLOUD_ONLY_CONDITIONS = {
    "iv_rank_less_than", "iv_rank_greater_than",
    "short_interest_less_than", "short_interest_greater_than",
    "earnings_within", "no_earnings_within",
}

# ── Metric tags (rank/weight metrics for hold strategies) ─────────

_register(TagSpec(
    name="momentum", kind="metric", usage="n/a",
    positional=[_p("period", NUMBER, required=True)],
    named={"skip": _p("skip", NUMBER, 0)},
))
_register(TagSpec(
    name="volatility", kind="metric", usage="n/a",
    positional=[_p("period", NUMBER, 20)],
))
_register(TagSpec(
    name="inverse_volatility", kind="metric", usage="n/a",
    positional=[_p("period", NUMBER, 20)],
))
_register(TagSpec(
    name="relative_strength", kind="metric", usage="n/a",
    positional=[_p("period", NUMBER, 63)],
))
_register(TagSpec(
    name="dollar_volume", kind="metric", usage="n/a",
    positional=[_p("period", NUMBER, 20)],
))

# ── Option tags (write [csp ...] / write [covered_call ...]) ───────

_register(TagSpec(
    name="csp", kind="option", usage="n/a",
    named={"delta": _p("delta", NUMBER, 25), "dte": _p("dte", NUMBER, 45)},
))
_register(TagSpec(
    name="covered_call", kind="option", usage="n/a",
    named={"delta": _p("delta", NUMBER, 25), "dte": _p("dte", NUMBER, 45)},
))

# Multi-leg credit structures (options slice 3). Structures are always
# tags, never spread() — locked 2026-07-07 so option verticals can never
# collide with the pairs operand. width = wing distance in strike points.
_register(TagSpec(
    name="put_spread", kind="option", usage="n/a",
    named={"delta": _p("delta", NUMBER, 25), "width": _p("width", NUMBER, 5),
           "dte": _p("dte", NUMBER, 45)},
))
_register(TagSpec(
    name="call_spread", kind="option", usage="n/a",
    named={"delta": _p("delta", NUMBER, 25), "width": _p("width", NUMBER, 5),
           "dte": _p("dte", NUMBER, 45)},
))
_register(TagSpec(
    name="iron_condor", kind="option", usage="n/a",
    named={"delta": _p("delta", NUMBER, 20), "width": _p("width", NUMBER, 5),
           "dte": _p("dte", NUMBER, 45)},
))
_register(TagSpec(
    name="straddle", kind="option", usage="n/a",
    named={"dte": _p("dte", NUMBER, 45)},
))
_register(TagSpec(
    name="strangle", kind="option", usage="n/a",
    named={"delta": _p("delta", NUMBER, 20), "dte": _p("dte", NUMBER, 45)},
))

# ── Management tags (close at ... / roll at ...) ───────────────────

_register(TagSpec(
    name="profit", kind="management", usage="n/a",
    positional=[_p("value", PERCENT, required=True)],
))
_register(TagSpec(
    name="loss", kind="management", usage="n/a",
    positional=[_p("value", PERCENT, required=True)],
))
_register(TagSpec(
    name="dte", kind="management", usage="n/a",
    positional=[_p("days", NUMBER, required=True)],
))

# ── Sizing tags (name-first form; the two special forms are handled
#    directly by the parser: [N% portfolio] and [$N]) ────────────────

_register(TagSpec(
    name="risk", kind="sizing", usage="n/a",
    positional=[_p("value", PERCENT, required=True)],
))

# ── Exit tags ──────────────────────────────────────────────────────

for name in ("stop", "target", "trailing"):
    _register(TagSpec(
        name=name, kind="exit", usage="n/a",
        positional=[_p("value", PERCENT, required=True)],
    ))
_register(TagSpec(
    name="after", kind="exit", usage="n/a",
    positional=[_p("bars", NUMBER, required=True), _p("unit", WORD, "bars")],
))
_register(TagSpec(
    name="breakeven", kind="exit", usage="n/a",
    positional=[_p("word", WORD, "after"), _p("trigger", PERCENT, required=True)],
))

# ── Risk tags ──────────────────────────────────────────────────────

_register(TagSpec(
    name="max_positions", kind="risk", usage="n/a",
    positional=[_p("value", NUMBER, required=True)],
))
_register(TagSpec(
    name="max_position", kind="risk", usage="n/a",
    positional=[_p("value", PERCENT, required=True)],
))
_register(TagSpec(
    name="daily_loss", kind="risk", usage="n/a",
    positional=[_p("value", DOLLAR, required=True)],
))
_register(TagSpec(
    name="cooldown", kind="risk", usage="n/a",
    positional=[_p("bars", NUMBER, required=True)],
))
_register(TagSpec(
    name="contracts", kind="risk", usage="n/a",
    positional=[_p("count", NUMBER, required=True)],
))
_register(TagSpec(
    name="collateral", kind="risk", usage="n/a",
    positional=[_p("value", PERCENT, required=True)],
))
_register(TagSpec(
    name="reverse", kind="risk", usage="n/a",
))

# ── Universe tags ──────────────────────────────────────────────────

for key in UNIVERSE_KEYS:
    _register(TagSpec(name=key, kind="universe", usage="n/a"))

_register(TagSpec(
    name="top_volume", kind="universe", usage="n/a",
    positional=[_p("count", NUMBER, required=True)],
    named={"period": _p("period", NUMBER, 20)},
))


def names_of_kind(kind: str) -> list[str]:
    return sorted(n for n, s in TAGS.items() if s.kind == kind)
