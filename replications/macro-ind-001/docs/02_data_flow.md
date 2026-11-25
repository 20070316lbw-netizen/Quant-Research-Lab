# 从月度利率到季度预测

1. 在项目根目录运行 scripts/01_fetch_and_clean.py。它读取 configs/us.yaml, 将 FRED 和 NBER 表标准化到 data/raw 并通过同一批记录生成 data/clean/quarterly.csv。字段与缺失检查见 [数据字典](../data/MANIFEST.md)。
2. scripts/03_spread.py 把利差按期限滞后, 以目标季为索引与衰退标签配对。四季度全样本 Probit 有 141 个配对, 训练不使用原文阈值。拟合结束后才读取 configs/paper_thresholds.csv 进行对照。
3. 对每个期限和目标季重新拟合模型。最晚训练标签等于预测起点。保存每次训练行数、历史衰退频率和预测概率至 outputs/forecasts.csv (4 × 97 行), 绘图以目标季为横轴。
4. scripts/verify_timing.py 在独立临时副本修改 1989Q4 之后的利差和衰退状态。317 条起报日期在 1989Q4 及以前的预测在绝对容差 1e-10 内一致。该检验覆盖信息时间对齐, 无法检验 NBER 历史公告可得性。
