-- Dolt CSV 一体处理流水线: data/stocks_csv/*.csv → lab.duckdb (ticker_segment + prices + calendar)
-- 无需 raw_data.duckdb 中间库, 直接用 DuckDB 原生 read_csv 一步到位
--
-- 前置条件 (独立在 DuckDB CLI / GUI 运行时, 先执行这两行):
--   SET VARIABLE stocks_csv_dir = 'data/stocks_csv';
--   SET VARIABLE gap_days = 120;
--
-- 处理步骤 (幂等, 重复执行结果一致):
--   1. 建表 (ticker_segment, prices)
--   2. 一次性扫描 ohlcv.csv 落入临时表 clean_ohlcv:
--        - 剔除 close <= 0 或 close IS NULL 的脏行
--        - 剔除全市场无有效成交量 (volume > 0) 的休市日假数据 (例如 2020-02-17 总统日)
--   3. 切段写入 ticker_segment:
--        - 同一代码前后两条行情间隔超过 gap_days 个交易日时切分为不同证券
--        - 最新一段沿用原代码, 旧段改名为 {symbol}~{YYYYMMDD}
--   4. 直接读取 split.csv / dividend.csv 做全收益复权写入 prices (向后复权, 最新价 = 原始价):
--        - 拆股: ex 日之前的价格乘以 for_factor / to_factor
--          * 幽灵拆股校验: 大比例拆合股 (|ln(f)| >= 0.15) 须使当日价格更连续
--            |ln((close / prev_close) / f)| < |ln(close / prev_close)|,
--            自动过滤 Dolt 源的重复/错日拆股记录 (如 AMZN 2022-05-26, GOOGL 2022-06-30)
--        - 分红: ex 日之前的价格乘以 1 - amount / 前一交易日原始收盘价
--        - 非交易日事件顺延至该段内 >= ex_date 的第一个交易日; 落在空档期的事件丢弃
--   5. 更新 calendar 视图并返回写入 prices 的行数

-- 1. 建表
CREATE TABLE IF NOT EXISTS ticker_segment (
    symbol VARCHAR NOT NULL,
    ticker VARCHAR NOT NULL,
    seg_no INTEGER NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    n_days INTEGER NOT NULL,
    gap_before INTEGER,

    PRIMARY KEY (ticker),
    UNIQUE (symbol, seg_no),
    CHECK (start_date <= end_date)
);

CREATE TABLE IF NOT EXISTS prices (
    date DATE NOT NULL,
    ticker VARCHAR NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE NOT NULL,
    adj_close DOUBLE,
    volume BIGINT,
    PRIMARY KEY (ticker, date),
    CHECK (volume >= 0)
);

-- 2. 一次性扫描 ohlcv.csv 清洗并落入临时表: 剔除无效收盘价 + 全市场零成交的休市日
-- 文件末尾手动 DROP
CREATE OR REPLACE TEMP TABLE clean_ohlcv AS
WITH raw_px AS (
    SELECT date, act_symbol, open, high, low, close, volume
    FROM read_csv(

        -- getvariable('stocks_csv_dir')：读取 DuckDB 的环境变量
        getvariable('stocks_csv_dir') || '/ohlcv.csv',
        header = true,      -- 第一行是表头

        -- 手动写死每一列的数据类型（日期用 DATE，代码用 VARCHAR，价格用 DOUBLE，成交量用 BIGINT
        -- 如果不写，DuckDB 会自己抽样猜类型
        columns = {
            'date': 'DATE',
            'act_symbol': 'VARCHAR',
            'open': 'DOUBLE',
            'high': 'DOUBLE',
            'low': 'DOUBLE',
            'close': 'DOUBLE',
            'volume': 'BIGINT'
        }
    )
    WHERE close > 0     -- 在 SQL 里，NULL > 0 的结果不是真
),
valid_dates AS (
    SELECT date
    FROM raw_px
    WHERE volume > 0
    GROUP BY date
)
SELECT o.*
FROM raw_px AS o

-- SEMI JOIN（半连接): 拿右表 v 当一个“白名单”去筛左表 o——只保留日期在白名单里的行，既不会把右表的列拼过来，也不会因为关联导致行数翻倍
-- USING (date)：当两张表用来关联的列名一模一样时，这是 ON o.date = v.date 的简写
-- 正常交易日里，有些极冷门的股票当天确实可能 0 成交，但它的收盘价依然有效
-- 先找 valid_dates 再 SEMI JOIN，就能精准做到“只删假休市日，不误伤冷门股”
SEMI JOIN valid_dates AS v USING (date);

-- 3. 切段写入 ticker_segment
DELETE FROM ticker_segment;

INSERT INTO ticker_segment (symbol, ticker, seg_no, start_date, end_date, n_days, gap_before)

-- 给全市场交易日编序号
WITH cal AS (
    SELECT date, row_number() OVER (ORDER BY date) AS di        -- 用 row_number() 给它们编上连续整数 1, 2, 3, ...
    FROM (SELECT DISTINCT date FROM clean_ohlcv)
),
gaps AS (
    SELECT
        o.act_symbol,
        o.date,
        c.di - lag(c.di) OVER (PARTITION BY o.act_symbol ORDER BY o.date) AS gap

    FROM clean_ohlcv AS o
    JOIN cal AS c USING (date)
),
flagged AS (
    SELECT
        act_symbol,
        date,
        CASE WHEN gap > getvariable('gap_days') THEN gap END AS new_seg_gap,
        sum(CASE WHEN gap > getvariable('gap_days') THEN 1 ELSE 0 END) OVER (
            PARTITION BY act_symbol ORDER BY date ROWS UNBOUNDED PRECEDING
        ) AS seg_no
    FROM gaps
),
seg AS (
    SELECT
        act_symbol AS symbol,
        seg_no,
        min(date) AS start_date,
        max(date) AS end_date,
        count(*) AS n_days,
        max(new_seg_gap) AS gap_before
    FROM flagged
    GROUP BY act_symbol, seg_no
)
SELECT
    symbol,
    CASE
        WHEN seg_no = max(seg_no) OVER (PARTITION BY symbol) THEN symbol
        ELSE symbol || '~' || strftime(end_date, '%Y%m%d')
    END AS ticker,
    seg_no,
    start_date,
    end_date,
    n_days,
    gap_before
FROM seg;

-- 4. 全收益复权写入 prices
DELETE FROM prices;

INSERT INTO prices (date, ticker, open, high, low, close, adj_close, volume)
WITH px AS (
    SELECT
        o.date,
        s.ticker,
        s.symbol,
        s.start_date,
        s.end_date,
        o.open,
        o.high,
        o.low,
        o.close,
        o.volume,
        lag(o.close) OVER (PARTITION BY s.ticker ORDER BY o.date) AS prev_close
    FROM clean_ohlcv AS o
    JOIN ticker_segment AS s
        ON o.act_symbol = s.symbol
        AND o.date BETWEEN s.start_date AND s.end_date
),
raw_events AS (
    SELECT act_symbol, ex_date, 'split' AS kind, for_factor / to_factor AS value
    FROM read_csv(
        getvariable('stocks_csv_dir') || '/split.csv',
        header = true,
        columns = {
            'act_symbol': 'VARCHAR',
            'ex_date': 'DATE',
            'to_factor': 'DOUBLE',
            'for_factor': 'DOUBLE'
        }
    )
    WHERE to_factor > 0 AND for_factor > 0
    UNION ALL
    SELECT act_symbol, ex_date, 'dividend' AS kind, amount AS value
    FROM read_csv(
        getvariable('stocks_csv_dir') || '/dividend.csv',
        header = true,
        columns = {
            'act_symbol': 'VARCHAR',
            'ex_date': 'DATE',
            'amount': 'DOUBLE'
        }
    )
    WHERE amount > 0
),
mapped AS (
    -- ASOF: 找同一代码 >= ex_date 的第一条行情
    SELECT e.kind, e.value, e.ex_date, p.ticker, p.date, p.close, p.prev_close, p.start_date
    FROM raw_events AS e
    ASOF JOIN px AS p
        ON e.act_symbol = p.symbol
        AND p.date >= e.ex_date
),
factors AS (
    SELECT
        ticker,
        date,
        CASE kind
            WHEN 'split' THEN value
            ELSE 1 - value / prev_close
        END AS f
    FROM mapped
    WHERE ex_date >= start_date                          -- 事件必须落在该段内
        AND prev_close IS NOT NULL                       -- 段首日没有可复权的历史
        AND (
            (
                kind = 'split'
                AND (
                    abs(ln(value)) < 0.15
                    OR abs(ln((close / prev_close) / value)) < abs(ln(close / prev_close))
                )
            )
            OR (kind = 'dividend' AND value < prev_close)
        )
),
ev AS (
    SELECT ticker, date, sum(ln(f)) AS log_f
    FROM factors
    GROUP BY ticker, date
)
SELECT
    p.date,
    p.ticker,
    p.open,
    p.high,
    p.low,
    p.close,
    p.close * exp(coalesce(sum(e.log_f) OVER (
        PARTITION BY p.ticker ORDER BY p.date DESC
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ), 0)) AS adj_close,
    p.volume
FROM px AS p
LEFT JOIN ev AS e USING (ticker, date);

DROP TABLE IF EXISTS clean_ohlcv;

-- 5. 更新交易日历视图
CREATE OR REPLACE VIEW calendar AS
SELECT DISTINCT date
FROM prices;

SELECT count(*) FROM prices;
