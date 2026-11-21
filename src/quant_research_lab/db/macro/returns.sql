-- 收益率表宏: 按每只证券自己的交易记录计数 (不补交易日), 端点缺失或价格非正时结果为 NULL
--
-- 提供 3 个表宏:
--   - pit_historical_return(as_of_date, n_periods := 5, price_col := 'adj_close')
--       price[t] / price[t - n_periods] - 1, 只用 date <= as_of_date 的行情, 可作特征
--   - pit_log_return(as_of_date, price_col := 'adj_close')
--       ln(price[t]) - ln(price[t - 1]), 只用 date <= as_of_date 的行情, 可作特征
--   - label_forward_return(n_periods := 5, gap := 1, price_col := 'adj_close')
--       price[t + gap + n_periods] / price[t + gap] - 1
--       !!! 使用未来数据, 只能作为监督学习标签, 回测引擎 / PIT DataView 禁止调用 !!!
--       额外输出 entry_date / exit_date, 交叉验证做 purging / embargo 时直接用 exit_date
--
-- PIT 规则: pit_* 宏先过滤 date <= as_of_date 再开窗, 任何输出行都只依赖 as_of_date 收盘时可见的价格
-- price_col 只接受 'adj_close' (全收益复权, 默认) 或 'close'; 参数不合法时直接报错

CREATE OR REPLACE MACRO pit_historical_return(as_of_date, n_periods := 5, price_col := 'adj_close') AS TABLE
WITH args AS (
    SELECT CASE
        WHEN n_periods IS NULL OR n_periods < 1 OR n_periods <> trunc(n_periods)
            THEN error('n_periods 必须是 >= 1 的整数, 实际为 ' || coalesce(CAST(n_periods AS VARCHAR), 'NULL'))
        WHEN price_col IS NULL OR price_col NOT IN ('adj_close', 'close')
            THEN error('price_col 只能是 adj_close 或 close, 实际为 ' || coalesce(CAST(price_col AS VARCHAR), 'NULL'))
    END AS invalid
),
raw AS (
    SELECT p.date, p.ticker, CASE WHEN price_col = 'close' THEN p.close ELSE p.adj_close END AS price
    FROM prices AS p, args
    WHERE p.date <= CAST(as_of_date AS DATE)
      AND args.invalid IS NULL
),
px AS (
    SELECT date, ticker, CASE WHEN price > 0 THEN price END AS price
    FROM raw
)
SELECT
    date,
    ticker,
    price / lag(price, CAST(n_periods AS INTEGER)) OVER (PARTITION BY ticker ORDER BY date) - 1 AS historical_return
FROM px
ORDER BY ticker, date;

CREATE OR REPLACE MACRO pit_log_return(as_of_date, price_col := 'adj_close') AS TABLE
WITH args AS (
    SELECT CASE
        WHEN price_col IS NULL OR price_col NOT IN ('adj_close', 'close')
            THEN error('price_col 只能是 adj_close 或 close, 实际为 ' || coalesce(CAST(price_col AS VARCHAR), 'NULL'))
    END AS invalid
),
raw AS (
    SELECT p.date, p.ticker, CASE WHEN price_col = 'close' THEN p.close ELSE p.adj_close END AS price
    FROM prices AS p, args
    WHERE p.date <= CAST(as_of_date AS DATE)
      AND args.invalid IS NULL
),
px AS (
    SELECT date, ticker, CASE WHEN price > 0 THEN price END AS price
    FROM raw
)
SELECT
    date,
    ticker,
    ln(price) - ln(lag(price) OVER (PARTITION BY ticker ORDER BY date)) AS log_return
FROM px
ORDER BY ticker, date;

CREATE OR REPLACE MACRO label_forward_return(n_periods := 5, gap := 1, price_col := 'adj_close') AS TABLE
WITH args AS (
    SELECT CASE
        WHEN n_periods IS NULL OR n_periods < 1 OR n_periods <> trunc(n_periods)
            THEN error('n_periods 必须是 >= 1 的整数, 实际为 ' || coalesce(CAST(n_periods AS VARCHAR), 'NULL'))
        WHEN gap IS NULL OR gap < 0 OR gap <> trunc(gap)
            THEN error('gap 必须是 >= 0 的整数, 实际为 ' || coalesce(CAST(gap AS VARCHAR), 'NULL'))
        WHEN price_col IS NULL OR price_col NOT IN ('adj_close', 'close')
            THEN error('price_col 只能是 adj_close 或 close, 实际为 ' || coalesce(CAST(price_col AS VARCHAR), 'NULL'))
    END AS invalid
),
raw AS (
    SELECT p.date, p.ticker, CASE WHEN price_col = 'close' THEN p.close ELSE p.adj_close END AS price
    FROM prices AS p, args
    WHERE args.invalid IS NULL
),
px AS (
    SELECT date, ticker, CASE WHEN price > 0 THEN price END AS price
    FROM raw
),
legs AS (
    SELECT
        date,
        ticker,
        lead(date, CAST(gap AS INTEGER)) OVER w AS entry_date,
        lead(date, CAST(gap + n_periods AS INTEGER)) OVER w AS exit_date,
        lead(price, CAST(gap AS INTEGER)) OVER w AS entry_price,
        lead(price, CAST(gap + n_periods AS INTEGER)) OVER w AS exit_price
    FROM px
    WINDOW w AS (PARTITION BY ticker ORDER BY date)
)
SELECT
    date,
    ticker,
    entry_date,
    exit_date,
    exit_price / entry_price - 1 AS forward_return
FROM legs
ORDER BY ticker, date;
