"""覆盖月度窗口、执行时间和样本切分的防泄漏约束"""

import numpy as np
import pandas as pd

from quant_research_lab.experiments.ant_transformer_pilot import (
    CONFIG,
    _forward_labels,
    _split,
    _windows,
)
from quant_research_lab.experiments import load_experiment_config


def test_windows_do_not_jump_over_missing_month_or_use_future_rows():
    dates = pd.date_range("2024-01-31", periods=6, freq="ME", name="date").as_unit("ns")
    tickers = pd.Index(["A"], name="ticker")
    index = pd.MultiIndex.from_product([dates, tickers])
    panel = pd.DataFrame({"factor": [1.0, 2.0, np.nan, 4.0, 5.0, 6.0]}, index=index)
    windows, endpoints = _windows(panel, dates, tickers, 2)
    assert endpoints.equals(index[[1, 4, 5]])
    np.testing.assert_array_equal(windows[:, :, 0], [[1, 2], [4, 5], [5, 6]])
    altered = panel.copy()
    altered.loc[(dates[-1], "A"), "factor"] = 700.0
    altered_windows, _ = _windows(altered, dates, tickers, 2)
    np.testing.assert_array_equal(windows[:-1], altered_windows[:-1])


def test_labels_use_next_open_and_fallback_without_dropping_tickers():
    cal = pd.bdate_range("2025-01-01", "2025-03-04", name="date").as_unit("ns")
    tickers = pd.Index(["A", "B", "C"], name="ticker")
    opens = pd.DataFrame(100.0, index=cal, columns=tickers)
    closes = opens.copy()
    opens.loc["2025-02-03", "C"] = np.nan
    opens.loc["2025-03-03", ["A", "B"]] = [115.0, np.nan]
    closes.loc["2025-02-28", "B"] = 75.0
    idx = pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-31"]).as_unit("ns"), tickers], names=["date", "ticker"]
    )
    result = _forward_labels(opens, closes, idx, cal, 1)
    np.testing.assert_allclose(result["return"], [0.15, -0.25, 0.0])
    assert result["no_entry"].tolist() == [False, False, True]
    assert result["proxy_exit"].tolist() == [False, True, False]


def test_holdout_purges_labels_realized_after_training_or_validation_end():
    config = load_experiment_config(CONFIG)
    signal_dates = pd.to_datetime(["2023-10-31", "2023-11-30", "2024-10-31", "2024-11-29", "2025-01-31"])
    index = pd.MultiIndex.from_arrays([signal_dates, ["A"] * 5], names=["date", "ticker"])
    exits = pd.to_datetime(["2023-12-01", "2024-01-02", "2024-12-02", "2025-01-02", "2025-03-03"])
    labels = pd.DataFrame({"exit_date": exits}, index=index)
    train, val, test = _split(labels, config)
    assert train.tolist() == [True, False, False, False, False]
    assert val.tolist() == [False, False, True, False, False]
    assert test.tolist() == [False, False, False, False, True]
