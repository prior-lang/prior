"""PRIOR Cloud client tests — HTTP layer mocked, no network."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from prior_lang import cloud
from prior_lang.cli import main

EXAMPLES = Path(__file__).parents[2] / "examples"
BOLLINGER = str(EXAMPLES / "bollinger_reversal.prior")


@pytest.fixture(autouse=True)
def temp_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud, "CRED_PATH", tmp_path / "credentials.json")


def _fake_http(responses):
    """Build an _http replacement serving canned responses keyed by (method, path prefix)."""
    calls = []

    def fake(method, path, payload=None, token=None):
        calls.append({"method": method, "path": path, "payload": payload, "token": token})
        for (m, prefix), resp in responses.items():
            if m == method and path.startswith(prefix):
                if isinstance(resp, cloud.CloudError):
                    raise resp
                return resp
        raise AssertionError(f"unexpected request {method} {path}")

    fake.calls = calls
    return fake


# ── Credentials ───────────────────────────────────────────────────

def test_save_load_clear_credentials():
    assert cloud.load_credentials() is None
    cloud.save_credentials({"token": "t1", "email": "a@b.co"})
    assert cloud.load_credentials()["token"] == "t1"
    assert oct(cloud.CRED_PATH.stat().st_mode)[-3:] == "600"
    assert cloud.clear_credentials() is True
    assert cloud.load_credentials() is None


def test_require_token_without_login_exits():
    with pytest.raises(SystemExit, match="prior login"):
        cloud.require_token()


def test_verify_code_saves_credentials():
    fake = _fake_http({("POST", "/prior/auth/verify"): {
        "token": "tok123", "email": "a@b.co", "expires_at": "2026-08-01",
        "plan": "expired", "quota": {"tier": "taster", "remaining": 3},
    }})
    with patch.object(cloud, "_http", fake):
        cloud.verify_code("a@b.co", "123456")
    assert cloud.load_credentials()["token"] == "tok123"


# ── CLI: login ────────────────────────────────────────────────────

def test_login_flow(capsys, monkeypatch):
    fake = _fake_http({
        ("POST", "/prior/auth/request-code"): {"status": "ok"},
        ("POST", "/prior/auth/verify"): {
            "token": "tok9", "email": "cli@x.co", "expires_at": "2026-08-01",
            "plan": "expired", "quota": {"tier": "taster", "remaining": 3},
        },
    })
    monkeypatch.setattr("builtins.input", lambda prompt="": "123456")
    with patch.object(cloud, "_http", fake):
        assert main(["login", "cli@x.co"]) == 0
    out = capsys.readouterr().out
    assert "3 free cloud runs" in out
    assert cloud.load_credentials()["token"] == "tok9"


# ── CLI: cloud status / logout ────────────────────────────────────

def test_cloud_status_taster(capsys):
    cloud.save_credentials({"token": "t", "email": "a@b.co"})
    fake = _fake_http({("GET", "/prior/quota"): {
        "plan": "expired", "tier": "taster",
        "lifetime_limit": 3, "lifetime_used": 1, "remaining": 2,
    }})
    with patch.object(cloud, "_http", fake):
        assert main(["cloud", "status"]) == 0
    out = capsys.readouterr().out
    assert "1 used" in out and "2 left" in out


def test_cloud_logout(capsys):
    cloud.save_credentials({"token": "t"})
    assert main(["cloud", "logout"]) == 0
    assert cloud.load_credentials() is None


# ── CLI: backtest --cloud ─────────────────────────────────────────

SINGLE_RESULT = {
    "kind": "single",
    "metrics": {
        "total_return_pct": 12.3, "buy_hold_return_pct": 8.0, "cagr_pct": 5.5,
        "sharpe": 0.91, "volatility_pct": 14.2, "max_drawdown_pct": -9.1,
        "trades": 21, "win_rate_pct": 62.0, "avg_trade_pct": 0.55, "bars": 2500,
    },
    "equity": [["2016-01-04", 1.0], ["2026-07-01", 1.123]],
    "trades": [{
        "entry_date": "2024-01-05", "exit_date": "2024-01-12", "direction": "long",
        "entry_price": 100.0, "exit_price": 103.2, "bars_held": 5,
        "return_pct": 3.2, "exit_reason": "middle_bollinger",
    }],
    "trades_truncated": 0,
    "meta": {"tickers": ["NVDA"], "missing_tickers": [], "timeframe": "1d",
             "data_start": "2016-01-04", "data_end": "2026-07-01"},
}


def test_backtest_cloud_end_to_end(capsys):
    cloud.save_credentials({"token": "t", "email": "a@b.co"})
    fake = _fake_http({
        ("POST", "/prior/backtest"): {"status": "queued", "run_id": 7,
                                      "quota": {"tier": "taster", "remaining": 2}},
        ("GET", "/prior/runs/7"): {"run_id": 7, "status": "done", "result": SINGLE_RESULT},
    })
    with patch.object(cloud, "_http", fake):
        assert main(["backtest", BOLLINGER, "--cloud", "--trades"]) == 0
    out = capsys.readouterr().out
    assert "run 7 submitted (2 runs left)" in out
    assert "cloud history (2016-01-04 to 2026-07-01)" in out
    assert "Total return" in out and "12.3%" in out
    assert "middle_bollinger" in out  # the trade row

    # The submission sent raw source + the strategy's own timeframe
    submit = next(c for c in fake.calls if c["path"] == "/prior/backtest")
    assert "lower_bollinger" in submit["payload"]["source"]
    assert submit["payload"]["params"]["timeframe"] == "1d"


def test_backtest_cloud_requires_login(capsys):
    with pytest.raises(SystemExit, match="prior login"):
        main(["backtest", BOLLINGER, "--cloud"])


def test_backtest_cloud_taster_exhausted(capsys):
    cloud.save_credentials({"token": "t"})
    # Mirrors the real server message, which carries the upgrade command + URL
    err = cloud.CloudError(
        "You've used your free cloud runs. PRIOR Cloud is $19/mo for 50 "
        "full-history runs a day — run `prior cloud upgrade` or visit "
        "https://autoquant.ai/prior/cloud",
        {"error": "taster_runs_exhausted"}, 402,
    )
    fake = _fake_http({("POST", "/prior/backtest"): err})
    with patch.object(cloud, "_http", fake):
        assert main(["backtest", BOLLINGER, "--cloud"]) == 1
    out = capsys.readouterr().out
    assert "prior cloud upgrade" in out


def test_backtest_cloud_run_error(capsys):
    cloud.save_credentials({"token": "t"})
    fake = _fake_http({
        ("POST", "/prior/backtest"): {"status": "queued", "run_id": 8,
                                      "quota": {"tier": "taster", "remaining": 1}},
        ("GET", "/prior/runs/8"): {"run_id": 8, "status": "error", "error": "no data available for: ZZZ"},
    })
    with patch.object(cloud, "_http", fake), pytest.raises(SystemExit, match="no data available"):
        main(["backtest", BOLLINGER, "--cloud"])


def test_backtest_cloud_compile_error_is_local(capsys, tmp_path):
    """Broken source never reaches the network — local compile fails first."""
    bad = tmp_path / "bad.prior"
    bad.write_text("when banana\n  buy [5% portfolio]\n")
    cloud.save_credentials({"token": "t"})
    fake = _fake_http({})  # any request would raise AssertionError
    with patch.object(cloud, "_http", fake):
        assert main(["backtest", str(bad), "--cloud"]) == 1
    assert fake.calls == []


def test_render_universe_result(capsys):
    cloud.save_credentials({"token": "t"})
    result = {
        "kind": "universe",
        "metrics": {
            "per_ticker": [
                {"ticker": "NVDA", "total_return_pct": 20.0, "buy_hold_return_pct": 30.0,
                 "sharpe": 1.1, "max_drawdown_pct": -12.0, "trades": 9, "win_rate_pct": 66.0},
                {"ticker": "AAPL", "total_return_pct": 5.0, "buy_hold_return_pct": 12.0,
                 "sharpe": 0.4, "max_drawdown_pct": -8.0, "trades": 7, "win_rate_pct": 55.0},
            ],
            "avg_return_pct": 12.5, "total_trades": 16,
        },
        "meta": {"tickers": ["AAPL", "NVDA"], "missing_tickers": ["ZZZ"],
                 "timeframe": "1d", "data_start": "2016-01-04", "data_end": "2026-07-01"},
    }

    class A:  # minimal args stand-in
        as_json = False
        equity = None
        trades = False

    cloud.render_result("test", {"status": "done", "result": result}, A())
    out = capsys.readouterr().out
    assert "NVDA" in out and "AAPL" in out
    assert "total trades: 16" in out
    assert "no cloud data yet for: ZZZ" in out
