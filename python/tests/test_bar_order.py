"""Bars must be in order, because the guarantee is stated in row order.

The grammar makes it impossible to *write* a reference to an unclosed bar.
That guarantee is expressed positionally: `close.shift(1)` is the previous
row. Hand the runner a file whose rows are shuffled and shift(1) faithfully
returns whatever sits above, which can be a later date, so lookahead walks
in through the data door and the run still prints a plausible result.

Reported by a quantitative researcher who had shipped exactly this bug: a
date column stored as text, which broke a sort deep in a pipeline and fed
a model each company's future financials.
"""

import pytest

pytest.importorskip("pandas")
import pandas as pd

from prior_lang.backtest import load_bars


def _write(tmp_path, dates, name="bars.csv", ticker=None):
    frame = {
        "date": dates,
        "open": range(1, len(dates) + 1),
        "high": range(2, len(dates) + 2),
        "low": range(0, len(dates)),
        "close": range(1, len(dates) + 1),
        "volume": [100] * len(dates),
    }
    if ticker is not None:
        frame["ticker"] = ticker
    p = tmp_path / name
    pd.DataFrame(frame).to_csv(p, index=False)
    return str(p)


def test_ordered_bars_load(tmp_path):
    path = _write(tmp_path, ["2024-01-02", "2024-01-03", "2024-01-04"])
    assert len(load_bars(path)) == 3


def test_shuffled_bars_are_refused(tmp_path):
    path = _write(tmp_path, ["2024-01-04", "2024-01-02", "2024-01-03"])
    with pytest.raises(SystemExit) as e:
        load_bars(path)
    assert "chronological" in str(e.value)


def test_the_error_points_at_the_offending_date(tmp_path):
    """'Something is wrong with your data' is not actionable."""
    path = _write(tmp_path, ["2024-01-02", "2024-01-03", "2024-01-01", "2024-01-04"])
    with pytest.raises(SystemExit) as e:
        load_bars(path)
    assert "2024-01-01" in str(e.value)


def test_duplicate_timestamps_are_refused(tmp_path):
    path = _write(tmp_path, ["2024-01-02", "2024-01-03", "2024-01-03"])
    with pytest.raises(SystemExit) as e:
        load_bars(path)
    assert "duplicated" in str(e.value)


def test_stacked_multi_ticker_is_not_a_violation(tmp_path):
    """A universe file restarts the dates for each ticker, so the index is
    legitimately non-monotonic overall. Only order *within* a ticker matters."""
    path = _write(
        tmp_path,
        ["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"],
        ticker=["AAA", "AAA", "BBB", "BBB"],
    )
    assert len(load_bars(path)) == 4


def test_disorder_inside_one_ticker_is_caught(tmp_path):
    path = _write(
        tmp_path,
        ["2024-01-02", "2024-01-03", "2024-01-03", "2024-01-02"],
        ticker=["AAA", "AAA", "BBB", "BBB"],
    )
    with pytest.raises(SystemExit) as e:
        load_bars(path)
    assert "BBB" in str(e.value)


def test_text_sorted_dates_are_caught(tmp_path):
    """The reported failure mode: dates sorted as strings rather than dates.
    Lexical order puts 2024-10 before 2024-9 when the month is unpadded."""
    path = _write(tmp_path, ["2024-1-02", "2024-10-02", "2024-9-02"])
    with pytest.raises(SystemExit) as e:
        load_bars(path)
    assert "chronological" in str(e.value)
