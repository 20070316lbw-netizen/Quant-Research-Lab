-- CBOE 日频波动率指数写入 vol_indices_daily
-- 输入 df: quant_research_lab.data.p0_fetch.fetch_cboe_vol_indices() 的输出
DELETE FROM vol_indices_daily;

INSERT INTO vol_indices_daily (
    date,
    vix_open,
    vix_high,
    vix_low,
    vix_close,
    vix3m_open,
    vix3m_high,
    vix3m_low,
    vix3m_close,
    vvix_close,
    skew_close
)
SELECT
    CAST(date AS DATE),
    vix_open,
    vix_high,
    vix_low,
    vix_close,
    vix3m_open,
    vix3m_high,
    vix3m_low,
    vix3m_close,
    vvix_close,
    skew_close
FROM df
ORDER BY date;
