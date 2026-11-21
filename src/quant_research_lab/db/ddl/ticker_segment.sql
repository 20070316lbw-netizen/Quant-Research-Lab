-- 代码切段表: 同一个 raw 代码前后两条行情间隔超过阈值 (默认 120 个交易日) 时视为不同证券
-- 最新一段沿用原代码, 更早的段改名为 {symbol}~{该段最后交易日 YYYYMMDD}
-- prices.ticker 和 universe.ticker 都取自本表的 ticker 列
CREATE TABLE IF NOT EXISTS ticker_segment (
    symbol VARCHAR NOT NULL,        -- raw_ohlcv.act_symbol 原始代码
    ticker VARCHAR NOT NULL,        -- 入库代码, 最新一段等于 symbol
    seg_no INTEGER NOT NULL,        -- 段序号, 从 0 开始按时间递增
    start_date DATE NOT NULL,       -- 该段第一条行情日期
    end_date DATE NOT NULL,         -- 该段最后一条行情日期
    n_days INTEGER NOT NULL,        -- 该段行情条数
    gap_before INTEGER,             -- 与上一段之间相隔的交易日数, 第一段为 NULL

    PRIMARY KEY (ticker),
    UNIQUE (symbol, seg_no),
    CHECK (start_date <= end_date)
);
