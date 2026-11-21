# 01. 搜罗架构与研究卡片设计

## 1. 设计目标
- **给人看**：格式化、突出特点、极致简洁 (单篇一屏扫完), 能迅速知道“研究对象怎么建模、用了什么数据、靠不靠谱、有没有做过”。
- **给 AI 看**：严格 Schema 校验, 自动汇总为结构化索引, 支持 AI 搜罗前**自动去重**、**按数据可行性筛选**、**按建模范式/领域查漏补缺**。

---

## 2. 存储架构：单卡 Markdown + 自动索引层

1. **主存储 (Source of Truth)**：每条研究成果 = 1 个 `.md` 文件 (YAML Frontmatter + 固定正文模板)。
   - 命名规范：`YYYY-<author_or_org>-<short-slug>.md`
   - 目录组织：
     - `research/equities/cross_sectional/`
     - `research/equities/stat_arb/`
     - `research/equities/event_driven/`
     - `research/equities/fundamental/`
     - `research/equities/portfolio_risk/`
     - `research/macro/`
2. **衍生索引层 (脚本自动生成, 禁止手改)**：
   - `research/INDEX.md`：按领域和状态分组的 Markdown 表格, 一眼总览全部研究。
   - `research/catalog.jsonl`：每行一条研究卡片的完整 YAML 元数据, 可直接被 DuckDB `read_json_auto('research/catalog.jsonl')` 查询, 供 AI 快速检索去重。

---

## 3. 研究卡片 YAML Frontmatter Schema (强校验)

动工后用 Pydantic 模型强制校验以下字段, 缺失或枚举值非法则拒绝入库：

```yaml
# --- 基础标识 ---
id: "eq-cs-001"                        # 全局唯一 ID (前缀按领域)
title: "Residual Momentum"             # 原始标题
source_type: "paper"                   # 枚举: paper | github | blog | book | macro_report
source_url: "https://..."              # 原始链接或 DOI / arXiv ID
year: 2011                             # 发表/发布年份
authors: ["David Blitz", "Joop Huij", "Martin Martens"]

# --- 领域与研究对象 ---
sector: "equities"                     # 枚举: equities | macro | cross_asset
domain: "cross_sectional"              # 枚举: cross_sectional | stat_arb | event_driven | fundamental | portfolio_risk | macro_regime | macro_indicator
universe: "SP500"                      # 目标标的池: SP500 | US_LargeCap | Macro_US | Global
horizon: "monthly"                     # 枚举: intraday | daily | weekly | monthly | quarterly | macro_cycle

# --- 核心建模元数据 (便于按模型横向对比)---
target_object: "单股月度超额收益率 r_{i,t}"   # 建模对象是什么
model_family: "factor_residual"        # 枚举: factor_residual | stat_arb_ou | pca_stat_factor | regime_hmm | event_study | panel_regression | ml_tree | portfolio_opt | macro_var
estimation_method: "rolling_ols_36m"   # 估计方法简写 (如 rolling_ols_36m / kalman / mle / shrinkage_cov)

# --- 数据对标与可行性 ---
data_required:                         # 必须引用 02-data-architecture 中定义的标准表名/数据集名
  - "prices_daily"
  - "sp500_pit_constituents"
feasibility: "ready"                   # 枚举: ready | needs_fundamental | needs_macro | blocked_data_missing

# --- 核心提炼与生命周期 ---
one_liner: "用 Fama-French 三因子滚动残差替代原始收益构造动量, 大幅削弱动量崩盘风险"
key_highlight: "在几乎不牺牲年化收益的前提下, 将动量策略夏普比率提升约一倍且显著降低风格暴露"
key_risk: "大盘股中换手成本敏感; 2015 年后残差动量拥挤度上升"
tags: ["momentum", "residual", "crash_risk", "fama_french"]
status: "scouted"                      # 枚举: scouted | reviewed | queued | in_progress | promoted | refuted | parked
scouted_at: "2026-11-22"
experiment_ref: null                   # 若已做实证, 填入对应实验路径/报告链接
```

---

## 4. 研究卡片正文固定模板 (严格限制篇幅)

```markdown
## 1. 核心直觉 (3 句话内)
- 解决了什么痛点？背后的经济学或市场微观结构逻辑是什么？

## 2. 研究对象的核心建模 (Core Modeling)
- **研究对象与因变量**：明确建模变量 (如 $r_{i,t} - r_{f,t}$、协整价差 $s_t$、隐含状态 $S_t$)
- **核心数学表达**：给出核心方程 / 状态空间 / 优化目标与约束
- **估计与防泄漏设定**：窗口长度、滞后阶数、横截面标准化/去极值、Point-in-Time 对齐方式
- **交易/决策映射**：模型输出如何转为仓位权重或宏观状态判断

## 3. 数据映射与复现改造
- **对应本地表**：列出需使用的 `lab.duckdb` / Parquet 表与关键列
- **缺失项与替代方案**：若缺少某字段 (如无日内数据/无一致预期), 写明能否替代或标记 `blocked`

## 4. 亮点、假设与失效边界
- **为什么值得做**：相对同类研究的增量价值
- **致命假设与失效场景**：例如高换手吞噬收益、低波动/剧烈风格切换期失效、多重检验风险

## 5. 实证结论 (做完后回填)
- 暂未实证 (待把关立项)
```

---

## 5. AI 搜罗工作流防呆规则
1. **先查重再搜罗**：AI 每次写入新卡片前, 先读取 `research/catalog.jsonl` 检查是否已有相同 `source_url` 或高度重合的 `model_family + target_object`。
2. **禁止长篇抄摘要**：单张卡片正文控制在 300~500 中文字 + 核心公式, 保证人眼 1 分钟内审完。
3. **自动重编索引**：每次新增或修改卡片后, 必须运行校验与索引编译命令, 确保 `INDEX.md` 和 `catalog.jsonl` 永不过期。
