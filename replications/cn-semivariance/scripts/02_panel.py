"""S1 / 表1: configs/pilot.yaml 与原始 Qlib 日线及五分钟 CSV 构造股票周面板"""

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

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
        buf = np.fromfile(raw / f"{ticker}.bin", dtype="<f4")
        offset = int(buf[0])
        close = pd.Series(
            buf[1:].astype(float), index=calendar[offset : offset + len(buf) - 1]
        )
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
        prev = bars.groupby("日期")["收盘"].shift()
        prev = prev.mask(bars["时间"].eq("09:35"), bars["开盘"])
        r = np.log(bars["收盘"] / prev)
        day = (
            pd.DataFrame(
                {"pos": r.clip(lower=0) ** 2, "neg": r.clip(upper=0) ** 2, "rv": r**2}
            )
            .groupby(bars["日期"])
            .sum()
        )
        np.testing.assert_allclose(day.pos + day.neg, day.rv, atol=1e-14)
        day.index = pd.to_datetime(day.index)
        assert day.index.isin(calendar).all()
        weeks = day.resample("W-TUE")
        w = np.sqrt(252 / 5 * weeks[["neg", "pos"]].sum(min_count=5))
        w.columns = ["rsn", "rsp"]
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
