"""拉取并标准化 P0 免费权威基准数据集到 Parquet

P0 数据集包含:
1 ff_factors_daily: Kenneth French 日频因子 (FF5 + 动量 + 短期/长期反转, 小数收益率)
2 vol_indices_daily: CBOE 官方历史波动率指数 (VIX, VIX3M, VVIX, SKEW)
3 aqr_factors_daily: AQR 官方美国日频因子 (BAB, QMJ, HML Devil, 小数收益率)
"""

from __future__ import annotations

import io
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

USER_AGENT = "Quant-Research-Lab/0.1 (Academic/Personal Quantitative Research)"

KEN_FRENCH_URLS: dict[str, str] = {
    "ff5": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "mom": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip",
    "st_rev": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_ST_Reversal_Factor_daily_CSV.zip",
    "lt_rev": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_LT_Reversal_Factor_daily_CSV.zip",
}

CBOE_URLS: dict[str, str] = {
    "vix": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
    "vix3m": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv",
    "vvix": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VVIX_History.csv",
    "skew": "https://cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv",
}

AQR_URLS: dict[str, tuple[str, str, str]] = {
    # key: (url, sheet_name, output_col)
    "bab": (
        "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Betting-Against-Beta-Equity-Factors-Daily.xlsx",
        "BAB Factors",
        "aqr_bab_usa",
    ),
    "qmj": (
        "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Quality-Minus-Junk-Factors-Daily.xlsx",
        "QMJ Factors",
        "aqr_qmj_usa",
    ),
    "hml_devil": (
        "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/The-Devil-in-HMLs-Details-Factors-Daily.xlsx",
        "HML Devil",
        "aqr_hml_devil_usa",
    ),
}


def _download_bytes(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_ken_french_daily_csv(raw_zip: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError("No CSV found inside Kenneth French ZIP archive")
        text = zf.read(csv_names[0]).decode("latin-1")

    lines = text.splitlines()
    header_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(",") and any(tok in stripped for tok in ("Mkt-RF", "Mom", "ST_Rev", "LT_Rev")):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Could not locate header row in Kenneth French CSV")

    headers = ["date"] + [c.strip() for c in lines[header_idx].split(",")[1:]]
    rows: list[list[str]] = []
    for line in lines[header_idx + 1 :]:
        parts = [p.strip() for p in line.split(",")]
        if not parts or len(parts[0]) != 8 or not parts[0].isdigit():
            if rows:
                break
            continue
        if len(parts) == len(headers):
            rows.append(parts)

    df = pd.DataFrame(rows, columns=headers)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.date
    for col in headers[1:]:
        s = pd.to_numeric(df[col], errors="coerce")
        s = s.mask(s.isin([-99.99, -999.0, -99.999]), np.nan)
        # 百分比收益率转换为小数收益率
        df[col] = s / 100.0
    return df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)


def fetch_ken_french_daily(out_path: Path | None = None) -> pd.DataFrame:
    """下载并合并 Kenneth French 日频因子数据, 收益率统一转换为小数口径

    Args:
        out_path: 可选输出 Parquet 路径, 默认 None 表示仅返回 DataFrame 不落盘

    Returns:
        pd.DataFrame: RangeIndex, 包含列 date, mkt_rf, smb, hml, rmw, cma, rf, mom, st_rev, lt_rev
            收益率单位为小数 (如 0.01 表示 1%), 缺失值以 NaN 表示

    Raises:
        ValueError: 压缩包中缺少 CSV 或表头格式异常
        urllib.error.URLError: 网络下载失败

    Example:
        >>> from pathlib import Path
        >>> df = fetch_ken_french_daily(Path("data/parquet/data/ff_factors_daily/data.parquet"))
        >>> {"date", "mkt_rf", "rf", "mom"}.issubset(df.columns)
        True
    """
    dfs: list[pd.DataFrame] = []
    for key, url in KEN_FRENCH_URLS.items():
        print(f"[P0] Downloading Kenneth French ({key})")
        raw = _download_bytes(url)
        dfs.append(_parse_ken_french_daily_csv(raw))

    merged = dfs[0]
    for df in dfs[1:]:
        merged = merged.merge(df, on="date", how="outer")

    rename_map = {
        "Mkt-RF": "mkt_rf",
        "SMB": "smb",
        "HML": "hml",
        "RMW": "rmw",
        "CMA": "cma",
        "RF": "rf",
        "Mom": "mom",
        "ST_Rev": "st_rev",
        "LT_Rev": "lt_rev",
    }
    merged = merged.rename(columns=rename_map)
    ordered_cols = ["date"] + [c for c in rename_map.values() if c in merged.columns]
    merged = merged[ordered_cols].sort_values("date").reset_index(drop=True)

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        merged.to_parquet(out_path, index=False, compression="zstd")
        print(f"[P0] Saved ff_factors_daily -> {out_path} ({len(merged):,} rows)")
    return merged


def fetch_cboe_vol_indices(out_path: Path | None = None) -> pd.DataFrame:
    """下载并合并 CBOE 官方日频波动率指数 (VIX, VIX3M, VVIX, SKEW)

    Args:
        out_path: 可选输出 Parquet 路径, 默认 None 表示仅返回 DataFrame 不落盘

    Returns:
        pd.DataFrame: RangeIndex, 包含列 date, vix_open/high/low/close, vix3m_open/high/low/close, vvix_close, skew_close
            单位为原始指数点位, 早期缺失序列以 NaN 表示

    Raises:
        ValueError: 原始 CSV 缺少 DATE 列
        urllib.error.URLError: 网络下载失败

    Example:
        >>> from pathlib import Path
        >>> df = fetch_cboe_vol_indices(Path("data/parquet/data/vol_indices_daily/data.parquet"))
        >>> {"date", "vix_close", "vix3m_close", "skew_close"}.issubset(df.columns)
        True
    """
    frames: list[pd.DataFrame] = []

    for key, url in CBOE_URLS.items():
        print(f"[P0] Downloading CBOE ({key})")
        raw = _download_bytes(url)
        df = pd.read_csv(io.BytesIO(raw))
        df.columns = [c.strip().upper() for c in df.columns]
        if "DATE" not in df.columns:
            raise ValueError(f"Unexpected columns in CBOE {key}: {df.columns.tolist()}")
        df["date"] = pd.to_datetime(df["DATE"]).dt.date

        if key in ("vix", "vix3m"):
            col_map = {
                "OPEN": f"{key}_open",
                "HIGH": f"{key}_high",
                "LOW": f"{key}_low",
                "CLOSE": f"{key}_close",
            }
            keep = ["date"] + [c for c in col_map if c in df.columns]
            sub = df[keep].rename(columns=col_map)
        else:
            value_col = [c for c in df.columns if c not in ("DATE", "date")][0]
            sub = df[["date", value_col]].rename(columns={value_col: f"{key}_close"})

        for c in sub.columns:
            if c != "date":
                sub[c] = pd.to_numeric(sub[c], errors="coerce")
        sub = sub.drop_duplicates(subset=["date"]).sort_values("date")
        frames.append(sub)

    merged = frames[0]
    for sub in frames[1:]:
        merged = merged.merge(sub, on="date", how="outer")
    merged = merged.sort_values("date").reset_index(drop=True)

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        merged.to_parquet(out_path, index=False, compression="zstd")
        print(f"[P0] Saved vol_indices_daily -> {out_path} ({len(merged):,} rows)")
    return merged


def _parse_aqr_usa_daily_xlsx(raw_xlsx: bytes, sheet_name: str, out_col: str) -> pd.DataFrame:
    df_raw = pd.read_excel(io.BytesIO(raw_xlsx), sheet_name=sheet_name, header=None, engine="openpyxl")
    header_row: int | None = None
    for idx in range(min(40, len(df_raw))):
        row_vals = [str(v).strip().upper() for v in df_raw.iloc[idx].tolist()]
        if "DATE" in row_vals and "USA" in row_vals:
            header_row = idx
            break
    if header_row is None:
        raise ValueError(f"Could not locate DATE/USA header row in AQR sheet '{sheet_name}'")

    headers = [str(v).strip() for v in df_raw.iloc[header_row].tolist()]
    data = df_raw.iloc[header_row + 1 :].copy()
    data.columns = headers
    date_col = next(c for c in headers if c.upper() == "DATE")
    usa_col = next(c for c in headers if c.upper() == "USA")

    sub = data[[date_col, usa_col]].copy()
    sub.columns = ["date", out_col]
    sub["date"] = pd.to_datetime(sub["date"], errors="coerce").dt.date
    sub[out_col] = pd.to_numeric(sub[out_col], errors="coerce")
    sub = sub.dropna(subset=["date"]).drop_duplicates(subset=["date"]).sort_values("date")
    return sub.reset_index(drop=True)


def fetch_aqr_factors_daily(out_path: Path | None = None) -> pd.DataFrame | None:
    """下载并合并 AQR 官方美国日频股票因子 (BAB, QMJ, HML Devil)

    Args:
        out_path: 可选输出 Parquet 路径, 默认 None 表示仅返回 DataFrame 不落盘

    Returns:
        pd.DataFrame | None: RangeIndex, 包含列 date, aqr_bab_usa, aqr_qmj_usa, aqr_hml_devil_usa
            单位为小数收益率, 缺失值以 NaN 表示, 若全部下载失败则返回 None

    Raises:
        无直接抛出异常, 单个序列下载或解析失败时打印警告并跳过

    Example:
        >>> from pathlib import Path
        >>> df = fetch_aqr_factors_daily(Path("data/parquet/data/aqr_factors_daily/data.parquet"))
        >>> df is not None and "aqr_qmj_usa" in df.columns
        True
    """
    frames: list[pd.DataFrame] = []
    for key, (url, sheet, col_name) in AQR_URLS.items():
        try:
            print(f"[P0] Downloading AQR ({key})")
            raw = _download_bytes(url, timeout=90)
            frames.append(_parse_aqr_usa_daily_xlsx(raw, sheet, col_name))
        except Exception as exc:
            print(f"[P0][WARN] Failed to fetch AQR {key}: {exc}")

    if not frames:
        return None

    merged = frames[0]
    for sub in frames[1:]:
        merged = merged.merge(sub, on="date", how="outer")
    merged = merged.sort_values("date").reset_index(drop=True)

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        merged.to_parquet(out_path, index=False, compression="zstd")
        print(f"[P0] Saved aqr_factors_daily -> {out_path} ({len(merged):,} rows)")
    return merged


def fetch_all_p0(parquet_root: Path = Path("data/parquet")) -> dict[str, Path]:
    """一键拉取全部 P0 基准表并写入标准 Parquet 目录结构

    Args:
        parquet_root: 本地 Parquet 快照根目录, 默认 Path("data/parquet")

    Returns:
        dict[str, Path]: 表名到生成 Parquet 文件路径的映射

    Raises:
        ValueError: 原始数据解析失败
        urllib.error.URLError: 网络请求失败

    Example:
        >>> paths = fetch_all_p0(Path("data/parquet"))
        >>> "ff_factors_daily" in paths and "vol_indices_daily" in paths
        True
    """
    data_dir = parquet_root / "data"
    outputs: dict[str, Path] = {}

    ff_path = data_dir / "ff_factors_daily" / "data.parquet"
    fetch_ken_french_daily(ff_path)
    outputs["ff_factors_daily"] = ff_path

    vol_path = data_dir / "vol_indices_daily" / "data.parquet"
    fetch_cboe_vol_indices(vol_path)
    outputs["vol_indices_daily"] = vol_path

    aqr_path = data_dir / "aqr_factors_daily" / "data.parquet"
    aqr_df = fetch_aqr_factors_daily(aqr_path)
    if aqr_df is not None:
        outputs["aqr_factors_daily"] = aqr_path

    return outputs
