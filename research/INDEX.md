# Quant Research Lab 研究总览 (自动生成, 请勿手改)

- **累计研究卡片**: 3 (已实证: 2)
- **状态分布**: `in_progress`: 2, `scouted`: 1
- **数据可行性**: `needs_macro`: 1, `ready`: 2

## equities / cross_sectional

| ID | 标题 | 模型范式 | 研究对象 | 可行性 | 状态 | 实验记录 | 一句话总结 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `eq-cs-001` | [Residual Momentum (2011)](./equities/cross_sectional/2011-blitz-residual-momentum.md) | `factor_residual` | 单股月度超额收益率 r_{i,t} | `ready` | `scouted` | 未实验 | 用 Fama-French 三因子滚动回归残差替代原始收益构造动量, 显著削弱动量崩盘风险 |
| `eq-cs-002` | [Ant-Transformer (2026)](./equities/cross_sectional/2026-liu-ant-transformer.md) | `other` | 个股下一持有月收益率的截面排序 | `ready` | `in_progress` | 已实验 (1): `eq-cs-002_ant_transformer.yaml` | 测试跨层注意力和软门控是否改善美股月度收益率排序 |

## macro / macro_indicator

| ID | 标题 | 模型范式 | 研究对象 | 可行性 | 状态 | 实验记录 | 一句话总结 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `macro-ind-001` | [The Yield Curve as a Predictor of U.S. Recessions (1996)](./macro/1996-estrella-the-yield-curve-as-a-predictor-of-u-s-recessions.md) | `other` | 指定未来季度的美国衰退概率 | `needs_macro` | `in_progress` | 已实验 (1): `us.yaml` | 检验季度国债利差对一年后美国衰退状态的预测力 |
