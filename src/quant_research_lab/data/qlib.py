"""Qlib 原生二进制行情字段读取"""

from pathlib import Path

import numpy as np
import pandas as pd


def read_qlib_feature(path: Path, calendar: pd.DatetimeIndex) -> pd.Series:
    """用配套日历还原单个 Qlib 字段的观测日期

    Args:
        path: 原生 .bin 字段路径, 小端 float32, 首元素为起始位置
        calendar: 同频完整交易日历, 无时区且升序唯一

    Returns:
        Series: date 索引, name 为文件名第一个点之前的部分, float64 数值
        保留文件原单位与缺失值, 只有起点而无观测时返回空序列

    Raises:
        ValueError: 日历无效、文件不完整或数据超出日历
        OSError: 文件读取失败

    Example:
        >>> from tempfile import TemporaryDirectory
        >>> import numpy as np
        >>> import pandas as pd
        >>> from pathlib import Path
        >>> with TemporaryDirectory() as folder:
        ...     path = Path(folder) / "close.day.bin"
        ...     np.array([1, 12], dtype="<f4").tofile(path)
        ...     read_qlib_feature(path, pd.date_range("2020-01-01", periods=2)).iloc[0].item()
        12.0
    """
    if (
        calendar.tz is not None
        or not calendar.is_monotonic_increasing
        or not calendar.is_unique
    ):
        raise ValueError("交易日历必须无时区并按时间严格递增")
    raw = np.frombuffer(Path(path).read_bytes(), dtype="<f4")
    if not raw.size or not float(raw[0]).is_integer() or raw[0] < 0:
        raise ValueError("Qlib 字段缺少有效的日历起点")
    start = int(raw[0])
    stop = start + len(raw) - 1
    if stop > len(calendar):
        raise ValueError("Qlib 字段超出交易日历")
    return pd.Series(
        raw[1:].astype(float),
        index=calendar[start:stop].rename("date"),
        name=Path(path).name.split(".")[0],
    )
