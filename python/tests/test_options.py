"""Options slice 1: the wheel, write-rules, management, state machine.

Synthetic chains are used for STATE-MACHINE verification only, never for
return claims (see PRIOR_OPTIONS_DESIGN.md §6).
"""

import math

import pytest

import prior_lang
from prior_lang import strategy_to_source
from prior_lang.codegen import compile_strategy

WHEEL = (
    'strategy "Wheel on Ford"\n'
    "universe $F\n\n"
    "wheel [delta=25 dte=45]\n\n"
    "close at [profit 50%]\n  or [loss 200%]\n\n"
    "roll at [dte 21]\n\n"
    "risk [contracts 1]\n"
)


def test_wheel_json_and_roundtrip():
    s = prior_lang.compile_source(WHEEL)
    o = s["options"]
    assert o["form"] == "wheel"
    assert o["option"] == {"type": "wheel", "delta": 25.0, "dte": 45}
    assert o["management"] == {"profit_pct": 50.0, "loss_pct": 200.0, "roll_dte": 21}
    assert s["risk"] == {"contracts": 1}
    assert prior_lang.compile_source(strategy_to_source(s)) == s


def test_write_rule_with_conditions():
    s = prior_lang.compile_source(
        "universe $F\n"
        "when [rsi] < 40\n  write [csp delta=20 dte=30]\n"
        "close at [profit 50%]\n"
    )
    o = s["options"]
    assert o["form"] == "rules"
    assert o["option"] == {"type": "csp", "delta": 20.0, "dte": 30}
    assert o["entry"]["conditions"][0]["condition"] == "rsi_less_than"
    assert prior_lang.compile_source(strategy_to_source(s)) == s


def test_options_exclude_equity_rules():
    with pytest.raises(prior_lang.PriorError, match="stands alone"):
        prior_lang.compile_source(
            "universe $F\nwheel [delta=25 dte=45]\n"
            "when [rsi] < 30\n  buy [5% portfolio]\nsell when [after 5 bars]\n"
        )


def test_options_single_ticker_only():
    with pytest.raises(prior_lang.PriorError, match="single-ticker"):
        prior_lang.compile_source("universe [big_banks]\nwheel [delta=25 dte=45]\n")


def test_management_requires_options():
    with pytest.raises(prior_lang.PriorError, match="wheel or a write rule"):
        prior_lang.compile_source(
            "universe [sp_top_30]\nwhen [rsi] < 30\n  buy [5% portfolio]\n"
            "sell when [after 5 bars]\nclose at [profit 50%]\n"
        )


def test_write_rejects_non_option_tag():
    with pytest.raises(prior_lang.PriorError, match="option tag"):
        prior_lang.compile_source(
            "universe $F\nwhen [rsi] < 40\n  write [stop 2%]\nclose at [profit 50%]\n"
        )


def test_explain_wheel():
    from prior_lang.explain import explain_strategy
    text = explain_strategy(prior_lang.compile_source(WHEEL))
    assert "Run the wheel" in text
    assert "50% of the credit captured" in text
    assert "roll at 21 DTE" in text


# ── State machine goldens on synthetic chains ──────────────────────

pd = pytest.importorskip("pandas")
import numpy as np  # noqa: E402


def _chains(days, expiries, put_mid):
    """One 25-delta ladder per day; put mids from the callable."""
    rows = []
    for d in days:
        for e in expiries:
            if d > e:
                continue
            for strike, delta in ((9.0, -15), (9.5, -25), (10.0, -40)):
                rows.append({"date": d, "expiry": e, "strike": strike, "right": "P",
                             "delta": delta, "mid": put_mid(d, e, strike)})
            for strike, delta in ((10.5, 25), (11.0, 15)):
                rows.append({"date": d, "expiry": e, "strike": strike, "right": "C",
                             "delta": delta, "mid": 0.30})
    return pd.DataFrame(rows)


def _orders(src, df, chains):
    ns = {"pd": pd, "np": np, "math": math}
    exec(compile_strategy(prior_lang.compile_source(src)), ns)
    return ns["generate_option_orders"](df, chains)


def _flat_df(days, price=10.0):
    c = pd.Series(price, index=days)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1e6})


def test_golden_profit_take_at_half_credit():
    days = pd.date_range("2026-01-05", periods=70, freq="B")
    E1 = days[35]
    def mid(d, e, strike):
        frac = max(0.0, (e - d).days / (e - days[0]).days)
        return round(0.50 * frac * (abs({9.0: -15, 9.5: -25, 10.0: -40}[strike]) / 25), 4)
    orders = _orders(WHEEL, _flat_df(days), _chains(days, [E1], mid))
    assert orders.iloc[0]["action"] == "sell_put"
    assert orders.iloc[0]["strike"] == 9.5          # nearest to 25-delta
    close = orders[orders["action"] == "close"].iloc[0]
    assert close["price"] <= 0.50 * 0.5 + 1e-9      # at or through half credit


def test_golden_assignment_then_covered_call():
    # Put held to expiry with the stock UNDER the strike → assigned; the
    # wheel then sells a call; price rises through the call strike at its
    # expiry → called away, back to cash.
    days = pd.date_range("2026-01-05", periods=80, freq="B")
    E1, E2 = days[30], days[75]
    src = (
        "universe $F\n\nwheel [delta=25 dte=20]\n"   # no profit mgmt: ride to expiry
    )
    closes = pd.Series(9.0, index=days)              # below the 9.5 put strike
    closes[days > E1] = 11.0                          # then above the 10.5 call strike
    df = pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1e6})
    orders = _orders(src, df, _chains(days, [E1, E2], lambda d, e, s: 0.4))
    acts = list(orders["action"])
    assert "sell_put" in acts
    assert "assigned" in acts
    i_assigned = acts.index("assigned")
    assert "sell_call" in acts[i_assigned:]
    assert "called_away" in acts[i_assigned:]


def test_golden_roll_at_dte():
    days = pd.date_range("2026-01-05", periods=60, freq="B")
    E1, E2 = days[30], days[59]
    src = "universe $F\n\nwheel [delta=25 dte=20]\n\nroll at [dte 10]\n"
    orders = _orders(src, _flat_df(days), _chains(days, [E1, E2], lambda d, e, s: 0.4))
    acts = list(orders["action"])
    assert "roll_close" in acts and "roll_open" in acts
    ro = orders[orders["action"] == "roll_open"].iloc[0]
    assert ro["expiry"] == E2                        # rolled out to the far expiry


def test_cli_backtest_guard(tmp_path, capsys):
    from prior_lang.cli import main
    f = tmp_path / "wheel.prior"
    f.write_text(WHEEL)
    data = tmp_path / "bars.csv"
    data.write_text("date,close\n2026-01-05,10\n")
    with pytest.raises(SystemExit) as e:
        main(["backtest", str(f), "--data", str(data)])
    assert "chain data" in str(e.value)


# ── jade lizard ──────────────────────────────────────────────────

JADE = '''strategy "Jade"

universe $SPY

when [ivrank] > 40
  write [jade_lizard delta=25 width=5 dte=45]

close at [profit 50%]
  or [dte 21]

risk [contracts 1]
'''


def test_jade_lizard_compiles_and_round_trips():
    from prior_lang import compile_source, strategy_to_source
    st = compile_source(JADE)
    assert compile_source(strategy_to_source(st)) == st


def test_jade_lizard_builds_three_legs_not_four():
    """An iron condor without the put wing. The missing wing is the whole
    point: it is what leaves the downside naked and the credit larger."""
    from prior_lang.codegen import _structure_build_snippet
    body = _structure_build_snippet("jade_lizard", 25, 5, 45)
    assert body.count('side="short"') == 2      # short put, short call
    assert body.count('side="long"') == 1       # the call wing only
    assert '"P", 25' in body and '"C", 25' in body


def test_jade_lizard_is_undefined_risk():
    """Collateral is unbounded below because the put is naked, so it must
    report like a strangle rather than like a condor. Falling through to
    a finite requirement would produce percent returns off a base that
    does not exist."""
    from prior_lang.options_backtest import _requirement
    legs = [
        {"side": "short", "right": "P", "strike": 400.0},
        {"side": "short", "right": "C", "strike": 460.0},
        {"side": "long", "right": "C", "strike": 465.0},
    ]
    assert _requirement(legs, entry_px=430.0, mult=100) is None


def test_jade_lizard_width_must_be_positive():
    from prior_lang import compile_source
    from prior_lang.errors import PriorError
    import pytest as _pytest
    with _pytest.raises(PriorError):
        compile_source(JADE.replace("width=5", "width=0"))


def test_jade_lizard_explains_its_asymmetry():
    """The reason to use this structure is that the upside risk vanishes
    once the credit covers the width. If explain does not say that, the
    readback is not describing the trade."""
    from prior_lang import compile_source
    from prior_lang.explain import explain_strategy
    text = explain_strategy(compile_source(JADE)).lower()
    assert "upside" in text
    assert "naked put" in text or "undefined" in text
