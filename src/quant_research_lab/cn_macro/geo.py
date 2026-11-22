"""中国地级市标准行政边界 GeoJSON 拉取与几何解析模块

数据源: 阿里云 DataV.GeoAtlas areas_v3 公开行政边界接口
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

DATAV_BOUND_URL = "https://geo.datav.aliyun.com/areas_v3/bound/{adcode}_full.json"

# 四个直辖市直接作为地级市单元纳入边界聚合
MUNICIPALITY_CODES: frozenset[int] = frozenset({110000, 120000, 310000, 500000})

# 排除港澳台及九段线等非内地地级市代码
SKIP_PROVINCE_CODES: frozenset[int] = frozenset({710000, 810000, 820000})


@dataclass(frozen=True)
class CityBoundary:
    """单个地级市行政单元的编码与多边形几何信息"""

    city_id: int
    pr_id: int
    city: str
    pr: str
    geometry: BaseGeometry


def _fetch_json(url: str, cache_path: Path) -> dict[str, Any]:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (QuantResearchLab/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    cache_path.write_bytes(raw)
    return json.loads(raw.decode("utf-8"))


def fetch_china_city_boundaries(raw_dir: Path = Path("data/cn_macro/raw")) -> list[CityBoundary]:
    """下载并缓存中国内地全部地级行政区 (含四个直辖市) 的标准边界多边形

    Args:
        raw_dir: 原始缓存目录, GeoJSON 缓存在 raw_dir/geojson/ 下

    Returns:
        list[CityBoundary]: 按 city_id 升序排列的地级市边界列表

    Raises:
        RuntimeError: 拉取全国或省级 GeoJSON 失败

    Example:
        >>> # boundaries = fetch_china_city_boundaries(Path("data/cn_macro/raw"))
        >>> # len(boundaries) > 330
        >>> True
        True
    """
    geo_dir = raw_dir / "geojson"
    china_gj = _fetch_json(
        DATAV_BOUND_URL.format(adcode=100000),
        geo_dir / "100000_full.json",
    )

    boundaries: list[CityBoundary] = []
    seen_city_ids: set[int] = set()

    for feat in china_gj.get("features", []):
        props = feat.get("properties") or {}
        adcode_raw = props.get("adcode")
        name = str(props.get("name") or "").strip()
        if not adcode_raw or not name:
            continue
        pr_id = int(adcode_raw)
        if pr_id in SKIP_PROVINCE_CODES:
            continue

        if pr_id in MUNICIPALITY_CODES:
            geom = shape(feat["geometry"])
            if not geom.is_valid:
                geom = geom.buffer(0)
            boundaries.append(
                CityBoundary(
                    city_id=pr_id,
                    pr_id=pr_id,
                    city=name,
                    pr=name,
                    geometry=geom,
                )
            )
            seen_city_ids.add(pr_id)
            continue

        prov_cache = geo_dir / f"{pr_id}_full.json"
        if not prov_cache.exists():
            time.sleep(0.15)
        prov_gj = _fetch_json(DATAV_BOUND_URL.format(adcode=pr_id), prov_cache)
        for cfeat in prov_gj.get("features", []):
            cprops = cfeat.get("properties") or {}
            cadcode_raw = cprops.get("adcode")
            cname = str(cprops.get("name") or "").strip()
            if not cadcode_raw or not cname:
                continue
            city_id = int(cadcode_raw)
            if city_id in seen_city_ids:
                continue
            geom = shape(cfeat["geometry"])
            if not geom.is_valid:
                geom = geom.buffer(0)
            boundaries.append(
                CityBoundary(
                    city_id=city_id,
                    pr_id=pr_id,
                    city=cname,
                    pr=name,
                    geometry=geom,
                )
            )
            seen_city_ids.add(city_id)

    boundaries.sort(key=lambda b: b.city_id)
    return boundaries
