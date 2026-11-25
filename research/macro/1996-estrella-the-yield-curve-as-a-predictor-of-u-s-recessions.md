---
id: macro-ind-001
title: The Yield Curve as a Predictor of U.S. Recessions
source_type: paper
source_url: https://www.newyorkfed.org/research/current_issues/ci2-7.html
year: 1996
authors:
- Arturo Estrella
- Frederic S. Mishkin
sector: macro
domain: macro_indicator
universe: 美国
horizon: quarterly
target_object: 指定未来季度的美国衰退概率
model_family: other
estimation_method: expanding_window_probit
data_required:
- treasury_monthly
- nber_quarterly_chronology
feasibility: needs_macro
one_liner: 检验季度国债利差对一年后美国衰退状态的预测力
key_highlight: 同一目标季度可对照不同预测起点的概率
key_risk: 标签确认滞后与领先指数历史修订影响实时解读
tags:
- yield_curve
- recession
- probit
status: in_progress
scouted_at: '2026-11-25'
experimented: true
experiments:
- name: us_term_spread_probit
  config_file: replications/macro-ind-001/configs/us.yaml
  report_path: replications/macro-ind-001/docs/03_repro_report.md
  ran_at: '2026-11-25'
  outcome: inconclusive
  summary: 美国单指标概率和期限模式接近原文, 跨指标排名尚待验证
---

# The Yield Curve as a Predictor of U.S. Recessions

## 1. 核心直觉
货币紧缩可能先推高短端利率, 随后经济活动才放缓。市场对未来利率和通胀的预期也会改变长短端利差。论文据此询问, 今天的利差能否预告某个未来季度处于衰退。

## 2. 研究对象的核心建模
用单变量 Probit 估计 P(Y[t+h]=1)=Φ(αₕ+βₕS[t])。S 是十年期减三个月期国债收益率的季度均值, 单位为百分点。逐季扩大估计窗口, 将预测概率记在目标季度。

## 3. 数据映射与复现改造
需要公开国债利率和 NBER 季度峰谷日期。短债须按债券等价收益率换算。比较指标另外需要 NYSE 指数和两种历史领先指数, 版本待核。

## 4. 亮点, 假设与失效边界
区分用全样本估出的概率刻度与当年可形成的预警。历史衰退次数少, 同一次衰退会覆盖多个季度。后见定年的标签会影响实时解释。

## 5. 实证结论
美国利差模型提前一年对 1990Q4 的估计为 27.23% (原文 25%)。12 档利差阈值平均绝对差 0.078 个百分点。三种比较指标的独立复算仍待补齐。[报告](../../replications/macro-ind-001/docs/03_repro_report.md)
