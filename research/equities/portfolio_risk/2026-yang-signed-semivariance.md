---
id: cn-semivariance
title: “好”“坏”波动与系统性风险预测
source_type: paper
source_url: https://doi.org/10.19920/j.cnki.jmsc.2026.01.001
year: 2026
authors:
- Zihui Yang
- Zhiying Dai
- Dongcheng Li
sector: equities
domain: portfolio_risk
universe: CSI300 2022-11
horizon: weekly
target_object: 公司周度收益与下周系统性风险
model_family: panel_regression
estimation_method: realized_semivariance
data_required:
- cn_5min
- qlib_cn_daily
- firm_week_dcovar
feasibility: blocked_data_missing
one_liner: 用日内正负收益的半方差检验风险预测增量
key_highlight: 区分方向与波动总量并验证下一周风险
key_risk: 事后成分及风险序列构造未完全公开
tags:
- china
- semivariance
status: in_progress
scouted_at: '2026-11-25'
experimented: true
experiments:
- name: 公开子样本表1第一列
  config_file: replications/cn-semivariance/configs/pilot.yaml
  report_path: replications/cn-semivariance/docs/03_repro_report.md
  ran_at: '2026-11-25'
  outcome: inconclusive
  summary: 4759 个公司周同周系数分别为 −0.8117 和 +0.7886, 风险预测有待验证
---

# “好”“坏”波动与系统性风险预测

## 1. 核心直觉
同样的总波动可以来自盘中上涨或下跌。将两侧拆开可以衡量下行压力在周度聚合后解释了多少股票收益差异, 并检验它是否携带下一周风险的信息。

## 2. 研究对象的核心建模
同周收益对正负半方差分别回归, 控制行业和年份效应。随后以公司下一周的条件在险价值差为被解释变量, 比较加入高频指标前后的样本外预测误差。

## 3. 数据映射与复现改造
先将 Qlib 日行情和历史成分与公开五分钟行情对齐。按周三至周二归集, 用完整的五日周独立核验表 1 第一列, 风险序列和控制变量保留为其他表的数据依赖。

## 4. 亮点, 假设与失效边界
原文选择研究期结束后的固定名单, 样本含存续选择效应。小样本中的行业权重不同, 方向和数量级需分开评估。同周关联本身无法证明下一周的风险可预测。

## 5. 实证结论
12 家企业共 4759 个公司周, RSN = −0.8117, RSP = +0.7886, 与表 1 方向一致。表 3 和表 4 尚缺风险口径。
