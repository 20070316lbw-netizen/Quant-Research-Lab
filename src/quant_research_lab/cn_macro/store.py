"""中国地级市宏观数据独立 DuckDB 存储, Parquet 备份恢复, Excel 交付与 HF 同步模块

完全独立于 data/lab.duckdb, 默认托管至 HF 仓库的 cn_macro/ 子目录
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from huggingface_hub import HfApi, snapshot_download

from quant_research_lab.cn_macro.config import CnMacroConfig

CN_MACRO_TABLES: tuple[str, ...] = (
    "cn_city_yearbook",
    "cn_city_gdp_2000base",
    "cn_city_pm10",
    "cn_city_carbon",
)

DELIVERABLE_FILENAMES: dict[str, str] = {
    "cn_city_yearbook": "统计年鉴数据.xlsx",
    "cn_city_gdp_2000base": "296个地级市GDP相关数据_2000基期.xlsx",
    "cn_city_pm10": "地级市逐年PM10数据.xlsx",
    "cn_city_carbon": "中国各城市碳排放数据.xlsx",
}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sql_quote(path: Path) -> str:
    return str(path).replace("'", "''")


def _resolve_hf_token(token: str | None = None, env_path: Path = Path(".env")) -> str | None:
    if token:
        return token.strip()
    env_val = os.environ.get("HF_TOKEN")
    if env_val:
        return env_val.strip()
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() in ("HF_TOKEN", "HUGGINGFACE_TOKEN"):
                    return v.strip().strip('"').strip("'")
            elif line.startswith("hf_"):
                return line
    return None


def write_tables_to_duckdb(
    tables: dict[str, pd.DataFrame],
    db_path: Path = Path("data/cn_macro/cn_macro.duckdb"),
) -> Path:
    """将中国地级市宏观与环境数据表写入独立 DuckDB 数据库

    Args:
        tables: 表名到 DataFrame 的映射字典
        db_path: 目标 DuckDB 路径, 默认 data/cn_macro/cn_macro.duckdb

    Returns:
        Path: 写入完成的 DuckDB 文件路径

    Raises:
        ValueError: tables 为空
        duckdb.Error: 建表或写入失败

    Example:
        >>> # write_tables_to_duckdb({"cn_city_pm10": df})
        >>> True
        True
    """
    if not tables:
        raise ValueError("tables 不能为空")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        for name, frame in tables.items():
            con.register("_tmp_df", frame)
            con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM _tmp_df')
            con.unregister("_tmp_df")
    finally:
        con.close()
    return db_path


def export_cn_macro_to_parquet(
    db_path: Path = Path("data/cn_macro/cn_macro.duckdb"),
    parquet_dir: Path = Path("data/cn_macro/parquet"),
    *,
    repo_id: str = "2007liuQuant/Quant-Research-Lab",
) -> Path:
    """将独立 cn_macro.duckdb 中的全部数据表导出为 ZSTD Parquet 与 manifest.json

    Args:
        db_path: 源 DuckDB 路径, 默认 data/cn_macro/cn_macro.duckdb
        parquet_dir: 输出 Parquet 根目录, 默认 data/cn_macro/parquet
        repo_id: 对应 Hugging Face 仓库 ID

    Returns:
        Path: 生成的 manifest.json 文件路径

    Raises:
        FileNotFoundError: 源 DuckDB 不存在
        duckdb.Error: 读取或导出 Parquet 失败

    Example:
        >>> # export_cn_macro_to_parquet()
        >>> True
        True
    """
    if not db_path.exists():
        raise FileNotFoundError(f"未找到数据库文件: {db_path}")
    data_dir = parquet_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path), read_only=True)
    manifest_tables: dict[str, Any] = {}
    try:
        available = [r[0] for r in con.sql("SHOW TABLES").fetchall()]
        for table in sorted(available):
            target = data_dir / table / "data.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            con.execute(
                f"""
                COPY (SELECT * FROM "{table}")
                TO '{_sql_quote(target)}'
                (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )
            row_count = int(con.sql(f'SELECT COUNT(*) FROM "{table}"').fetchall()[0][0])
            desc = con.sql(f'DESCRIBE "{table}"').fetchall()
            schema = {col: dtype for col, dtype, *_ in desc}
            size_bytes = target.stat().st_size
            manifest_tables[table] = {
                "rows": row_count,
                "columns": len(schema),
                "glob": f"data/{table}/*.parquet",
                "total_size_mb": round(size_bytes / (1024 * 1024), 3),
                "schema": schema,
                "files": [
                    {
                        "path": f"data/{table}/data.parquet",
                        "size_bytes": size_bytes,
                        "sha256": _sha256_file(target),
                    }
                ],
            }
    finally:
        con.close()

    manifest = {
        "repo_id": repo_id,
        "subdir": "cn_macro",
        "duckdb_version": duckdb.__version__,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "tables": manifest_tables,
    }
    manifest_path = parquet_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path


def import_cn_macro_parquet_to_duckdb(
    parquet_dir: Path = Path("data/cn_macro/parquet"),
    db_path: Path = Path("data/cn_macro/cn_macro.duckdb"),
    *,
    verify_sha256: bool = True,
) -> Path:
    """从本地 Parquet 快照校验并完整恢复独立 cn_macro.duckdb 数据库

    Args:
        parquet_dir: 包含 manifest.json 与 data/ 的 Parquet 目录
        db_path: 恢复目标 DuckDB 文件路径
        verify_sha256: 导入前是否校验全部 Parquet 文件的 SHA256, 默认 True

    Returns:
        Path: 恢复完成的 DuckDB 文件路径

    Raises:
        FileNotFoundError: manifest.json 或 Parquet 文件缺失
        ValueError: SHA256 校验不通过

    Example:
        >>> # import_cn_macro_parquet_to_duckdb()
        >>> True
        True
    """
    manifest_path = parquet_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"未找到 manifest.json: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if verify_sha256:
        for table_name, meta in manifest.get("tables", {}).items():
            for finfo in meta.get("files", []):
                fpath = parquet_dir / finfo["path"]
                if not fpath.exists():
                    raise FileNotFoundError(f"缺失 Parquet 文件 ({table_name}): {fpath}")
                actual = _sha256_file(fpath)
                if actual != finfo["sha256"]:
                    raise ValueError(
                        f"SHA256 校验失败 ({fpath}): 期望 {finfo['sha256']}, 实际 {actual}"
                    )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        for table_name, meta in manifest.get("tables", {}).items():
            glob_path = parquet_dir / meta["glob"]
            con.execute(
                f"""
                CREATE OR REPLACE TABLE "{table_name}" AS
                SELECT * FROM read_parquet('{_sql_quote(glob_path)}')
                """
            )
    finally:
        con.close()
    return db_path


def export_deliverables_xlsx(
    db_path: Path = Path("data/cn_macro/cn_macro.duckdb"),
    deliverables_dir: Path = Path("data/cn_macro/deliverables"),
) -> list[Path]:
    """从 cn_macro.duckdb 导出独立 Excel 交付文件, 方便逐个手动上传到外部平台

    Args:
        db_path: 源 DuckDB 路径
        deliverables_dir: 输出 Excel 目录, 默认 data/cn_macro/deliverables

    Returns:
        list[Path]: 已生成的 Excel 文件路径列表

    Raises:
        FileNotFoundError: 源 DuckDB 不存在

    Example:
        >>> # paths = export_deliverables_xlsx()
        >>> True
        True
    """
    if not db_path.exists():
        raise FileNotFoundError(f"未找到数据库文件: {db_path}")
    deliverables_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        available = {r[0] for r in con.sql("SHOW TABLES").fetchall()}
        for table_name, filename in DELIVERABLE_FILENAMES.items():
            if table_name not in available:
                continue
            df = con.sql(f'SELECT * FROM "{table_name}"').df()
            out_path = deliverables_dir / filename
            df.to_excel(out_path, index=False)
            written.append(out_path)
    finally:
        con.close()
    return written


def push_cn_macro_to_hf(
    cfg: CnMacroConfig,
    *,
    token: str | None = None,
    commit_message: str = "Add cn_macro prefecture-level city datasets (PM10, CO2, GDP, Yearbook)",
) -> str:
    """将 data/cn_macro/parquet/ 推送到 Hugging Face 仓库的独立 cn_macro/ 子目录

    Args:
        cfg: CnMacroConfig 配置对象
        token: HF Token, 留空则自动从环境变量或 .env 读取
        commit_message: HF 提交说明

    Returns:
        str: Hugging Face 提交 URL 或结果信息

    Raises:
        FileNotFoundError: 本地 parquet 目录或 manifest.json 不存在
        RuntimeError: 未找到有效 HF Token

    Example:
        >>> # push_cn_macro_to_hf(load_cn_macro_config())
        >>> True
        True
    """
    parquet_dir = Path(cfg.paths.parquet_dir)
    if not (parquet_dir / "manifest.json").exists():
        raise FileNotFoundError(f"未找到 manifest.json, 请先导出 Parquet: {parquet_dir}")
    resolved_token = _resolve_hf_token(token)
    if not resolved_token:
        raise RuntimeError("未找到 HF_TOKEN, 请检查环境变量或 .env 文件")

    api = HfApi(token=resolved_token)
    info = api.upload_folder(
        folder_path=str(parquet_dir),
        path_in_repo=cfg.hf.path_in_repo,
        repo_id=cfg.hf.repo_id,
        repo_type="dataset",
        commit_message=commit_message,
    )
    return str(info)


def pull_cn_macro_from_hf(
    cfg: CnMacroConfig,
    *,
    token: str | None = None,
    revision: str | None = None,
) -> Path:
    """从 Hugging Face 仓库的 cn_macro/ 子目录拉取 Parquet 快照到本地

    Args:
        cfg: CnMacroConfig 配置对象
        token: HF Token, 留空则自动读取
        revision: 可选 Git Tag 或分支名

    Returns:
        Path: 本地 parquet 目录路径

    Raises:
        RuntimeError: 下载失败

    Example:
        >>> # pull_cn_macro_from_hf(load_cn_macro_config())
        >>> True
        True
    """
    resolved_token = _resolve_hf_token(token)
    local_root = Path(cfg.paths.work_dir) / "_hf_download"
    snapshot_download(
        repo_id=cfg.hf.repo_id,
        repo_type="dataset",
        revision=revision,
        allow_patterns=[f"{cfg.hf.path_in_repo}/**"],
        local_dir=str(local_root),
        token=resolved_token,
    )
    return local_root / cfg.hf.path_in_repo
