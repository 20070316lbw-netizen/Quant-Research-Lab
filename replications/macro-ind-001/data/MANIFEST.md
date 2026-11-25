# 美国季度面板数据字典

2026-11-25 抓取。FRED 和 NBER 的来源 URL 在 configs/us.yaml。数据按仓库约定在本地生成, 原始数据与清洗面板不进入版本控制。

| 本地 CSV | 主键及范围 | 列与口径 | 消费脚本 |
| --- | --- | --- | --- |
| raw/rates.csv | observation_date, 1959-01 至 1995-03, 435 行 | 日期为月初的观测期标记。GS10 为十年期固定期限年收益率, TB3MS 为三个月券二级市场年贴现率, 单位均为百分数 | 01_fetch_and_clean.py |
| raw/cycles.csv | peak, 样本期内 6 轮 | peak、trough 均为 NBER 直接给出的季度代码, 使用最终定年 | 01_fetch_and_clean.py |
| clean/quarterly.csv | quarter, 1959Q1 至 1995Q1, 145 行 | GS10、TB3MS 为原月度报价的季均值。bill_be 为先换算再平均的短债年收益率 (%)。spread = GS10 − bill_be (百分点)。recession 为 0/1 状态 | 03_spread.py |

## 数据拆分说明

取 435 个连续月份, 每季 3 行, 日期无重复、无缺失。对 TB3MS 的每个月值 d (百分数) 计算 365d/(360−91d/100)。合并季度标签时排除峰值季、包含谷底季, 合计 21 个衰退季度。保留 1959 年作为利差滞后观测, 四季预测自 1960Q1 起形成完整配对。六季预测最早配对目标为 1960Q3。

短债固定 91 天是近似值。作者历史源表及 NBER 逐期公告版本没有随本项目输入。样本外采用事后定年, 属于伪实时预测。Commerce LEAD、Stock-Watson XLI 和 NYSE 月均价原口径的全长同版本输入尚未取得。
