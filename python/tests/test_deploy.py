"""prior deploy — the plan-aware router verb. Executes nothing, ever."""

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


@pytest.fixture(autouse=True)
def no_browser(monkeypatch):
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: True)


def _with_plan(plan):
    return patch.object(cloud, "_http", lambda m, p, payload=None, token=None: {"plan": plan})


def test_deploy_signed_out_gets_trial_pitch(capsys):
    assert main(["deploy", BOLLINGER]) == 0
    out = capsys.readouterr().out
    assert "local-first" in out
    assert "autoquant.ai/prior/deploy" in out
    assert "14-day trial" in out


def test_deploy_taster_and_cloud_get_trial_pitch(capsys):
    for plan in ("expired", "prior_cloud"):
        cloud.save_credentials({"token": "t", "email": "a@b.co"})
        with _with_plan(plan):
            assert main(["deploy", BOLLINGER]) == 0
        assert "autoquant.ai/prior/deploy" in capsys.readouterr().out


def test_deploy_professional_gets_desktop_steps(capsys):
    cloud.save_credentials({"token": "t", "email": "pro@b.co"})
    with _with_plan("professional"):
        assert main(["deploy", BOLLINGER]) == 0
    out = capsys.readouterr().out
    assert "AutoQuant desktop" in out
    assert "Deploy" in out
    assert "never leave your machine" in out


def test_deploy_quant_mentions_headless(capsys):
    cloud.save_credentials({"token": "t", "email": "q@b.co"})
    with _with_plan("quant"):
        assert main(["deploy", BOLLINGER]) == 0
    out = capsys.readouterr().out
    assert "Headless" in out
    assert "autoquant CLI" in out


def test_deploy_validates_the_file_first(tmp_path, capsys):
    bad = tmp_path / "bad.prior"
    bad.write_text("when banana\n  buy [5% portfolio]\n")
    assert main(["deploy", str(bad)]) == 1


def test_cloud_result_prints_deploy_hint(capsys):
    cloud.save_credentials({"token": "t", "email": "a@b.co"})
    result = {
        "kind": "single",
        "metrics": {
            "total_return_pct": 1.0, "buy_hold_return_pct": 1.0, "cagr_pct": 1.0,
            "sharpe": 0.5, "volatility_pct": 10.0, "max_drawdown_pct": -5.0,
            "trades": 3, "win_rate_pct": 66.0, "avg_trade_pct": 0.3, "bars": 100,
        },
        "equity": [], "trades": [], "trades_truncated": 0,
        "meta": {"tickers": ["NVDA"], "missing_tickers": [], "timeframe": "1d",
                 "data_start": "2024-01-01", "data_end": "2026-01-01"},
    }

    def fake(method, path, payload=None, token=None):
        if path == "/prior/backtest":
            return {"status": "queued", "run_id": 1, "quota": {"tier": "taster", "remaining": 2}}
        return {"run_id": 1, "status": "done", "result": result}

    with patch.object(cloud, "_http", fake):
        assert main(["backtest", BOLLINGER, "--cloud"]) == 0
    out = capsys.readouterr().out
    assert f"prior deploy {BOLLINGER}" in out
