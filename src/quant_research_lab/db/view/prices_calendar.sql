CREATE OR REPLACE VIEW prices_calendar AS
SELECT
    c.date,
    c.weekday,
    c.is_open,
    p.ticker,
    p.open,
    p.high,
    p.low,
    p.close,
    p.adj_close,
    p.volume
FROM market_calendar AS c
LEFT JOIN prices AS p USING (date);
