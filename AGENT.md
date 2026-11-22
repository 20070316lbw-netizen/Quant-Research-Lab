## 工程与代码规范

- 代码注释中不能使用句号, 如果必须使用, 用回车来换行替代
- 项目不需要 cli 命令行启动, 所以不要使用 argparse
- 不许为了兼容旧代码而保留旧名字和旧接口
- 所有 commit 信息统一使用 `类型: 中文描述` 格式, 例如 `feat: 新增动量因子`, 类型可使用 feat、fix、docs、test、refactor、chore 等英文标识; 类型标记后的描述统一使用中文

新增或修改公开计算函数时, 使用中文 docstring, 注释中不要出现中文句号, 说明计算口径, 并包含:
- `Args`: 输入 DataFrame 的索引、必需列、参数默认值、单位及限制
- `Returns`: 输出类型、索引、Series.name 或 DataFrame 列名、单位、缺失值和样本不足的行为
- `Raises`: 主要参数与数据校验错误
- `Example`: 自包含、可执行、具有正确预期结果的调用示例

## 符号与格式规范

- 编辑器可能提示 U+FF0C 全角符号与常见源码字符 U+002C ASCII 符号混淆
- 项目源码、注释、docstring、示范与文档统一使用 ASCII 逗号, 分号, 括号等 `,`, `;`, `()`;
- 正文逗号后加一个空格, 保留中文文字。提及全角逗号, 分号或者括号时使用 `U+FF0C`
- 或转义形式 `\uFF0C`, 避免再次引入触发警告的字符
- 不要通过关闭 Unicode 字符提示来掩盖问题。涉及外部原始数据、解析匹配或
- 测试输入时, 如必须表示全角逗号, 使用转义并注明其业务用途

## 研究与实验全流程规范

以下规则依据 `design/` 架构文档制定, 约束 Agent 在搜罗、立项、数据读取、模型实现、统计审计与结论回填全流程中的行为。

### 1. 搜罗、卡片与人工把关 (Scout & Gatekeep)

- **先查重再建卡**: 新增研究卡片前, 必须先检查 `research/catalog.jsonl` (或调用 `quant_research_lab.cards.check_duplicate`), 排查是否已有相同 `source_url` 或高度重合的 `model_family + target_object`
- **强校验入库**: 卡片必须通过 `quant_research_lab.cards` (`ResearchCard`, `write_card`) 校验并写入对应研究域目录, 命名遵循 `YYYY-<author_or_org>-<short-slug>.md`; 正文控制在 300~500 中文字 + 核心公式, 严禁长篇照抄摘要
- **禁止手改衍生索引**: `research/INDEX.md` 与 `research/catalog.jsonl` 只能由 `quant_research_lab.cards.build_index` 自动生成; 每次新增或更新卡片后必须立即重编索引
- **人工把关门禁**: 严禁跳过研究卡片直接编写孤立的策略回测脚本; 只有经人工确认放行的卡片 (`reviewed` / `queued` / `in_progress`) 才允许进入实证实现阶段, 不得擅自把 `scouted` 卡片直接推进为完整实证

### 2. 锁定数据与防泄漏铁律 (Frozen Data & Anti-Leakage)

- **统一读取入口**: 所有实验必须通过 `quant_research_lab.data.loader` (`load_prices`, `load_universe_panel`, `load_ff_factors`, `load_vol_indices`, `load_aqr_factors`, `load_calendar`) 获取数据, 禁止在实验脚本中各自拼写裸 SQL 绕过标准过滤与索引契约
- **核心基表只读不可变**: `data/lab.duckdb` 中的锁版本基表 (`prices`, `universe`, `fundamental_instant`, `fundamental_period`, `ticker_segment`, `calendar`, `market_calendar` 等) 严禁在实验过程中修改或覆写; 新增数据域仅通过新增独立表与新版本 Tag 扩展; `data/` 下数据文件严禁提交至 Git
- **防幸存者偏差**: S&P 500 权益研究默认按当日 PIT `universe` 成分股过滤、排序与建仓, 严禁使用当前静态成分股列表回溯历史
- **防基本面与宏观前视偏差**:
  - SEC 基本面数据必须严格按 `filed` (真实申报日) 对齐, 禁止按报告期末 `end_date` 提前使用
  - 宏观序列必须严格按 `release_date` (真实发布日) 向前填充 (`ffill`) 到交易日历, 禁止用观测期 `obs_date` 直接对齐
- **信号时间戳铁律**: 索引日期 `date = t` 的信号值只能使用 `t` 日收盘及之前公开可得的信息, 默认预测 `t -> t+1` (或 `t -> t+h`) 未来收益; 严禁在信号构造函数中提前 `shift(-1)`

### 3. 内存数据契约与模块边界 (In-Memory Contracts)

- **严格遵守标准数据对象**: 模块间只传递 `PanelFrame`, `SignalSeries`, `WeightFrame`, `TimeSeriesFrame`, `EventTable` 与 `StatResult`
  - 面板与信号索引必须为升序、无重复的 `pd.MultiIndex(names=["date", "ticker"])`, `date` 为无时区 `datetime64[ns]`, 数值列为 `float64`, 严禁出现 `±inf`
  - 时间序列索引必须为升序、无重复、无时区的 `pd.DatetimeIndex(name="date")`
- **边界强制校验**: 公开的因子、模型、回测与统计入口必须使用 `validate_panel`, `validate_signal`, `validate_timeseries` 或 `@require_panel` 做运行时拦截
- **计算与存储解耦**: 因子计算、组合构建与统计检验函数必须保持纯函数形态, 不直接耦合 DuckDB 连接

### 4. 实证实现与实验记录 (`src/quant_research_lab/experiments/`)

- **按卡片归档**: 立项实验统一放置在 `src/quant_research_lab/experiments/` 下, 并与研究卡片 `id` 一一对应
- **显式声明实验口径**: 每个实验必须在代码与输出中固定并记录:
  - 样本区间、样本内/样本外或滚动窗口切分方式 (`walk_forward_splits` / `purged_kfold_splits`)
  - 基准对照 (如传统因子基准、`SPY` 或无风险利率 `RF`)
  - 交易执行口径 (`t` 日收盘或 `t+1` 日开盘建仓)、调仓频率、冷启动与停牌处理规则
  - 交易成本假设与换手率/成本敏感性分析
- **记录真实试验次数**: 严禁隐瞒调参或变体筛选过程; 实验过程中尝试的参数组合与变体总数必须显式记为 `n_trials`, 作为多重检验校正 (`deflated_sharpe_ratio`, `adjust_pvalues`) 的输入

### 5. 统计学审计与防过拟合门禁 (Statistical Audit)

- **统一使用内置统计库**: 禁止在实验脚本中临时手写不一致的 IC、t 检验、Sharpe 或回撤公式, 必须统一调用 `quant_research_lab.stats`:
  - 截面因子: `winsorize_cs`, `standardize_cs`, `neutralize_cs`, `compute_ic_series`, `summarize_ic`, `ic_decay`, `quantile_portfolio_returns`, `fama_macbeth`
  - 时序与统计套利: `adf_test`, `kpss_test`, `engle_granger_coint`, `ou_half_life`, `hurst_exponent`, `ledoit_wolf_cov`
  - 事件研究: `run_event_study`
  - 绩效与防过拟合审计: `performance_summary`, `probabilistic_sharpe_ratio`, `deflated_sharpe_ratio`, `adjust_pvalues`, `walk_forward_splits`, `purged_kfold_splits`
- **拒绝裸指标汇报**: 所有实证结论必须基于结构化 `StatResult`, 完整呈现点估计、标准误或 t 统计量、p 值、置信区间、有效样本量 `n_obs`、换手与成本后表现, 以及 `StatResult.warnings` 中的全部假设违背警告
- **严禁数据窥探与美化**: 结论以样本外及多重检验校正 (PSR / DSR / FDR) 与成本扣除后的表现为准; 若策略失效或无法显著跑赢基准, 必须如实给出否定结论, 严禁截取局部最优子区间或事后更改检验口径

### 6. 实证闭环与测试验证 (Close the Loop)

- **回填研究卡片**: 实验完成后必须更新对应卡片的"5. 实证结论"章节与 `experiment_ref`, 按实证结果并经人工确认更新 `status` (`promoted` / `refuted` / `parked`), 随后运行 `build_index` 刷新 `research/INDEX.md` 与 `research/catalog.jsonl`
- **单元测试兜底**: 新增核心计算函数或实验可复用模块必须配套 `tests/` 单元测试, 优先用解析解或合成数据验证数学正确性与无前视偏差 (如修改未来数据不得改变历史信号), 提交前确保 `uv run pytest` 全部通过
