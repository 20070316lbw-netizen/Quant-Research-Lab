-- Kenneth French 日频因子写入 ff_factors_daily
-- 输入 df: quant_research_lab.data.p0_fetch.fetch_ken_french_daily() 的输出
DELETE FROM ff_factors_daily;

INSERT INTO ff_factors_daily (date, mkt_rf, smb, hml, rmw, cma, rf, mom, st_rev, lt_rev)
SELECT
    CAST(date AS DATE),
    mkt_rf,
    smb,
    hml,
    rmw,
    cma,
    rf,
    mom,
    st_rev,
    lt_rev
FROM df
ORDER BY date;
