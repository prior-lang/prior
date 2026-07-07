"""Options slice 3b: multi-leg order emission for credit structures.

Synthetic chains: flat spot at 100, one expiry, strikes 80..120 step 5,
|delta| approximated linearly from moneyness, time value decaying to 0
at expiry — enough structure for deterministic leg selection and a
profit-take to trigger.
"""

import math

import pytest

import prior_lang
from prior_lang.codegen import compile_strategy

pd = pytest.importorskip("pandas")
import numpy as np  # noqa: E402


def _chains(days, expiry):
    rows = []
    for d in days:
        dte = (expiry - d).days
        if dte < 0:
            continue
        for strike in range(80, 121, 5):
            for right in ("P", "C"):
                if right == "P":
                    delta = max(1.0, min(99.0, 50.0 - (100 - strike) * 2.5))
                    intrinsic = max(0.0, strike - 100.0)
                else:
                    delta = max(1.0, min(99.0, 50.0 - (strike - 100) * 2.5))
                    intrinsic = max(0.0, 100.0 - strike)
                tv = 0.02 * delta * (dte / 40.0)
                rows.append({"date": d, "expiry": expiry, "strike": float(strike),
                             "right": right, "delta": delta, "mid": round(intrinsic + tv, 4)})
    return pd.DataFrame(rows)


def _run(tag, mgmt="close at [profit 50%]"):
    src = f"universe $SPY\nwhen price above 1\n  write [{tag}]\n{mgmt}\n"
    strategy = prior_lang.compile_source(src)
    ns = {"pd": pd, "np": np, "math": math}
    exec(compile_strategy(strategy), ns)
    days = pd.date_range("2026-01-05", periods=45, freq="D")
    df = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0,
                       "close": 100.0, "volume": 0}, index=days)
    return ns["generate_option_orders"](df, _chains(days, days[40]))


def test_put_spread_legs_and_profit_take():
    orders = _run("put_spread delta=25 width=5 dte=30")
    opens = orders[orders["action"] == "open"]
    assert len(opens) == 2
    short = opens[opens["side"] == "short"].iloc[0]
    long_ = opens[opens["side"] == "long"].iloc[0]
    assert short["right"] == "P" and long_["right"] == "P"
    assert short["strike"] - long_["strike"] == 5.0  # the width
    assert short["price"] > long_["price"]            # net credit positive
    closes = orders[orders["action"] == "close"]
    assert len(closes) == 2                            # profit take, both legs
    net_open = short["price"] - long_["price"]
    net_close = (closes[closes["side"] == "short"].iloc[0]["price"]
                 - closes[closes["side"] == "long"].iloc[0]["price"])
    assert net_close <= net_open * 0.5 + 1e-9          # the 50% target


def test_call_spread_wing_above():
    orders = _run("call_spread delta=25 width=10 dte=30")
    opens = orders[orders["action"] == "open"]
    short = opens[opens["side"] == "short"].iloc[0]
    long_ = opens[opens["side"] == "long"].iloc[0]
    assert short["right"] == "C" and long_["right"] == "C"
    assert long_["strike"] - short["strike"] == 10.0


def test_iron_condor_four_legs_one_expiry():
    orders = _run("iron_condor delta=20 width=5 dte=30")
    opens = orders[orders["action"] == "open"]
    assert len(opens) == 4
    assert sorted(opens["side"]) == ["long", "long", "short", "short"]
    assert set(opens["right"]) == {"P", "C"}
    assert opens["expiry"].nunique() == 1
    puts = opens[opens["right"] == "P"]
    calls = opens[opens["right"] == "C"]
    assert puts[puts["side"] == "short"].iloc[0]["strike"] > puts[puts["side"] == "long"].iloc[0]["strike"]
    assert calls[calls["side"] == "short"].iloc[0]["strike"] < calls[calls["side"] == "long"].iloc[0]["strike"]


def test_straddle_same_strike_strangle_apart():
    st = _run("straddle dte=30")
    st_opens = st[st["action"] == "open"]
    assert len(st_opens) == 2
    assert st_opens["strike"].nunique() == 1           # same strike
    assert set(st_opens["right"]) == {"P", "C"}
    assert set(st_opens["side"]) == {"short"}          # both legs short

    sg = _run("strangle delta=20 dte=30")
    sg_opens = sg[sg["action"] == "open"]
    assert sg_opens["strike"].nunique() == 2           # strikes apart
    assert set(sg_opens["side"]) == {"short"}


def test_settlement_when_never_managed():
    orders = _run("put_spread delta=25 width=5 dte=30", mgmt="close at [loss 900%]")
    assert "settle" in set(orders["action"])           # ran to expiry, cash-settled
    settles = orders[orders["action"] == "settle"]
    assert (settles["price"] == 0.0).all()             # flat at 100: both puts OTM
