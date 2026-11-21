-- 标普500 历史成分写入 universe
-- 输入 df: sources/sp500_history.build_universe_frame() 的输出
--   snapshot_date, symbol, wiki_cik, wiki_name, sub_industry, sec_cik, sec_name
-- 前置条件: ticker_segment 已生成, 已 SET VARIABLE stocks_csv_dir = '<CSV 目录>'
--
-- 代码映射: 找该 symbol 在 snapshot_date 当天或之前开始的最近一段;
--   找不到 (快照早于行情起点) 时取之后最早开始的一段; 都没有则保留原代码
-- 当前代码查到的 CIK/名称是否可信: 只有映射到最新一段且该段仍在交易 (结束日在全市场最后日期前 10 天内) 时才用
--   旧段或已退市段: cik 填占位 '0000000000' (与 sp500_history.CIK_PLACEHOLDER 一致)
--   name: 最新一段用 Wikipedia → SEC → symbol.csv, 旧段没有可靠名称时用入库代码本身
DELETE FROM universe;

INSERT INTO universe (snapshot_date, ticker, cik, name, exchange, sic, sub_industry)
WITH m AS (
    SELECT * FROM df
),
sym AS (
    SELECT act_symbol, security_name, listing_exchange
    FROM read_csv(
        getvariable('stocks_csv_dir') || '/symbol.csv',
        header = true,
        columns = {
            'act_symbol': 'VARCHAR',
            'security_name': 'VARCHAR',
            'listing_exchange': 'VARCHAR',
            'market_category': 'VARCHAR',
            'is_etf': 'BIGINT',
            'round_lot_size': 'BIGINT',
            'is_test_issue': 'BIGINT',
            'financial_status': 'VARCHAR',
            'cqs_symbol': 'VARCHAR',
            'nasdaq_symbol': 'VARCHAR',
            'is_next_shares': 'BIGINT',
            'last_seen': 'DATE'
        }
    )
),
back AS (
    SELECT m.*, s.ticker AS seg_ticker, s.end_date AS seg_end
    FROM m
    ASOF LEFT JOIN ticker_segment AS s
        ON m.symbol = s.symbol
        AND m.snapshot_date >= s.start_date
),
fwd AS (
    SELECT m.snapshot_date, m.symbol, s.ticker AS seg_ticker, s.end_date AS seg_end
    FROM m
    ASOF JOIN ticker_segment AS s
        ON m.symbol = s.symbol
        AND s.start_date >= m.snapshot_date
),
mapped AS (
    SELECT
        b.*,
        coalesce(b.seg_ticker, f.seg_ticker, b.symbol) AS ticker,
        coalesce(b.seg_end, f.seg_end) AS end_date
    FROM back AS b
    LEFT JOIN fwd AS f USING (snapshot_date, symbol)
),
flags AS (
    SELECT
        mapped.*,
        ticker = symbol AND end_date IS NOT NULL AS is_latest,
        ticker = symbol
            AND end_date >= (SELECT max(end_date) FROM ticker_segment) - INTERVAL 10 DAY
            AS is_trading
    FROM mapped
)
SELECT
    f.snapshot_date,
    f.ticker,
    CASE WHEN f.is_trading THEN coalesce(f.wiki_cik, f.sec_cik, '0000000000') ELSE '0000000000' END AS cik,
    CASE
        WHEN f.is_trading THEN coalesce(f.wiki_name, f.sec_name, r.security_name, f.ticker)
        WHEN f.is_latest THEN coalesce(r.security_name, f.ticker)
        ELSE f.ticker
    END AS name,
    CASE WHEN f.is_latest THEN r.listing_exchange END AS exchange,
    NULL AS sic,
    CASE WHEN f.is_trading THEN f.sub_industry END AS sub_industry
FROM flags AS f
LEFT JOIN sym AS r ON r.act_symbol = f.symbol
QUALIFY row_number() OVER (PARTITION BY f.snapshot_date, f.ticker ORDER BY f.symbol) = 1;
