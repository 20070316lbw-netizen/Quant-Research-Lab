"""中国地级市逐年 PM10 数据拉取与空间区域均值聚合模块

数据源: CHAP (ChinaHighPM10 V4, 1km 空间分辨率, Zenodo 3752465 & 10475457)
输出单位: 微克/立方米 (ug/m3)
"""

from __future__ import annotations

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import netCDF4 as nc
import numpy as np
import pandas as pd
from rasterio.features import rasterize
from rasterio.transform import from_origin

from quant_research_lab.cn_macro.geo import CityBoundary

ZENODO_RECORD_IDS: tuple[int, ...] = (3752465, 10475457)


def _fetch_zenodo_pm10_urls(start_year: int, end_year: int) -> dict[int, tuple[str, str]]:
    """查询 Zenodo API 获取 CHAP PM10 年度 Y1K NetCDF 直链"""
    year_urls: dict[int, tuple[str, str]] = {}
    for rec_id in ZENODO_RECORD_IDS:
        url = f"https://zenodo.org/api/records/{rec_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "QuantResearchLab/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        for f in payload.get("files", []):
            key = str(f.get("key", ""))
            if not (key.startswith("CHAP_PM10_Y1K_") and key.endswith("_V4.nc")):
                continue
            parts = key.split("_")
            if len(parts) < 5:
                continue
            try:
                year = int(parts[3])
            except ValueError:
                continue
            if start_year <= year <= end_year:
                dl_url = str(f["links"]["self"])
                year_urls[year] = (key, dl_url)
    return year_urls


def _download_file(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "QuantResearchLab/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp, tmp.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(dest)
    return dest


def download_chap_pm10_yearly(
    raw_dir: Path = Path("data/cn_macro/raw"),
    *,
    start_year: int = 2000,
    end_year: int = 2025,
    max_workers: int = 4,
) -> dict[int, Path]:
    """批量下载 CHAP PM10 年度 1km NetCDF 栅格文件 (支持断点复用)

    Args:
        raw_dir: 原始缓存根目录, 文件存入 raw_dir/pm10/
        start_year: 起始年份 (含), 默认 2000
        end_year: 截止年份 (含), 默认 2025
        max_workers: 并发下载线程数, 默认 4

    Returns:
        dict[int, Path]: 年份到本地 .nc 文件路径的有序映射

    Raises:
        RuntimeError: 无法获取全部目标年份文件

    Example:
        >>> # files = download_chap_pm10_yearly(start_year=2024, end_year=2024)
        >>> True
        True
    """
    pm_dir = raw_dir / "pm10"
    pm_dir.mkdir(parents=True, exist_ok=True)
    year_urls = _fetch_zenodo_pm10_urls(start_year, end_year)
    if not year_urls:
        raise RuntimeError(f"Zenodo 未返回 {start_year}-{end_year} 的 CHAP PM10 文件")

    results: dict[int, Path] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(_download_file, dl_url, pm_dir / key): year
            for year, (key, dl_url) in year_urls.items()
        }
        for fut in as_completed(future_map):
            year = future_map[fut]
            results[year] = fut.result()
    return dict(sorted(results.items()))


def build_city_pm10_table(
    boundaries: list[CityBoundary],
    nc_files: dict[int, Path],
) -> pd.DataFrame:
    """将 CHAP PM10 年度栅格按地级市行政边界聚合为宽表

    Args:
        boundaries: 地级市行政边界列表 (含 city_id, pr_id, city, pr, geometry)
        nc_files: 年份到 CHAP PM10 .nc 文件路径的映射

    Returns:
        pd.DataFrame: 宽表, 列为 ['CITY_ID', 'PR_ID', 'CITY', 'PR', '2000', ...], 单位 ug/m3

    Raises:
        ValueError: boundaries 或 nc_files 为空

    Example:
        >>> # df = build_city_pm10_table(boundaries, nc_files)
        >>> True
        True
    """
    if not boundaries:
        raise ValueError("boundaries 不能为空")
    if not nc_files:
        raise ValueError("nc_files 不能为空")

    years = sorted(nc_files.keys())
    first_nc = nc_files[years[0]]
    with nc.Dataset(first_nc) as ds:
        lat = np.asarray(ds.variables["lat"][:], dtype=np.float64)
        lon = np.asarray(ds.variables["lon"][:], dtype=np.float64)

    n_lat, n_lon = len(lat), len(lon)
    dx = float(abs(lon[1] - lon[0]))
    dy = float(abs(lat[1] - lat[0]))
    lat_descending = bool(lat[0] > lat[-1])
    north = float(max(lat[0], lat[-1])) + dy / 2.0
    west = float(min(lon[0], lon[-1])) - dx / 2.0
    transform = from_origin(west, north, dx, dy)

    # 一次性将所有地级市多边形栅格化为 1..N 标签矩阵
    shapes = [(b.geometry, idx + 1) for idx, b in enumerate(boundaries)]
    labels = rasterize(
        shapes=shapes,
        out_shape=(n_lat, n_lon),
        transform=transform,
        fill=0,
        dtype=np.int32,
        all_touched=True,
    )
    if not lat_descending:
        labels = labels[::-1, :]

    valid_city_mask = labels > 0
    flat_labels = labels[valid_city_mask]
    n_cities = len(boundaries)

    data: dict[str, list[object]] = {
        "CITY_ID": [b.city_id for b in boundaries],
        "PR_ID": [b.pr_id for b in boundaries],
        "CITY": [b.city for b in boundaries],
        "PR": [b.pr for b in boundaries],
    }

    for year in years:
        with nc.Dataset(nc_files[year]) as ds:
            arr = ds.variables["PM10"][:]
            vals = np.ma.filled(arr, np.nan).astype(np.float64)
        if vals.shape != (n_lat, n_lon):
            raise ValueError(f"CHAP PM10 {year} 网格尺寸不一致: {vals.shape} != {(n_lat, n_lon)}")
        flat_vals = vals[valid_city_mask]
        finite = np.isfinite(flat_vals)
        lbl_ok = flat_labels[finite]
        val_ok = flat_vals[finite]
        sums = np.bincount(lbl_ok, weights=val_ok, minlength=n_cities + 1)[1:]
        cnts = np.bincount(lbl_ok, minlength=n_cities + 1)[1:]
        means = np.where(cnts > 0, np.round(sums / np.maximum(cnts, 1), 3), np.nan)
        data[str(year)] = means.tolist()

    return pd.DataFrame(data)
