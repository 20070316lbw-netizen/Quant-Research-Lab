-- 批量写入 fundamental_instant (由 sources/fundamental.py 按批传入 df)
-- 过滤空必填字段与非有限数值, 并按主键去重 (保留 filed 最新、带 frame 优先)
INSERT OR IGNORE INTO fundamental_instant (
    cik, taxonomy, tag, unit, end_date, val, accn, filed, form, fy, fp, frame
)
SELECT
    cik,
    taxonomy,
    tag,
    unit,
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
    AND end_date IS NOT NULL
    AND val IS NOT NULL AND isfinite(val)
    AND accn IS NOT NULL
    AND filed IS NOT NULL
    AND form IS NOT NULL
QUALIFY row_number() OVER (
    PARTITION BY cik, taxonomy, tag, unit, CAST(end_date AS DATE), accn
    ORDER BY CAST(filed AS DATE) DESC, frame DESC NULLS LAST
) = 1;
