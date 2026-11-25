"""S1/S2 用季度利差重估原表和四种期限的样本外预测。上游为 01_fetch_and_clean.py 和 configs/us.yaml"""
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import yaml
from scipy.stats import norm

config = yaml.safe_load(Path("configs/us.yaml").read_text())
panel = pd.read_csv("data/clean/quarterly.csv", index_col="quarter")
panel.index = pd.PeriodIndex(panel.index, freq="Q")
out = Path("outputs")
out.mkdir(exist_ok=True)
forecasts = []
for h in config["horizons"]:
    # S1/S2 以目标季度为索引, 每行的利差严格来自提前 h 期的季度
    pairs = pd.DataFrame({"spread": panel.spread.shift(h), "recession": panel.recession})
    pairs = pairs.loc[config["target_start"]:config["target_end"]].dropna()
    x = sm.add_constant(pairs.spread)
    if h == 4:
        model = sm.Probit(pairs.recession, x).fit(disp=False)
        alpha, beta = model.params
        published = pd.read_csv("configs/paper_thresholds.csv")
        published["replicated_pp"] = (norm.ppf(published.probability_pct / 100) - alpha) / beta
        published["difference_pp"] = published.replicated_pp - published.paper_pp
        published.to_csv(out / "thresholds.csv", index=False)
        print("S1", len(pairs), alpha, beta, published.to_string(index=False))
        for q in ["1981Q1", "1994Q3"]:
            print(q, norm.cdf(alpha + beta * panel.loc[q, "spread"]))
    for target in pairs.loc[config["forecast_start"]:].index:
        origin = target - h
        train = pairs.loc[:origin]
        fit = sm.Probit(train.recession, x.loc[train.index]).fit(disp=False)
        if not fit.mle_retvals["converged"]:
            raise RuntimeError(f"Probit did not converge for {target}, h={h}")
        probability = fit.predict(x.loc[[target]]).iloc[0]
        forecasts.append((h, str(origin), str(target), str(train.index[-1]), len(train),
                          int(pairs.loc[target, "recession"]), probability, train.recession.mean()))
results = pd.DataFrame(forecasts, columns=["h","origin","target","last_label","n_train",
                                           "recession","probability","historical_rate"])
results.to_csv(out / "forecasts.csv", index=False)
print(results.loc[results.target == "1990Q4"].to_string(index=False))
for horizon, group in results.groupby("h"):
    print(horizon, len(group), int(group.recession.sum()), np.mean((group.probability-group.recession)**2),
          np.mean((group.historical_rate-group.recession)**2))

# S2 将预测画在目标季度, 灰带表示按 NBER 季度定年的衰退
import matplotlib.pyplot as plt

figure, axes = plt.subplots(2, 2, figsize=(10, 5.6), sharex=True, sharey=True)
for axis, (horizon, group) in zip(axes.flat, results.groupby("h"), strict=True):
    dates = pd.PeriodIndex(group.target, freq="Q")
    for quarter in dates[group.recession.to_numpy() == 1]:
        axis.axvspan(quarter.start_time, (quarter + 1).start_time, color="#e0e4e7", lw=0)
    axis.plot(dates.to_timestamp(), group.probability * 100, color="#145d74", lw=1.6)
    axis.set_title(f"{horizon} quarter{'s' if horizon > 1 else ''} ahead", loc="left")
    axis.grid(axis="y", alpha=0.2)
    axis.set_ylim(0,100)
figure.supylabel("Forecast probability (%)")
figure.supxlabel("Target quarter  |  Shading: NBER recession")
figure.tight_layout()
figure.savefig(out / "forecast-panel.png", dpi=150)
