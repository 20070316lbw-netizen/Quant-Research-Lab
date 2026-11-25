"""S1 / 表 1 第一列: 对 02_panel.py 的股票周样本进行同周回归"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t

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
X = x.to_numpy(dtype=float)
y = w.ret.to_numpy()
coef, _, rank, _ = np.linalg.lstsq(X, y, rcond=None)
n, k = X.shape
assert rank == k
resid = y - X @ coef
# 以同一周为聚类组, 保留组内股票残差的同期相关
scores = pd.DataFrame(X * resid[:, None]).groupby(w.week).sum().to_numpy()
g = len(scores)
bread = np.linalg.inv(X.T @ X)
cov = (g / (g - 1)) * ((n - 1) / (n - k)) * bread @ (scores.T @ scores) @ bread
se = np.sqrt(np.diag(cov))
q = t.ppf(0.975, g - 1)
est = pd.DataFrame(
    {
        "term": x.columns,
        "estimate": coef,
        "se_week": se,
        "ci_low": coef - q * se,
        "ci_high": coef + q * se,
        "p_week": 2 * t.sf(abs(coef / se), g - 1),
    }
)
out = ROOT / "outputs/tables"
est.to_csv(out / "table1.csv", index=False)
pair = pd.read_csv(clean / "daily_crosscheck.csv")
coverage = pd.read_csv(out / "coverage.csv")
summary = {
    "n_obs": n,
    "weeks": g,
    "tickers": w.ticker.nunique(),
    "first": str(w.week.min().date()),
    "last": str(w.week.max().date()),
    "r2": 1 - resid @ resid / ((y - y.mean()) @ (y - y.mean())),
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
