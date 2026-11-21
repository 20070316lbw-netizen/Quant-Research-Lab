-- SEC EDGAR 财务数据（XBRL / companyfacts）长表, 对应会计里的流量（Period）
-- period（期间表）：存利润表、现金流量表数据（比如营收、净利润）。这些指标是一段时间内赚的，必须同时有 start_date 和 end_date
-- accn 保留所有历史版本，再配合 filed 日期还原“在历史上的某一天，市场当时到底只能看到哪份数据”

CREATE TABLE IF NOT EXISTS fundamental_period (
    cik VARCHAR NOT NULL,
    taxonomy VARCHAR NOT NULL,
    tag VARCHAR NOT NULL,
    unit VARCHAR NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    val DOUBLE NOT NULL,
    accn VARCHAR NOT NULL,
    filed DATE NOT NULL,        -- filed 是公司真正向 SEC 提交财报的日期
    form VARCHAR NOT NULL,

    -- frame 是 SEC 官方帮大家归类的标准日历标签
    -- SEC 只会给最干净的那条记录打上 frame，大量历史对比数据里这个字段都是空的
    -- fy（财年）和 fp（财季，如 Q1/FY）在部分非标准公告里也偶尔缺失
    -- 设为可空，是为了防止数据入库时因为原始数据缺字段而直接报错崩溃
    fy INTEGER,
    fp VARCHAR,
    frame VARCHAR,

    -- cik, taxonomy, tag, unit：定死“哪家公司（CIK）、哪套会计准则（如 us-gaap）、哪个财务指标（如 Revenues）、什么单位（如 USD）”
    -- start_date, end_date：同一份财报里，同一个指标往往会同时披露多个时间跨度, 必须靠起止日期区分
    -- accn（财报唯一编号）
    -- 同一个季度的营收，今年发 10-Q 时会报一次，明年发 10-Q 做同比时还会再报一次（甚至可能发生财务重述/修改
    -- 把 accn 放进主键，就能把历史上每一份财报披露的版本都原封不动地留下来，不会互相覆盖
    PRIMARY KEY (
        cik,
        taxonomy,
        tag,
        unit,
        start_date,
        end_date,
        accn
    ),

    CHECK (start_date <= end_date)
);
