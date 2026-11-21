CREATE TABLE IF NOT EXISTS market_calendar (
    date DATE NOT NULL PRIMARY KEY,     -- 防止出现重复日期
    weekday VARCHAR NOT NULL,
    is_open BOOLEAN NOT NULL
);
