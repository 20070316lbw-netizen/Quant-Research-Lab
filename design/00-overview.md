# 00. Quant Research Lab 总体架构设计

## 1. 项目定位
本项目是一个 **AI 驱动、人工把关** 的量化与宏观研究实验室。核心目标不是盲目堆砌回测脚本, 而是建立一套**可复现、可追溯、防过拟合**的研究流水线：
1. **AI 搜罗 (Scout)**：自动检索学术论文、开源量化项目、业界研究报告与宏观研究, 按统一格式沉淀为高密度研究卡片。
2. **人工把关 (Gatekeep)**：所有底层架构 (存储、数据契约、统计工具)与每条进入实证的研究选题, 均由人工审核后放行。
3. **固定底座 (Frozen Data)**：在严格锁版本的 S&P 500 (无幸存者偏差)与宏观数据集上做公平横向对比, 杜绝数据漂移。
4. **严谨实证 (Verify)**：统一使用项目内置的统计学工具库检验信号显著性、稳健性与多重检验风险。

---

## 2. 系统五大模块与文档索引

| 编号 | 模块 | 设计文档 | 当前状态 |
| :--- | :--- | :--- | :--- |
| 01 | 搜罗架构与研究卡片 (含核心建模与自动索引) | [01-scouting-and-cards.md](./01-scouting-and-cards.md) | 草案待审 |
| 02 | 数据托管 (HF + Parquet + DuckDB)与表结构基线 | [02-data-architecture.md](./02-data-architecture.md) | 草案待审 |
| 02b | 函数边界与内存数据格式契约 (MultiIndex 等) | [02b-data-contracts.md](./02b-data-contracts.md) | 草案待审 |
| 02c | 现有数据缺口分析与免费权威数据源清单 | [02c-external-free-data.md](./02c-external-free-data.md) | 草案待审 |
| 03 | 金融市场 (S&P 500)与宏观经济研究域地图 | [03-research-domains.md](./03-research-domains.md) | 草案待审 |
| 04 | 统计学工具库设计 | [04-statistics-toolkit.md](./04-statistics-toolkit.md) | 草案待审 |

---

## 3. 端到端研究生命周期

```mermaid
flowchart LR
    A["AI 搜罗\n(论文 / GitHub / 宏观报告)"] --> B["写入研究卡片\n(YAML Schema 强校验)"]
    B --> C["自动编译索引\n(INDEX.md + catalog.jsonl)"]
    C --> D{"人工把关\nReview & 选题"}
    D -- 拒绝/暂缓 --> E["status: rejected / parked"]
    D -- 批准立项 --> F["基于锁定数据实现模型\n(DuckDB / Parquet)"]
    F --> G["统计学工具库审计\n(样本外 / 多重检验 / 稳健性)"]
    G --> H["回填卡片结论\n(promoted / refuted)"]
```

---

## 4. 规划中的项目目录结构 (动工后落地)

```text
Quant-Research-Lab/
├── design/                     # 架构设计文档 (动工前全部由此定稿)
├── research/                   # 搜罗架构主目录 (纯文本 + Git 管理)
│   ├── INDEX.md                # 自动生成的全局总览表 (给人速览)
│   ├── catalog.jsonl           # 自动生成的机器索引 (给 AI 查重/筛选)
│   ├── equities/               # 权益研究卡片 (按方向分子目录)
│   └── macro/                  # 宏观经济研究卡片
├── data/                       # 本地数据目录 (大文件不入 Git, 由 HF 托管)
│   ├── lab.duckdb              # 本地计算引擎文件
│   └── parquet/                # 与 HF Dataset 同步的标准 Parquet 快照
├── src/quant_research_lab/
│   ├── cards/                  # 研究卡片 Pydantic Schema 校验 & 索引编译器
│   ├── data/                   # DuckDB <-> Parquet 互转、HF 拉取/发布、数据契约校验
│   ├── stats/                  # 统计学工具库 (检验、时序、多重检验校正、组合统计)
│   └── experiments/            # 通过把关后进入实证的策略/模型代码
├── tests/                      # 契约校验与统计工具单元测试
└── pyproject.toml              # 精确锁定 Python 与 duckdb 等核心依赖版本
```

---

## 5. 关键工程原则
- **依赖锁死**：`pyproject.toml` 与 `uv.lock` 精确锁定 `duckdb` Python 包版本, 避免不同版本存储格式不兼容。
- **数据不可变**：核心 `prices` 表锁版本后只读不改; 新增数据域 (如基本面、宏观)只通过新增独立表与新版本号 (如 `v1.1`)扩展。
- **设计与实现分离**：`design/` 下 4 份核心设计文档全部确认通过后, 再正式创建 `src/` 下的代码与启动 AI 搜罗。
