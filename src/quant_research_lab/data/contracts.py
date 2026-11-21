"""内存标准数据格式运行时校验器

规范参见 design/02b-data-contracts.md:
- PanelFrame: MultiIndex(date, ticker) 的 DataFrame, 无时区日期, 升序无重复
- SignalSeries: MultiIndex(date, ticker) 的 float64 Series, 不含 +/-inf
- TimeSeriesFrame: DatetimeIndex(date) 的 DataFrame 或 Series, 无时区升序无重复
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import wraps
from typing import ParamSpec, TypeVar

import numpy as np
import pandas as pd

P = ParamSpec("P")
R = TypeVar("R")


class DataContractError(ValueError):
    """输入或输出违反项目数据格式契约时抛出的异常"""


def _validate_date_index(idx: pd.Index, *, label: str) -> None:
    if not isinstance(idx, pd.DatetimeIndex):
        raise DataContractError(f"{label}: expected DatetimeIndex, got {type(idx).__name__}")
    if idx.tz is not None:
        raise DataContractError(f"{label}: date index must be tz-naive, got tz={idx.tz}")


def validate_panel(
    df: pd.DataFrame,
    *,
    required_cols: Sequence[str] = (),
    allow_inf: bool = False,
    name: str = "PanelFrame",
) -> pd.DataFrame:
    """校验面板数据是否符合 MultiIndex(date, ticker) 标准契约

    Args:
        df: 待校验的面板 DataFrame, 索引须为升序无重复的 MultiIndex(date, ticker)
        required_cols: 必须包含的列名序列, 默认为空元组
        allow_inf: 是否允许出现 +/-inf, 默认 False
        name: 错误信息中的对象标识名, 默认 "PanelFrame"

    Returns:
        pd.DataFrame: 通过校验的原 DataFrame, 索引与列保持不变

    Raises:
        DataContractError: 类型, 索引层级, 排序, 重复键, 缺失列或无穷值校验不通过

    Example:
        >>> idx = pd.MultiIndex.from_tuples(
        ...     [(pd.Timestamp("2024-01-02"), "AAPL")], names=["date", "ticker"]
        ... )
        >>> df = pd.DataFrame({"close": [185.0]}, index=idx)
        >>> validate_panel(df, required_cols=("close",)).shape
        (1, 1)
    """
    if not isinstance(df, pd.DataFrame):
        raise DataContractError(f"{name}: expected DataFrame, got {type(df).__name__}")
    if not isinstance(df.index, pd.MultiIndex) or df.index.nlevels != 2:
        raise DataContractError(f"{name}: index must be a 2-level MultiIndex(date, ticker)")
    if list(df.index.names) != ["date", "ticker"]:
        raise DataContractError(f"{name}: index names must be ['date', 'ticker'], got {list(df.index.names)}")

    _validate_date_index(df.index.levels[0], label=f"{name}.index[0]")

    if not df.index.is_monotonic_increasing:
        raise DataContractError(f"{name}: MultiIndex(date, ticker) must be sorted ascending")
    if df.index.has_duplicates:
        raise DataContractError(f"{name}: duplicate (date, ticker) keys detected")

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise DataContractError(f"{name}: missing required columns {missing}")

    if not allow_inf:
        num_df = df.select_dtypes(include=[np.number])
        if not num_df.empty and np.isinf(num_df.to_numpy(dtype=float, copy=False)).any():
            raise DataContractError(f"{name}: contains +/-inf values")

    return df


def validate_signal(s: pd.Series, *, allow_inf: bool = False, name: str = "SignalSeries") -> pd.Series:
    """校验单因子或单信号 Series 是否符合 MultiIndex(date, ticker) 标准契约

    Args:
        s: 待校验的数值型 Series, 索引须为升序无重复的 MultiIndex(date, ticker)
        allow_inf: 是否允许出现 +/-inf, 默认 False
        name: 错误信息中的对象标识名, 默认 "SignalSeries"

    Returns:
        pd.Series: 通过校验的原 Series, 允许包含 NaN

    Raises:
        DataContractError: 类型, 索引, 排序, 重复键, 非数值类型或无穷值校验不通过

    Example:
        >>> idx = pd.MultiIndex.from_tuples(
        ...     [(pd.Timestamp("2024-01-02"), "AAPL")], names=["date", "ticker"]
        ... )
        >>> s = pd.Series([0.5], index=idx, name="mom")
        >>> validate_signal(s).name
        'mom'
    """
    if not isinstance(s, pd.Series):
        raise DataContractError(f"{name}: expected Series, got {type(s).__name__}")
    if not isinstance(s.index, pd.MultiIndex) or s.index.nlevels != 2:
        raise DataContractError(f"{name}: index must be a 2-level MultiIndex(date, ticker)")
    if list(s.index.names) != ["date", "ticker"]:
        raise DataContractError(f"{name}: index names must be ['date', 'ticker'], got {list(s.index.names)}")

    _validate_date_index(s.index.levels[0], label=f"{name}.index[0]")

    if not s.index.is_monotonic_increasing:
        raise DataContractError(f"{name}: MultiIndex(date, ticker) must be sorted ascending")
    if s.index.has_duplicates:
        raise DataContractError(f"{name}: duplicate (date, ticker) keys detected")
    if not pd.api.types.is_numeric_dtype(s.dtype):
        raise DataContractError(f"{name}: dtype must be numeric, got {s.dtype}")
    if not allow_inf and np.isinf(s.to_numpy(dtype=float, copy=False)).any():
        raise DataContractError(f"{name}: contains +/-inf values")

    return s


def validate_timeseries(
    obj: pd.DataFrame | pd.Series,
    *,
    required_cols: Sequence[str] = (),
    allow_inf: bool = False,
    name: str = "TimeSeriesFrame",
) -> pd.DataFrame | pd.Series:
    """校验时间序列是否符合 DatetimeIndex(date) 标准契约

    Args:
        obj: 待校验的 DataFrame 或 Series, 索引须为无时区升序无重复的 DatetimeIndex(name="date")
        required_cols: obj 为 DataFrame 时必须包含的列名, 默认为空元组
        allow_inf: 是否允许出现 +/-inf, 默认 False
        name: 错误信息中的对象标识名, 默认 "TimeSeriesFrame"

    Returns:
        pd.DataFrame | pd.Series: 通过校验的原对象

    Raises:
        DataContractError: 类型, 索引名, 时区, 排序, 重复日期, 缺失列或无穷值校验不通过

    Example:
        >>> idx = pd.DatetimeIndex(["2024-01-02"], name="date")
        >>> s = pd.Series([0.01], index=idx, name="ret")
        >>> validate_timeseries(s).index.name
        'date'
    """
    if not isinstance(obj, (pd.DataFrame, pd.Series)):
        raise DataContractError(f"{name}: expected DataFrame or Series, got {type(obj).__name__}")
    if obj.index.name != "date":
        raise DataContractError(f"{name}: index name must be 'date', got {obj.index.name!r}")
    _validate_date_index(obj.index, label=name)
    if not obj.index.is_monotonic_increasing:
        raise DataContractError(f"{name}: DatetimeIndex must be sorted ascending")
    if obj.index.has_duplicates:
        raise DataContractError(f"{name}: duplicate dates detected")

    if isinstance(obj, pd.DataFrame):
        missing = [c for c in required_cols if c not in obj.columns]
        if missing:
            raise DataContractError(f"{name}: missing required columns {missing}")
        if not allow_inf:
            num_df = obj.select_dtypes(include=[np.number])
            if not num_df.empty and np.isinf(num_df.to_numpy(dtype=float, copy=False)).any():
                raise DataContractError(f"{name}: contains +/-inf values")
    elif not allow_inf and pd.api.types.is_numeric_dtype(obj.dtype):
        if np.isinf(obj.to_numpy(dtype=float, copy=False)).any():
            raise DataContractError(f"{name}: contains +/-inf values")

    return obj


def require_panel(
    arg: str = "prices",
    *,
    required_cols: Sequence[str] = (),
    allow_inf: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """为公开计算函数绑定 PanelFrame 入参契约校验的装饰器

    Args:
        arg: 需要校验的参数名, 默认 "prices"
        required_cols: 必须包含的列名序列, 默认为空元组
        allow_inf: 是否允许出现 +/-inf, 默认 False

    Returns:
        Callable: 包装后的函数装饰器

    Raises:
        DataContractError: 目标参数不存在或传入数据不满足 PanelFrame 契约

    Example:
        >>> @require_panel("prices", required_cols=("close",))
        ... def dummy(prices: pd.DataFrame) -> int:
        ...     return len(prices)
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        import inspect

        sig = inspect.signature(fn)

        @wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            if arg not in bound.arguments:
                raise DataContractError(f"Decorator @require_panel: argument {arg!r} not found in {fn.__name__}")
            validate_panel(
                bound.arguments[arg],
                required_cols=required_cols,
                allow_inf=allow_inf,
                name=f"{fn.__name__}({arg})",
            )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
