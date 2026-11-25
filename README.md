# Quant Research Lab

QRL 是一个用 Python 和 DuckDB 做金融与宏观实证研究的项目。每项研究从一张卡片开始, 记录论文的问题、数据口径和待检验的假设。进入实验后, 可以沿着卡片找到配置、样本外结果和复现差异。

## 从研究问题开始

| 研究问题 | 目前做到哪一步 | 阅读入口 |
| --- | --- | --- |
| 美国国债的 10 年期与 3 个月期利差能提前一年预警衰退吗? | 美国单指标模型已部分复现并暂存。模型对 1990 年第四季度的提前一年预测为 27.23%, 原文报告 25%。与原文另外三种指标的比较仍缺历史序列。 | [复现报告与重跑命令](replications/macro-ind-001/docs/03_repro_report.md) · [逐季预测表](replications/macro-ind-001/outputs/forecasts.csv) |
| Ant-Transformer 能改善美股的月度收益排序吗? | 已完成首轮试验。19 个样本外月份中, 完整模型与岭回归的平均 Rank IC 仅相差 0.0002, 差值的 95% 置信区间包含零。 | [试验报告与复跑步骤](outputs/eq-cs-002/ant_transformer_pilot/report.md) · [实验配置](configs/eq-cs-002_ant_transformer.yaml) |
| 用三因子回归残差构造动量会怎样? | 已整理论文方法和实验配置, 尚待实证。 | [残差动量研究卡片](research/equities/cross_sectional/2011-blitz-residual-momentum.md) |

[研究总览](research/INDEX.md) 按研究领域列出全部卡片及其状态。

## 本地运行

在仓库根目录使用 Python 3.12 和 uv。完整测试会导入中国城市宏观模块, 需要一并安装地理和栅格数据依赖。

```sh
uv run --locked --extra cn-macro pytest -q
```

如果想从头复现一项研究, 可以从美国利差模型开始。[数据流程](replications/macro-ind-001/docs/02_data_flow.md) 说明如何从 FRED 和 NBER 构造季度面板。复现报告末尾的命令在该实验的独立环境中运行, 从抓取数据一直到检查预测时点。美股试验则需要另行准备报告指定的模型版本和冻结数据快照 `quant-lab-data-v1.0.0`。

## 数据与代码

- **中国城市宏观数据**涵盖地级市 GDP、城市统计年鉴、PM10 和碳排放。各表覆盖的城市和年份不同, 合并前可查阅[表结构、单位与缺失情况](src/quant_research_lab/cn_macro/README.md)。
- **美股数据**按交易日和当时可见的信息对齐价格、指数成分及 SEC 财报。参见[数据库定义与 SQL](src/quant_research_lab/db/) 和 [Python 数据读取接口](src/quant_research_lab/data/loader.py)。
- **统计检验**包括截面因子检验、时间序列检验、事件研究和多重检验校正。参见[统计模块](src/quant_research_lab/stats/)。
- **新增研究**可从[研究卡片模板](research/TEMPLATE.md) 入手, 再查阅[实验配置规范](design/05-experiment-config.md)和[项目协作约定](AGENT.md)。
