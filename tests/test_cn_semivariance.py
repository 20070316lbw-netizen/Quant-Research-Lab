"""用已知半方差和两个相邻周收盘验证表 1 数据脚本"""

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml


def test_complete_week_and_first_bar(tmp_path: Path):
    """周二收盘之间含隔夜, 日内半方差只计当日首开以后的价格变化"""
    root = Path(__file__).resolve().parents[1] / "replications/cn-semivariance"
    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    (tmp_path / "outputs/tables").mkdir(parents=True)
    (tmp_path / "configs").mkdir()
    shutil.copytree(root / "scripts", tmp_path / "scripts")
    cfg = {"industries": {"bank": ["test"]}, "snapshot": "2022-11-30", "years": [2020]}
    (tmp_path / "configs/pilot.yaml").write_text(yaml.safe_dump(cfg))
    dates = pd.bdate_range("2020-01-07", periods=7)
    (raw / "day.txt").write_text("\n".join(dates.strftime("%Y-%m-%d")))
    (raw / "csi300.txt").write_text("TEST\t2010-01-01\t2026-01-01\n")
    np.array([0, 100, 101, 102, 103, 104, 110, 111], dtype="<f4").tofile(
        raw / "test.bin"
    )
    rows = []
    for date in dates:
        times = [
            *pd.date_range("2000-01-01 09:35", periods=24, freq="5min"),
            *pd.date_range("2000-01-01 13:05", periods=24, freq="5min"),
        ]
        for i, stamp in enumerate(times):
            close = 100 * np.exp(0.01 if i == 0 else -0.01)
            rows.append((date, stamp.strftime("%H:%M"), 100, close, 1))
    pd.DataFrame(rows, columns=["日期", "时间", "开盘", "收盘", "成交量"]).to_csv(
        raw / "test-2020.csv", index=False
    )
    subprocess.run([sys.executable, str(tmp_path / "scripts/02_panel.py")], check=True)
    w = pd.read_csv(tmp_path / "data/clean/weekly.csv")
    assert w.week.tolist() == ["2020-01-14"]
    np.testing.assert_allclose(
        w.loc[0, ["rsp", "rsn", "ret"]].astype(float),
        [0.01 * np.sqrt(252), 0.02 * np.sqrt(252), 0.10],
    )


def test_qlib_offset_and_missing(tmp_path: Path):
    from quant_research_lab.data import read_qlib_feature

    calendar = pd.date_range("2020-01-01", periods=3)
    path = tmp_path / "volume.day.bin"
    np.array([1, np.nan, 18], dtype="<f4").tofile(path)
    expected = pd.Series(
        [np.nan, 18.0], index=calendar[1:].rename("date"), name="volume"
    )
    pd.testing.assert_series_equal(read_qlib_feature(path, calendar), expected)
    with pytest.raises(ValueError, match="超出"):
        read_qlib_feature(path, calendar[:2])


def test_intraday_variance_excludes_overnight():
    from quant_research_lab.stats import realized_semivariance

    idx = pd.DatetimeIndex(
        ["2020-01-01 10:00", "2020-01-01 11:00", "2020-01-02 10:00"], name="date"
    )
    bars = pd.DataFrame({"open": [1.0, 2.0, 9.0], "close": [2.0, 1.0, 9.0]}, index=idx)
    daily = realized_semivariance(bars)
    variance = np.log(2.0) ** 2
    np.testing.assert_allclose(
        daily, [[variance, variance, 2 * variance], [0.0, 0.0, 0.0]]
    )
    assert realized_semivariance(bars.iloc[:0]).empty
    with pytest.raises(ValueError):
        realized_semivariance(bars.assign(close=np.nan))
