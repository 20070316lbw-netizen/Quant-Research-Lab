-- 每次跑都会先清空旧日历，再把新生成的整张表灌进去，保证数据是最新的且不冲突

DELETE FROM market_calendar;

INSERT INTO market_calendar (date, weekday, is_open)
SELECT CAST(date AS DATE), weekday, is_open     -- 因为 pandas 里存的是带时分秒的 datetime64，写进数据库前强转成纯日期 DATE，和建表语句里的类型对齐
FROM df     -- DuckDB 特色
ORDER BY date;
