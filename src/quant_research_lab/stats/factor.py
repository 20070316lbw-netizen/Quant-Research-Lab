"""横截面因子预处理与统计检验模块

提供统一的横截面去极值, 标准化, 行业与风格中性化, IC/RankIC 分析,
IC 衰减曲线, 分位数分组多空检验与 Fama-MacBeth 两步回归
所有函数均为纯函数, 严格遵循 design/02b-data-contracts.md 内存数据契约
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from quant_research_lab.data.contracts import (
    DataContractError,
    validate_panel,
    validate_signal,
    validate_timeseries,
)
from quant_research_lab.stats.result import StatResult


def _default_nw_lags(n_obs: int) -> int:
    if n_obs <= 1:
        return 0
    return max(0, min(n_obs - 1, int(np.floor(4.0 * (n_obs / 100.0) ** (2.0 / 9.0)))))


def _newey_west_mean_test(
    values: np.ndarray,
    *,
    name: str,
    nw_lags: int | None = None,
    meta: dict[str, object] | None = None,
    min_warn_obs: int = 30,
) -> StatResult:
    """对一维时间序列均值执行 Newey-West HAC 稳健 t 检验"""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = int(arr.size)
    extra = dict(meta or {})
    warnings_list: list[str] = []

    if n == 0:
        warnings_list.append("有效样本量为 0, 无法估计均值与显著性")
        return StatResult(name=name, estimate=float("nan"), n_obs=0, meta=extra, warnings=tuple(warnings_list))

    mean_val = float(np.mean(arr))
    if n < min_warn_obs:
        warnings_list.append(f"有效样本量偏小 (n_obs={n} < {min_warn_obs}), 渐近检验可能不稳定")

    if n == 1:
        warnings_list.append("仅 1 个有效样本, 无法计算标准误与 p 值")
        extra["nw_lags"] = 0
        return StatResult(name=name, estimate=mean_val, n_obs=1, meta=extra, warnings=tuple(warnings_list))

    lags = _default_nw_lags(n) if nw_lags is None else int(nw_lags)
    if lags < 0:
        raise ValueError(f"nw_lags must be >= 0, got {lags}")
    lags = min(lags, n - 1)
    extra["nw_lags"] = lags

    resid = arr - mean_val
    gamma0 = float(np.dot(resid, resid) / n)
    omega = gamma0
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        gamma_l = float(np.dot(resid[lag:], resid[:-lag]) / n)
        omega += 2.0 * weight * gamma_l

    # 自由度小样本修正 T / (T - 1)
    var_mean = max(omega, 0.0) * (n / (n - 1.0)) / n
    se = float(np.sqrt(var_mean))

    if se == 0.0:
        warnings_list.append("Newey-West 标准误为 0, 序列无波动")
        return StatResult(
            name=name,
            estimate=mean_val,
            se=0.0,
            t_stat=None,
            p_value=None,
            ci_low=mean_val,
            ci_high=mean_val,
            n_obs=n,
            meta=extra,
            warnings=tuple(warnings_list),
        )

    t_stat = float(mean_val / se)
    df = n - 1
    p_value = float(2.0 * scipy_stats.t.sf(abs(t_stat), df=df))
    t_crit = float(scipy_stats.t.ppf(0.975, df=df))
    ci_low = float(mean_val - t_crit * se)
    ci_high = float(mean_val + t_crit * se)

    return StatResult(
        name=name,
        estimate=mean_val,
        se=se,
        t_stat=t_stat,
        p_value=p_value,
        ci_low=ci_low,
        ci_high=ci_high,
        n_obs=n,
        meta=extra,
        warnings=tuple(warnings_list),
    )


def winsorize_cs(
    signal: pd.Series,
    *,
    method: Literal["mad", "quantile"] = "mad",
    n_mad: float = 5.0,
    lower: float = 0.01,
    upper: float = 0.99,
) -> pd.Series:
    """按交易日执行横截面去极值

    method="mad" 时按 median +/- n_mad * 1.4826 * MAD 截断, MAD 为 0 的日期保持原值
    method="quantile" 时按当日 [lower, upper] 分位数截断

    Args:
        signal: 标准 SignalSeries, 索引为升序无重复 MultiIndex(date, ticker)
        method: 去极值方法, 可选 "mad" 或 "quantile", 默认 "mad"
        n_mad: MAD 倍数阈值 (仅 method="mad" 生效), 须 > 0, 默认 5.0
        lower: 下分位点 (仅 method="quantile" 生效), 须满足 0 <= lower < upper <= 1, 默认 0.01
        upper: 上分位点 (仅 method="quantile" 生效), 默认 0.99

    Returns:
        pd.Series: 去极值后的 float64 SignalSeries, 保留原索引与 Series.name, NaN 保持 NaN

    Raises:
        DataContractError: signal 不符合 SignalSeries 契约
        ValueError: method 不支持或阈值参数非法

    Example:
        >>> idx = pd.MultiIndex.from_tuples(
        ...     [(pd.Timestamp("2024-01-02"), t) for t in ["A", "B", "C", "D", "E"]],
        ...     names=["date", "ticker"],
        ... )
        >>> s = pd.Series([1.0, 2.0, 3.0, 4.0, 100.0], index=idx, name="sig")
        >>> float(winsorize_cs(s, method="mad", n_mad=3.0).max()) < 100.0
        True
    """
    validate_signal(signal, name="winsorize_cs(signal)")
    if method not in ("mad", "quantile"):
        raise ValueError(f"Unsupported winsorize method: {method!r}")
    if method == "mad" and n_mad <= 0:
        raise ValueError(f"n_mad must be > 0, got {n_mad}")
    if method == "quantile" and not (0.0 <= lower < upper <= 1.0):
        raise ValueError(f"Require 0 <= lower < upper <= 1, got lower={lower}, upper={upper}")

    s = signal.astype(float)

    def _clip_group(g: pd.Series) -> pd.Series:
        valid = g.dropna()
        if valid.empty:
            return g
        if method == "mad":
            med = float(valid.median())
            mad = float((valid - med).abs().median())
            if mad == 0.0:
                return g
            bound = n_mad * 1.4826 * mad
            return g.clip(lower=med - bound, upper=med + bound)
        lo = float(valid.quantile(lower))
        hi = float(valid.quantile(upper))
        return g.clip(lower=lo, upper=hi)

    out = s.groupby(level="date", group_keys=False).apply(_clip_group)
    out.name = signal.name
    return validate_signal(out, name="winsorize_cs(output)")


def standardize_cs(
    signal: pd.Series,
    *,
    method: Literal["zscore", "rank", "rank_gauss"] = "zscore",
) -> pd.Series:
    """按交易日执行横截面标准化

    - "zscore": (x - mean) / std (ddof=1), 样本不足 2 或标准差为 0 时返回 NaN
    - "rank": 均匀秩映射至 (-1, 1), 公式为 2 * ((rank - 0.5) / n) - 1
    - "rank_gauss": Blom/Van der Waerden 风格正态分位映射 norm.ppf((rank - 0.5) / n)

    Args:
        signal: 标准 SignalSeries, 索引为升序无重复 MultiIndex(date, ticker)
        method: 标准化方法, 可选 "zscore", "rank", "rank_gauss", 默认 "zscore"

    Returns:
        pd.Series: 标准化后的 float64 SignalSeries, 保留原索引与 Series.name

    Raises:
        DataContractError: signal 不符合 SignalSeries 契约
        ValueError: method 不受支持

    Example:
        >>> idx = pd.MultiIndex.from_tuples(
        ...     [(pd.Timestamp("2024-01-02"), t) for t in ["A", "B", "C"]],
        ...     names=["date", "ticker"],
        ... )
        >>> s = pd.Series([10.0, 20.0, 30.0], index=idx, name="sig")
        >>> round(float(standardize_cs(s).mean()), 12)
        0.0
    """
    validate_signal(signal, name="standardize_cs(signal)")
    if method not in ("zscore", "rank", "rank_gauss"):
        raise ValueError(f"Unsupported standardize method: {method!r}")

    s = signal.astype(float)

    def _norm_group(g: pd.Series) -> pd.Series:
        valid = g.dropna()
        n = len(valid)
        if n == 0:
            return g
        if method == "zscore":
            if n < 2:
                return pd.Series(np.nan, index=g.index, dtype=float)
            std = float(valid.std(ddof=1))
            if std == 0.0 or not np.isfinite(std):
                return pd.Series(np.nan, index=g.index, dtype=float)
            return (g - float(valid.mean())) / std

        ranks = g.rank(method="average", na_option="keep")
        u = (ranks - 0.5) / float(n)
        if method == "rank":
            return 2.0 * u - 1.0
        out_arr = np.full(len(g), np.nan, dtype=float)
        mask = u.notna().to_numpy()
        out_arr[mask] = scipy_stats.norm.ppf(u.to_numpy()[mask])
        return pd.Series(out_arr, index=g.index, dtype=float)

    out = s.groupby(level="date", group_keys=False).apply(_norm_group)
    out.name = signal.name
    return validate_signal(out, name="standardize_cs(output)")


def neutralize_cs(
    signal: pd.Series,
    *,
    industry: pd.Series | None = None,
    controls: pd.DataFrame | pd.Series | None = None,
    weights: pd.Series | None = None,
    min_obs: int = 10,
) -> pd.Series:
    """按交易日对行业哑变量与连续风格变量做横截面 OLS/WLS 残差中性化

    使用最小二乘 SVD (np.linalg.lstsq) 求解, 自动兼容行业哑变量共线性
    传入 weights 时执行加权最小二乘 (WLS), 仅保留严格为正的权重样本

    Args:
        signal: 标准 SignalSeries, 索引为 MultiIndex(date, ticker)
        industry: 可选行业分类 Series (如 sub_industry), 索引为 MultiIndex(date, ticker), 默认 None
        controls: 可选连续控制变量 (如 log_mcap, beta), DataFrame 或 Series, 索引为 MultiIndex(date, ticker)
        weights: 可选正权重 Series (如市值权重), 索引为 MultiIndex(date, ticker), 默认 None 表示等权 OLS
        min_obs: 单日最少有效样本数, 低于该值时当日残差设为 NaN, 默认 10

    Returns:
        pd.Series: 中性化后的残差 SignalSeries, 与输入 signal 索引一致, 保留 signal.name

    Raises:
        DataContractError: 输入对象不符合 PanelFrame 或 SignalSeries 契约
        ValueError: industry 和 controls 同时为 None, 或 min_obs < 2

    Example:
        >>> idx = pd.MultiIndex.from_tuples(
        ...     [(pd.Timestamp("2024-01-02"), f"T{i}") for i in range(6)],
        ...     names=["date", "ticker"],
        ... )
        >>> x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], index=idx, name="size")
        >>> y = 2.0 * x + 1.0
        >>> y.name = "sig"
        >>> float(neutralize_cs(y, controls=x, min_obs=4).abs().max()) < 1e-10
        True
    """
    validate_signal(signal, name="neutralize_cs(signal)")
    if industry is None and controls is None:
        raise ValueError("At least one of industry or controls must be provided")
    if min_obs < 2:
        raise ValueError(f"min_obs must be >= 2, got {min_obs}")

    work = pd.DataFrame({"_y": signal.astype(float)}, index=signal.index)

    if industry is not None:
        if not isinstance(industry, pd.Series) or list(industry.index.names) != ["date", "ticker"]:
            raise DataContractError("neutralize_cs(industry): must be a Series indexed by MultiIndex(date, ticker)")
        if industry.index.has_duplicates:
            raise DataContractError("neutralize_cs(industry): duplicate (date, ticker) keys detected")
        work["_ind"] = industry.reindex(signal.index)

    ctrl_cols: list[str] = []
    if controls is not None:
        if isinstance(controls, pd.Series):
            validate_signal(controls, name="neutralize_cs(controls)")
            col_name = f"_ctrl_{controls.name or '0'}"
            work[col_name] = controls.astype(float).reindex(signal.index)
            ctrl_cols = [col_name]
        else:
            validate_panel(controls, name="neutralize_cs(controls)")
            reindexed = controls.reindex(signal.index)
            for col in reindexed.columns:
                work[f"_ctrl_{col}"] = reindexed[col].astype(float)
                ctrl_cols.append(f"_ctrl_{col}")

    if weights is not None:
        validate_signal(weights, name="neutralize_cs(weights)")
        work["_w"] = weights.astype(float).reindex(signal.index)

    result = pd.Series(np.nan, index=signal.index, dtype=float, name=signal.name)

    for _, grp in work.groupby(level="date", sort=False):
        valid_mask = grp["_y"].notna()
        if "_ind" in grp.columns:
            valid_mask &= grp["_ind"].notna()
        for c in ctrl_cols:
            valid_mask &= grp[c].notna()
        if "_w" in grp.columns:
            valid_mask &= grp["_w"].notna() & (grp["_w"] > 0.0)

        sub = grp.loc[valid_mask]
        if len(sub) < min_obs:
            continue

        blocks: list[np.ndarray] = []
        if "_ind" in sub.columns:
            dummies = pd.get_dummies(sub["_ind"], drop_first=False, dtype=float).to_numpy()
            blocks.append(dummies)
        else:
            blocks.append(np.ones((len(sub), 1), dtype=float))

        if ctrl_cols:
            blocks.append(sub[ctrl_cols].to_numpy(dtype=float))

        x_mat = np.hstack(blocks)
        y_vec = sub["_y"].to_numpy(dtype=float)

        if "_w" in sub.columns:
            sqrt_w = np.sqrt(sub["_w"].to_numpy(dtype=float))
            beta, *_ = np.linalg.lstsq(x_mat * sqrt_w[:, None], y_vec * sqrt_w, rcond=None)
        else:
            beta, *_ = np.linalg.lstsq(x_mat, y_vec, rcond=None)

        resid = y_vec - x_mat @ beta
        result.loc[sub.index] = resid

    return validate_signal(result, name="neutralize_cs(output)")


def compute_ic_series(
    signal: pd.Series,
    forward_return: pd.Series,
    *,
    method: Literal["spearman", "pearson"] = "spearman",
    min_obs: int = 10,
) -> pd.Series:
    """计算逐期横截面 IC 或 RankIC 时间序列

    自动按 (date, ticker) 内连接对齐并剔除缺失值, 单日有效样本低于 min_obs 或
    任一侧截面无方差时该日返回 NaN (不纳入有效截面)

    Args:
        signal: 因子信号 SignalSeries, 索引为 MultiIndex(date, ticker)
        forward_return: 未来收益率 SignalSeries, 索引为 MultiIndex(date, ticker)
        method: 相关系数类型, "spearman" (RankIC, 默认) 或 "pearson" (IC)
        min_obs: 单日最少有效截面对数, 须 >= 3, 默认 10

    Returns:
        pd.Series: 符合 TimeSeriesFrame 契约的日频 IC 序列, 索引为 DatetimeIndex(name="date")
            Series.name 为 "rank_ic" (spearman) 或 "ic" (pearson)

    Raises:
        DataContractError: signal 或 forward_return 不符合 SignalSeries 契约
        ValueError: method 非法或 min_obs < 3

    Example:
        >>> idx = pd.MultiIndex.from_tuples(
        ...     [(pd.Timestamp("2024-01-02"), f"T{i}") for i in range(5)],
        ...     names=["date", "ticker"],
        ... )
        >>> sig = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx, name="sig")
        >>> ret = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05], index=idx, name="ret")
        >>> round(float(compute_ic_series(sig, ret, min_obs=3).iloc[0]), 6)
        1.0
    """
    validate_signal(signal, name="compute_ic_series(signal)")
    validate_signal(forward_return, name="compute_ic_series(forward_return)")
    if method not in ("spearman", "pearson"):
        raise ValueError(f"Unsupported IC method: {method!r}")
    if min_obs < 3:
        raise ValueError(f"min_obs must be >= 3, got {min_obs}")

    aligned = pd.concat([signal.rename("sig"), forward_return.rename("ret")], axis=1, join="inner").dropna()
    series_name = "rank_ic" if method == "spearman" else "ic"
    if aligned.empty:
        empty = pd.Series(dtype=float, index=pd.DatetimeIndex([], dtype="datetime64[ns]", name="date"), name=series_name)
        return validate_timeseries(empty, name="compute_ic_series(output)")

    dates: list[pd.Timestamp] = []
    values: list[float] = []
    for dt, grp in aligned.groupby(level="date", sort=True):
        if len(grp) < min_obs:
            continue
        x = grp["sig"].to_numpy(dtype=float)
        y = grp["ret"].to_numpy(dtype=float)
        if np.std(x) == 0.0 or np.std(y) == 0.0:
            continue
        if method == "spearman":
            corr = float(scipy_stats.spearmanr(x, y).statistic)
        else:
            corr = float(np.corrcoef(x, y)[0, 1])
        if np.isfinite(corr):
            dates.append(pd.Timestamp(dt))
            values.append(corr)

    out = pd.Series(values, index=pd.DatetimeIndex(dates, dtype="datetime64[ns]", name="date"), dtype=float, name=series_name)
    return validate_timeseries(out, name="compute_ic_series(output)")


def summarize_ic(
    ic_series: pd.Series,
    *,
    nw_lags: int | None = None,
) -> StatResult:
    """对逐期 IC 序列汇总均值, ICIR, 胜率与 Newey-West 稳健 t 检验

    Args:
        ic_series: 符合 TimeSeriesFrame 契约的逐期 IC Series
        nw_lags: Newey-West HAC 滞后阶数, 默认 None 按 Newey-West (1994) 规则自动选择

    Returns:
        StatResult: estimate 为 IC 均值, se/t_stat/p_value/ci_low/ci_high 为 Newey-West HAC 推断
            meta 包含 ic_std, icir, hit_rate, nw_lags

    Raises:
        DataContractError: ic_series 不符合 TimeSeriesFrame 契约
        ValueError: nw_lags < 0

    Example:
        >>> idx = pd.date_range("2024-01-02", periods=5, name="date")
        >>> s = pd.Series([0.04, 0.05, 0.03, 0.06, 0.02], index=idx, name="rank_ic")
        >>> round(summarize_ic(s).estimate, 4)
        0.04
    """
    validate_timeseries(ic_series, name="summarize_ic(ic_series)")
    valid = ic_series.dropna().to_numpy(dtype=float)
    n = int(valid.size)
    ic_std = float(np.std(valid, ddof=1)) if n >= 2 else float("nan")
    mean_ic = float(np.mean(valid)) if n >= 1 else float("nan")
    icir = float(mean_ic / ic_std) if n >= 2 and ic_std > 0.0 else float("nan")
    hit_rate = float(np.mean(valid > 0.0)) if n >= 1 else float("nan")

    label = f"mean_{ic_series.name}" if ic_series.name else "mean_ic"
    return _newey_west_mean_test(
        valid,
        name=label,
        nw_lags=nw_lags,
        meta={
            "ic_std": ic_std,
            "icir": icir,
            "hit_rate": hit_rate,
        },
    )


def ic_decay(
    signal: pd.Series,
    forward_returns: Mapping[int, pd.Series],
    *,
    method: Literal["spearman", "pearson"] = "spearman",
    min_obs: int = 10,
    nw_lags: int | None = None,
) -> pd.DataFrame:
    """计算同一因子在多个前瞻持有期上的 IC 衰减曲线

    Args:
        signal: 标准 SignalSeries
        forward_returns: 键为持有期步数 (如 1, 5, 10, 20), 值为对应未来收益 SignalSeries 的映射
        method: "spearman" (默认) 或 "pearson"
        min_obs: 单日最少有效样本数, 默认 10
        nw_lags: Newey-West 滞后阶数, 默认 None (当未指定时取 max(h - 1, 自动规则) 以适配重叠收益自相关)

    Returns:
        pd.DataFrame: 按 horizon 升序索引的衰减摘要表, 包含列
            mean_ic, ic_std, icir, t_stat, p_value, hit_rate, n_obs, nw_lags

    Raises:
        DataContractError: signal 或任一 forward_return 不符合 SignalSeries 契约
        ValueError: forward_returns 为空或包含非正 horizon

    Example:
        >>> idx = pd.MultiIndex.from_tuples(
        ...     [(pd.Timestamp("2024-01-02"), f"T{i}") for i in range(5)],
        ...     names=["date", "ticker"],
        ... )
        >>> sig = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx, name="sig")
        >>> ret = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05], index=idx, name="ret")
        >>> ic_decay(sig, {1: ret}, min_obs=3).index.tolist()
        [1]
    """
    validate_signal(signal, name="ic_decay(signal)")
    if not forward_returns:
        raise ValueError("forward_returns must not be empty")

    rows: list[dict[str, object]] = []
    for horizon in sorted(forward_returns):
        if horizon < 1:
            raise ValueError(f"horizon must be >= 1, got {horizon}")
        ic_s = compute_ic_series(signal, forward_returns[horizon], method=method, min_obs=min_obs)
        effective_lags = nw_lags if nw_lags is not None else max(horizon - 1, _default_nw_lags(len(ic_s)))
        summary = summarize_ic(ic_s, nw_lags=effective_lags)
        rows.append(
            {
                "horizon": int(horizon),
                "mean_ic": summary.estimate,
                "ic_std": summary.meta["ic_std"],
                "icir": summary.meta["icir"],
                "t_stat": summary.t_stat,
                "p_value": summary.p_value,
                "hit_rate": summary.meta["hit_rate"],
                "n_obs": summary.n_obs,
                "nw_lags": summary.meta["nw_lags"],
            }
        )

    return pd.DataFrame(rows).set_index("horizon")


def quantile_portfolio_returns(
    signal: pd.Series,
    forward_return: pd.Series,
    *,
    n_quantiles: int = 5,
    weights: pd.Series | None = None,
    min_obs: int | None = None,
    nw_lags: int | None = None,
) -> tuple[pd.DataFrame, StatResult]:
    """构建横截面分位数分组组合收益率并检验多空组合 (Q_n - Q_1) 显著性与单调性

    每日按因子值升序分入 Q1 (最低) 至 Q{n_quantiles} (最高), 使用 rank(method="average")
    将结值 (ties) 分入同一组以避免按 ticker 字母序引入偏差; 计算各组等权或加权收益以及多空收益 long_short = Q{n} - Q1

    Args:
        signal: 因子信号 SignalSeries
        forward_return: 未来收益率 SignalSeries
        n_quantiles: 分组数, 须 >= 2, 默认 5
        weights: 可选正权重 SignalSeries (如市值加权), 默认 None 表示等权
        min_obs: 单日最少有效样本数, 默认 None 时取 max(n_quantiles * 2, 10)
        nw_lags: 多空组合均值检验的 Newey-West 滞后阶数, 默认 None 自动选择

    Returns:
        tuple[pd.DataFrame, StatResult]:
            - DataFrame: 符合 TimeSeriesFrame 契约, 列为 Q1..Q{n_quantiles} 与 long_short
            - StatResult: long_short 均值收益的 Newey-West HAC 显著性检验,
              meta 包含 quantile_means 与 monotonicity_rho (分组序号与组均收益的 Spearman 相关)

    Raises:
        DataContractError: 输入不符合 SignalSeries 契约
        ValueError: n_quantiles < 2 或 min_obs < n_quantiles

    Example:
        >>> idx = pd.MultiIndex.from_tuples(
        ...     [(pd.Timestamp("2024-01-02"), f"T{i}") for i in range(10)],
        ...     names=["date", "ticker"],
        ... )
        >>> sig = pd.Series(range(10), index=idx, dtype=float, name="sig")
        >>> ret = pd.Series([i * 0.01 for i in range(10)], index=idx, dtype=float, name="ret")
        >>> qdf, ls = quantile_portfolio_returns(sig, ret, n_quantiles=5, min_obs=5)
        >>> float(qdf["long_short"].iloc[0]) > 0.0
        True
    """
    validate_signal(signal, name="quantile_portfolio_returns(signal)")
    validate_signal(forward_return, name="quantile_portfolio_returns(forward_return)")
    if n_quantiles < 2:
        raise ValueError(f"n_quantiles must be >= 2, got {n_quantiles}")

    eff_min_obs = max(n_quantiles * 2, 10) if min_obs is None else int(min_obs)
    if eff_min_obs < n_quantiles:
        raise ValueError(f"min_obs ({eff_min_obs}) must be >= n_quantiles ({n_quantiles})")

    parts = [signal.rename("sig"), forward_return.rename("ret")]
    if weights is not None:
        validate_signal(weights, name="quantile_portfolio_returns(weights)")
        parts.append(weights.rename("w"))

    aligned = pd.concat(parts, axis=1, join="inner").dropna()
    if "w" in aligned.columns:
        aligned = aligned.loc[aligned["w"] > 0.0]

    q_cols = [f"Q{i}" for i in range(1, n_quantiles + 1)]
    all_cols = [*q_cols, "long_short"]

    if aligned.empty:
        empty_df = pd.DataFrame(
            {c: pd.Series(dtype=float) for c in all_cols},
            index=pd.DatetimeIndex([], dtype="datetime64[ns]", name="date"),
        )
        validate_timeseries(empty_df, required_cols=all_cols, name="quantile_portfolio_returns(output)")
        empty_stat = _newey_west_mean_test(
            np.array([], dtype=float),
            name="quantile_long_short",
            nw_lags=nw_lags,
            meta={"quantile_means": {}, "monotonicity_rho": float("nan")},
        )
        return empty_df, empty_stat

    dates: list[pd.Timestamp] = []
    records: list[list[float]] = []

    for dt, grp in aligned.groupby(level="date", sort=True):
        if len(grp) < eff_min_obs:
            continue
        ranks = grp["sig"].rank(method="average").to_numpy(dtype=float)
        buckets = np.minimum(((ranks - 1.0) * n_quantiles // float(len(grp))).astype(int), n_quantiles - 1)
        rets = grp["ret"].to_numpy(dtype=float)
        w_arr = grp["w"].to_numpy(dtype=float) if "w" in grp.columns else None

        row_vals: list[float] = []
        for q_idx in range(n_quantiles):
            mask = buckets == q_idx
            if not np.any(mask):
                row_vals.append(float("nan"))
            elif w_arr is None:
                row_vals.append(float(np.mean(rets[mask])))
            else:
                w_sub = w_arr[mask]
                row_vals.append(float(np.dot(rets[mask], w_sub) / np.sum(w_sub)))
        row_vals.append(row_vals[-1] - row_vals[0])
        dates.append(pd.Timestamp(dt))
        records.append(row_vals)

    q_df = pd.DataFrame(
        records,
        index=pd.DatetimeIndex(dates, dtype="datetime64[ns]", name="date"),
        columns=all_cols,
        dtype=float,
    )
    validate_timeseries(q_df, required_cols=all_cols, name="quantile_portfolio_returns(output)")

    q_means = {c: float(q_df[c].mean()) for c in q_cols}
    mean_vec = np.array([q_means[c] for c in q_cols], dtype=float)
    if np.all(np.isfinite(mean_vec)) and np.std(mean_vec) > 0.0:
        mono_rho = float(scipy_stats.spearmanr(np.arange(1, n_quantiles + 1), mean_vec).statistic)
    else:
        mono_rho = float("nan")

    ls_stat = _newey_west_mean_test(
        q_df["long_short"].to_numpy(dtype=float),
        name="quantile_long_short",
        nw_lags=nw_lags,
        meta={
            "quantile_means": q_means,
            "monotonicity_rho": mono_rho,
            "n_quantiles": n_quantiles,
        },
    )
    return q_df, ls_stat


def fama_macbeth(
    forward_return: pd.Series,
    exposures: pd.DataFrame | pd.Series,
    *,
    add_const: bool = True,
    nw_lags: int | None = None,
    min_obs: int = 20,
) -> dict[str, StatResult]:
    """执行 Fama-MacBeth 两步横截面回归 (配 Newey-West HAC 稳健标准误)

    第一步: 逐交易日以未来收益对因子暴露做横截面 OLS 回归, 提取每日风险溢价 gamma_t 与截面 R^2
    第二步: 对每个因子的 gamma_t 时间序列计算均值与 Newey-West HAC 标准误, t 统计量与 p 值

    Args:
        forward_return: 未来收益率 SignalSeries, 索引为 MultiIndex(date, ticker)
        exposures: 因子暴露 PanelFrame (多因子) 或 SignalSeries (单因子), 索引为 MultiIndex(date, ticker)
        add_const: 横截面回归是否自动添加截距项 "const", 默认 True
        nw_lags: 第二步时间序列均值检验的 Newey-West 滞后阶数, 默认 None 自动选择
        min_obs: 单日最少有效截面样本数, 须大于回归变量数, 默认 20

    Returns:
        dict[str, StatResult]: 键为因子名 (含 "const" 若 add_const=True), 值为对应风险溢价的 StatResult
            meta 包含 avg_r2 与 avg_cross_section_n

    Raises:
        DataContractError: 输入不符合 SignalSeries 或 PanelFrame 契约
        ValueError: exposures 无列或 min_obs 不足

    Example:
        >>> rng = np.random.default_rng(42)
        >>> dates = pd.date_range("2024-01-02", periods=30)
        >>> tickers = [f"T{i:02d}" for i in range(25)]
        >>> idx = pd.MultiIndex.from_product([dates, tickers], names=["date", "ticker"])
        >>> x = pd.Series(rng.normal(size=len(idx)), index=idx, name="beta")
        >>> y = pd.Series(0.01 * x.to_numpy() + rng.normal(scale=0.01, size=len(idx)), index=idx, name="ret")
        >>> res = fama_macbeth(y, x, min_obs=10)
        >>> res["beta"].estimate > 0.005
        True
    """
    validate_signal(forward_return, name="fama_macbeth(forward_return)")
    if isinstance(exposures, pd.Series):
        validate_signal(exposures, name="fama_macbeth(exposures)")
        factor_name = str(exposures.name or "factor")
        exp_df = exposures.astype(float).to_frame(name=factor_name)
    else:
        validate_panel(exposures, name="fama_macbeth(exposures)")
        if exposures.shape[1] == 0:
            raise ValueError("exposures must contain at least one column")
        exp_df = exposures.astype(float)

    factor_cols = list(exp_df.columns)
    internal_x_cols = [f"_x_{i}" for i in range(len(factor_cols))]
    n_params = len(factor_cols) + (1 if add_const else 0)
    if min_obs <= n_params:
        raise ValueError(f"min_obs ({min_obs}) must be > number of regressors ({n_params})")

    exp_renamed = exp_df.copy()
    exp_renamed.columns = internal_x_cols
    aligned = pd.concat([forward_return.rename("_y"), exp_renamed], axis=1, join="inner").dropna()
    param_names = (["const", *factor_cols]) if add_const else list(factor_cols)

    gammas: list[np.ndarray] = []
    r2_list: list[float] = []
    cs_counts: list[int] = []
    skipped_rank_deficient = 0

    for _, grp in aligned.groupby(level="date", sort=True):
        if len(grp) < min_obs:
            continue
        y = grp["_y"].to_numpy(dtype=float)
        x = grp[internal_x_cols].to_numpy(dtype=float)
        if add_const:
            x = np.column_stack([np.ones(len(grp), dtype=float), x])

        if int(np.linalg.matrix_rank(x)) < x.shape[1]:
            skipped_rank_deficient += 1
            continue

        beta, *_ = np.linalg.lstsq(x, y, rcond=None)
        resid = y - x @ beta
        tss = float(np.sum((y - np.mean(y)) ** 2))
        r2 = float(1.0 - np.sum(resid**2) / tss) if tss > 0.0 else float("nan")
        gammas.append(beta)
        r2_list.append(r2)
        cs_counts.append(len(grp))

    avg_r2 = float(np.nanmean(r2_list)) if r2_list else float("nan")
    avg_n = float(np.mean(cs_counts)) if cs_counts else 0.0
    gamma_mat = np.vstack(gammas) if gammas else np.empty((0, n_params), dtype=float)

    results: dict[str, StatResult] = {}
    for j, col in enumerate(param_names):
        results[col] = _newey_west_mean_test(
            gamma_mat[:, j],
            name=f"fm_{col}",
            nw_lags=nw_lags,
            meta={
                "avg_r2": avg_r2,
                "avg_cross_section_n": avg_n,
                "skipped_rank_deficient": skipped_rank_deficient,
            },
        )
    return results
