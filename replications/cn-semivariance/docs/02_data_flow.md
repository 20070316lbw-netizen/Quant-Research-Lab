# S1 的数据流与重跑

在本复现目录运行以下命令。uv 使用 QRL 根目录的 uv.lock 和 src 包。

```sh
uv run --locked python scripts/01_daily.py
uv run --locked python scripts/01_fetch.py
uv run --locked python scripts/02_panel.py
uv run --locked python scripts/03_table1.py
```

1. configs/pilot.yaml 固定两份行情快照、十二家公司和四个行业。01_daily.py 从 Qlib 社区完整压缩包选择复权收盘、日历及历史股票池。01_fetch.py 从免费分钟源逐股逐年读取。
2. 02_panel.py 依 2022 年 11 月底检查成分, 对每日 48 个交易时点、价格和成交量做核查。从分钟表计算日内方向风险, 单独从 Qlib 日收盘构造周收益, 按股票及结束周二对齐。完整五日周才进入回归。原始字段与派生表见 data/MANIFEST.md。
3. 03_table1.py 读取股票周样本, 缩尾并加入年份和行业哑变量, 完成表 1 第 (1) 列 OLS。OLS R² 使用全样本均值作基准, 标准误按 429 个自然周聚类, 使用有限样本修正及 G−1 自由度。原文只说明括号为标准误, 两者标准误不作直接对标。一次模型, 无参数搜索、持仓或交易成本。

其他实验可从 quant_research_lab.data 导入 read_qlib_feature 读取单项行情, 从 quant_research_lab.stats 导入 realized_semivariance 计算单股日度 RSP、RSN 和 RV。交易时段、周界线与年化约定由各实验指定。
