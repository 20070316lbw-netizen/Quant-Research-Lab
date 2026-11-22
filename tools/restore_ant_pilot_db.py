"""从冻结快照恢复本地研究数据库并核对全表行数"""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from quant_research_lab.data import import_parquet_to_duckdb

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = Path(os.environ.get("QUANT_LAB_SNAPSHOT", ROOT / "data" / "parquet")).resolve()
DATABASE = ROOT / "data" / "lab.duckdb"


def _validate(path, tables):
    with duckdb.connect(str(path), read_only=True) as con:
        for name, info in tables.items():
            count, = con.execute(f'SELECT count(*) FROM "{name}"').fetchall()[0]
            if count != info["rows"]:
                raise ValueError(f"{name}: expected {info['rows']} rows, got {count}")


def _main():
    manifest = json.loads((SNAPSHOT / "manifest.json").read_text(encoding="utf-8"))
    tables = manifest["tables"]
    if DATABASE.exists():
        _validate(DATABASE, tables)
        print(f"Existing database matches the manifest row counts: {DATABASE}")
        return
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="lab-restore-", dir=DATABASE.parent) as directory:
        staged = Path(directory) / DATABASE.name
        import_parquet_to_duckdb(SNAPSHOT, staged, verify_checksums=True)
        _validate(staged, tables)
        DATABASE.hardlink_to(staged)


if __name__ == "__main__":
    _main()
