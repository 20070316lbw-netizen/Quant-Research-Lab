"""S1 / 表 1 第一列: 对 02_panel.py 的股票周样本进行同周回归"""

import json
from pathlib import Path

import pandas as pd
from statsmodels.regression.linear_model import OLS

ROOT = Path(__file__).resolve().parents[1]
clean = ROOT / "data/clean"
w = pd.read_csv(clean / "weekly.csv", parse_dates=["week"])
w["year"] = w.week.dt.year.astype(str)
cols = ["ret", "rsn", "rsp"]
for col in cols:
    w[col] = w[col].clip(*w[col].quantile([0.01, 0.99]))
x = pd.concat(
    [w[["rsn", "rsp"]], pd.get_dummies(w[["year", "industry"]], drop_first=True)],
    axis=1,
)
x.insert(0, "const", 1.0)
# 按周聚类, 使用有限样本修正与聚类组数减一的 t 自由度
fit = OLS(w.ret, x.astype(float)).fit(
    cov_type="cluster", cov_kwds={"groups": w.week, "use_correction": True}, use_t=True
)
interval = fit.conf_int()
est = (
    pd.DataFrame(
        {
            "estimate": fit.params,
            "se_week": fit.bse,
            "ci_low": interval[0],
            "ci_high": interval[1],
            "p_week": fit.pvalues,
        }
    )
    .rename_axis("term")
    .reset_index()
)
out = ROOT / "outputs/tables"
est.to_csv(out / "table1.csv", index=False)
pair = pd.read_csv(clean / "daily_crosscheck.csv")
coverage = pd.read_csv(out / "coverage.csv")
summary = {
    "n_obs": int(fit.nobs),
    "weeks": w.week.nunique(),
    "tickers": w.ticker.nunique(),
    "first": str(w.week.min().date()),
    "last": str(w.week.max().date()),
    "r2": fit.rsquared,
    "raw_bars": int(coverage.bars.sum()),
    "days": int(coverage.days.sum()),
    "valid_days": int(coverage.valid_days.sum()),
    "annual_files": int(coverage.annual_files.sum()),
    "snapshot": len(pd.read_csv(clean / "snapshot.csv")),
    "n_trials": 1,
    "daily_crosscheck_n": len(pair),
    "daily_return_corr": pair.qlib.corr(pair.minute),
    "daily_median_abs_diff": (pair.qlib - pair.minute).abs().median(),
    "daily_max_abs_diff": (pair.qlib - pair.minute).abs().max(),
}
(out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(summary)
print(est.iloc[1:3])
