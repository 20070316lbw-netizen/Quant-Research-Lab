"""S1/S2 数据准备。在复现项目根目录执行, 上游为 FRED 月度利率与 NBER 季度定年表"""
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
import yaml

config = yaml.safe_load(Path("configs/us.yaml").read_text())
raw = Path("data/raw")
clean = Path("data/clean")
raw.mkdir(parents=True, exist_ok=True)
clean.mkdir(parents=True, exist_ok=True)
rates = pd.read_csv(config["rates_url"], parse_dates=["observation_date"])
months = rates.observation_date.dt.to_period("Q")
rates = rates.loc[months.between(config["predictor_start"], config["target_end"])].copy()
rates.to_csv(raw / "rates.csv", index=False)
page = urlopen(Request(config["cycles_url"], headers={"User-Agent": "Mozilla/5.0"})).read()
table = pd.read_html(BytesIO(page))[0]
cycles = table.iloc[:, :2].apply(lambda col: col.str.extract(r"(\d{4}Q[1-4])", expand=False)).dropna()
cycles.columns = ["peak", "trough"]
cycles = cycles.loc[(cycles.peak <= config["target_end"]) & (cycles.trough >= config["predictor_start"])]
cycles.to_csv(raw / "cycles.csv", index=False)

rates = rates.set_index("observation_date").to_period("M")
assert rates.index.equals(pd.period_range(rates.index.min(), rates.index.max(), freq="M"))
assert rates.notna().all().all()
rates["bill_be"] = 365 * rates.TB3MS / (360 - config["bill_days"] * rates.TB3MS / 100)
rates["spread"] = rates.GS10 - rates.bill_be
panel = rates.groupby(rates.index.asfreq("Q")).mean()
assert len(rates) == 3 * len(panel)
panel["recession"] = 0
for cycle in cycles.itertuples():
    panel.loc[(panel.index > cycle.peak) & (panel.index <= cycle.trough), "recession"] = 1
panel.to_csv(clean / "quarterly.csv", index_label="quarter")
print(len(rates), len(panel), len(cycles), int(panel.recession.sum()))
print(panel.loc[["1981Q1", "1989Q4", "1994Q3"]])
