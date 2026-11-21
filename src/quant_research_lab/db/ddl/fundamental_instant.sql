-- 对应会计里的存量（Instant）
-- instant（时点表）：存资产负债表数据（比如总资产、现金, 这些指标是某一天的快照，没有起始日期

CREATE TABLE IF NOT EXISTS fundamental_instant (
    cik VARCHAR NOT NULL,
    taxonomy VARCHAR NOT NULL,      -- 指标所属分类，例如 us-gaap
    tag VARCHAR NOT NULL,           -- 原始指标名，例如 Assets
    unit VARCHAR NOT NULL,          -- 单位，例如 USD、shares
    end_date DATE NOT NULL,         -- 指标对应的时点
    val DOUBLE NOT NULL,            -- 披露的数值
    accn VARCHAR NOT NULL,          -- SEC 申报编号，用来区分披露文件
    filed DATE NOT NULL,            -- 申报日期，用于判断当时是否已披露
    form VARCHAR NOT NULL,          -- 申报类型，例如 10-K、10-Q
    fy INTEGER,
    fp VARCHAR,
    frame VARCHAR,
                                    -- fy、`fp`、`frame`	保留的原始辅助信息，不用它们替代实际报告日期

    PRIMARY KEY (
        cik,
        taxonomy,
        tag,
        unit,
        end_date,
        accn
    )
);
