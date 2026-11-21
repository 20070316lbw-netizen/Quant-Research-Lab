-- CBOE 官方日频隐含波动率与尾部偏度指数表 (单位: 指数点位)
CREATE TABLE IF NOT EXISTS vol_indices_daily (
    date DATE NOT NULL PRIMARY KEY,     -- 交易日, 防止重复日期
    vix_open DOUBLE,
    vix_high DOUBLE,
    vix_low DOUBLE,
    vix_close DOUBLE,
    vix3m_open DOUBLE,
    vix3m_high DOUBLE,
    vix3m_low DOUBLE,
    vix3m_close DOUBLE,
    vvix_close DOUBLE,
    skew_close DOUBLE
);
