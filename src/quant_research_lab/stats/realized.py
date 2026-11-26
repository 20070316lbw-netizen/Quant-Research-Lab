"""由单只资产的日内行情计算已实现方差"""

import numpy as np
import pandas as pd

from quant_research_lab.data.contracts import validate_timeseries


def realized_semivariance(bars: pd.DataFrame) -> pd.DataFrame:
    """按自然交易日拆分日内对数收益的正负半方差

    Args:
        bars: 单只资产的 open 和 close 价格, 索引为升序唯一、
            无时区的 DatetimeIndex(name="date"), 使用交易所当地时间
            调用方先按交易日历筛选完整交易时段

    Returns:
        DataFrame: 日期索引 date, 列 rsp、rsn、rv 为上行、下行及总方差,
        单位为小数收益平方, 未年化, 首根从开盘计算, 后续使用上根收盘,
        单根也可计算, 空输入返回空表

    Raises:
        ValueError: 索引不符合时间序列契约、缺列、价格缺失或非正、非有限

    Example:
        >>> import pandas as pd
        >>> idx = pd.DatetimeIndex(["2020-01-02 10:00"], name="date")
        >>> bars = pd.DataFrame({"open": [10.0], "close": [10.0]}, index=idx)
        >>> realized_semivariance(bars).iloc[0].tolist()
        [0.0, 0.0, 0.0]
    """
    validate_timeseries(bars, required_cols=("open", "close"))
    prices = bars[["open", "close"]].astype(float)

    if not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any():
        raise ValueError("open 与 close 必须是有效正价格")
    day = prices.index.normalize()
    previous = prices.close.groupby(day).shift().fillna(prices.open)
    returns = np.log(prices.close / previous)
    squared = pd.DataFrame(
        {
            "rsp": returns.clip(lower=0) ** 2,
            "rsn": returns.clip(upper=0) ** 2,
            "rv": returns**2,
        }
    )
    return squared.groupby(day).sum()
