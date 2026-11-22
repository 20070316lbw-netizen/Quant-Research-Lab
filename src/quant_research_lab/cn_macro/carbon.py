"""中国各城市逐年碳排放 (CO2) 数据拉取与空间区域加总模块

数据源: EDGAR 2025 GHG (欧盟 JRC 官方 0.1 度全球总 CO2 排放栅格, 2000-2024)
输出单位: 百万吨 CO2 (Mt CO2)
"""

from __future__ import annotations

import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import netCDF4 as nc
import numpy as np
import pandas as pd
from rasterio.features import rasterize
from rasterio.transform import from_origin

from quant_research_lab.cn_macro.geo import CityBoundary

EDGAR_CO2_URL_TEMPLATE = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/EDGAR/datasets/"
    "EDGAR_2025_GHG/CO2/TOTALS/emi_nc/EDGAR_2025_GHG_CO2_{year}_TOTALS_emi_nc.zip"
)


def _download_and_extract_edgar(year: int, co2_dir: Path) -> Path:
    expected_nc = co2_dir / f"EDGAR_2025_GHG_CO2_{year}_TOTALS_emi.nc"
    if expected_nc.exists() and expected_nc.stat().st_size > 500_000:
        return expected_nc

    zip_path = co2_dir / f"EDGAR_2025_GHG_CO2_{year}_TOTALS_emi_nc.zip"
    if not zip_path.exists() or zip_path.stat().st_size < 100_000:
        co2_dir.mkdir(parents=True, exist_ok=True)
        tmp = zip_path.with_suffix(".zip.part")
        url = EDGAR_CO2_URL_TEMPLATE.format(year=year)
        req = urllib.request.Request(url, headers={"User-Agent": "QuantResearchLab/1.0"})
        with urllib.request.urlopen(req, timeout=180) as resp, tmp.open("wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        tmp.replace(zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        nc_names = [n for n in zf.namelist() if n.endswith(".nc")]
        if not nc_names:
            raise RuntimeError(f"EDGAR 压缩包内未找到 .nc 文件: {zip_path}")
        zf.extract(nc_names[0], co2_dir)
        extracted = co2_dir / nc_names[0]
        if extracted != expected_nc:
            extracted.replace(expected_nc)
    return expected_nc


def download_edgar_co2_yearly(
    raw_dir: Path = Path("data/cn_macro/raw"),
    *,
    start_year: int = 2000,
    end_year: int = 2024,
    max_workers: int = 4,
) -> dict[int, Path]:
    """批量下载并解压 EDGAR 2025 GHG 年度 CO2 排放 NetCDF 文件 (支持断点复用)

    Args:
        raw_dir: 原始缓存根目录, 文件存入 raw_dir/carbon/
        start_year: 起始年份 (含), 默认 2000
        end_year: 截止年份 (含), 默认 2024
        max_workers: 并发下载线程数, 默认 4

    Returns:
        dict[int, Path]: 年份到本地 .nc 文件路径的有序映射

    Raises:
        RuntimeError: 下载或解压失败

    Example:
        >>> # files = download_edgar_co2_yearly(start_year=2024, end_year=2024)
        >>> True
        True
    """
    co2_dir = raw_dir / "carbon"
    co2_dir.mkdir(parents=True, exist_ok=True)
    results: dict[int, Path] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(_download_and_extract_edgar, year, co2_dir): year
            for year in range(start_year, end_year + 1)
        }
        for fut in as_completed(future_map):
            year = future_map[fut]
            results[year] = fut.result()
    return dict(sorted(results.items()))


def build_city_carbon_table(
    boundaries: list[CityBoundary],
    nc_files: dict[int, Path],
    *,
    oversample: int = 5,
) -> pd.DataFrame:
    """将 EDGAR 0.1 度 CO2 排放栅格按地级市行政边界精准加总为宽表

    采用子网格过采样 (默认 5x -> 0.02 度) 提升小面积地级市边界重叠分配精度
    输出单位由 Tonnes 换算为百万吨 CO2 (Mt CO2)

    Args:
        boundaries: 地级市行政边界列表
        nc_files: 年份到 EDGAR CO2 .nc 文件路径的映射
        oversample: 子网格过采样倍率, 默认 5

    Returns:
        pd.DataFrame: 宽表, 列为 ['CITY_ID', 'PR_ID', 'CITY', 'PR', '2000', ...], 单位 Mt CO2

    Raises:
        ValueError: boundaries 或 nc_files 为空

    Example:
        >>> # df = build_city_carbon_table(boundaries, nc_files)
        >>> True
        True
    """
    if not boundaries:
        raise ValueError("boundaries 不能为空")
    if not nc_files:
        raise ValueError("nc_files 不能为空")
    if oversample < 1:
        raise ValueError("oversample 必须 >= 1")

    years = sorted(nc_files.keys())
    with nc.Dataset(nc_files[years[0]]) as ds:
        lat_all = np.asarray(ds.variables["lat"][:], dtype=np.float64)
        lon_all = np.asarray(ds.variables["lon"][:], dtype=np.float64)

    # 裁剪至中国外接矩形 [15N..56N, 72E..136E]
    lat_idx = np.where((lat_all >= 15.0) & (lat_all <= 56.0))[0]
    lon_idx = np.where((lon_all >= 72.0) & (lon_all <= 136.0))[0]
    lat_sub = lat_all[lat_idx]
    lon_sub = lon_all[lon_idx]

    dx = float(abs(lon_sub[1] - lon_sub[0]))
    dy = float(abs(lat_sub[1] - lat_sub[0]))
    sub_dx = dx / oversample
    sub_dy = dy / oversample

    n_lat_sub = len(lat_sub) * oversample
    n_lon_sub = len(lon_sub) * oversample
    north = float(max(lat_sub[0], lat_sub[-1])) + dy / 2.0
    west = float(min(lon_sub[0], lon_sub[-1])) - dx / 2.0
    transform = from_origin(west, north, sub_dx, sub_dy)

    shapes = [(b.geometry, idx + 1) for idx, b in enumerate(boundaries)]
    labels = rasterize(
        shapes=shapes,
        out_shape=(n_lat_sub, n_lon_sub),
        transform=transform,
        fill=0,
        dtype=np.int32,
        all_touched=False,
    )

    # 对极小城市若无中心命中, 用 all_touched 兜底补齐
    hit_ids = set(np.unique(labels))
    missing_shapes = [
        (b.geometry, idx + 1) for idx, b in enumerate(boundaries) if (idx + 1) not in hit_ids
    ]
    if missing_shapes:
        fallback = rasterize(
            shapes=missing_shapes,
            out_shape=(n_lat_sub, n_lon_sub),
            transform=transform,
            fill=0,
            dtype=np.int32,
            all_touched=True,
        )
        labels = np.where(labels == 0, fallback, labels)

    # EDGAR lat 升序 (南到北), 与栅格化 (北到南) 对齐时需上下翻转
    lat_ascending = bool(lat_sub[0] < lat_sub[-1])
    if lat_ascending:
        labels = labels[::-1, :]

    valid_mask = labels > 0
    flat_labels = labels[valid_mask]
    n_cities = len(boundaries)
    cell_scale = float(oversample * oversample) * 1e6  # 均分到子网格并换算 Tonnes -> Mt CO2

    data: dict[str, list[object]] = {
        "CITY_ID": [b.city_id for b in boundaries],
        "PR_ID": [b.pr_id for b in boundaries],
        "CITY": [b.city for b in boundaries],
        "PR": [b.pr for b in boundaries],
    }

    r0, r1 = int(lat_idx[0]), int(lat_idx[-1]) + 1
    c0, c1 = int(lon_idx[0]), int(lon_idx[-1]) + 1

    for year in years:
        with nc.Dataset(nc_files[year]) as ds:
            raw_crop = np.asarray(ds.variables["emissions"][r0:r1, c0:c1], dtype=np.float64)
        raw_crop = np.nan_to_num(raw_crop, nan=0.0)
        sub_grid = np.repeat(np.repeat(raw_crop, oversample, axis=0), oversample, axis=1)
        flat_vals = sub_grid[valid_mask] / cell_scale
        totals = np.bincount(flat_labels, weights=flat_vals, minlength=n_cities + 1)[1:]
        data[str(year)] = np.round(totals, 4).tolist()

    return pd.DataFrame(data)
