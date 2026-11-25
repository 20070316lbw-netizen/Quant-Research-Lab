# 数据清单与拆分

|原始文件|来源与字段|下游|
|---|---|---|
|qlib_bin.tar.gz|chenditc/investment_data 的 2026-11-24 发布包。日历 day.txt 为交易日期, csi300.txt 为代码及纳入/退出区间, adjclose.day.bin 首元素为日历起点偏移, 后续为复权收盘 float32|01_daily.py → 02_panel.py|
|股票代码-年份.csv|OpenFinMind/stock_dataset, 提交固定于 configs/pilot.yaml。日期与北京时间为条末, 开盘/最高/最低/收盘为源行情价, 成交量和成交额沿用源单位。仅用方向、价格比与全天是否有成交|01_fetch.py → 02_panel.py|

## 数据拆分说明

- snapshot.csv 保留 2022-11-30 落在成员起止日期内的记录 (ticker/start/end), 校验抽样名单。先选银行、保险、白酒、家电各三家, 固定名单写入 YAML。行业是本试验的手工分组。
- weekly.csv 每行一股一周, week 为周二标签, ticker 为交易所加代码, industry 为上述行业, rsn/rsp 为年化下行/上行波动, ret 为相邻自然周最后一个交易日的复权收盘简单收益, 均以小数表示。每个完整交易日必须有 48 个唯一时点、有效正价格且总成交量大于零。以日内首开作为首根起点, 午后第一根接上午收盘。只保留五个有效交易日的周, 不向前借日。模型在 03_table1.py 读取此表。
- daily_crosscheck.csv 将Qlib 日线收益与分钟源最后一根收盘的日收益对齐, date/qlib/minute/ticker; 分钟源复权口径未披露, 除权日等可能出现差异。coverage.csv 按股票列出实际年文件数、缺年、分钟行数、原始交易日数、有效交易日数及最终周数。summary.json 和 table1.csv 保存该次试验的统计量。
- **偏差**: 使用期后固定名单有幸存者偏差。12 家便利样本、四行业分类与完整五日周会改变行业、假期及停牌周权重。原文的申报日、重述及风险指标细则未取得。原始行情及公司周明细不随 Git 分发。
