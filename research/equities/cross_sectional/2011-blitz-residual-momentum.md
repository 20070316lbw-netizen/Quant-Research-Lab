---
id: eq-cs-001
title: Residual Momentum
source_type: paper
source_url: https://doi.org/10.1016/j.jempfin.2011.04.001
year: 2011
authors:
- David Blitz
- Joop Huij
- Martin Martens
sector: equities
domain: cross_sectional
universe: SP500
horizon: monthly
target_object: 单股月度超额收益率 r_{i,t}
model_family: factor_residual
estimation_method: rolling_ols_36m
data_required:
- prices
- universe
- ff_factors_daily
feasibility: ready
one_liner: 用 Fama-French 三因子滚动回归残差替代原始收益构造动量, 显著削弱动量崩盘风险
key_highlight: 在几乎不牺牲年化收益的前提下, 夏普比率接近翻倍并大幅降低对市场与价值因子的时变暴露
key_risk: S&P 500 大盘股中换手成本敏感, 且 2015 年后纯价量残差动量拥挤度上升
tags:
- momentum
- residual
- crash_risk
- fama_french
status: scouted
scouted_at: '2026-11-22'
experiment_ref: null
---

# Residual Momentum

## 1. 核心直觉
- 传统价格动量隐含大量对市场, 规模与价值因子的时变暴露, 在市场急转折时容易发生剧烈动量崩盘
- 将个股收益对 Fama-French 三因子做滚动回归剥离系统性风格后, 仅对特质残差构造动量可大幅平滑尾部风险

## 2. 研究对象的核心建模
- **研究对象与因变量**: 单股 t 月超额收益率 $r_{i,t} - r_{f,t}$
- **核心数学表达**: 滚动 36 个月 OLS 回归 $r_{i,\tau} - r_{f,\tau} = \alpha_i + \beta_{i,1} MKT_\tau + \beta_{i,2} SMB_\tau + \beta_{i,3} HML_\tau + \varepsilon_{i,\tau}$, 构造标准化残差动量 $RM_{i,t} = \frac{\sum_{k=2}^{12} \hat{\varepsilon}_{i,t-k}}{\sigma(\hat{\varepsilon}_{i,t-12:t-2})}$
- **估计与防泄漏设定**: 严格跳过最近 1 个月 (t-1) 规避短期反转, 回归窗口仅使用 t-36 至 t-1 已公开收益, 仅在当日 universe 成分股内排序
- **交易/决策映射**: 月末按 $RM_{i,t}$ 横截面排序, 做多前十分位 (或前 20%), 做空后十分位, 等权月度调仓

## 3. 数据映射与复现改造
- **对应本地表**: `prices` (`adj_close` 计算月度复权收益), `universe` (PIT S&P 500 成分股), `ff_factors_daily` (合成月度 MKT, SMB, HML, RF)
- **缺失项与替代方案**: 无, v1.0.0 锁定数据集已 100% 覆盖

## 4. 亮点, 假设与失效边界
- **为什么值得做**: 经典基准策略, 最适合作为首个端到端验证 S&P 500 PIT 管道与统计学工具库 (Fama-MacBeth, DSR) 的试金石
- **致命假设与失效场景**: 36 个月窗口要求成分股有较长上市历史 (新纳入股需处理冷启动), 高换手空头腿在震荡市易被交易成本侵蚀

## 5. 实证结论
- 暂未实证 (待把关立项)
