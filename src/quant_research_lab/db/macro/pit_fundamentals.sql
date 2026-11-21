-- Point-in-Time (PIT) 基本面查询表宏
--
-- 遵守 Design.md 时点规则:
--   1. universe: 取 snapshot_date <= as_of_date 的最新一期快照, 将 ticker 映射到 cik
--   2. fundamental_*: 仅可见 filed < as_of_date 的记录 (filed 之后下一个交易日才可见)
--   3. 财报类型: 仅包含常规季报/年报及其修订版 (10-K, 10-Q, 10-K/A, 10-Q/A)
--   4. 修订去重: 同一 (fact_kind, cik, taxonomy, tag, unit, start_date, end_date)
--      在可见记录中取 filed 最新的一条 (同日按 accn 降序)
--   5. 截取期数: 每个指标按 end_date 倒序编号 report_rank (1 为最新), 保留前 n_reports 条 (默认 5)
--
-- 提供 2 个表宏:
--   - pit_fundamentals(as_of_date, n_reports := 5)
--   - pit_fundamentals_by_ticker(target_ticker, as_of_date, n_reports := 5)

CREATE OR REPLACE MACRO pit_fundamentals(as_of_date, n_reports := 5) AS TABLE
WITH pit_univ AS (
    SELECT ticker, cik
    FROM universe
    WHERE snapshot_date = (
        SELECT max(snapshot_date)
        FROM universe
        WHERE snapshot_date <= CAST(as_of_date AS DATE)
    )
    AND cik <> '0000000000'
),
target_ciks AS (
    SELECT DISTINCT cik FROM pit_univ
),
visible_facts AS (
    SELECT
        'instant' AS fact_kind,
        f.cik,
        f.taxonomy,
        f.tag,
        f.unit,
        CAST(NULL AS DATE) AS start_date,
        f.end_date,
        f.val,
        f.accn,
        f.filed,
        f.form,
        f.fy,
        f.fp,
        f.frame
    FROM fundamental_instant AS f
    SEMI JOIN target_ciks AS c USING (cik)
    WHERE f.filed < CAST(as_of_date AS DATE)
      AND f.form IN ('10-K', '10-Q', '10-K/A', '10-Q/A')

    UNION ALL

    SELECT
        'period' AS fact_kind,
        f.cik,
        f.taxonomy,
        f.tag,
        f.unit,
        f.start_date,
        f.end_date,
        f.val,
        f.accn,
        f.filed,
        f.form,
        f.fy,
        f.fp,
        f.frame
    FROM fundamental_period AS f
    SEMI JOIN target_ciks AS c USING (cik)
    WHERE f.filed < CAST(as_of_date AS DATE)
      AND f.form IN ('10-K', '10-Q', '10-K/A', '10-Q/A')
),
deduped AS (
    SELECT *
    FROM visible_facts
    QUALIFY row_number() OVER (
        PARTITION BY fact_kind, cik, taxonomy, tag, unit, start_date, end_date
        ORDER BY filed DESC, accn DESC
    ) = 1
),
ranked AS (
    SELECT
        u.ticker,
        d.cik,
        d.fact_kind,
        d.taxonomy,
        d.tag,
        d.unit,
        d.start_date,
        d.end_date,
        d.val,
        d.accn,
        d.filed,
        d.form,
        d.fy,
        d.fp,
        d.frame,
        row_number() OVER (
            PARTITION BY u.ticker, d.fact_kind, d.cik, d.taxonomy, d.tag, d.unit
            ORDER BY d.end_date DESC, d.start_date DESC NULLS LAST, d.filed DESC, d.accn DESC
        ) AS report_rank
    FROM deduped AS d
    JOIN pit_univ AS u USING (cik)
)
SELECT *
FROM ranked
WHERE report_rank <= n_reports;

CREATE OR REPLACE MACRO pit_fundamentals_by_ticker(target_ticker, as_of_date, n_reports := 5) AS TABLE
WITH pit_univ AS (
    SELECT ticker, cik
    FROM universe
    WHERE snapshot_date = (
        SELECT max(snapshot_date)
        FROM universe
        WHERE snapshot_date <= CAST(as_of_date AS DATE)
    )
    AND ticker = target_ticker
    AND cik <> '0000000000'
),
visible_facts AS (
    SELECT
        'instant' AS fact_kind,
        f.cik,
        f.taxonomy,
        f.tag,
        f.unit,
        CAST(NULL AS DATE) AS start_date,
        f.end_date,
        f.val,
        f.accn,
        f.filed,
        f.form,
        f.fy,
        f.fp,
        f.frame
    FROM fundamental_instant AS f
    SEMI JOIN pit_univ AS c USING (cik)
    WHERE f.filed < CAST(as_of_date AS DATE)
      AND f.form IN ('10-K', '10-Q', '10-K/A', '10-Q/A')

    UNION ALL

    SELECT
        'period' AS fact_kind,
        f.cik,
        f.taxonomy,
        f.tag,
        f.unit,
        f.start_date,
        f.end_date,
        f.val,
        f.accn,
        f.filed,
        f.form,
        f.fy,
        f.fp,
        f.frame
    FROM fundamental_period AS f
    SEMI JOIN pit_univ AS c USING (cik)
    WHERE f.filed < CAST(as_of_date AS DATE)
      AND f.form IN ('10-K', '10-Q', '10-K/A', '10-Q/A')
),
deduped AS (
    SELECT *
    FROM visible_facts
    QUALIFY row_number() OVER (
        PARTITION BY fact_kind, cik, taxonomy, tag, unit, start_date, end_date
        ORDER BY filed DESC, accn DESC
    ) = 1
),
ranked AS (
    SELECT
        u.ticker,
        d.cik,
        d.fact_kind,
        d.taxonomy,
        d.tag,
        d.unit,
        d.start_date,
        d.end_date,
        d.val,
        d.accn,
        d.filed,
        d.form,
        d.fy,
        d.fp,
        d.frame,
        row_number() OVER (
            PARTITION BY u.ticker, d.fact_kind, d.cik, d.taxonomy, d.tag, d.unit
            ORDER BY d.end_date DESC, d.start_date DESC NULLS LAST, d.filed DESC, d.accn DESC
        ) AS report_rank
    FROM deduped AS d
    JOIN pit_univ AS u USING (cik)
)
SELECT *
FROM ranked
WHERE report_rank <= n_reports;
