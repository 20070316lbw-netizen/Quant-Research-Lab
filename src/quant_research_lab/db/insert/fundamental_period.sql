-- 批量写入 fundamental_period (由 sources/fundamental.py 按批传入 df)
-- 过滤空必填字段、非有限数值与 start_date > end_date 脏行, 并按主键去重
INSERT OR IGNORE INTO fundamental_period (
    cik, taxonomy, tag, unit, start_date, end_date, val, accn, filed, form, fy, fp, frame
)
SELECT
    cik,
    taxonomy,
    tag,
    unit,
    CAST(start_date AS DATE) AS start_date,
    CAST(end_date AS DATE) AS end_date,
    val,
    accn,
    CAST(filed AS DATE) AS filed,
    form,
    fy,
    fp,
    frame
FROM df
WHERE cik IS NOT NULL
    AND taxonomy IS NOT NULL
    AND tag IS NOT NULL
    AND unit IS NOT NULL
    AND start_date IS NOT NULL
    AND end_date IS NOT NULL
    AND CAST(start_date AS DATE) <= CAST(end_date AS DATE)
    AND val IS NOT NULL AND isfinite(val)
    AND accn IS NOT NULL
    AND filed IS NOT NULL
    AND form IS NOT NULL
QUALIFY row_number() OVER (
    PARTITION BY cik, taxonomy, tag, unit, CAST(start_date AS DATE), CAST(end_date AS DATE), accn
    ORDER BY CAST(filed AS DATE) DESC, frame DESC NULLS LAST
) = 1;
