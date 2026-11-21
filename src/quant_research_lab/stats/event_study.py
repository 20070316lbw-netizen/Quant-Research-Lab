"""事件研究统计检验模块 (AR, CAR, BHAR 与 BMP 稳健检验)

专为 S&P 500 纳入/剔除, 财报公告与极端冲击事件设计
严格遵守 design/02b-data-contracts.md 中的 EventTable, SignalSeries 与 TimeSeriesFrame 契约
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from quant_research_lab.data.contracts import (
    DataContractError,
    validate_signal,
    validate_timeseries,
)
from quant_research_lab.stats.result import StatResult

EVENT_REQUIRED_COLS: tuple[str, ...] = ("event_id", "event_date", "ticker", "event_type")


def _validate_event_table(events: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(events, pd.DataFrame):
        raise DataContractError(f"EventTable: expected DataFrame, got {type(events).__name__}")
    missing = [c for c in EVENT_REQUIRED_COLS if c not in events.columns]
    if missing:
        raise DataContractError(f"EventTable: missing required columns {missing}")
    if events["event_id"].duplicated().any():
        raise DataContractError("EventTable: duplicate event_id detected")
    return events


def _one_sample_t_result(values: np.ndarray, *, name: str, meta: dict[str, object] | None = None) -> StatResult:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = int(arr.size)
    extra = dict(meta or {})
    if n == 0:
        return StatResult(name=name, estimate=float("nan"), n_obs=0, meta=extra, warnings=("无有效事件样本",))
    mean_val = float(np.mean(arr))
    if n < 2:
        return StatResult(
            name=name,
            estimate=mean_val,
            n_obs=n,
            meta=extra,
            warnings=("有效事件数不足 2, 无法计算横截面标准误与 p 值",),
        )
    se = float(np.std(arr, ddof=1) / np.sqrt(n))
    if se == 0.0:
        return StatResult(
            name=name,
            estimate=mean_val,
            se=0.0,
            ci_low=mean_val,
            ci_high=mean_val,
            n_obs=n,
            meta=extra,
            warnings=("横截面标准误为 0",),
        )
    df = n - 1
    t_stat = float(mean_val / se)
    p_val = float(2.0 * scipy_stats.t.sf(abs(t_stat), df=df))
    t_crit = float(scipy_stats.t.ppf(0.975, df=df))
    warn = (f"有效事件数偏少 (n_obs={n} < 20), 检验功效有限",) if n < 20 else ()
    return StatResult(
        name=name,
        estimate=mean_val,
        se=se,
        t_stat=t_stat,
        p_value=p_val,
        ci_low=float(mean_val - t_crit * se),
        ci_high=float(mean_val + t_crit * se),
        n_obs=n,
        meta=extra,
        warnings=warn,
    )


def run_event_study(
    events: pd.DataFrame,
    stock_returns: pd.Series,
    market_returns: pd.Series,
    *,
    est_window: tuple[int, int] = (-120, -21),
    event_window: tuple[int, int] = (-5, 5),
    model: Literal["market_model", "market_adjusted"] = "market_model",
    min_est_obs: int = 30,
) -> tuple[pd.DataFrame, dict[str, StatResult]]:
    """执行标准事件研究, 计算逐事件 CAR/BHAR/SCAR 与横截面 BMP 显著性检验

    支持两种正常收益基准模型:
    - "market_model": 估计窗口 OLS 拟合 r_i = alpha + beta * r_m + eps
    - "market_adjusted": 设 alpha = 0, beta = 1, AR = r_i - r_m
    显著性检验包含普通横截面 t 检验以及 Boehmer-Musumeci-Poulsen (1991) 标准化横截面检验 (BMP),
    BMP 检验对事件窗口期方差膨胀具有稳健性

    Args:
        events: 标准 EventTable DataFrame, 必含列 event_id, event_date, ticker, event_type
        stock_returns: 个股日频简单收益率 SignalSeries (MultiIndex(date, ticker))
        market_returns: 市场基准日频简单收益率 TimeSeriesFrame (DatetimeIndex(name="date"))
        est_window: 相对事件日 0 的估计窗口闭区间 (start, end), 须满足 start < end < event_window[0], 默认 (-120, -21)
        event_window: 相对事件日 0 的事件窗口闭区间 (start, end), 须满足 start <= end, 默认 (-5, 5)
        model: 正常收益模型, "market_model" (默认) 或 "market_adjusted"
        min_est_obs: 估计窗口最少有效交易日数, 须 >= 5, 默认 30

    Returns:
        tuple[pd.DataFrame, dict[str, StatResult]]:
            - DataFrame: 逐事件明细表, 含 event_id, event_date, ticker, event_type,
              alpha, beta, car, bhar, scar, est_obs, event_obs
            - dict[str, StatResult]: 包含 car_mean, car_bmp, bhar_mean 三项汇总统计检验

    Raises:
        DataContractError: events, stock_returns 或 market_returns 违反数据契约
        ValueError: 窗口边界重叠或参数非法

    Example:
        >>> dates = pd.date_range("2023-01-02", periods=160, freq="B", name="date")
        >>> mkt = pd.Series(0.0005, index=dates, name="mkt")
        >>> idx = pd.MultiIndex.from_product([dates, ["A", "B", "C"]], names=["date", "ticker"])
        >>> stk = pd.Series(0.0005, index=idx, name="ret")
        >>> ev = pd.DataFrame({
        ...     "event_id": ["e1", "e2", "e3"],
        ...     "event_date": [dates[130], dates[130], dates[130]],
        ...     "ticker": ["A", "B", "C"],
        ...     "event_type": ["sp500_add"] * 3,
        ... })
        >>> df_ev, stats = run_event_study(ev, stk, mkt, est_window=(-100, -11), event_window=(-2, 2))
        >>> len(df_ev)
        3
    """
    _validate_event_table(events)
    validate_signal(stock_returns, name="run_event_study(stock_returns)")
    validate_timeseries(market_returns, name="run_event_study(market_returns)")

    if model not in ("market_model", "market_adjusted"):
        raise ValueError(f"Unsupported event study model: {model!r}")
    est_lo, est_hi = est_window
    ev_lo, ev_hi = event_window
    if est_lo >= est_hi:
        raise ValueError(f"est_window must satisfy start < end, got {est_window}")
    if ev_lo > ev_hi:
        raise ValueError(f"event_window must satisfy start <= end, got {event_window}")
    if est_hi >= ev_lo:
        raise ValueError(f"est_window {est_window} must end strictly before event_window {event_window}")
    if min_est_obs < 5:
        raise ValueError(f"min_est_obs must be >= 5, got {min_est_obs}")

    mkt_clean = market_returns.astype(float).dropna()
    cal = mkt_clean.index
    cal_len = len(cal)
    expected_ev_len = ev_hi - ev_lo + 1

    # 按 ticker 预分组以加速多事件查询
    stk_by_ticker: dict[str, pd.Series] = {}
    for tkr, grp in stock_returns.astype(float).groupby(level="ticker", sort=False):
        s = grp.droplevel("ticker")
        stk_by_ticker[str(tkr)] = s

    rows: list[dict[str, object]] = []
    for row in events.itertuples(index=False):
        ev_id = row.event_id
        ev_dt = pd.Timestamp(row.event_date)
        tkr = str(row.ticker)
        ev_type = str(row.event_type)

        stk_s = stk_by_ticker.get(tkr)
        if stk_s is None or cal_len == 0:
            continue

        # 映射事件日到首个 >= event_date 的基准交易日
        pos = int(cal.searchsorted(ev_dt, side="left"))
        if pos >= cal_len:
            continue
        if pos + est_lo < 0 or pos + ev_hi >= cal_len:
            continue

        est_dates = cal[pos + est_lo : pos + est_hi + 1]
        ev_dates = cal[pos + ev_lo : pos + ev_hi + 1]

        est_df = pd.concat(
            [stk_s.reindex(est_dates).rename("r"), mkt_clean.reindex(est_dates).rename("rm")],
            axis=1,
        ).dropna()
        ev_df = pd.concat(
            [stk_s.reindex(ev_dates).rename("r"), mkt_clean.reindex(ev_dates).rename("rm")],
            axis=1,
        ).dropna()

        m_obs = len(est_df)
        l2 = len(ev_df)
        if m_obs < min_est_obs or l2 < expected_ev_len:
            continue

        r_est = est_df["r"].to_numpy(dtype=float)
        rm_est = est_df["rm"].to_numpy(dtype=float)
        r_ev = ev_df["r"].to_numpy(dtype=float)
        rm_ev = ev_df["rm"].to_numpy(dtype=float)

        if model == "market_model":
            rm_mean = float(np.mean(rm_est))
            sxx = float(np.sum((rm_est - rm_mean) ** 2))
            if sxx <= 0.0:
                continue
            x_mat = np.column_stack([np.ones(m_obs, dtype=float), rm_est])
            coef, *_ = np.linalg.lstsq(x_mat, r_est, rcond=None)
            alpha = float(coef[0])
            beta = float(coef[1])
            est_resid = r_est - (alpha + beta * rm_est)
            sigma2 = float(np.dot(est_resid, est_resid) / float(m_obs - 2))
            expected_r = alpha + beta * rm_ev
            ar = r_ev - expected_r
            car = float(np.sum(ar))
            sum_rm_dev = float(np.sum(rm_ev - rm_mean))
            car_var = sigma2 * (float(l2) + (float(l2) ** 2) / float(m_obs) + (sum_rm_dev**2) / sxx)
        else:
            alpha = 0.0
            beta = 1.0
            est_ar = r_est - rm_est
            sigma2 = float(np.var(est_ar, ddof=1))
            expected_r = rm_ev
            ar = r_ev - expected_r
            car = float(np.sum(ar))
            car_var = sigma2 * float(l2)

        bhar = float(np.prod(1.0 + r_ev) - np.prod(1.0 + expected_r))
        scar = float(car / np.sqrt(car_var)) if car_var > 0.0 else float("nan")

        rows.append(
            {
                "event_id": ev_id,
                "event_date": cal[pos],
                "ticker": tkr,
                "event_type": ev_type,
                "alpha": alpha,
                "beta": beta,
                "car": car,
                "bhar": bhar,
                "scar": scar,
                "est_obs": m_obs,
                "event_obs": l2,
            }
        )

    out_cols = [
        "event_id",
        "event_date",
        "ticker",
        "event_type",
        "alpha",
        "beta",
        "car",
        "bhar",
        "scar",
        "est_obs",
        "event_obs",
    ]
    ev_results = pd.DataFrame(rows, columns=out_cols)

    meta_common = {
        "model": model,
        "est_window": est_window,
        "event_window": event_window,
        "total_events": len(events),
        "valid_events": len(ev_results),
    }

    car_mean = _one_sample_t_result(ev_results["car"].to_numpy(dtype=float), name="car_mean", meta=meta_common)
    car_bmp = _one_sample_t_result(ev_results["scar"].to_numpy(dtype=float), name="car_bmp", meta=meta_common)
    bhar_mean = _one_sample_t_result(ev_results["bhar"].to_numpy(dtype=float), name="bhar_mean", meta=meta_common)

    return ev_results, {
        "car_mean": car_mean,
        "car_bmp": car_bmp,
        "bhar_mean": bhar_mean,
    }
