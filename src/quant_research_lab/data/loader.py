"""标准数据读取器

从本地 DuckDB (默认 data/lab.duckdb) 以只读模式加载行情, 成分股, 日历与基准因子,
统一转换为符合 design/02b-data-contracts.md 规范的内存对象:
- PanelFrame: MultiIndex(date, ticker), 无时区 datetime64[ns], 升序无重复
- TimeSeriesFrame: DatetimeIndex(date), 无时区 datetime64[ns], 升序无重复
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from quant_research_lab.data.contracts import validate_panel, validate_timeseries
from quant_research_lab.db.operation import get_duckdb

DateLike = str | date | datetime | pd.Timestamp

DEFAULT_DB_PATH = Path("data/lab.duckdb")

PRICE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "adj_close", "volume")
UNIVERSE_COLUMNS: tuple[str, ...] = ("cik", "name", "exchange", "sic", "sub_industry")
FF_FACTOR_COLUMNS: tuple[str, ...] = (
    "mkt_rf",
    "smb",
    "hml",
    "rmw",
    "cma",
    "rf",
    "mom",
    "st_rev",
    "lt_rev",
)
AQR_FACTOR_COLUMNS: tuple[str, ...] = (
    "aqr_bab_usa",
    "aqr_qmj_usa",
    "aqr_hml_devil_usa",
)
VOL_INDEX_COLUMNS: tuple[str, ...] = (
    "vix_open",
    "vix_high",
    "vix_low",
    "vix_close",
    "vix3m_open",
    "vix3m_high",
    "vix3m_low",
    "vix3m_close",
    "vvix_close",
    "skew_close",
)


def _normalize_date(value: DateLike | None, *, param_name: str) -> str | None:
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        raise ValueError(f"{param_name} cannot be NaT")
    if ts.tzinfo is not None:
        raise ValueError(f"{param_name} must be tz-naive, got tz={ts.tzinfo}")
    return ts.strftime("%Y-%m-%d")


def _validate_date_bounds(
    start_date: DateLike | None,
    end_date: DateLike | None,
) -> tuple[str | None, str | None]:
    start_str = _normalize_date(start_date, param_name="start_date")
    end_str = _normalize_date(end_date, param_name="end_date")
    if start_str is not None and end_str is not None and start_str > end_str:
        raise ValueError(f"start_date ({start_str}) must be <= end_date ({end_str})")
    return start_str, end_str


def _validate_columns(
    columns: Sequence[str] | None,
    *,
    allowed: tuple[str, ...],
    table: str,
) -> tuple[str, ...]:
    if columns is None:
        return allowed
    cols = tuple(dict.fromkeys(columns))
    if not cols:
        raise ValueError(f"{table}: columns must not be empty")
    invalid = [c for c in cols if c not in allowed]
    if invalid:
        raise ValueError(f"{table}: unsupported columns {invalid}, allowed={list(allowed)}")
    return cols


def _to_panel_frame(
    raw: pd.DataFrame,
    *,
    columns: Sequence[str],
    name: str,
) -> pd.DataFrame:
    if raw.empty:
        empty_idx = pd.MultiIndex.from_arrays(
            [
                pd.DatetimeIndex([], dtype="datetime64[ns]", name="date"),
                pd.Index([], dtype="str", name="ticker"),
            ]
        )
        df = pd.DataFrame(index=empty_idx)
        for col in columns:
            df[col] = pd.Series(dtype="int64" if col == "volume" else "float64", index=empty_idx)
        return validate_panel(df, required_cols=columns, name=name)

    dates = pd.to_datetime(raw["date"]).astype("datetime64[ns]")
    tickers = raw["ticker"].astype("str")
    idx = pd.MultiIndex.from_arrays([dates, tickers], names=["date", "ticker"])
    df = raw.loc[:, list(columns)].copy()
    df.index = idx
    if not df.index.is_monotonic_increasing:
        df = df.sort_index()
    return validate_panel(df, required_cols=columns, name=name)


def _to_timeseries_frame(
    raw: pd.DataFrame,
    *,
    columns: Sequence[str],
    name: str,
) -> pd.DataFrame:
    if raw.empty:
        empty_idx = pd.DatetimeIndex([], dtype="datetime64[ns]", name="date")
        df = pd.DataFrame({col: pd.Series(dtype="float64", index=empty_idx) for col in columns})
        return validate_timeseries(df, required_cols=columns, name=name)

    dates = pd.DatetimeIndex(pd.to_datetime(raw["date"]).astype("datetime64[ns]"), name="date")
    df = raw.loc[:, list(columns)].copy()
    df.index = dates
    if not df.index.is_monotonic_increasing:
        df = df.sort_index()
    return validate_timeseries(df, required_cols=columns, name=name)


def load_prices(
    start_date: DateLike | None = None,
    end_date: DateLike | None = None,
    *,
    sp500_only: bool = True,
    tickers: Sequence[str] | None = None,
    columns: Sequence[str] = PRICE_COLUMNS,
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    """从 DuckDB 加载日频价量面板数据并返回标准 PanelFrame

    当 sp500_only=True 时, 严格按 Point-in-Time (PIT) 规则对每个交易日匹配
    snapshot_date <= date 的最新一期 universe 成分股快照, 避免幸存者偏差

    Args:
        start_date: 起始交易日 (含), 支持 YYYY-MM-DD 字符串, date 或无时区 Timestamp, 默认 None 不限
        end_date: 结束交易日 (含), 格式同 start_date, 默认 None 不限
        sp500_only: 是否仅保留当日 PIT S&P 500 成分股, 默认 True
        tickers: 可选标的列表过滤 (分段 ticker 名称), 默认 None 不限
        columns: 需要读取的价量列名子集, 默认全部 6 列 (open, high, low, close, adj_close, volume)
        db_path: DuckDB 文件路径, 默认 Path("data/lab.duckdb")

    Returns:
        pd.DataFrame: 通过 validate_panel 校验的标准 PanelFrame
            索引为升序无重复的 MultiIndex(date, ticker), date 为无时区 datetime64[ns]
            无匹配记录时返回结构完整且含目标列的空 PanelFrame

    Raises:
        FileNotFoundError: 数据库文件不存在
        ValueError: 日期范围非法, 日期含时区或 columns 包含不支持的列名
        DataContractError: 返回结果违反 PanelFrame 数据契约

    Example:
        >>> df = load_prices("2024-01-02", "2024-01-05", tickers=["AAPL", "MSFT"])
        >>> list(df.index.names)
        ['date', 'ticker']
    """
    start_str, end_str = _validate_date_bounds(start_date, end_date)
    cols = _validate_columns(columns, allowed=PRICE_COLUMNS, table="prices")

    where_clauses: list[str] = []
    params: list[object] = []

    if start_str is not None:
        where_clauses.append("p.date >= CAST(? AS DATE)")
        params.append(start_str)
    if end_str is not None:
        where_clauses.append("p.date <= CAST(? AS DATE)")
        params.append(end_str)

    ticker_list: list[str] | None = None
    if tickers is not None:
        ticker_list = list(dict.fromkeys(str(t) for t in tickers))
        if not ticker_list:
            return _to_panel_frame(pd.DataFrame(), columns=cols, name="load_prices")
        placeholders = ", ".join(["?"] * len(ticker_list))
        where_clauses.append(f"p.ticker IN ({placeholders})")
        params.extend(ticker_list)

    select_cols = ", ".join(f"p.{c}" for c in cols)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    if sp500_only:
        date_filters: list[str] = []
        date_params: list[object] = []
        if start_str is not None:
            date_filters.append("c.date >= CAST(? AS DATE)")
            date_params.append(start_str)
        if end_str is not None:
            date_filters.append("c.date <= CAST(? AS DATE)")
            date_params.append(end_str)
        cal_where = f"WHERE {' AND '.join(date_filters)}" if date_filters else ""

        sql = f"""
            WITH snap_dates AS (
                SELECT DISTINCT snapshot_date
                FROM universe
            ),
            date_snap AS (
                SELECT c.date, max(s.snapshot_date) AS snapshot_date
                FROM calendar AS c
                JOIN snap_dates AS s
                  ON s.snapshot_date <= c.date
                {cal_where}
                GROUP BY c.date
            )
            SELECT p.date, p.ticker, {select_cols}
            FROM prices AS p
            JOIN date_snap AS ds
              ON p.date = ds.date
            JOIN universe AS u
              ON u.snapshot_date = ds.snapshot_date
             AND u.ticker = p.ticker
            {where_sql}
            ORDER BY p.date ASC, p.ticker ASC
        """
        query_params = date_params + params
    else:
        sql = f"""
            SELECT p.date, p.ticker, {select_cols}
            FROM prices AS p
            {where_sql}
            ORDER BY p.date ASC, p.ticker ASC
        """
        query_params = params

    with get_duckdb(path=db_path, read_only=True) as con:
        raw = con.execute(sql, query_params).df()

    return _to_panel_frame(raw, columns=cols, name="load_prices")


def load_universe_panel(
    start_date: DateLike | None = None,
    end_date: DateLike | None = None,
    *,
    columns: Sequence[str] = UNIVERSE_COLUMNS,
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    """将稀疏 PIT S&P 500 成分股快照展开到交易日历并返回标准 PanelFrame

    每个交易日匹配 snapshot_date <= date 的最新一期快照, 用于行业中性化与成分股掩码

    Args:
        start_date: 起始交易日 (含), 默认 None 不限
        end_date: 结束交易日 (含), 默认 None 不限
        columns: 需要读取的成分股属性列, 默认全部 5 列 (cik, name, exchange, sic, sub_industry)
        db_path: DuckDB 文件路径, 默认 Path("data/lab.duckdb")

    Returns:
        pd.DataFrame: 通过 validate_panel 校验的成分股 PanelFrame, 索引为 MultiIndex(date, ticker)

    Raises:
        FileNotFoundError: 数据库文件不存在
        ValueError: 日期范围非法, 日期含时区或 columns 包含不支持的列名
        DataContractError: 返回结果违反 PanelFrame 数据契约

    Example:
        >>> univ = load_universe_panel("2024-01-02", "2024-01-03", columns=("cik", "sub_industry"))
        >>> list(univ.index.names)
        ['date', 'ticker']
    """
    start_str, end_str = _validate_date_bounds(start_date, end_date)
    cols = _validate_columns(columns, allowed=UNIVERSE_COLUMNS, table="universe")

    date_filters: list[str] = []
    params: list[object] = []
    if start_str is not None:
        date_filters.append("c.date >= CAST(? AS DATE)")
        params.append(start_str)
    if end_str is not None:
        date_filters.append("c.date <= CAST(? AS DATE)")
        params.append(end_str)
    cal_where = f"WHERE {' AND '.join(date_filters)}" if date_filters else ""

    select_cols = ", ".join(f"u.{c}" for c in cols)
    sql = f"""
        WITH snap_dates AS (
            SELECT DISTINCT snapshot_date
            FROM universe
        ),
        date_snap AS (
            SELECT c.date, max(s.snapshot_date) AS snapshot_date
            FROM calendar AS c
            JOIN snap_dates AS s
              ON s.snapshot_date <= c.date
            {cal_where}
            GROUP BY c.date
        )
        SELECT ds.date, u.ticker, {select_cols}
        FROM date_snap AS ds
        JOIN universe AS u
          ON u.snapshot_date = ds.snapshot_date
        ORDER BY ds.date ASC, u.ticker ASC
    """

    with get_duckdb(path=db_path, read_only=True) as con:
        raw = con.execute(sql, params).df()

    if raw.empty:
        empty_idx = pd.MultiIndex.from_arrays(
            [
                pd.DatetimeIndex([], dtype="datetime64[ns]", name="date"),
                pd.Index([], dtype="str", name="ticker"),
            ]
        )
        df = pd.DataFrame({col: pd.Series(dtype="str", index=empty_idx) for col in cols})
        return validate_panel(df, required_cols=cols, name="load_universe_panel")

    return _to_panel_frame(raw, columns=cols, name="load_universe_panel")


def load_calendar(
    start_date: DateLike | None = None,
    end_date: DateLike | None = None,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DatetimeIndex:
    """加载美股交易日历并返回无时区升序 DatetimeIndex

    Args:
        start_date: 起始日期 (含), 默认 None 不限
        end_date: 结束日期 (含), 默认 None 不限
        db_path: DuckDB 文件路径, 默认 Path("data/lab.duckdb")

    Returns:
        pd.DatetimeIndex: name="date", dtype="datetime64[ns]", 无时区升序无重复的交易日索引

    Raises:
        FileNotFoundError: 数据库文件不存在
        ValueError: 日期范围非法或日期含时区

    Example:
        >>> cal = load_calendar("2024-01-02", "2024-01-05")
        >>> cal.name
        'date'
    """
    start_str, end_str = _validate_date_bounds(start_date, end_date)
    where_clauses: list[str] = []
    params: list[object] = []
    if start_str is not None:
        where_clauses.append("date >= CAST(? AS DATE)")
        params.append(start_str)
    if end_str is not None:
        where_clauses.append("date <= CAST(? AS DATE)")
        params.append(end_str)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    sql = f"SELECT date FROM calendar {where_sql} ORDER BY date ASC"
    with get_duckdb(path=db_path, read_only=True) as con:
        raw = con.execute(sql, params).df()

    if raw.empty:
        return pd.DatetimeIndex([], dtype="datetime64[ns]", name="date")
    return pd.DatetimeIndex(pd.to_datetime(raw["date"]).astype("datetime64[ns]"), name="date")


def _load_daily_timeseries(
    table: str,
    *,
    allowed_cols: tuple[str, ...],
    start_date: DateLike | None,
    end_date: DateLike | None,
    columns: Sequence[str] | None,
    db_path: Path,
    name: str,
) -> pd.DataFrame:
    start_str, end_str = _validate_date_bounds(start_date, end_date)
    cols = _validate_columns(columns, allowed=allowed_cols, table=table)

    where_clauses: list[str] = []
    params: list[object] = []
    if start_str is not None:
        where_clauses.append("date >= CAST(? AS DATE)")
        params.append(start_str)
    if end_str is not None:
        where_clauses.append("date <= CAST(? AS DATE)")
        params.append(end_str)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    select_cols = ", ".join(cols)
    sql = f"SELECT date, {select_cols} FROM {table} {where_sql} ORDER BY date ASC"
    with get_duckdb(path=db_path, read_only=True) as con:
        raw = con.execute(sql, params).df()

    return _to_timeseries_frame(raw, columns=cols, name=name)


def load_ff_factors(
    start_date: DateLike | None = None,
    end_date: DateLike | None = None,
    *,
    columns: Sequence[str] | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    """加载 Kenneth French 日频因子序列并返回标准 TimeSeriesFrame

    所有收益率列均已转换为小数形式 (例如 0.01 代表 1%)

    Args:
        start_date: 起始日期 (含), 默认 None 不限
        end_date: 结束日期 (含), 默认 None 不限
        columns: 需要读取的因子列子集, 默认 None 读取全部 9 列
        db_path: DuckDB 文件路径, 默认 Path("data/lab.duckdb")

    Returns:
        pd.DataFrame: 通过 validate_timeseries 校验的日频因子 DataFrame, 索引为 DatetimeIndex(name="date")

    Raises:
        FileNotFoundError: 数据库文件不存在
        ValueError: 日期范围非法, 日期含时区或 columns 包含不支持的列名
        DataContractError: 返回结果违反 TimeSeriesFrame 数据契约

    Example:
        >>> ff = load_ff_factors("2024-01-02", "2024-01-05", columns=("mkt_rf", "rf"))
        >>> ff.index.name
        'date'
    """
    return _load_daily_timeseries(
        "ff_factors_daily",
        allowed_cols=FF_FACTOR_COLUMNS,
        start_date=start_date,
        end_date=end_date,
        columns=columns,
        db_path=db_path,
        name="load_ff_factors",
    )


def load_aqr_factors(
    start_date: DateLike | None = None,
    end_date: DateLike | None = None,
    *,
    columns: Sequence[str] | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    """加载 AQR 日频因子序列 (BAB, QMJ, HML-Devil) 并返回标准 TimeSeriesFrame

    Args:
        start_date: 起始日期 (含), 默认 None 不限
        end_date: 结束日期 (含), 默认 None 不限
        columns: 需要读取的因子列子集, 默认 None 读取全部 3 列
        db_path: DuckDB 文件路径, 默认 Path("data/lab.duckdb")

    Returns:
        pd.DataFrame: 通过 validate_timeseries 校验的日频因子 DataFrame, 索引为 DatetimeIndex(name="date")

    Raises:
        FileNotFoundError: 数据库文件不存在
        ValueError: 日期范围非法, 日期含时区或 columns 包含不支持的列名
        DataContractError: 返回结果违反 TimeSeriesFrame 数据契约

    Example:
        >>> aqr = load_aqr_factors("2024-01-02", "2024-01-05")
        >>> list(aqr.columns)
        ['aqr_bab_usa', 'aqr_qmj_usa', 'aqr_hml_devil_usa']
    """
    return _load_daily_timeseries(
        "aqr_factors_daily",
        allowed_cols=AQR_FACTOR_COLUMNS,
        start_date=start_date,
        end_date=end_date,
        columns=columns,
        db_path=db_path,
        name="load_aqr_factors",
    )


def load_vol_indices(
    start_date: DateLike | None = None,
    end_date: DateLike | None = None,
    *,
    columns: Sequence[str] | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    """加载 CBOE 日频波动率与偏度指数 (VIX, VIX3M, VVIX, SKEW) 并返回标准 TimeSeriesFrame

    Args:
        start_date: 起始日期 (含), 默认 None 不限
        end_date: 结束日期 (含), 默认 None 不限
        columns: 需要读取的指数列子集, 默认 None 读取全部 10 列
        db_path: DuckDB 文件路径, 默认 Path("data/lab.duckdb")

    Returns:
        pd.DataFrame: 通过 validate_timeseries 校验的波动率指数 DataFrame, 索引为 DatetimeIndex(name="date")

    Raises:
        FileNotFoundError: 数据库文件不存在
        ValueError: 日期范围非法, 日期含时区或 columns 包含不支持的列名
        DataContractError: 返回结果违反 TimeSeriesFrame 数据契约

    Example:
        >>> vol = load_vol_indices("2024-01-02", "2024-01-05", columns=("vix_close", "vix3m_close"))
        >>> vol.index.name
        'date'
    """
    return _load_daily_timeseries(
        "vol_indices_daily",
        allowed_cols=VOL_INDEX_COLUMNS,
        start_date=start_date,
        end_date=end_date,
        columns=columns,
        db_path=db_path,
        name="load_vol_indices",
    )
