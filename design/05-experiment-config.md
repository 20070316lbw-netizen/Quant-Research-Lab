# 05. 实验 YAML 配置与可复现产物规范

## 1. 设计目标
本项目禁止使用 `argparse` 等命令行参数解析器。所有实验运行、参数变体切换与复现均通过 **YAML 配置文件** 驱动:
1. **高灵活性无耦合**: 不设强绑定的中央总入口; 各实验脚本直接调用 `load_experiment_config("配置文件名.yaml")` 获取强校验后的配置对象, 切换实验或变体时只需修改脚本中的配置文件名。
2. **通用外壳强校验**: 所有实验共享统一的 Pydantic 模型 `ExperimentConfig` (`extra="forbid"`), 强制拦截日期倒挂、提前泄漏 (`signal_lag_days < 1`)、非法 `n_trials` 或字段拼写错误。
3. **专属参数内核解耦**: 各研究域 (截面因子、统计套利、事件研究、宏观择时) 的策略专属参数放在 `model.params` 中, 由对应实验模块用各自的 Pydantic 子模型二次校验。
4. **轻量报告入 Git, 大文件忽略, 100% 可复现**:
   - `configs/*.yaml` 与轻量报告 (`outputs/<card_id>/<run_name>/summary.json`, `report.md`) 提交至 Git。
   - 大体积明细产物 (`outputs/**/*.csv`, `*.parquet`, `*.pkl` 等) 列入 `.gitignore`。
   - 由于 `data/lab.duckdb` 已按版本锁死, `summary.json` 记录 `config_file`, `config_sha256`, `dataset_version`, `seed`, `git_commit`, 任意历史实验均可凭配置文件完整复现。

---

## 2. 目录组织约定

```text
Quant-Research-Lab/
├── configs/                                    # 实验 YAML 配置文件 (入 Git)
│   └── eq-cs-001_residual_momentum.yaml        # 命名: <card_id>_<short_slug>.yaml
├── outputs/                                    # 实验产物目录
│   └── eq-cs-001/
│       └── residual_momentum_baseline/
│           ├── summary.json                    # 轻量结构化指标与复现元数据 (入 Git)
│           ├── report.md                       # 轻量可读审计报告 (入 Git)
│           └── returns.parquet                 # 大明细文件 (.gitignore 忽略)
└── src/quant_research_lab/experiments/
    ├── config.py                               # ExperimentConfig Schema 与 load_experiment_config
    └── eq_cs_001_residual_momentum.py          # 具体实验脚本 (直接调用 load_experiment_config)
```

---

## 3. YAML 配置文件 Schema (7 个固定区块)

```yaml
meta:
  card_id: "eq-cs-001"                   # 对应研究卡片 id
  name: "residual_momentum_baseline"     # 单次实验名称 (用于输出子目录与卡片登记)
  seed: 42                               # 固定随机种子
  notes: "实验目的简述"

data:
  dataset_version: "v1.0.0"              # 锁定数据集版本标签
  db_path: "data/lab.duckdb"             # 本地 DuckDB 路径
  start_date: "2011-01-03"               # 样本起始日 (含)
  end_date: "2026-08-18"                 # 样本截止日 (含)
  universe: "SP500"                      # 标的池标识 (默认 PIT SP500)
  tables:                                # 引用的锁定表列表
    - "prices"
    - "universe"
    - "ff_factors_daily"
  benchmark:
    market_ticker: "SPY"
    risk_free_col: "rf"

split:
  method: "holdout"                      # 枚举: holdout | walk_forward | purged_kfold
  is_end_date: "2020-12-31"              # holdout 必填: 样本内截止日
  oos_start_date: "2021-01-01"           # holdout 必填: 样本外起始日
  train_window: null                     # walk_forward 必填: 训练窗口长度 (期数)
  test_window: null                      # walk_forward 必填: 测试窗口长度 (期数)
  step_size: null                        # walk_forward 可选: 步长
  n_splits: null                         # purged_kfold 必填: 折数
  purge_days: 21                         # 隔离标签重叠期
  embargo_days: 5                        # 禁运期

execution:
  rebalance_freq: "monthly"              # 枚举: daily | weekly | monthly | quarterly | event
  signal_lag_days: 1                     # 必须 >= 1, 防止前视偏差
  price_field: "adj_close"               # 枚举: close | adj_close | open
  weighting: "equal"                     # 枚举: equal | value | inverse_vol | signal_proportional
  long_short:
    enabled: true
    n_quantiles: 10
  cost_bps_default: 10.0                 # 默认单边交易成本 (bps)
  cost_bps_grid: [0.0, 5.0, 10.0, 20.0, 30.0]
  min_history_days: 252                  # 冷启动最小历史交易日数

audit:
  n_trials: 1                            # 累计试验次数 (传入 DSR 校正)
  alpha: 0.05                            # 显著性水平
  p_adjust_method: "bh"                  # 枚举: bh | bonferroni | holm
  nw_lags: 6                             # Newey-West 滞后阶数 (null 为自动)
  annualization_factor: 12               # 年化系数 (日频 252, 月频 12)

model:
  family: "factor_residual"              # 对齐研究卡片 model_family
  params: {}                             # 实验专属参数 (由实验模块二次强校验)

output:
  dir: "outputs/eq-cs-001"               # 产物根目录
  save_returns: true                     # 是否保存大明细收益文件 (本地复查用, 不入 Git)
  save_weights: false                    # 是否保存明细权重文件 (本地复查用, 不入 Git)
  save_report_md: true                   # 是否生成轻量 report.md (入 Git)
```

---

## 4. 研究卡片与实验配置双向联动

研究卡片 (`ResearchCard`) 中显式登记实验状态与配置文件映射:
- `experimented: bool` — 该卡片是否已经执行过实证实验
- `experiments: list[ExperimentRecord]` — 已执行的实验清单, 每条记录包含:
  - `name`: 实验名称 (对齐 YAML `meta.name`)
  - `config_file`: 配置文件路径 (如 `configs/eq-cs-001_residual_momentum.yaml`)
  - `report_path`: 轻量报告路径 (如 `outputs/eq-cs-001/residual_momentum_baseline/report.md`)
  - `ran_at`: 实验执行日期
  - `outcome`: `pending | passed | failed | inconclusive`
  - `summary`: 一句话核心量化结论 (可选)

强校验约束:
- `experimented == True` 时 `experiments` 不能为空; `experiments` 非空时 `experimented` 必须为 `True`。
- 同一张卡片内不允许登记重复的实验 `name` 或重复的 `config_file`。
- `build_index` 会自动把实验状态与配置文件数量汇总到 `research/INDEX.md` 和 `research/catalog.jsonl`。
