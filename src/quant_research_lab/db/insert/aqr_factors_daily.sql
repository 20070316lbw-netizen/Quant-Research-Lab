-- AQR 美国日频因子写入 aqr_factors_daily
-- 输入 df: quant_research_lab.data.p0_fetch.fetch_aqr_factors_daily() 的输出
DELETE FROM aqr_factors_daily;

INSERT INTO aqr_factors_daily (date, aqr_bab_usa, aqr_qmj_usa, aqr_hml_devil_usa)
SELECT
    CAST(date AS DATE),
    aqr_bab_usa,
    aqr_qmj_usa,
    aqr_hml_devil_usa
FROM df
ORDER BY date;
