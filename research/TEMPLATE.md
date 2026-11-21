---
id: "eq-cs-000"
title: "论文或项目原始标题"
source_type: "paper"
source_url: "https://..."
year: 2024
authors:
  - "First Author"
sector: "equities"
domain: "cross_sectional"
universe: "SP500"
horizon: "monthly"
target_object: "单股月度超额收益率 r_{i,t}"
model_family: "factor_residual"
estimation_method: "rolling_ols_36m"
data_required:
  - "prices"
  - "universe"
  - "ff_factors_daily"
feasibility: "ready"
one_liner: "一句话总结核心思想与主要发现"
key_highlight: "相对同类研究的增量亮点"
key_risk: "主要风险, 过拟合隐患或失效边界"
tags:
  - "example"
status: "scouted"
scouted_at: "2026-11-22"
experiment_ref: null
---

# 论文或项目原始标题

## 1. 核心直觉
- 解决了什么痛点, 背后的经济学或市场微观结构逻辑是什么 (3 句话内)

## 2. 研究对象的核心建模
- **研究对象与因变量**: 明确建模目标
- **核心数学表达**: 核心回归方程, 状态空间或优化目标与约束
- **估计与防泄漏设定**: 窗口长度, 滞后阶数, 横截面标准化与 Point-in-Time 对齐方式
- **交易/决策映射**: 模型输出如何转为持仓权重或状态判断

## 3. 数据映射与复现改造
- **对应本地表**: 列出 `lab.duckdb` / Parquet 表与关键列
- **缺失项与替代方案**: 无或注明替代口径

## 4. 亮点, 假设与失效边界
- **为什么值得做**: 增量价值
- **致命假设与失效场景**: 换手成本, 拥挤度, 风格切换等边界条件

## 5. 实证结论
- 暂未实证 (待把关立项)
