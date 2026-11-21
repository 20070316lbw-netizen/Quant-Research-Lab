CREATE TABLE IF NOT EXISTS prices(
    date DATE NOT NULL,
    ticker VARCHAR NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE NOT NULL,
    adj_close DOUBLE,
    volume BIGINT,
    PRIMARY KEY(ticker, date),
    CHECK (volume >= 0)
);
