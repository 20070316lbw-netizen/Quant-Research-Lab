"""中国地级市宏观数据构建, 2000基期GDP派生与 Parquet 恢复单元测试"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb
import pandas as pd

from quant_research_lab.cn_macro import (
    GDP_DELIVERABLE_COLUMNS,
    append_yearbook_gdp_rows,
    build_296_city_gdp_2000base,
    export_cn_macro_to_parquet,
    import_cn_macro_parquet_to_duckdb,
    load_cn_macro_config,
    write_tables_to_duckdb,
)


def _make_mock_yearbook() -> pd.DataFrame:
    rows = [
        # 城市 A: 2000-2002 完整基期
        {
            "年份": 2000,
            "省份": "北京市",
            "城市": "北京市",
            "城市.1": "北京市",
            "城市年份": "北京市2000",
            "城市代码": 110000,
            "城市代码年份": "1100002000",
            "所属地域": "东部",
            "胡焕庸线": "东南侧",
            "地区生产总值(万元)": 25000000.0,  # 2500 亿元
            "地区生产总值增长率(%)": 11.0,
        },
        {
            "年份": 2001,
            "省份": "北京市",
            "城市": "北京市",
            "城市.1": "北京市",
            "城市年份": "北京市2001",
            "城市代码": 110000,
            "城市代码年份": "1100002001",
            "所属地域": "东部",
            "胡焕庸线": "东南侧",
            "地区生产总值(万元)": 28600000.0,  # 2860 亿元
            "地区生产总值增长率(%)": 10.0,     # 实际GDP = 2750, 平减指数 = 2860/2750*100 = 104
        },
        {
            "年份": 2002,
            "省份": "北京市",
            "城市": "北京市",
            "城市.1": "北京市",
            "城市年份": "北京市2002",
            "城市代码": 110000,
            "城市代码年份": "1100002002",
            "所属地域": "东部",
            "胡焕庸线": "东南侧",
            "地区生产总值(万元)": 33000000.0,  # 3300 亿元
            "地区生产总值增长率(%)": 10.0,     # 指数 = 121, 实际GDP = 3025
        },
        # 排除的非 296 特殊城市: 莱芜市 (371200)
        {
            "年份": 2000,
            "省份": "山东省",
            "城市": "莱芜市",
            "城市.1": "莱芜市",
            "城市年份": "莱芜市2000",
            "城市代码": 371200,
            "城市代码年份": "3712002000",
            "所属地域": "东部",
            "胡焕庸线": "东南侧",
            "地区生产总值(万元)": 1000000.0,
            "地区生产总值增长率(%)": 9.0,
        },
    ]
    return pd.DataFrame(rows)


class TestCnMacroPipeline(unittest.TestCase):
    """验证配置读取, 2000基期GDP解析解与 DuckDB/Parquet 恢复一致性"""

    def test_load_default_config(self) -> None:
        cfg = load_cn_macro_config()
        self.assertEqual(cfg.years.base_year, 2000)
        self.assertEqual(cfg.hf.path_in_repo, "cn_macro")

    def test_gdp_2000_base_exact_formula_and_append(self) -> None:
        yb = _make_mock_yearbook()
        gdp_df = build_296_city_gdp_2000base(yb, base_year=2000, start_year=2000)
        self.assertEqual(tuple(gdp_df.columns), GDP_DELIVERABLE_COLUMNS)
        # 莱芜市 (371200) 必须被过滤
        self.assertNotIn("莱芜市", set(gdp_df["城市"]))
        self.assertEqual(len(gdp_df), 3)

        r2000 = gdp_df[gdp_df["年份"] == 2000].iloc[0]
        r2001 = gdp_df[gdp_df["年份"] == 2001].iloc[0]
        r2002 = gdp_df[gdp_df["年份"] == 2002].iloc[0]

        self.assertAlmostEqual(r2000["名义GDP"], 2500.0, places=4)
        self.assertAlmostEqual(r2000["GDP指数"], 100.0, places=4)
        self.assertAlmostEqual(r2000["实际GDP"], 2500.0, places=4)
        self.assertAlmostEqual(r2000["GDP平减指数"], 100.0, places=4)

        self.assertAlmostEqual(r2001["GDP指数"], 110.0, places=4)
        self.assertAlmostEqual(r2001["实际GDP"], 2750.0, places=4)
        self.assertAlmostEqual(r2001["GDP平减指数"], 104.0, places=4)

        self.assertAlmostEqual(r2002["GDP指数"], 121.0, places=4)
        self.assertAlmostEqual(r2002["实际GDP"], 3025.0, places=4)

        # 测试追加最新年份 GDP 行
        extra = pd.DataFrame([{"城市代码": 110000, "名义GDP_亿元": 3600.0, "实际增速_pct": 5.0}])
        yb_ext = append_yearbook_gdp_rows(yb, extra, year=2003)
        gdp_ext = build_296_city_gdp_2000base(yb_ext, base_year=2000, start_year=2000)
        r2003 = gdp_ext[gdp_ext["年份"] == 2003].iloc[0]
        self.assertAlmostEqual(r2003["名义GDP"], 3600.0, places=4)
        self.assertAlmostEqual(r2003["GDP指数"], 127.05, places=4)

    def test_duckdb_parquet_export_and_restore_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db1 = root / "src.duckdb"
            pq_dir = root / "parquet"
            db2 = root / "restored.duckdb"

            sample = pd.DataFrame({"CITY_ID": [110000, 310000], "CITY": ["北京市", "上海市"], "2024": [59.3, 41.2]})
            write_tables_to_duckdb({"cn_city_pm10": sample}, db1)
            manifest = export_cn_macro_to_parquet(db1, pq_dir)
            self.assertTrue(manifest.exists())

            import_cn_macro_parquet_to_duckdb(pq_dir, db2, verify_sha256=True)
            con = duckdb.connect(str(db2), read_only=True)
            restored = con.sql("SELECT * FROM cn_city_pm10 ORDER BY CITY_ID").df()
            con.close()
            self.assertEqual(len(restored), 2)
            self.assertAlmostEqual(float(restored.loc[0, "2024"]), 59.3, places=4)

            # 篡改 Parquet 字节后必须触发 SHA256 校验失败
            pq_file = pq_dir / "data" / "cn_city_pm10" / "data.parquet"
            pq_file.write_bytes(pq_file.read_bytes() + b"corrupt")
            with self.assertRaises(ValueError):
                import_cn_macro_parquet_to_duckdb(pq_dir, root / "bad.duckdb", verify_sha256=True)


if __name__ == "__main__":
    unittest.main()
