CREATE TABLE IF NOT EXISTS universe (
    snapshot_date DATE NOT NULL,
    ticker VARCHAR NOT NULL,

    cik VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    exchange VARCHAR,
    sic VARCHAR,
    sub_industry VARCHAR,

    PRIMARY KEY (snapshot_date, ticker)
);
