-- Kenneth French 日频学术因子与无风险利率表 (单位: 小数收益率)
CREATE TABLE IF NOT EXISTS ff_factors_daily (
    date DATE NOT NULL PRIMARY KEY,     -- 交易日, 防止重复日期
    mkt_rf DOUBLE,
    smb DOUBLE,
    hml DOUBLE,
    rmw DOUBLE,
    cma DOUBLE,
    rf DOUBLE,
    mom DOUBLE,
    st_rev DOUBLE,
    lt_rev DOUBLE
);
