---
id: eq-cs-002
title: Ant-Transformer
source_type: github
source_url: https://github.com/20070316lbw-netizen/ant-transformer
year: 2026
authors:
- Bowei Liu
sector: equities
domain: cross_sectional
universe: SP500
horizon: monthly
target_object: 个股下一持有月收益率的截面排序
model_family: other
estimation_method: supervised_sequence_regression
data_required:
- prices
- universe
- calendar
feasibility: ready
one_liner: 测试跨层注意力和软门控是否改善美股月度收益率排序
key_highlight: 以同深度的无门控模型、线性模型和动量控制结构增量
key_risk: 月度截面样本有限, 行情缺失时只能用价格近似退出价值
tags:
- transformer
- momentum
- ablation
status: in_progress
scouted_at: '2026-11-22'
experimented: true
experiments:
- name: ant_transformer_pilot
  config_file: configs/eq-cs-002_ant_transformer.yaml
  report_path: outputs/eq-cs-002/ant_transformer_pilot/report.md
  ran_at: '2026-11-22'
  outcome: inconclusive
  summary: 在 19 个样本外月份中, 完整 Ant Rank IC +0.0233, 岭回归 +0.0231。完整 Ant 相对岭回归的 Holm 校正
    p 值 1.000。
---

# Ant-Transformer

## 1. 核心直觉
模型在单只股票的月度特征序列上学习非线性关系, 并在更深的层读取先前层的隐状态。实验检查这两种机制的增量信息能否超过动量与岭回归。

## 2. 研究对象的核心建模
以连续六个月的价量因子为输入, 输出下一持有月收益的截面分数。门控计算 $h=g\odot f+(1-g)\odot h_{in}$。按标签实现时间隔离训练和验证, 用验证集 Rank IC 选轮次, 在留出的时间段比较等权头尾五分位。

## 3. 数据映射与复现改造
用 lab.duckdb 的行情、历史成分和交易日历构造月度样本。用五个美股价量特征代替原 A 股六因子, 保留 Ant 编码器和首 token 读出。

## 4. 亮点, 假设与失效边界
跨层注意力与门控做两因素消融。逐月股票数目较多, 但有效时间样本有限。无下一开盘报价时按预定规则处理, 交易成本以固定费率估算。

## 5. 实证结论
在 19 个样本外月份中, 完整 Ant Rank IC +0.0233, 岭回归 +0.0231。完整 Ant 相对岭回归的 Holm 校正 p 值 1.000。 详见对应报告的结构消融、成本敏感性和样本警告。
