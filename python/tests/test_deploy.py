"""prior deploy — the local-first router verb. Executes nothing, ever."""

from pathlib import Path

import pytest

from prior_lang.cli import main

EXAMPLES = Path(__file__).parents[2] / "examples"
BOLLINGER = str(EXAMPLES / "bollinger_reversal.prior")


@pytest.fixture(autouse=True)
def no_browser(monkeypatch):
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: True)


def test_deploy_prints_local_first_pitch(capsys):
    assert main(["deploy", BOLLINGER]) == 0
    out = capsys.readouterr().out
    assert "Local-first" in out
    assert "autoquant.ai/prior/deploy" in out
    assert "14-day trial" in out


def test_deploy_mentions_desktop_and_headless(capsys):
    assert main(["deploy", BOLLINGER]) == 0
    out = capsys.readouterr().out
    assert "Desktop:" in out
    assert "Headless" in out
    assert "autoquant CLI" in out


def test_deploy_never_touches_our_servers(capsys):
    assert main(["deploy", BOLLINGER]) == 0
    out = capsys.readouterr().out
    assert "never touch our servers" in out


def test_deploy_validates_the_file_first(tmp_path, capsys):
    bad = tmp_path / "bad.prior"
    bad.write_text("when banana\n  buy [5% portfolio]\n")
    assert main(["deploy", str(bad)]) == 1
