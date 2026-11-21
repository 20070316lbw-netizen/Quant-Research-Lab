-- AQR 官方美国日频股票因子表 (单位: 小数收益率)
CREATE TABLE IF NOT EXISTS aqr_factors_daily (
    date DATE NOT NULL PRIMARY KEY,     -- 交易日, 防止重复日期
    aqr_bab_usa DOUBLE,
    aqr_qmj_usa DOUBLE,
    aqr_hml_devil_usa DOUBLE
);
