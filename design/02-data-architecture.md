# 02. 数据托管 (Hugging Face + Parquet + DuckDB)与数据契约设计

## 1. 核心原则
1. **固定数据范围优于持续追新**：`lab.duckdb` 中核心 `prices` (`2011-01-03` ~ `2026-11-16`)已完成清洗且锁死不更新, 所有研究在同一基准面上公平对比。
2. **托管与计算分离**：
   - **远端托管与版本锁定**：Hugging Face Dataset 仓库 **`2007liuQuant/Quant-Research-Lab`** (原生启用 **Xet** 大文件加速, 通过 `huggingface-hub` + `hf-xet` 推送/拉取), 以列式 **Parquet (ZSTD)** 存储, 通过 Git Tag (如 `v1.0.0`)永久锁死版本。
   - **本地高速计算**：本地 `data/lab.duckdb`, `pyproject.toml` 精确锁定 `duckdb` Python 依赖 (当前已锁定 `duckdb==2.0.1`、`huggingface-hub==2.4.0`、`hf-xet==1.8.0`)。
3. **去冗余瘦身**：经检查, `prices_calendar` (29,617,662 行)正好等于 `market_calendar LEFT JOIN prices USING (date)` (多出的 1,797 行即非交易日空行)。**远端不上传 `prices_calendar`**, 本地导入时用 DuckDB `VIEW` 秒级还原, 直接节省约 40%~45% 体积与上传时间。

> **安全/合规提醒**：目前 `2007liuQuant/Quant-Research-Lab` 在 HF 页面上显示为 **Public (MIT)**。如果后续不希望公开全量美股价格与清洗结果, 建议上传前在 HF 仓库 `Settings` 里切换为 **Private** (AI 和本地脚本配只读 `HF_TOKEN` 同样无感拉取)。

---

## 2. Hugging Face 仓库目录与文件组织规范

在 `2007liuQuant/Quant-Research-Lab` 中按如下结构组织文件 (兼顾 **HF Dataset Viewer 在线预览** 与 **DuckDB `hf://` 直接 SQL 懒查询**)：

```text
2007liuQuant/Quant-Research-Lab/
├── README.md                              # HF Dataset Card (含 configs 元数据, 支持网页分表预览)
├── manifest.json                          # 版本清单：每张表的行数、起止日期、Schema、SHA256、导出时间
└── data/
    ├── prices/                            # 按年份分片 (便于 DuckDB 按年分区裁剪 + Xet 并发传输)
    │   ├── year=2011/part-0.parquet
    │   ├── ...
    │   └── year=2026/part-0.parquet
    ├── fundamental_instant/               # 5.77M 行, 按单文件或按 filed 年份分片 (~100-200MB)
    │   └── data.parquet
    ├── fundamental_period/                # 9.45M 行, 按单文件或按 filed 年份分片 (~200-350MB)
    │   └── data.parquet
    ├── universe/
    │   └── data.parquet                   # 513K 行 (S&P 500 PIT 成分股 + CIK + GICS sub_industry)
    ├── ticker_segment/
    │   └── data.parquet                   # 24K 行 (代码复用分段表)
    ├── market_calendar/
    │   └── data.parquet                   # 5.8K 行
    └── calendar/
        └── data.parquet                   # 4.0K 行
```

### 为什么 `prices` 按 `year` 分片, 其余表按单文件？
- `prices` 有 **2,961 万行**, 按 `EXTRACT(YEAR FROM date)` 分成 16 个年度 Parquet 文件 (每个约 30~60 MB)：
  - 上传/下载时 `hf-xet` 并发极快、支持断点续传; 
  - AI 只需要查近 5 年数据时, DuckDB 的 Hive 分区裁剪可以只拉取对应年份文件, 不用扫全量。
- 其余表压成 ZSTD Parquet 后都在几 KB ~ 几百 MB 以内, 单文件最清爽, DuckDB 读取零开销。

### HF Dataset Card (`README.md`) 的 `configs` 声明
在 `README.md` 顶部 YAML 声明各表为独立 subset, HF 网页端就能直接下拉切换预览每张表：
```yaml
---
license: mit
configs:
  - config_name: prices
    data_files: "data/prices/**/*.parquet"
  - config_name: universe
    data_files: "data/universe/*.parquet"
  - config_name: fundamental_instant
    data_files: "data/fundamental_instant/*.parquet"
  - config_name: fundamental_period
    data_files: "data/fundamental_period/*.parquet"
  - config_name: ticker_segment
    data_files: "data/ticker_segment/*.parquet"
  - config_name: market_calendar
    data_files: "data/market_calendar/*.parquet"
  - config_name: calendar
    data_files: "data/calendar/*.parquet"
---
```

---

## 3. DuckDB ↔ Parquet ↔ Hugging Face 互转与同步设计

动工后在 `src/quant_research_lab/data/` 下实现 3 个轻量模块, 全部用 **DuckDB 原生 SQL + Python** 驱动, 不经过 Pandas 内存膨胀：

### 3.1 `export_to_parquet` (本地 `lab.duckdb` → `data/parquet/`)
- 以 `read_only=True` 打开 `data/lab.duckdb`; 
- 对 `prices` 执行 DuckDB 原生 Hive 分区导出 (按 `ticker, date` 排序提升列式压缩率与查询速度)：
  ```sql
  COPY (
      SELECT *, EXTRACT(YEAR FROM date)::INTEGER AS year
      FROM prices
      ORDER BY date, ticker
  ) TO 'data/parquet/data/prices'
 (FORMAT PARQUET, PARTITION_BY (year), COMPRESSION ZSTD, ROW_GROUP_SIZE 500000, OVERWRITE_OR_IGNORE TRUE);
  ```
- 对其余 6 张基表 (`universe`, `fundamental_instant`, `fundamental_period`, `ticker_segment`, `market_calendar`, `calendar`)执行单文件 ZSTD 导出：
  ```sql
  COPY (SELECT * FROM universe ORDER BY snapshot_date, ticker)
  TO 'data/parquet/data/universe/data.parquet'
 (FORMAT PARQUET, COMPRESSION ZSTD);
  ```
- 自动计算每张表的行数、Schema、日期范围与文件 SHA256, 写出 `manifest.json` 与 `README.md`。

### 3.2 `push_to_hf` (本地 `data/parquet/` → HF `2007liuQuant/Quant-Research-Lab`)
- 认证方式：读取环境变量 `HF_TOKEN` 或本地 `hf auth login` 凭据 (严禁把 Token 写进代码或 Git)。
- 使用 `huggingface_hub.HfApi().upload_large_folder(...)` 或 `upload_folder(...)` 推送至 `repo_id="2007liuQuant/Quant-Research-Lab", repo_type="dataset"` (自动走 `hf-xet` 分块去重传输)。
- 推送完成后, 自动打不可变版本标签：
  ```python
  api.create_tag(
      repo_id="2007liuQuant/Quant-Research-Lab",
      repo_type="dataset",
      tag="v1.0.0",
      tag_message="Locked baseline: prices (2011-2026), SP500 PIT universe, SEC fundamentals",
  )
  ```

### 3.3 `pull_from_hf` & `import_to_duckdb` (HF → 本地 Parquet → `lab.duckdb`)
- **方式 A (整包拉取并重建本地 DuckDB, 适合频繁回测)**：
  1. `snapshot_download(repo_id="2007liuQuant/Quant-Research-Lab", repo_type="dataset", revision="v1.0.0", local_dir="data/parquet")`
  2. 校验 `manifest.json` 中的 SHA256; 
  3. DuckDB 原生 SQL 极速灌入并自动重建 `prices_calendar` 视图：
     ```sql
     CREATE OR REPLACE TABLE prices AS
     SELECT * EXCLUDE (year) FROM read_parquet('data/parquet/data/prices/**/*.parquet', hive_partitioning=true);
     -- 其余 6 张表同理 CREATE OR REPLACE TABLE ...
     CREATE OR REPLACE VIEW prices_calendar AS
     SELECT mc.date, mc.weekday, mc.is_open, p.ticker, p.open, p.high, p.low, p.close, p.adj_close, p.volume
     FROM market_calendar mc
     LEFT JOIN prices p ON mc.date = p.date;
     ```
- **方式 B (免下载远程直连, 适合 AI 临时探索)**：
  DuckDB 2.x 原生支持 `hf://` 协议直接查锁定版本：
  ```sql
  SELECT * FROM 'hf://datasets/2007liuQuant/Quant-Research-Lab@v1.0.0/data/universe/data.parquet' LIMIT 10;
  ```

---

## 4. `lab.duckdb` 实际表结构与数据契约 (`v1.0.0` 基线)

已通过 `duckdb==2.0.1` 只读实测提取出 `data/lab.duckdb` 当前全部 8 张表的真实 Schema (后续如需再对标你另一个现有项目的口径或附加约束, 直接在此表上补充)：

| 表名 | 行数 | 时间覆盖 | 主键/关键维度 | 字段 Schema | HF 托管方式 |
| :--- | ---: | :--- | :--- | :--- | :--- |
| **`prices`** | 29,615,865 | `2011-01-03` ~ `2026-11-16` | `(date, ticker)` (24,366 个分段 ticker) | `date DATE, ticker VARCHAR, open/high/low/close/adj_close DOUBLE, volume BIGINT` | 按 `year` 分区 Parquet (**锁版本不更新**) |
| **`universe`** | 513,463 | `2010-12-31` ~ `2026-08-18` | `(snapshot_date, ticker)` (853 ticker / 602 CIK) | `snapshot_date DATE, ticker VARCHAR, cik VARCHAR, name VARCHAR, exchange VARCHAR, sic VARCHAR, sub_industry VARCHAR` | 单文件 Parquet |
| **`fundamental_instant`** | 5,766,263 | `filed`: `2009-04-15` ~ `2026-10-08` | `(cik, tag, end_date, filed, accn)` (600 CIK) | `cik/taxonomy/tag/unit/accn/form/fp/frame VARCHAR, end_date/filed DATE, val DOUBLE, fy INTEGER` | 单文件 Parquet |
| **`fundamental_period`** | 9,445,876 | `filed`: `2009-04-15` ~ `2026-10-08` | `(cik, tag, start_date, end_date, filed, accn)` (600 CIK) | 同上 + `start_date DATE` | 单文件 Parquet |
| **`ticker_segment`** | 24,366 | 全周期 | `ticker` (分段后唯一键) | `symbol/ticker VARCHAR, seg_no/n_days/gap_before INTEGER, start_date/end_date DATE` | 单文件 Parquet |
| **`market_calendar`** | 5,797 | `2011-01-03` ~ `2026-11-16` | `date` | `date DATE, weekday VARCHAR, is_open BOOLEAN` | 单文件 Parquet |
| **`calendar`** | 4,000 | `2011-01-03` ~ `2026-11-16` | `date` | `date DATE` | 单文件 Parquet |
| `prices_calendar` | 29,617,662 | `2011-01-03` ~ `2026-11-16` | `market_calendar LEFT JOIN prices` | 同 `market_calendar` + `prices` | **不上传**, 本地导入时建为 `VIEW` |

---

## 5. 版本演进与防污染规则
- **`v1.0.0`**：上述 7 张核心基表 (锁定基线)。
- **`v1.x.0`**：未来新增宏观经济表 (如 `macro_series`)或其他数据集时, **只增新目录、不修改 `v1.0.0` 已有表**, 并发布新 Tag。
- **`.gitignore` 保护**：把 `data/` 加入 `.gitignore`, 确保大文件和 `.duckdb` 永远不会被误提交到代码 Git 仓库。
