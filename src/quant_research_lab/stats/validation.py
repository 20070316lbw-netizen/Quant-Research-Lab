"""业绩评估, 多重检验校正与防泄漏交叉验证模块

提供核心绩效指标 (年化收益/波动, Lo 自相关调整 Sharpe, Sortino, Calmar, 最大回撤),
Probabilistic Sharpe Ratio (PSR), Deflated Sharpe Ratio (DSR),
Benjamini-Hochberg / Bonferroni / Holm 多重检验校正,
以及 Purged & Embargoed K-Fold 与 Walk-Forward 切分器
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from quant_research_lab.data.contracts import validate_timeseries
from quant_research_lab.stats.result import StatResult

_EULER_MASCHERONI = 0.5772156649015329


def _align_excess_returns(returns: pd.Series, rf: float | pd.Series) -> pd.Series:
    validate_timeseries(returns, name="returns")
    r = returns.astype(float).dropna()
    if isinstance(rf, pd.Series):
        validate_timeseries(rf, name="rf")
        aligned = pd.concat([r.rename("r"), rf.astype(float).rename("rf")], axis=1, join="inner").dropna()
        return aligned["r"] - aligned["rf"]
    return r - float(rf)


def _mertens_sharpe_se(sr_per_period: float, n_obs: int, skew: float, kurtosis: float) -> float:
    """非正态收益率下的单期 Sharpe 标准误 (Mertens 2002 / Bailey & Lopez de Prado 2012)"""
    if n_obs <= 1:
        return float("nan")
    numer = 1.0 - skew * sr_per_period + ((kurtosis - 1.0) / 4.0) * (sr_per_period**2)
    return float(np.sqrt(max(numer, 0.0) / (n_obs - 1.0)))


def _lo_autocorr_factor(arr: np.ndarray, lags: int) -> float:
    """Lo (2002) Bartlett 核自相关方差缩放因子 eta_q"""
    n = len(arr)
    if lags <= 0 or n <= 2:
        return 1.0
    max_lag = min(lags, n - 2)
    centered = arr - float(np.mean(arr))
    denom = float(np.dot(centered, centered))
    if denom <= 0.0:
        return 1.0
    eta = 1.0
    for k in range(1, max_lag + 1):
        rho_k = float(np.dot(centered[k:], centered[:-k]) / denom)
        weight = 1.0 - k / (max_lag + 1.0)
        eta += 2.0 * weight * rho_k
    return max(eta, 1e-12)


def performance_summary(
    returns: pd.Series,
    *,
    rf: float | pd.Series = 0.0,
    periods_per_year: int = 252,
    lo_lags: int | None = None,
) -> dict[str, StatResult]:
    """计算组合日频/周期收益率的核心稳健绩效指标

    包含年化复合收益率, 年化波动率, 年化 Sharpe (附 Mertens 非正态标准误与 Lo 自相关调整值),
    Sortino, Calmar 与最大回撤 (含峰值日, 谷底日与最大水下持续期)

    Args:
        returns: 符合 TimeSeriesFrame 契约的策略简单收益率 Series (小数形式, 如 0.01 代表 1%)
        rf: 无风险收益率 (与 returns 同频率的常数或 TimeSeriesFrame Series), 默认 0.0
        periods_per_year: 每年期数, 日频默认 252, 月频传 12
        lo_lags: Lo (2002) 自相关调整滞后阶数, 默认 None 按 floor(4 * (n/100)^(2/9)) 自动选择

    Returns:
        dict[str, StatResult]: 包含键 annual_return, annual_volatility, sharpe,
            sortino, calmar, max_drawdown 的结构化结果字典

    Raises:
        DataContractError: returns 或 rf 不符合 TimeSeriesFrame 契约
        ValueError: periods_per_year <= 0 或 lo_lags < 0

    Example:
        >>> idx = pd.date_range("2024-01-02", periods=50, name="date")
        >>> r = pd.Series(0.001, index=idx, name="ret")
        >>> summary = performance_summary(r)
        >>> summary["annual_return"].estimate > 0.2
        True
    """
    if periods_per_year <= 0:
        raise ValueError(f"periods_per_year must be > 0, got {periods_per_year}")
    if lo_lags is not None and lo_lags < 0:
        raise ValueError(f"lo_lags must be >= 0, got {lo_lags}")

    validate_timeseries(returns, name="performance_summary(returns)")
    r_clean = returns.astype(float).dropna()
    excess = _align_excess_returns(returns, rf)
    n = len(r_clean)

    if n == 0:
        empty = StatResult(name="empty", estimate=float("nan"), n_obs=0, warnings=("有效样本量为 0",))
        return {
            "annual_return": StatResult(name="annual_return", estimate=float("nan"), n_obs=0, warnings=empty.warnings),
            "annual_volatility": StatResult(name="annual_volatility", estimate=float("nan"), n_obs=0, warnings=empty.warnings),
            "sharpe": StatResult(name="sharpe", estimate=float("nan"), n_obs=0, warnings=empty.warnings),
            "sortino": StatResult(name="sortino", estimate=float("nan"), n_obs=0, warnings=empty.warnings),
            "calmar": StatResult(name="calmar", estimate=float("nan"), n_obs=0, warnings=empty.warnings),
            "max_drawdown": StatResult(name="max_drawdown", estimate=float("nan"), n_obs=0, warnings=empty.warnings),
        }

    arr = r_clean.to_numpy(dtype=float)
    ann_scale = float(np.sqrt(periods_per_year))

    # 复合年化收益
    ret_warnings: list[str] = []
    if np.any(arr <= -1.0):
        ret_warnings.append("存在 <= -100% 的极端单期收益, 组合已爆仓")
        ann_ret = -1.0
        wealth = np.cumprod(np.maximum(1.0 + arr, 0.0))
    else:
        wealth = np.cumprod(1.0 + arr)
        total_ret = float(wealth[-1])
        ann_ret = float(total_ret ** (periods_per_year / float(n)) - 1.0)

    # 年化波动率
    vol_warnings: list[str] = []
    if n < 2:
        ann_vol = float("nan")
        vol_warnings.append("样本量不足 2, 无法计算波动率")
    else:
        ann_vol = float(np.std(arr, ddof=1) * ann_scale)

    # 最大回撤与水下持续期 (计入初始净值 1.0, 避免首日亏损漏计回撤)
    running_max = np.maximum(1.0, np.maximum.accumulate(wealth))
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdowns = np.where(running_max > 0.0, wealth / running_max - 1.0, -1.0)
    trough_pos = int(np.argmin(drawdowns))
    max_dd = float(drawdowns[trough_pos])
    dates_idx = r_clean.index
    pre_trough = wealth[: trough_pos + 1]
    if float(np.max(pre_trough)) < 1.0:
        peak_date: str | None = None
    else:
        peak_pos = int(np.argmax(pre_trough))
        peak_date = str(dates_idx[peak_pos].date())

    # 水下持续期 (连续低于前高的最大期数)
    underwater_cur = 0
    max_underwater = 0
    for dd_val in drawdowns:
        if dd_val < 0.0:
            underwater_cur += 1
            max_underwater = max(max_underwater, underwater_cur)
        else:
            underwater_cur = 0

    # Sharpe (含 Mertens 非正态 SE 与 Lo 自相关调整)
    ex_arr = excess.to_numpy(dtype=float)
    n_ex = len(ex_arr)
    sr_warnings: list[str] = []
    if n_ex < 30:
        sr_warnings.append(f"有效样本量偏小 (n_obs={n_ex} < 30), Sharpe 置信区间较宽")

    if n_ex < 2:
        sharpe_res = StatResult(
            name="sharpe",
            estimate=float("nan"),
            n_obs=n_ex,
            warnings=(*sr_warnings, "样本量不足 2, 无法计算 Sharpe"),
        )
    else:
        ex_std = float(np.std(ex_arr, ddof=1))
        ex_mean = float(np.mean(ex_arr))
        if ex_std == 0.0:
            sr_warnings.append("超额收益标准差为 0, Sharpe 未定义")
            sharpe_res = StatResult(
                name="sharpe",
                estimate=float("nan"),
                n_obs=n_ex,
                meta={"mean_excess_per_period": ex_mean},
                warnings=tuple(sr_warnings),
            )
        else:
            sr_1 = ex_mean / ex_std
            sr_ann = float(sr_1 * ann_scale)
            skew = float(scipy_stats.skew(ex_arr, bias=False)) if n_ex >= 3 else 0.0
            kurt = float(scipy_stats.kurtosis(ex_arr, fisher=False, bias=False)) if n_ex >= 4 else 3.0
            se_1 = _mertens_sharpe_se(sr_1, n_ex, skew, kurt)
            se_ann = float(se_1 * ann_scale)
            t_stat = float(sr_1 / se_1) if se_1 > 0.0 else None
            p_val = float(2.0 * scipy_stats.norm.sf(abs(t_stat))) if t_stat is not None else None
            ci_low = float(sr_ann - 1.959963984540054 * se_ann) if np.isfinite(se_ann) else None
            ci_high = float(sr_ann + 1.959963984540054 * se_ann) if np.isfinite(se_ann) else None

            eff_lags = (
                max(0, min(n_ex - 2, int(np.floor(4.0 * (n_ex / 100.0) ** (2.0 / 9.0)))))
                if lo_lags is None
                else int(lo_lags)
            )
            eta_q = _lo_autocorr_factor(ex_arr, eff_lags)
            sr_lo_ann = float(sr_ann / np.sqrt(eta_q))

            sharpe_res = StatResult(
                name="sharpe",
                estimate=sr_ann,
                se=se_ann,
                t_stat=t_stat,
                p_value=p_val,
                ci_low=ci_low,
                ci_high=ci_high,
                n_obs=n_ex,
                meta={
                    "sharpe_per_period": sr_1,
                    "sharpe_lo_adjusted": sr_lo_ann,
                    "lo_eta": eta_q,
                    "lo_lags": eff_lags,
                    "skew": skew,
                    "kurtosis": kurt,
                },
                warnings=tuple(sr_warnings),
            )

    # Sortino (使用目标收益 0 以下的下行半偏差 RMS)
    downside = np.minimum(ex_arr, 0.0)
    downside_rms = float(np.sqrt(np.mean(downside**2))) if n_ex > 0 else float("nan")
    if n_ex >= 2 and downside_rms > 0.0:
        sortino_val = float((float(np.mean(ex_arr)) / downside_rms) * ann_scale)
        sortino_warn: tuple[str, ...] = ()
    else:
        sortino_val = float("nan")
        sortino_warn = ("无负超额收益或样本不足, Sortino 未定义",)

    # Calmar
    if max_dd < 0.0 and np.isfinite(ann_ret):
        calmar_val = float(ann_ret / abs(max_dd))
        calmar_warn: tuple[str, ...] = ()
    else:
        calmar_val = float("nan")
        calmar_warn = ("最大回撤为 0, Calmar 未定义",)

    return {
        "annual_return": StatResult(
            name="annual_return",
            estimate=ann_ret,
            n_obs=n,
            meta={"total_return": float(wealth[-1] - 1.0), "periods_per_year": periods_per_year},
            warnings=tuple(ret_warnings),
        ),
        "annual_volatility": StatResult(
            name="annual_volatility",
            estimate=ann_vol,
            n_obs=n,
            meta={"periods_per_year": periods_per_year},
            warnings=tuple(vol_warnings),
        ),
        "sharpe": sharpe_res,
        "sortino": StatResult(
            name="sortino",
            estimate=sortino_val,
            n_obs=n_ex,
            meta={"downside_vol_ann": float(downside_rms * ann_scale) if np.isfinite(downside_rms) else float("nan")},
            warnings=sortino_warn,
        ),
        "calmar": StatResult(
            name="calmar",
            estimate=calmar_val,
            n_obs=n,
            meta={"max_drawdown": max_dd},
            warnings=calmar_warn,
        ),
        "max_drawdown": StatResult(
            name="max_drawdown",
            estimate=max_dd,
            n_obs=n,
            meta={
                "peak_date": peak_date,
                "trough_date": str(dates_idx[trough_pos].date()),
                "max_underwater_periods": max_underwater,
            },
        ),
    }


def probabilistic_sharpe_ratio(
    returns: pd.Series,
    *,
    benchmark_sr: float = 0.0,
    rf: float | pd.Series = 0.0,
    periods_per_year: int = 252,
) -> StatResult:
    """计算 Probabilistic Sharpe Ratio (PSR, Bailey & Lopez de Prado 2012)

    评估观测 Sharpe 比率在考虑收益率偏度与峰度后, 真实值高于基准 Sharpe 的后验概率
    p_value 为单侧拒绝概率 (1 - PSR), 越小表示超越基准越显著

    Args:
        returns: 符合 TimeSeriesFrame 契约的收益率 Series
        benchmark_sr: 年化基准 Sharpe 比率阈值, 默认 0.0
        rf: 无风险收益率 (常数或 TimeSeriesFrame Series), 默认 0.0
        periods_per_year: 每年期数, 默认 252

    Returns:
        StatResult: estimate 为 PSR (区间 [0, 1]), t_stat 为检验 z 值, p_value 为 1 - PSR
            meta 包含 observed_sr_ann, benchmark_sr_ann, skew, kurtosis

    Raises:
        DataContractError: returns 或 rf 不符合 TimeSeriesFrame 契约
        ValueError: periods_per_year <= 0

    Example:
        >>> rng = np.random.default_rng(7)
        >>> idx = pd.date_range("2020-01-02", periods=500, name="date")
        >>> r = pd.Series(rng.normal(0.001, 0.01, size=500), index=idx, name="ret")
        >>> probabilistic_sharpe_ratio(r).estimate > 0.95
        True
    """
    if periods_per_year <= 0:
        raise ValueError(f"periods_per_year must be > 0, got {periods_per_year}")

    excess = _align_excess_returns(returns, rf)
    arr = excess.to_numpy(dtype=float)
    n = len(arr)
    if n < 4:
        return StatResult(
            name="PSR",
            estimate=float("nan"),
            n_obs=n,
            meta={"benchmark_sr_ann": benchmark_sr},
            warnings=("样本量不足 4, 无法稳定估计偏度, 峰度与 PSR",),
        )

    std_val = float(np.std(arr, ddof=1))
    if std_val == 0.0:
        return StatResult(
            name="PSR",
            estimate=float("nan"),
            n_obs=n,
            meta={"benchmark_sr_ann": benchmark_sr},
            warnings=("超额收益标准差为 0, PSR 未定义",),
        )

    ann_scale = float(np.sqrt(periods_per_year))
    sr_1 = float(np.mean(arr) / std_val)
    sr_0 = float(benchmark_sr / ann_scale)
    skew = float(scipy_stats.skew(arr, bias=False))
    kurt = float(scipy_stats.kurtosis(arr, fisher=False, bias=False))
    se_1 = _mertens_sharpe_se(sr_1, n, skew, kurt)

    if se_1 <= 0.0 or not np.isfinite(se_1):
        return StatResult(
            name="PSR",
            estimate=float("nan"),
            n_obs=n,
            meta={"observed_sr_ann": sr_1 * ann_scale, "benchmark_sr_ann": benchmark_sr, "skew": skew, "kurtosis": kurt},
            warnings=("非正态标准误非正, PSR 未定义",),
        )

    z_val = float((sr_1 - sr_0) / se_1)
    psr = float(scipy_stats.norm.cdf(z_val))
    p_val = float(scipy_stats.norm.sf(z_val))
    warnings_list = (f"样本量偏小 (n_obs={n} < 30), PSR 近似精度有限",) if n < 30 else ()

    return StatResult(
        name="PSR",
        estimate=psr,
        se=se_1,
        t_stat=z_val,
        p_value=p_val,
        n_obs=n,
        meta={
            "observed_sr_ann": float(sr_1 * ann_scale),
            "observed_sr_per_period": sr_1,
            "benchmark_sr_ann": benchmark_sr,
            "skew": skew,
            "kurtosis": kurt,
        },
        warnings=warnings_list,
    )


def deflated_sharpe_ratio(
    returns: pd.Series,
    *,
    n_trials: int,
    sr_variance: float | None = None,
    rf: float | pd.Series = 0.0,
    periods_per_year: int = 252,
) -> StatResult:
    """计算 Deflated Sharpe Ratio (DSR, Bailey & Lopez de Prado 2014)

    针对多重试验数据窥探 (Selection Bias) 与非正态分布双重校正的 Sharpe 显著性概率
    当 n_trials > 1 时, 先计算 N 次独立试验下零假设最大 Sharpe 期望值 SR*, 再计算 PSR(SR*)

    Args:
        returns: 符合 TimeSeriesFrame 契约的收益率 Series
        n_trials: 独立尝试的策略或参数组合总数, 须 >= 1
        sr_variance: 各次试验非年化 Sharpe 的截面方差; 默认 None 时使用零假设基准方差 1 / (T - 1)
        rf: 无风险收益率 (常数或 TimeSeriesFrame Series), 默认 0.0
        periods_per_year: 每年期数, 默认 252

    Returns:
        StatResult: estimate 为 DSR (区间 [0, 1]), p_value 为 1 - DSR
            meta 包含 n_trials, sr_variance, sr_star_per_period, sr_star_ann 等诊断信息

    Raises:
        DataContractError: returns 或 rf 不符合 TimeSeriesFrame 契约
        ValueError: n_trials < 1, sr_variance < 0 或 periods_per_year <= 0

    Example:
        >>> rng = np.random.default_rng(7)
        >>> idx = pd.date_range("2020-01-02", periods=500, name="date")
        >>> r = pd.Series(rng.normal(0.0005, 0.01, size=500), index=idx, name="ret")
        >>> dsr_1 = deflated_sharpe_ratio(r, n_trials=1).estimate
        >>> dsr_50 = deflated_sharpe_ratio(r, n_trials=50).estimate
        >>> dsr_50 < dsr_1
        True
    """
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")
    if sr_variance is not None and sr_variance < 0.0:
        raise ValueError(f"sr_variance must be >= 0, got {sr_variance}")
    if periods_per_year <= 0:
        raise ValueError(f"periods_per_year must be > 0, got {periods_per_year}")

    excess = _align_excess_returns(returns, rf)
    n = len(excess)
    if n < 4:
        return StatResult(
            name="DSR",
            estimate=float("nan"),
            n_obs=n,
            meta={"n_trials": n_trials},
            warnings=("样本量不足 4, 无法计算 DSR",),
        )

    extra_warnings: list[str] = []
    if sr_variance is None:
        eff_var = 1.0 / float(n - 1)
        if n_trials > 1:
            extra_warnings.append("未提供试验间 Sharpe 方差 sr_variance, 已回退使用零假设近似方差 1/(T-1)")
    else:
        eff_var = float(sr_variance)

    if n_trials == 1 or eff_var == 0.0:
        sr_star_1 = 0.0
    else:
        z1 = float(scipy_stats.norm.ppf(1.0 - 1.0 / float(n_trials)))
        z2 = float(scipy_stats.norm.ppf(1.0 - 1.0 / (float(n_trials) * np.e)))
        e_max_z = (1.0 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2
        sr_star_1 = float(np.sqrt(eff_var) * e_max_z)

    sr_star_ann = float(sr_star_1 * np.sqrt(periods_per_year))
    psr_res = probabilistic_sharpe_ratio(
        returns,
        benchmark_sr=sr_star_ann,
        rf=rf,
        periods_per_year=periods_per_year,
    )
    meta = dict(psr_res.meta)
    meta.update(
        {
            "n_trials": n_trials,
            "sr_variance": eff_var,
            "sr_star_per_period": sr_star_1,
            "sr_star_ann": sr_star_ann,
        }
    )
    return StatResult(
        name="DSR",
        estimate=psr_res.estimate,
        se=psr_res.se,
        t_stat=psr_res.t_stat,
        p_value=psr_res.p_value,
        n_obs=psr_res.n_obs,
        meta=meta,
        warnings=(*psr_res.warnings, *extra_warnings),
    )


def adjust_pvalues(
    p_values: Sequence[float] | Mapping[str, float],
    *,
    method: Literal["bh", "bonferroni", "holm"] = "bh",
) -> pd.DataFrame:
    """对一组假设检验 p 值执行多重检验校正 (防数据窥探假阳性)

    支持:
    - "bh": Benjamini-Hochberg (控制错误发现率 FDR)
    - "bonferroni": Bonferroni 校正 (控制族错误率 FWER)
    - "holm": Holm-Bonferroni 逐步下降校正 (一致强于 Bonferroni 且控制 FWER)

    Args:
        p_values: 原始 p 值序列或 {检验名称: p_value} 映射, 每个值须在 [0, 1] 区间内
        method: 校正方法, 可选 "bh", "bonferroni", "holm", 默认 "bh"

    Returns:
        pd.DataFrame: 含列 p_raw, p_adj, reject_05, reject_01, 索引与输入顺序一致

    Raises:
        ValueError: 输入为空, method 不支持或存在超出 [0, 1] / NaN 的 p 值

    Example:
        >>> df = adjust_pvalues({"f1": 0.001, "f2": 0.04, "f3": 0.50}, method="bh")
        >>> bool(df.loc["f1", "reject_05"])
        True
    """
    if method not in ("bh", "bonferroni", "holm"):
        raise ValueError(f"Unsupported multiple-testing method: {method!r}")

    if isinstance(p_values, Mapping):
        labels: list[object] = list(p_values.keys())
        raw = np.array([float(v) for v in p_values.values()], dtype=float)
    else:
        raw = np.array([float(v) for v in p_values], dtype=float)
        labels = list(range(len(raw)))

    m = len(raw)
    if m == 0:
        raise ValueError("p_values must not be empty")
    if np.any(~np.isfinite(raw)) or np.any(raw < 0.0) or np.any(raw > 1.0):
        raise ValueError("All p_values must be finite numbers in [0, 1]")

    if method == "bonferroni":
        adj = np.minimum(raw * m, 1.0)
    elif method == "holm":
        order = np.argsort(raw)
        sorted_p = raw[order]
        scaled = sorted_p * np.arange(m, 0, -1, dtype=float)
        mono = np.minimum(np.maximum.accumulate(scaled), 1.0)
        adj = np.empty(m, dtype=float)
        adj[order] = mono
    else:
        # Benjamini-Hochberg
        order = np.argsort(raw)
        sorted_p = raw[order]
        ranks = np.arange(1, m + 1, dtype=float)
        scaled = sorted_p * (float(m) / ranks)
        mono = np.minimum(np.minimum.accumulate(scaled[::-1])[::-1], 1.0)
        adj = np.empty(m, dtype=float)
        adj[order] = mono

    return pd.DataFrame(
        {
            "p_raw": raw,
            "p_adj": adj,
            "reject_05": adj < 0.05,
            "reject_01": adj < 0.01,
        },
        index=pd.Index(labels, name="test"),
    )


def purged_kfold_splits(
    dates: pd.DatetimeIndex,
    *,
    n_splits: int = 5,
    label_end_dates: pd.Series | pd.DatetimeIndex | None = None,
    embargo_pct: float = 0.01,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """生成 Purged & Embargoed K-Fold 时间序列防泄漏交叉验证切分

    遵循 Lopez de Prado (2018) 规范:
    1. 将升序时间戳连续切分为 n_splits 个测试折
    2. Purge: 剔除训练集中标签区间 [t_i, label_end_i] 与当前测试折区间有交集的样本
    3. Embargo: 剔除紧跟测试折之后的 ceil(N * embargo_pct) 个样本, 防止序列自相关泄漏

    Args:
        dates: 升序无时区 DatetimeIndex (样本特征观测日)
        n_splits: 折数, 须满足 2 <= n_splits <= len(dates), 默认 5
        label_end_dates: 与 dates 等长的标签结束日序列 (如 forward_return 的 exit_date);
            默认 None 表示单期无重叠 (label_end_dates = dates)
        embargo_pct: 测试折之后的禁入区比例, 须在 [0.0, 0.5) 之间, 默认 0.01

    Returns:
        list[tuple[np.ndarray, np.ndarray]]: 长度为 n_splits 的 (train_indices, test_indices) 整数位置列表

    Raises:
        ValueError: dates 非升序, n_splits 非法, embargo_pct 非法或 label_end_dates 长度不匹配

    Example:
        >>> d = pd.date_range("2024-01-01", periods=20)
        >>> splits = purged_kfold_splits(d, n_splits=4, embargo_pct=0.05)
        >>> len(splits)
        4
    """
    if not isinstance(dates, pd.DatetimeIndex) or dates.tz is not None:
        raise ValueError("dates must be a tz-naive DatetimeIndex")
    if not dates.is_monotonic_increasing:
        raise ValueError("dates must be sorted ascending")
    n = len(dates)
    if n_splits < 2 or n_splits > n:
        raise ValueError(f"n_splits must be in [2, {n}], got {n_splits}")
    if not (0.0 <= embargo_pct < 0.5):
        raise ValueError(f"embargo_pct must be in [0.0, 0.5), got {embargo_pct}")

    t_start = dates.to_numpy(dtype="datetime64[ns]")
    if label_end_dates is None:
        t_end = t_start.copy()
    else:
        if len(label_end_dates) != n:
            raise ValueError(f"label_end_dates length ({len(label_end_dates)}) must match dates ({n})")
        end_idx = pd.DatetimeIndex(pd.to_datetime(label_end_dates))
        if end_idx.tz is not None:
            raise ValueError("label_end_dates must be tz-naive")
        t_end = end_idx.to_numpy(dtype="datetime64[ns]")
        if np.any(t_end < t_start):
            raise ValueError("label_end_dates cannot be earlier than dates")

    embargo_n = int(np.ceil(n * embargo_pct))
    all_pos = np.arange(n, dtype=int)
    folds = np.array_split(all_pos, n_splits)

    splits: list[tuple[np.ndarray, np.ndarray]] = []
    for test_idx in folds:
        test_start = t_start[test_idx[0]]
        test_end = t_end[test_idx].max()

        # 任一训练样本区间 [t_start[i], t_end[i]] 与 [test_start, test_end] 相交即剔除
        overlap = (t_start <= test_end) & (t_end >= test_start)
        keep_mask = ~overlap
        keep_mask[test_idx] = False

        if embargo_n > 0:
            embargo_start = int(np.searchsorted(t_start, test_end, side="right"))
            embargo_stop = min(n, embargo_start + embargo_n)
            keep_mask[embargo_start:embargo_stop] = False

        train_idx = all_pos[keep_mask]
        splits.append((train_idx, test_idx))

    return splits


def walk_forward_splits(
    dates: pd.DatetimeIndex,
    *,
    train_size: int,
    test_size: int,
    step_size: int | None = None,
    expanding: bool = False,
    embargo: int = 0,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """生成滚动 (Rolling) 或扩张 (Expanding) Walk-Forward 样本外切分

    Args:
        dates: 升序无时区 DatetimeIndex
        train_size: 初始训练窗口长度 (期数), 须 >= 1
        test_size: 每轮样本外测试窗口长度 (期数), 须 >= 1
        step_size: 每次前进步长, 默认 None 表示等于 test_size (测试窗口无重叠)
        expanding: False 为固定长度滚动窗口, True 为起点固定的扩张窗口, 默认 False
        embargo: 训练集末尾与测试集起点之间的隔离期数, 须 >= 0, 默认 0

    Returns:
        list[tuple[np.ndarray, np.ndarray]]: (train_indices, test_indices) 整数位置列表

    Raises:
        ValueError: dates 非升序或窗口参数非法

    Example:
        >>> d = pd.date_range("2024-01-01", periods=20)
        >>> wf = walk_forward_splits(d, train_size=10, test_size=5)
        >>> len(wf)
        2
    """
    if not isinstance(dates, pd.DatetimeIndex) or dates.tz is not None:
        raise ValueError("dates must be a tz-naive DatetimeIndex")
    if not dates.is_monotonic_increasing:
        raise ValueError("dates must be sorted ascending")
    if train_size < 1 or test_size < 1:
        raise ValueError(f"train_size and test_size must be >= 1, got {train_size}, {test_size}")
    if embargo < 0:
        raise ValueError(f"embargo must be >= 0, got {embargo}")
    step = test_size if step_size is None else int(step_size)
    if step < 1:
        raise ValueError(f"step_size must be >= 1, got {step}")

    n = len(dates)
    splits: list[tuple[np.ndarray, np.ndarray]] = []
    train_end = train_size

    while train_end + embargo + test_size <= n:
        train_start = 0 if expanding else (train_end - train_size)
        test_start = train_end + embargo
        test_end = test_start + test_size
        splits.append(
            (
                np.arange(train_start, train_end, dtype=int),
                np.arange(test_start, test_end, dtype=int),
            )
        )
        train_end += step

    return splits
