"""打开 DuckDB 数据库, 默认只读

读取时直接使用 get_duckdb, 写入时传 read_only=False
连接用 with 管理, 或由调用方手动关闭
导入模块时不会连接数据库
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
from loguru import logger


def get_duckdb(*, path: Path, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    """打开 DuckDB 数据库连接

    Args:
        path: 数据库文件路径 (Path 或可转换为 Path 的字符串)
        read_only: 是否只读, 默认 True, 避免读取和回测时意外改写数据

    Returns:
        duckdb.DuckDBPyConnection: 数据库连接对象, 可用 with 管理生命周期

    Raises:
        FileNotFoundError: 只读模式下数据库不存在
        duckdb.Error: 打开失败、锁冲突或文件格式错误

    Notes:
        read_only=False 自动创建父目录和新数据库文件; 数据表由写入方法初始化
        只读连接不创建目录或文件
    """
    path = Path(path)
    if read_only and not path.exists():
        logger.error(f"数据库文件不存在: {path}")
        raise FileNotFoundError(f"Database file not found at {path}")
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)

    logger.debug(f"正在连接 DuckDB: {path} (read_only = {read_only})")
    return duckdb.connect(str(path), read_only=read_only)


def read_sql(sql: Path) -> str:
    """读取 sql 文件的文本

    Args:
        sql: *.sql 文件路径

    Returns:
        str: 文件内容
    """
    return Path(sql).read_text(encoding="utf-8")


def operation_sql(
    sql: str,
    ddl: str,
    connection: duckdb.DuckDBPyConnection,
    df: pd.DataFrame | None = None,
) -> int:
    """在事务中执行建表语句和写入语句

    Args:
        sql: 写入 SQL, 多条语句用分号分隔
            语句中的 df 指向同名参数, 不引用数据表时该参数为 None
        ddl: 建表 SQL, 表不存在时由此建表
        connection: 可写 DuckDB 连接, 调用前不应有未结束的事务
            本函数负责事务, 连接由调用方关闭
        df: 供 sql 引用的 DataFrame, 默认 None

    Returns:
        int: 最后一条语句返回的计数
        INSERT 时为写入行数
        写入失败时回滚, 已提交的数据保留

    Raises:
        duckdb.Error: 数据库只读, 字段不匹配或事务执行失败

    Example:
        >>> import duckdb
        >>> import pandas as pd
        >>> df = pd.DataFrame([{
        ...     "ticker": "AAPL", "name": "Apple Inc.",
        ...     "sub_industry": "Technology Hardware",
        ... }])
        >>> with duckdb.connect(":memory:") as connection:
        ...     operation_sql(
        ...         read_sql(SQL_DIR / "universe.sql"),
        ...         read_sql(SQL_DIR / "universe_ddl.sql"),
        ...         connection,
        ...         df,
        ...     )
        1
    """
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute(ddl)

        row = connection.execute(sql).fetchone()
        if row is None:
            raise ValueError("最后一条 SQL 没有返回写入数量")

        written = int(row[0])
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise

    return written
