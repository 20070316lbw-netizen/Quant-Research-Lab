"""中国城市统计年鉴清洗与 296 个地级市 2000 年基期 GDP 派生模块"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# 年鉴 300 城市中 2023 年无常规 GDP 的 4 个特殊/已撤销地区 (300 - 4 = 296)
EXCLUDED_NON_296_CITY_CODES: frozenset[int] = frozenset({341400, 371200, 460300, 632500})

GDP_COL = "地区生产总值(万元)"
GDP_GROWTH_COL = "地区生产总值增长率(%)"

GDP_DELIVERABLE_COLUMNS: tuple[str, ...] = (
    "省份",
    "城市",
    "年份",
    "城市年份",
    "名义GDP",
    "GDP指数",
    "实际GDP",
    "GDP平减指数",
)


def load_yearbook_xlsx(source_xlsx: Path = Path("data/统计年鉴数据.xlsx")) -> pd.DataFrame:
    """读取原始《中国城市统计年鉴》Excel 表并校验主键完整性

    Args:
        source_xlsx: 统计年鉴源 Excel 文件路径

    Returns:
        pd.DataFrame: 清洗类型后的完整年鉴 DataFrame (保留全部原始列名)

    Raises:
        FileNotFoundError: 源文件不存在
        ValueError: 缺少必需标识列或存在重复 (年份, 城市代码)

    Example:
        >>> # df = load_yearbook_xlsx(Path("data/统计年鉴数据.xlsx"))
        >>> True
        True
    """
    if not source_xlsx.exists():
        raise FileNotFoundError(f"未找到统计年鉴源文件: {source_xlsx}")
    df = pd.read_excel(source_xlsx)
    required = {"年份", "省份", "城市", "城市代码", GDP_COL, GDP_GROWTH_COL}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"统计年鉴缺少必需列: {sorted(missing)}")
    df["年份"] = df["年份"].astype(int)
    df["城市代码"] = df["城市代码"].astype(int)
    if df.duplicated(subset=["年份", "城市代码"]).any():
        raise ValueError("统计年鉴存在重复的 (年份, 城市代码) 主键")
    return df.sort_values(["年份", "城市代码"]).reset_index(drop=True)


def append_yearbook_gdp_rows(
    yearbook_df: pd.DataFrame,
    gdp_extra_df: pd.DataFrame,
    *,
    year: int = 2024,
) -> pd.DataFrame:
    """向统计年鉴面板追加最新年份 (如 2024 年) 的地级市 GDP 与增速记录

    未发布的其他年鉴细项列保留为 NaN, 绝不虚构数据

    Args:
        yearbook_df: 现有统计年鉴 DataFrame (1990-2023)
        gdp_extra_df: 最新年份 GDP 补充表, 需含列 ['城市代码', '名义GDP_亿元', '实际增速_pct']
        year: 追加的年份, 默认 2024

    Returns:
        pd.DataFrame: 追加最新年份后的完整年鉴 DataFrame

    Raises:
        ValueError: 补充表缺少必需列

    Example:
        >>> # merged = append_yearbook_gdp_rows(yb, gdp_2024, year=2024)
        >>> True
        True
    """
    req = {"城市代码", "名义GDP_亿元", "实际增速_pct"}
    missing = req - set(gdp_extra_df.columns)
    if missing:
        raise ValueError(f"gdp_extra_df 缺少必需列: {sorted(missing)}")

    # 以最新一年 (2023) 的城市静态元信息为骨架构造 2024 行
    latest_yr = int(yearbook_df["年份"].max())
    if year <= latest_yr:
        return yearbook_df

    base_meta = yearbook_df[yearbook_df["年份"] == latest_yr][
        ["省份", "城市", "城市.1", "城市代码", "所属地域", "胡焕庸线"]
    ].copy()

    new_rows = pd.DataFrame(np.nan, index=range(len(base_meta)), columns=yearbook_df.columns)
    new_rows["年份"] = year
    for col in ("省份", "城市", "城市.1", "城市代码", "所属地域", "胡焕庸线"):
        new_rows[col] = base_meta[col].to_numpy()
    new_rows["城市年份"] = new_rows["城市"].astype(str) + str(year)
    new_rows["城市代码年份"] = new_rows["城市代码"].astype(int).astype(str) + str(year)

    extra_map = gdp_extra_df.drop_duplicates(subset=["城市代码"]).set_index("城市代码")
    gdp_map = (extra_map["名义GDP_亿元"] * 10000.0).to_dict()
    gr_map = extra_map["实际增速_pct"].to_dict()

    new_rows[GDP_COL] = new_rows["城市代码"].map(gdp_map)
    new_rows[GDP_GROWTH_COL] = new_rows["城市代码"].map(gr_map)

    out = pd.concat([yearbook_df, new_rows], ignore_index=True)
    out["年份"] = out["年份"].astype(int)
    out["城市代码"] = out["城市代码"].astype(int)
    return out.sort_values(["年份", "城市代码"]).reset_index(drop=True)


def build_296_city_gdp_2000base(
    yearbook_df: pd.DataFrame,
    *,
    base_year: int = 2000,
    start_year: int = 2000,
    end_year: int | None = None,
) -> pd.DataFrame:
    """基于统计年鉴派生 296 个地级市以 2000 年为基期的不变价 GDP 面板

    计算口径:
    - 名义GDP: 地区生产总值(万元) / 10000, 单位为亿元
    - GDP指数: 以 2000 年 = 100 的定基实际 GDP 指数, 由各年官方实际增长率累乘
    - 实际GDP: 以 2000 年为基期的不变价 GDP (亿元)
    - GDP平减指数: (名义GDP / 实际GDP) * 100
    对 2000 年尚未撤地设市的少数城市, 在其首个可观测年份采用同省中位平减指数衔接 2000 基期,
    此后各年严格使用该市自身官方实际增速累乘

    Args:
        yearbook_df: 包含历年 GDP 与实际增速的统计年鉴 DataFrame
        base_year: 不变价基期年份, 默认 2000
        start_year: 输出起始年份, 默认 2000
        end_year: 输出截止年份, None 表示取数据最大年份

    Returns:
        pd.DataFrame: 296 个地级市 GDP 长表, 列严格为
            ['省份', '城市', '年份', '城市年份', '名义GDP', 'GDP指数', '实际GDP', 'GDP平减指数']

    Raises:
        ValueError: 数据中不存在 base_year 记录

    Example:
        >>> # gdp_df = build_296_city_gdp_2000base(yb)
        >>> True
        True
    """
    max_yr = int(yearbook_df["年份"].max()) if end_year is None else end_year
    sub = yearbook_df[
        (yearbook_df["年份"] >= start_year)
        & (yearbook_df["年份"] <= max_yr)
        & (~yearbook_df["城市代码"].isin(EXCLUDED_NON_296_CITY_CODES))
    ][["省份", "城市", "城市代码", "年份", GDP_COL, GDP_GROWTH_COL]].copy()

    if (sub["年份"] == base_year).sum() == 0:
        raise ValueError(f"输入数据中缺少基期年份 {base_year}")

    sub["名义GDP"] = pd.to_numeric(sub[GDP_COL], errors="coerce") / 10000.0
    sub["增长率"] = pd.to_numeric(sub[GDP_GROWTH_COL], errors="coerce")
    sub = sub.sort_values(["城市代码", "年份"]).reset_index(drop=True)

    # 第一遍: 计算 2000 年有完整基期名义 GDP 的城市
    records: list[pd.DataFrame] = []
    deferred: list[pd.DataFrame] = []

    for _, g in sub.groupby("城市代码", sort=True):
        g = g.sort_values("年份").copy()
        base_row = g[g["年份"] == base_year]
        base_nom = float(base_row["名义GDP"].iloc[0]) if len(base_row) > 0 else np.nan
        if np.isnan(base_nom):
            deferred.append(g)
            continue

        idx_vals = np.full(len(g), np.nan, dtype=np.float64)
        yrs = g["年份"].to_numpy()
        grs = g["增长率"].to_numpy(dtype=np.float64)
        base_pos = int(np.where(yrs == base_year)[0][0])
        idx_vals[base_pos] = 100.0
        for i in range(base_pos + 1, len(g)):
            if np.isfinite(idx_vals[i - 1]) and np.isfinite(grs[i]):
                idx_vals[i] = idx_vals[i - 1] * (1.0 + grs[i] / 100.0)
        for i in range(base_pos - 1, -1, -1):
            if np.isfinite(idx_vals[i + 1]) and np.isfinite(grs[i + 1]):
                idx_vals[i] = idx_vals[i + 1] / (1.0 + grs[i + 1] / 100.0)

        g["GDP指数"] = idx_vals
        g["实际GDP"] = base_nom * (idx_vals / 100.0)
        g["GDP平减指数"] = np.where(
            np.isfinite(g["名义GDP"]) & np.isfinite(g["实际GDP"]) & (g["实际GDP"] > 0),
            (g["名义GDP"] / g["实际GDP"]) * 100.0,
            np.nan,
        )
        records.append(g)

    anchored_df = pd.concat(records, ignore_index=True)

    # 计算省级与全国分年度中位平减指数, 用于衔接 2000 年尚未撤地设市的少数城市
    prov_defl = anchored_df.groupby(["省份", "年份"])["GDP平减指数"].median().to_dict()
    nat_defl = anchored_df.groupby("年份")["GDP平减指数"].median().to_dict()

    for g in deferred:
        g = g.sort_values("年份").copy()
        valid_mask = g["名义GDP"].notna().to_numpy()
        if not valid_mask.any():
            g["GDP指数"] = np.nan
            g["实际GDP"] = np.nan
            g["GDP平减指数"] = np.nan
            records.append(g)
            continue

        first_pos = int(np.where(valid_mask)[0][0])
        first_yr = int(g["年份"].iloc[first_pos])
        prov = str(g["省份"].iloc[first_pos])
        defl0 = prov_defl.get((prov, first_yr), nat_defl.get(first_yr, 100.0))
        if not np.isfinite(defl0) or defl0 <= 0:
            defl0 = 100.0

        nom0 = float(g["名义GDP"].iloc[first_pos])
        real0 = nom0 / (defl0 / 100.0)

        real_vals = np.full(len(g), np.nan, dtype=np.float64)
        idx_vals = np.full(len(g), np.nan, dtype=np.float64)
        grs = g["增长率"].to_numpy(dtype=np.float64)

        real_vals[first_pos] = real0
        idx_vals[first_pos] = 100.0
        for i in range(first_pos + 1, len(g)):
            if np.isfinite(real_vals[i - 1]) and np.isfinite(grs[i]):
                factor = 1.0 + grs[i] / 100.0
                real_vals[i] = real_vals[i - 1] * factor
                idx_vals[i] = idx_vals[i - 1] * factor

        g["GDP指数"] = idx_vals
        g["实际GDP"] = real_vals
        g["GDP平减指数"] = np.where(
            np.isfinite(g["名义GDP"]) & np.isfinite(g["实际GDP"]) & (g["实际GDP"] > 0),
            (g["名义GDP"] / g["实际GDP"]) * 100.0,
            np.nan,
        )
        records.append(g)

    full = pd.concat(records, ignore_index=True)
    full = full.sort_values(["年份", "城市代码"]).reset_index(drop=True)
    full["城市年份"] = full["城市"].astype(str) + full["年份"].astype(int).astype(str)
    for col in ("名义GDP", "GDP指数", "实际GDP", "GDP平减指数"):
        full[col] = full[col].round(4)

    return full[list(GDP_DELIVERABLE_COLUMNS)].copy()
