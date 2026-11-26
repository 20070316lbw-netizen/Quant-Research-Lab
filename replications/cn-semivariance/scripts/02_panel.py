"""S1 / 表1: configs/pilot.yaml 与原始 Qlib 日线及五分钟 CSV 构造股票周面板"""

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from quant_research_lab.data import read_qlib_feature
from quant_research_lab.stats import realized_semivariance

ROOT = Path(__file__).resolve().parents[1]
raw = ROOT / "data/raw"
clean = ROOT / "data/clean"
clean.mkdir(exist_ok=True)
cfg = yaml.safe_load((ROOT / "configs/pilot.yaml").read_text())
calendar = pd.DatetimeIndex(pd.to_datetime((raw / "day.txt").read_text().splitlines()))
members = pd.read_csv(raw / "csi300.txt", sep="\t", names=["ticker", "start", "end"])
snapshot = members[
    (members.start <= cfg["snapshot"]) & (members.end >= cfg["snapshot"])
]
snapshot.to_csv(clean / "snapshot.csv", index=False)
grid = set(pd.date_range("2000-01-01 09:35", periods=24, freq="5min").strftime("%H:%M"))
grid.update(
    pd.date_range("2000-01-01 13:05", periods=24, freq="5min").strftime("%H:%M")
)
panels = []
audit = []
crosschecks = []
for industry, tickers in cfg["industries"].items():
    for ticker in tickers:
        assert ticker.upper() in set(snapshot.ticker)
        close = read_qlib_feature(raw / f"{ticker}.bin", calendar)
        # 分别取得相邻两个自然周最后交易日的收盘, 空周不会跨过
        last = (
            close.reindex(calendar)
            .resample("W-TUE")
            .agg(lambda s: s.iloc[-1] if len(s) else np.nan)
        )
        ret = last.pct_change(fill_method=None).rename("ret")
        files = sorted(raw.glob(f"{ticker}-????.csv"))
        bars = pd.concat(
            [
                pd.read_csv(f, usecols=["日期", "时间", "开盘", "收盘", "成交量"])
                for f in files
            ]
        )
        bars = bars.sort_values(["日期", "时间"])
        groups = bars.groupby("日期")
        days = groups.size()
        good_grid = groups["时间"].agg(lambda s: len(s) == 48 and set(s) == grid)
        valid = (bars["开盘"] > 0) & (bars["收盘"] > 0)
        good_day = (
            good_grid & valid.groupby(bars["日期"]).all() & (groups["成交量"].sum() > 0)
        )
        bars = bars[bars["日期"].isin(good_day[good_day].index)].copy()
        prices = bars.rename(columns={"开盘": "open", "收盘": "close"})[
            ["open", "close"]
        ]
        prices.index = pd.DatetimeIndex(
            pd.to_datetime(bars["日期"] + " " + bars["时间"]), name="date"
        )
        day = realized_semivariance(prices)
        assert day.index.isin(calendar).all()
        weeks = day.resample("W-TUE")
        w = np.sqrt(252 / 5 * weeks[["rsn", "rsp"]].sum(min_count=5))
        w = w.loc[weeks.size().eq(5)].join(ret).dropna()
        w = w[w.index.year.isin(cfg["years"])]
        panels.append(w.assign(ticker=ticker, industry=industry))
        audit.append(
            {
                "ticker": ticker,
                "annual_files": len(files),
                "bars": int(days.sum()),
                "days": len(days),
                "valid_days": len(day),
                "weeks": len(w),
                "missing_years": " ".join(
                    str(y)
                    for y in cfg["years"]
                    if not (raw / f"{ticker}-{y}.csv").exists()
                ),
            }
        )
        intraday_close = bars.groupby("日期")["收盘"].last()
        intraday_close.index = pd.to_datetime(intraday_close.index)
        pair = pd.concat(
            [
                close.reindex(calendar).pct_change(fill_method=None).rename("qlib"),
                intraday_close.reindex(calendar)
                .pct_change(fill_method=None)
                .rename("minute"),
            ],
            axis=1,
        ).dropna()
        crosschecks.append(pair.assign(ticker=ticker))
pd.concat(crosschecks).to_csv(clean / "daily_crosscheck.csv", index_label="date")
pd.concat(panels).sort_index().to_csv(clean / "weekly.csv", index_label="week")
pd.DataFrame(audit).to_csv(ROOT / "outputs/tables/coverage.csv", index=False)
