"""DuckDB <-> Parquet <-> Hugging Face 数据同步模块

默认 Hugging Face 私有仓库: 2007liuQuant/Quant-Research-Lab (Xet 加速)
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from huggingface_hub import HfApi, snapshot_download

DEFAULT_HF_REPO_ID = "2007liuQuant/Quant-Research-Lab"
DEFAULT_GH_REPO = "20070316lbw-netizen/Quant-Research-Lab"

# 从 lab.duckdb 导出的单文件基表 (prices_calendar 在导入时自动建为 VIEW, 不重复落盘)
CORE_SINGLE_TABLES: dict[str, str] = {
    "universe": "ORDER BY snapshot_date, ticker",
    "fundamental_instant": "ORDER BY cik, filed, end_date, tag",
    "fundamental_period": "ORDER BY cik, filed, end_date, tag",
    "ticker_segment": "ORDER BY ticker",
    "market_calendar": "ORDER BY date",
    "calendar": "ORDER BY date",
}

P0_TABLES: tuple[str, ...] = (
    "ff_factors_daily",
    "vol_indices_daily",
    "aqr_factors_daily",
)


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


def export_duckdb_to_parquet(
    db_path: Path = Path("data/lab.duckdb"),
    out_dir: Path = Path("data/parquet"),
    *,
    export_prices: bool = True,
) -> Path:
    """将本地 DuckDB 核心表导出为 ZSTD Parquet 并生成 manifest 和 README

    prices 按 year 做 Hive 分区导出, prices_calendar 跳过不导出
    目录中已存在的 P0 Parquet 表会被自动纳入 manifest 统计

    Args:
        db_path: 源 DuckDB 文件路径, 默认 Path("data/lab.duckdb")
        out_dir: 输出 Parquet 根目录, 默认 Path("data/parquet")
        export_prices: 是否导出 prices 大表, 默认 True

    Returns:
        Path: 生成的 manifest.json 文件路径

    Raises:
        duckdb.Error: 数据库读取或 Parquet 导出失败

    Example:
        >>> from pathlib import Path
        >>> manifest = export_duckdb_to_parquet(Path("data/lab.duckdb"), Path("data/parquet"))
        >>> manifest.name
        'manifest.json'
    """
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        available = {r[0] for r in con.sql("SHOW TABLES").fetchall()}

        if export_prices and "prices" in available:
            prices_dir = data_dir / "prices"
            if prices_dir.exists():
                shutil.rmtree(prices_dir)
            prices_dir.mkdir(parents=True, exist_ok=True)
            print(f"[export] Exporting prices (Hive partitioned by year, ZSTD) -> {prices_dir}")
            con.execute(
                f"""
                COPY (
                    SELECT *, EXTRACT(YEAR FROM date)::INTEGER AS year
                    FROM prices
                    ORDER BY date, ticker
                ) TO '{_sql_quote(prices_dir)}'
                (FORMAT PARQUET, PARTITION_BY (year), COMPRESSION ZSTD, ROW_GROUP_SIZE 500000, OVERWRITE_OR_IGNORE TRUE)
                """
            )

        for table, order_clause in CORE_SINGLE_TABLES.items():
            if table not in available:
                continue
            target = data_dir / table / "data.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            print(f"[export] Exporting {table} -> {target}")
            con.execute(
                f"""
                COPY (SELECT * FROM "{table}" {order_clause})
                TO '{_sql_quote(target)}'
                (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )
    finally:
        con.close()

    manifest_path = build_manifest_and_card(out_dir)
    print(f"[export] Wrote manifest -> {manifest_path}")
    return manifest_path


def build_manifest_and_card(parquet_root: Path = Path("data/parquet")) -> Path:
    """扫描 Parquet 目录下全部数据表, 生成 manifest.json 与 HF Dataset Card

    Args:
        parquet_root: Parquet 快照根目录, 默认 Path("data/parquet")

    Returns:
        Path: 生成的 manifest.json 路径

    Raises:
        FileNotFoundError: data 子目录不存在
        duckdb.Error: 读取 Parquet 元数据失败

    Example:
        >>> from pathlib import Path
        >>> p = build_manifest_and_card(Path("data/parquet"))
        >>> p.exists()
        True
    """
    data_dir = parquet_root / "data"
    con = duckdb.connect(":memory:")
    tables_meta: dict[str, Any] = {}
    configs_yaml: list[str] = []

    try:
        for table_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
            table_name = table_dir.name
            parquet_files = sorted(table_dir.rglob("*.parquet"))
            if not parquet_files:
                continue

            is_partitioned = any(p.parent != table_dir for p in parquet_files)
            glob_rel = f"data/{table_name}/**/*.parquet" if is_partitioned else f"data/{table_name}/*.parquet"
            glob_abs = table_dir / ("**/*.parquet" if is_partitioned else "*.parquet")

            read_expr = (
                f"read_parquet('{_sql_quote(glob_abs)}', hive_partitioning=true)"
                if is_partitioned
                else f"read_parquet('{_sql_quote(glob_abs)}')"
            )
            row_count = int(con.sql(f"SELECT COUNT(*) FROM {read_expr}").fetchall()[0][0])
            schema_rows = con.sql(f"DESCRIBE SELECT * FROM {read_expr}").fetchall()
            schema = {r[0]: r[1] for r in schema_rows if not (is_partitioned and r[0] == "year")}

            date_col = next((c for c in ("date", "snapshot_date", "filed") if c in schema), None)
            date_range = None
            if date_col:
                min_d, max_d = con.sql(f"SELECT MIN({date_col}), MAX({date_col}) FROM {read_expr}").fetchall()[0]
                date_range = [str(min_d), str(max_d)]

            files_info = [
                {
                    "path": str(p.relative_to(parquet_root)),
                    "size_bytes": p.stat().st_size,
                    "sha256": _sha256_file(p),
                }
                for p in parquet_files
            ]
            total_bytes = sum(f["size_bytes"] for f in files_info)

            tables_meta[table_name] = {
                "rows": row_count,
                "partitioned": is_partitioned,
                "glob": glob_rel,
                "date_column": date_col,
                "date_range": date_range,
                "total_size_mb": round(total_bytes / (1024 * 1024), 2),
                "schema": schema,
                "files": files_info,
            }
            configs_yaml.append(f"  - config_name: {table_name}\n    data_files: \"{glob_rel}\"")
    finally:
        con.close()

    manifest = {
        "repo_id": DEFAULT_HF_REPO_ID,
        "duckdb_version": duckdb.__version__,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "tables": tables_meta,
    }
    manifest_path = parquet_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rows_md = [
        "| Table | Rows | Date Range | Size (MB) | Partitioned |",
        "| :--- | ---: | :--- | ---: | :---: |",
    ]
    for name, info in tables_meta.items():
        dr = f"`{info['date_range'][0]}` ~ `{info['date_range'][1]}`" if info["date_range"] else "-"
        rows_md.append(
            f"| `{name}` | {info['rows']:,} | {dr} | {info['total_size_mb']:.2f} | {'year' if info['partitioned'] else 'no'} |"
        )

    readme = (
        "---\n"
        "configs:\n"
        + "\n".join(configs_yaml)
        + "\n---\n\n"
        "# Quant Research Lab Dataset\n\n"
        "Version-locked S&P 500 Point-in-Time equity prices, SEC EDGAR fundamentals, "
        "and P0 benchmark factor/volatility series for reproducible quantitative research\n\n"
        "## Tables\n\n"
        + "\n".join(rows_md)
        + "\n\n"
        "> Note: `prices_calendar` is omitted from Parquet storage and reconstructed locally as a DuckDB `VIEW` "
        "(`market_calendar LEFT JOIN prices USING (date)`)\n"
    )
    (parquet_root / "README.md").write_text(readme, encoding="utf-8")
    return manifest_path


def import_parquet_to_duckdb(
    parquet_root: Path = Path("data/parquet"),
    db_path: Path = Path("data/lab.duckdb"),
    *,
    tables: list[str] | None = None,
    verify_checksums: bool = True,
) -> None:
    """将 Parquet 快照校验并导入本地 DuckDB, 自动重建 prices_calendar 视图

    Args:
        parquet_root: Parquet 快照根目录, 需包含 manifest.json
        db_path: 目标 DuckDB 文件路径, 默认 Path("data/lab.duckdb")
        tables: 指定导入的表名列表, 默认 None 表示导入全部表
        verify_checksums: 是否在导入前校验 SHA256, 默认 True

    Returns:
        None: 直接写入目标 DuckDB 文件

    Raises:
        FileNotFoundError: manifest.json 或 Parquet 文件不存在
        ValueError: SHA256 校验不通过
        duckdb.Error: DuckDB 写入失败

    Example:
        >>> from pathlib import Path
        >>> import_parquet_to_duckdb(Path("data/parquet"), Path("data/lab.duckdb"), tables=["calendar"])
    """
    manifest_path = parquet_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tables_meta: dict[str, Any] = manifest["tables"]

    target_tables = tables if tables is not None else list(tables_meta.keys())

    if verify_checksums:
        for t in target_tables:
            for f_info in tables_meta[t]["files"]:
                fpath = parquet_root / f_info["path"]
                actual = _sha256_file(fpath)
                if actual != f_info["sha256"]:
                    raise ValueError(f"SHA256 mismatch for {fpath}: expected {f_info['sha256']}, got {actual}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=False)
    try:
        for t in target_tables:
            info = tables_meta[t]
            glob_abs = parquet_root / info["glob"]
            if info["partitioned"]:
                con.execute(
                    f"""
                    CREATE OR REPLACE TABLE "{t}" AS
                    SELECT * EXCLUDE (year)
                    FROM read_parquet('{_sql_quote(glob_abs)}', hive_partitioning=true)
                    """
                )
            else:
                con.execute(
                    f"""
                    CREATE OR REPLACE TABLE "{t}" AS
                    SELECT * FROM read_parquet('{_sql_quote(glob_abs)}')
                    """
                )
            print(f"[import] Loaded table {t} ({info['rows']:,} rows) into {db_path}")

        existing = {r[0] for r in con.sql("SHOW TABLES").fetchall()}
        if {"market_calendar", "prices"}.issubset(existing) and "prices_calendar" not in existing:
            con.execute(
                """
                CREATE OR REPLACE VIEW prices_calendar AS
                SELECT
                    mc.date,
                    mc.weekday,
                    mc.is_open,
                    p.ticker,
                    p.open,
                    p.high,
                    p.low,
                    p.close,
                    p.adj_close,
                    p.volume
                FROM market_calendar mc
                LEFT JOIN prices p ON mc.date = p.date
                """
            )
            print("[import] Created VIEW prices_calendar")
    finally:
        con.close()


def push_to_hf(
    parquet_root: Path = Path("data/parquet"),
    *,
    repo_id: str = DEFAULT_HF_REPO_ID,
    tag: str | None = None,
    commit_message: str = "chore: 上传锁定版本 Parquet 数据快照",
    token: str | None = None,
) -> None:
    """将本地 Parquet 快照推送至 Hugging Face 私有数据集仓库并可选打版本标签

    Args:
        parquet_root: 本地 Parquet 快照根目录, 默认 Path("data/parquet")
        repo_id: HF 数据集仓库 ID, 默认 "2007liuQuant/Quant-Research-Lab"
        tag: 可选不可变版本标签, 例如 "v1.0.0"
        commit_message: HF 仓库提交说明
        token: HF 访问令牌, 默认 None 时自动读取环境变量 HF_TOKEN 或本地登录凭据

    Returns:
        None: 推送完成并打印结果

    Raises:
        huggingface_hub.errors.HfHubHTTPError: 认证失败或仓库权限不足

    Example:
        >>> push_to_hf(tag="v1.0.0", commit_message="feat: 上传 v1.0.0 基线数据与 P0 基准")
    """
    api = HfApi(token=_resolve_hf_token(token))
    print(f"[hf] Uploading {parquet_root} -> {repo_id} (dataset)")
    api.upload_folder(
        folder_path=str(parquet_root),
        repo_id=repo_id,
        repo_type="dataset",
        commit_message=commit_message,
    )
    if tag:
        api.create_tag(
            repo_id=repo_id,
            repo_type="dataset",
            tag=tag,
            tag_message=commit_message,
            exist_ok=True,
        )
        print(f"[hf] Tagged {repo_id}@{tag}")


def pull_from_hf(
    *,
    revision: str,
    repo_id: str = DEFAULT_HF_REPO_ID,
    out_dir: Path = Path("data/parquet"),
    token: str | None = None,
) -> Path:
    """从 Hugging Face 拉取指定锁定版本 (Tag 或 Commit Hash) 的 Parquet 快照

    Args:
        revision: 必须显式指定的版本标签或提交哈希, 如 "v1.0.0"
        repo_id: HF 数据集仓库 ID, 默认 "2007liuQuant/Quant-Research-Lab"
        out_dir: 本地保存目录, 默认 Path("data/parquet")
        token: HF 访问令牌, 默认 None 时读取环境变量 HF_TOKEN 或本地登录凭据

    Returns:
        Path: 本地保存目录路径

    Raises:
        huggingface_hub.errors.HfHubHTTPError: 版本不存在或无访问权限

    Example:
        >>> out = pull_from_hf(revision="v1.0.0")
        >>> out.name
        'parquet'
    """
    print(f"[hf] Pulling {repo_id}@{revision} -> {out_dir}")
    snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        revision=revision,
        local_dir=str(out_dir),
        token=_resolve_hf_token(token),
    )
    return out_dir


def pull_from_github_release(
    *,
    tag: str = "data-v1.0.0",
    repo: str = DEFAULT_GH_REPO,
    out_dir: Path = Path("data/parquet"),
) -> Path:
    """从私有 GitHub Release 拉取并解压锁定版本 Parquet 快照 (HF 的备用镜像通道)

    Args:
        tag: GitHub Release 标签, 默认 "data-v1.0.0"
        repo: GitHub 仓库名, 默认 "20070316lbw-netizen/Quant-Research-Lab"
        out_dir: 解压目标目录, 默认 Path("data/parquet")

    Returns:
        Path: 解压后的本地 Parquet 根目录

    Raises:
        subprocess.CalledProcessError: gh CLI 下载失败或未登录
        FileNotFoundError: Release 中未找到对应 .tar 附件

    Example:
        >>> out = pull_from_github_release(tag="data-v1.0.0")
        >>> (out / "manifest.json").exists()
        True
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"quant-lab-{tag}.tar"
    archive_path = out_dir.parent / archive_name

    print(f"[gh] Downloading {repo}@{tag} ({archive_name}) -> {archive_path}")
    subprocess.run(
        [
            "gh",
            "release",
            "download",
            tag,
            "--repo",
            repo,
            "--pattern",
            archive_name,
            "--dir",
            str(out_dir.parent),
            "--clobber",
        ],
        check=True,
    )
    if not archive_path.exists():
        raise FileNotFoundError(f"未找到下载的快照压缩包: {archive_path}")

    print(f"[gh] Extracting {archive_path} -> {out_dir}")
    with tarfile.open(archive_path, "r") as tf:
        tf.extractall(path=out_dir, filter="data")
    archive_path.unlink(missing_ok=True)
    return out_dir
