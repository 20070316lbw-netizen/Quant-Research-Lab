"""时间序列平稳性, 协整, 均值回归与协方差收缩模块

提供 ADF, KPSS 单位根检验, Engle-Granger 协整检验,
OU 过程半衰期估计, Hurst 指数估计与 Ledoit-Wolf (2004) 协方差收缩
"""

from __future__ import annotations

import warnings
from typing import Literal

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from statsmodels.tools.sm_exceptions import InterpolationWarning
from statsmodels.tsa.stattools import adfuller, coint, kpss

from quant_research_lab.data.contracts import validate_timeseries
from quant_research_lab.stats.result import StatResult


def adf_test(
    series: pd.Series,
    *,
    regression: Literal["c", "ct", "n"] = "c",
    autolag: Literal["AIC", "BIC", "t-stat"] | None = "AIC",
    maxlag: int | None = None,
) -> StatResult:
    """执行 Augmented Dickey-Fuller (ADF) 单位根检验

    原假设 H0: 序列存在单位根 (非平稳); p_value < 0.05 时拒绝原假设, 支持平稳性

    Args:
        series: 符合 TimeSeriesFrame 契约的一维数值 Series
        regression: 确定性趋势项, "c" (仅常数, 默认), "ct" (常数+线性趋势), "n" (无)
        autolag: 自动滞后阶数准则, 可选 "AIC", "BIC", "t-stat" 或 None, 默认 "AIC"
        maxlag: 最大滞后阶数, 默认 None 由 statsmodels 自动设定

    Returns:
        StatResult: estimate 与 t_stat 为 ADF 统计量, p_value 为 MacKinnon 近似 p 值
            meta 包含 usedlag, critical_values, regression

    Raises:
        DataContractError: series 不符合 TimeSeriesFrame 契约
        ValueError: regression 非法

    Example:
        >>> rng = np.random.default_rng(0)
        >>> s = pd.Series(rng.normal(size=200), index=pd.date_range("2022-01-01", periods=200, name="date"))
        >>> adf_test(s).p_value < 0.05
        True
    """
    validate_timeseries(series, name="adf_test(series)")
    if regression not in ("c", "ct", "n"):
        raise ValueError(f"Unsupported regression option: {regression!r}")

    arr = series.astype(float).dropna().to_numpy()
    n = len(arr)
    if n < 10 or np.std(arr) == 0.0:
        return StatResult(
            name="ADF",
            estimate=float("nan"),
            n_obs=n,
            meta={"regression": regression},
            warnings=("样本量不足 10 或序列为常数, 无法执行 ADF 检验",),
        )

    adf_res = adfuller(
        arr,
        maxlag=maxlag,
        regression=regression,
        autolag=autolag,
        result_object=False,
    )
    stat, pval, usedlag, nobs, crit_vals = adf_res[:5]
    warn = (f"有效样本量偏小 (n_obs={nobs} < 30), ADF 检验功效较低",) if nobs < 30 else ()
    return StatResult(
        name="ADF",
        estimate=float(stat),
        t_stat=float(stat),
        p_value=float(pval),
        n_obs=int(nobs),
        meta={
            "usedlag": int(usedlag),
            "critical_values": {k: float(v) for k, v in crit_vals.items()},
            "regression": regression,
        },
        warnings=warn,
    )


def kpss_test(
    series: pd.Series,
    *,
    regression: Literal["c", "ct"] = "c",
    nlags: Literal["auto", "legacy"] | int = "auto",
) -> StatResult:
    """执行 Kwiatkowski-Phillips-Schmidt-Shin (KPSS) 平稳性检验

    原假设 H0: 序列平稳 (与 ADF 互补); p_value < 0.05 时拒绝平稳性原假设

    Args:
        series: 符合 TimeSeriesFrame 契约的一维数值 Series
        regression: "c" (水平平稳, 默认) 或 "ct" (趋势平稳)
        nlags: 滞后阶数, 可选 "auto" (默认), "legacy" 或非负整数

    Returns:
        StatResult: estimate 为 KPSS 统计量, p_value 为插值 p 值 (截断于 [0.01, 0.10])
            meta 包含 lags, critical_values, regression; 截断边界告警收集于 warnings

    Raises:
        DataContractError: series 不符合 TimeSeriesFrame 契约
        ValueError: regression 非法

    Example:
        >>> rng = np.random.default_rng(1)
        >>> s = pd.Series(rng.normal(size=200), index=pd.date_range("2022-01-01", periods=200, name="date"))
        >>> kpss_test(s).p_value >= 0.05
        True
    """
    validate_timeseries(series, name="kpss_test(series)")
    if regression not in ("c", "ct"):
        raise ValueError(f"Unsupported regression option: {regression!r}")

    arr = series.astype(float).dropna().to_numpy()
    n = len(arr)
    if n < 10 or np.std(arr) == 0.0:
        return StatResult(
            name="KPSS",
            estimate=float("nan"),
            n_obs=n,
            meta={"regression": regression},
            warnings=("样本量不足 10 或序列为常数, 无法执行 KPSS 检验",),
        )

    captured_warnings: list[str] = []
    with warnings.catch_warnings(record=True) as w_list:
        warnings.simplefilter("always", InterpolationWarning)
        stat, pval, lags, crit_vals = kpss(arr, regression=regression, nlags=nlags)
        for item in w_list:
            captured_warnings.append(str(item.message))

    return StatResult(
        name="KPSS",
        estimate=float(stat),
        p_value=float(pval),
        n_obs=n,
        meta={
            "lags": int(lags),
            "critical_values": {k: float(v) for k, v in crit_vals.items()},
            "regression": regression,
        },
        warnings=tuple(captured_warnings),
    )


def engle_granger_coint(
    y: pd.Series,
    x: pd.Series,
    *,
    trend: Literal["c", "ct", "n"] = "c",
    autolag: Literal["aic", "bic", "t-stat"] | None = "aic",
) -> StatResult:
    """执行 Engle-Granger 两步协整检验并估计 OLS 对冲比率

    先按日期内连接对齐 y 与 x, 对 y = alpha + beta * x + eps 估计对冲比率 beta,
    再对残差执行 MacKinnon 临界值修正的协整检验 (H0: 无协整关系)

    Args:
        y: 因变量价格或对数价格序列 (TimeSeriesFrame)
        x: 自变量价格或对数价格序列 (TimeSeriesFrame)
        trend: 协整回归趋势项, "c" (默认), "ct", "n"
        autolag: 残差 ADF 滞后选择准则, 默认 "aic"

    Returns:
        StatResult: estimate 与 t_stat 为协整 t 统计量, p_value 为 MacKinnon p 值
            meta 包含 hedge_ratio, intercept, critical_values (1%, 5%, 10%)

    Raises:
        DataContractError: y 或 x 不符合 TimeSeriesFrame 契约
        ValueError: trend 非法

    Example:
        >>> rng = np.random.default_rng(42)
        >>> idx = pd.date_range("2022-01-01", periods=300, name="date")
        >>> x = pd.Series(np.cumsum(rng.normal(size=300)), index=idx)
        >>> y = pd.Series(2.0 * x.to_numpy() + rng.normal(scale=0.5, size=300), index=idx)
        >>> res = engle_granger_coint(y, x)
        >>> res.p_value < 0.05 and abs(res.meta["hedge_ratio"] - 2.0) < 0.1
        True
    """
    validate_timeseries(y, name="engle_granger_coint(y)")
    validate_timeseries(x, name="engle_granger_coint(x)")
    if trend not in ("c", "ct", "n"):
        raise ValueError(f"Unsupported trend option: {trend!r}")

    aligned = pd.concat([y.astype(float).rename("y"), x.astype(float).rename("x")], axis=1, join="inner").dropna()
    n = len(aligned)
    if n < 20:
        return StatResult(
            name="Engle-Granger",
            estimate=float("nan"),
            n_obs=n,
            warnings=("对齐后样本量不足 20, 无法执行协整检验",),
        )

    y_arr = aligned["y"].to_numpy()
    x_arr = aligned["x"].to_numpy()
    trend_coef: float | None = None
    if trend == "n":
        design = x_arr[:, None]
        coef, *_ = np.linalg.lstsq(design, y_arr, rcond=None)
        intercept = 0.0
        hedge_ratio = float(coef[0])
    elif trend == "ct":
        t_idx = np.arange(n, dtype=float)
        design = np.column_stack([np.ones(n, dtype=float), t_idx, x_arr])
        coef, *_ = np.linalg.lstsq(design, y_arr, rcond=None)
        intercept = float(coef[0])
        trend_coef = float(coef[1])
        hedge_ratio = float(coef[2])
    else:
        design = np.column_stack([np.ones(n, dtype=float), x_arr])
        coef, *_ = np.linalg.lstsq(design, y_arr, rcond=None)
        intercept = float(coef[0])
        hedge_ratio = float(coef[1])

    t_stat, pval, crit = coint(y_arr, x_arr, trend=trend, autolag=autolag)
    meta: dict[str, object] = {
        "hedge_ratio": hedge_ratio,
        "intercept": intercept,
        "critical_values": {
            "1%": float(crit[0]),
            "5%": float(crit[1]),
            "10%": float(crit[2]),
        },
        "trend": trend,
    }
    if trend_coef is not None:
        meta["trend_coef"] = trend_coef

    return StatResult(
        name="Engle-Granger",
        estimate=float(t_stat),
        t_stat=float(t_stat),
        p_value=float(pval),
        n_obs=n,
        meta=meta,
    )


def ou_half_life(spread: pd.Series) -> StatResult:
    """估计 Ornstein-Uhlenbeck (OU) 均值回归过程的半衰期 (Half-Life)

    基于离散回归 delta_s_t = alpha + lambda * s_{t-1} + eps_t:
    - 仅当 -1 < lambda < 0 时存在有限正半衰期: half_life = -ln(2) / ln(1 + lambda)
    - 当 lambda >= 0 时序列非均值回归, 返回 estimate=nan 并在 warnings 标明

    Args:
        spread: 符合 TimeSeriesFrame 契约的价差或残差序列

    Returns:
        StatResult: estimate 为半衰期 (单位: 序列周期数, 如交易日)
            se, t_stat, p_value 为回归斜率 lambda 的 OLS 推断结果
            meta 包含 lambda_coef, long_run_mean, r2

    Raises:
        DataContractError: spread 不符合 TimeSeriesFrame 契约

    Example:
        >>> rng = np.random.default_rng(12)
        >>> idx = pd.date_range("2022-01-01", periods=500, name="date")
        >>> s = np.zeros(500)
        >>> for i in range(1, 500):
        ...     s[i] = 0.9 * s[i - 1] + rng.normal(scale=0.1)
        >>> res = ou_half_life(pd.Series(s, index=idx))
        >>> 3.0 < res.estimate < 12.0
        True
    """
    validate_timeseries(spread, name="ou_half_life(spread)")
    arr = spread.astype(float).dropna().to_numpy()
    n = len(arr)
    if n < 5:
        return StatResult(
            name="ou_half_life",
            estimate=float("nan"),
            n_obs=n,
            warnings=("样本量不足 5, 无法估计 OU 半衰期",),
        )

    s_lag = arr[:-1]
    ds = np.diff(arr)
    m = len(ds)
    x = np.column_stack([np.ones(m, dtype=float), s_lag])
    beta, *_ = np.linalg.lstsq(x, ds, rcond=None)
    alpha = float(beta[0])
    lam = float(beta[1])

    resid = ds - x @ beta
    rss = float(np.dot(resid, resid))
    tss = float(np.sum((ds - float(np.mean(ds))) ** 2))
    r2 = float(1.0 - rss / tss) if tss > 0.0 else float("nan")

    dof = m - 2
    s_var = float(np.sum((s_lag - float(np.mean(s_lag))) ** 2))
    if dof > 0 and s_var > 0.0:
        se_lam = float(np.sqrt((rss / dof) / s_var))
        t_lam = float(lam / se_lam) if se_lam > 0.0 else None
        p_lam = float(2.0 * scipy_stats.t.sf(abs(t_lam), df=dof)) if t_lam is not None else None
    else:
        se_lam, t_lam, p_lam = None, None, None

    warn_list: list[str] = [
        "p_value 基于标准 OLS t 分布而非 Dickey-Fuller 分布, 单位根显著性请以 adf_test 为准"
    ]
    if lam >= 0.0:
        half_life = float("nan")
        long_run_mean = float("nan")
        warn_list.append(f"回归斜率 lambda={lam:.4f} >= 0, 序列未呈现均值回归特征")
    elif lam <= -1.0:
        half_life = float("nan")
        long_run_mean = float(-alpha / lam)
        warn_list.append(f"回归斜率 lambda={lam:.4f} <= -1, 序列呈振荡发散特征")
    else:
        half_life = float(-np.log(2.0) / np.log(1.0 + lam))
        long_run_mean = float(-alpha / lam)

    return StatResult(
        name="ou_half_life",
        estimate=half_life,
        se=se_lam,
        t_stat=t_lam,
        p_value=p_lam,
        n_obs=m,
        meta={
            "lambda_coef": lam,
            "intercept": alpha,
            "long_run_mean": long_run_mean,
            "r2": r2,
        },
        warnings=tuple(warn_list),
    )


def hurst_exponent(series: pd.Series, *, max_lag: int = 20) -> StatResult:
    """基于滞后差分方差标度法估计 Hurst 指数 H

    对 lag = 2..max_lag 计算 tau(lag) = std(x_{t+lag} - x_t), 拟合 log(tau) ~ H * log(lag)
    H < 0.5 指向均值回归, H = 0.5 对应随机游走, H > 0.5 指向趋势持续性
    t_stat 与 p_value 检验 H0: H = 0.5

    Args:
        series: 符合 TimeSeriesFrame 契约的一维水平序列 (如对数价格或价差)
        max_lag: 最大滞后步数, 须 >= 4 且小于样本长度的一半, 默认 20

    Returns:
        StatResult: estimate 为 Hurst 指数 H, se 为对数回归斜率标准误
            t_stat = (H - 0.5) / se, p_value 为 H != 0.5 的双侧 p 值

    Raises:
        DataContractError: series 不符合 TimeSeriesFrame 契约
        ValueError: max_lag < 4

    Example:
        >>> rng = np.random.default_rng(7)
        >>> idx = pd.date_range("2020-01-01", periods=600, name="date")
        >>> rw = pd.Series(np.cumsum(rng.normal(size=600)), index=idx)
        >>> 0.35 < hurst_exponent(rw).estimate < 0.65
        True
    """
    validate_timeseries(series, name="hurst_exponent(series)")
    if max_lag < 4:
        raise ValueError(f"max_lag must be >= 4, got {max_lag}")

    arr = series.astype(float).dropna().to_numpy()
    n = len(arr)
    eff_max_lag = min(max_lag, n // 2)
    if eff_max_lag < 4:
        return StatResult(
            name="hurst_exponent",
            estimate=float("nan"),
            n_obs=n,
            warnings=("样本量过短, 无法在足够滞后阶数上估计 Hurst 指数",),
        )

    lags = np.arange(2, eff_max_lag + 1, dtype=int)
    taus = np.array([float(np.std(arr[lag:] - arr[:-lag], ddof=1)) for lag in lags], dtype=float)
    valid_mask = taus > 0.0
    if int(np.sum(valid_mask)) < 3:
        return StatResult(
            name="hurst_exponent",
            estimate=float("nan"),
            n_obs=n,
            warnings=("有效非零滞后方差不足 3 点, 无法拟合 Hurst 指数",),
        )

    log_lags = np.log(lags[valid_mask].astype(float))
    log_taus = np.log(taus[valid_mask])
    reg = scipy_stats.linregress(log_lags, log_taus)
    h_est = float(reg.slope)
    se = float(reg.stderr) if np.isfinite(reg.stderr) else None
    df = int(np.sum(valid_mask)) - 2

    if se is not None and se > 0.0 and df > 0:
        t_stat = float((h_est - 0.5) / se)
        p_val = float(2.0 * scipy_stats.t.sf(abs(t_stat), df=df))
        t_crit = float(scipy_stats.t.ppf(0.975, df=df))
        ci_low = float(h_est - t_crit * se)
        ci_high = float(h_est + t_crit * se)
    else:
        t_stat, p_val, ci_low, ci_high = None, None, None, None

    return StatResult(
        name="hurst_exponent",
        estimate=h_est,
        se=se,
        t_stat=t_stat,
        p_value=p_val,
        ci_low=ci_low,
        ci_high=ci_high,
        n_obs=n,
        meta={"max_lag_used": int(eff_max_lag), "r2": float(reg.rvalue**2)},
        warnings=("se 与 p_value 基于重叠滞后方差 OLS 拟合, 忽略了滞后点间相关性, 仅供参考",),
    )


def ledoit_wolf_cov(returns: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """计算 Ledoit-Wolf (2004) 常数方差单位阵目标解析收缩协方差矩阵

    将样本协方差矩阵 S 向目标矩阵 mu * I 收缩: Sigma_hat = (1 - delta) * S + delta * mu * I
    其中最优收缩强度 delta in [0, 1] 由解析渐近公式闭式给出

    Args:
        returns: 符合 TimeSeriesFrame 契约的多资产收益率宽表 DataFrame (行=date, 列=资产)
            内部会剔除含缺失值的日期行

    Returns:
        tuple[pd.DataFrame, float]:
            - DataFrame: 对称半正定收缩协方差矩阵, 行列索引均为 returns.columns
            - float: 最优收缩强度 delta, 区间 [0, 1]

    Raises:
        DataContractError: returns 不符合 TimeSeriesFrame 契约
        ValueError: 资产数 < 1 或有效观测行数 < 2

    Example:
        >>> rng = np.random.default_rng(0)
        >>> idx = pd.date_range("2024-01-02", periods=60, name="date")
        >>> df = pd.DataFrame(rng.normal(scale=0.01, size=(60, 4)), index=idx, columns=["A", "B", "C", "D"])
        >>> cov, delta = ledoit_wolf_cov(df)
        >>> cov.shape == (4, 4) and 0.0 <= delta <= 1.0
        True
    """
    validate_timeseries(returns, name="ledoit_wolf_cov(returns)")
    clean = returns.astype(float).dropna(axis=0, how="any")
    n_obs, n_assets = clean.shape
    if n_assets < 1:
        raise ValueError("returns must contain at least 1 asset column")
    if n_obs < 2:
        raise ValueError(f"Need at least 2 complete observations, got {n_obs}")

    x = clean.to_numpy(dtype=float)
    x = x - np.mean(x, axis=0, keepdims=True)
    sample_cov = (x.T @ x) / float(n_obs)

    mu = float(np.trace(sample_cov) / n_assets)
    target = mu * np.eye(n_assets, dtype=float)
    diff = sample_cov - target
    d2 = float(np.sum(diff * diff) / n_assets)

    if d2 <= 1e-18:
        delta = 1.0
    else:
        # Ledoit & Wolf (2004) Lemma 3.4: b_bar^2 = (1 / (n^2 * p)) * sum_t ||x_t x_t' - S||_F^2
        # 等价化简避免构造 n 个 p x p 矩阵:
        # sum_t ||x_t x_t'||_F^2 = sum_t (||x_t||_2^2)^2, 且 sum_t <x_t x_t', S> = n * ||S||_F^2
        row_norm_sq = np.sum(x * x, axis=1)
        sum_outer_sq = float(np.sum(row_norm_sq * row_norm_sq))
        s_norm_sq = float(np.sum(sample_cov * sample_cov))
        b_bar2 = (sum_outer_sq - float(n_obs) * s_norm_sq) / (float(n_obs) ** 2 * float(n_assets))
        b2 = min(max(b_bar2, 0.0), d2)
        delta = float(b2 / d2)

    shrunk = (1.0 - delta) * sample_cov + delta * target
    cov_df = pd.DataFrame(shrunk, index=clean.columns, columns=clean.columns, dtype=float)
    return cov_df, delta
