"""标准数据读取器 (data/loader.py) 单元测试与本地 DuckDB 集成冒烟测试"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from quant_research_lab.data import (
    DEFAULT_DB_PATH,
    load_aqr_factors,
    load_calendar,
    load_ff_factors,
    load_prices,
    load_universe_panel,
    load_vol_indices,
    validate_panel,
    validate_timeseries,
)


def _build_fixture_db(db_path: Path) -> None:
    with duckdb.connect(str(db_path)) as con:
        con.execute("CREATE TABLE calendar (date DATE)")
        con.execute(
            """
            INSERT INTO calendar VALUES
                (DATE '2024-01-02'),
                (DATE '2024-01-03'),
                (DATE '2024-01-04'),
                (DATE '2024-01-05')
            """
        )

        con.execute(
            """
            CREATE TABLE universe (
                snapshot_date DATE,
                ticker VARCHAR,
                cik VARCHAR,
                name VARCHAR,
                exchange VARCHAR,
                sic VARCHAR,
                sub_industry VARCHAR
            )
            """
        )
        # 2023-12-31 快照含 AAPL 和 OLDX; 2024-01-04 快照剔除 OLDX 并纳入 NEWX
        con.execute(
            """
            INSERT INTO universe VALUES
                (DATE '2023-12-31', 'AAPL', '0000320193', 'Apple Inc', 'NASDAQ', '3571', 'Tech Hardware'),
                (DATE '2023-12-31', 'OLDX', '0000000001', 'Old Corp', 'NYSE', '1000', 'Old Sector'),
                (DATE '2024-01-04', 'AAPL', '0000320193', 'Apple Inc', 'NASDAQ', '3571', 'Tech Hardware'),
                (DATE '2024-01-04', 'NEWX', '0000000002', 'New Corp', 'NASDAQ', '7372', 'Software')
            """
        )

        con.execute(
            """
            CREATE TABLE prices (
                date DATE,
                ticker VARCHAR,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                adj_close DOUBLE,
                volume BIGINT
            )
            """
        )
        # 故意乱序插入以验证读取器输出严格按 (date, ticker) 升序
        con.execute(
            """
            INSERT INTO prices VALUES
                (DATE '2024-01-05', 'NEWX', 52.0, 53.0, 51.0, 52.5, 52.5, 2000),
                (DATE '2024-01-02', 'OLDX', 10.0, 11.0, 9.5, 10.5, 10.5, 1000),
                (DATE '2024-01-02', 'AAPL', 185.0, 186.0, 184.0, 185.5, 185.5, 50000),
                (DATE '2024-01-02', 'NEWX', 50.0, 51.0, 49.0, 50.5, 50.5, 1500),
                (DATE '2024-01-02', 'NONSP', 20.0, 21.0, 19.0, 20.5, 20.5, 500),
                (DATE '2024-01-03', 'AAPL', 184.0, 185.0, 183.0, 184.2, 184.2, 48000),
                (DATE '2024-01-03', 'OLDX', 10.5, 10.8, 10.1, 10.2, 10.2, 900),
                (DATE '2024-01-03', 'NEWX', 50.5, 51.5, 50.0, 51.0, 51.0, 1600),
                (DATE '2024-01-04', 'AAPL', 182.0, 183.0, 181.0, 181.9, 181.9, 52000),
                (DATE '2024-01-04', 'OLDX', 10.2, 10.4, 9.8, 9.9, 9.9, 800),
                (DATE '2024-01-04', 'NEWX', 51.0, 52.0, 50.5, 51.8, 51.8, 1900),
                (DATE '2024-01-05', 'AAPL', 181.5, 182.5, 180.5, 181.2, 181.2, 51000)
            """
        )

        con.execute(
            """
            CREATE TABLE ff_factors_daily (
                date DATE,
                mkt_rf DOUBLE, smb DOUBLE, hml DOUBLE, rmw DOUBLE, cma DOUBLE,
                rf DOUBLE, mom DOUBLE, st_rev DOUBLE, lt_rev DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO ff_factors_daily VALUES
                (DATE '2024-01-03', -0.008, -0.002, 0.001, 0.003, 0.001, 0.0002, 0.004, -0.001, 0.002),
                (DATE '2024-01-02', -0.005, 0.001, 0.002, 0.001, 0.000, 0.0002, -0.003, 0.001, -0.001)
            """
        )

        con.execute(
            """
            CREATE TABLE aqr_factors_daily (
                date DATE,
                aqr_bab_usa DOUBLE,
                aqr_qmj_usa DOUBLE,
                aqr_hml_devil_usa DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO aqr_factors_daily VALUES
                (DATE '2024-01-02', 0.001, 0.002, -0.001),
                (DATE '2024-01-03', -0.002, 0.003, 0.001)
            """
        )

        con.execute(
            """
            CREATE TABLE vol_indices_daily (
                date DATE,
                vix_open DOUBLE, vix_high DOUBLE, vix_low DOUBLE, vix_close DOUBLE,
                vix3m_open DOUBLE, vix3m_high DOUBLE, vix3m_low DOUBLE, vix3m_close DOUBLE,
                vvix_close DOUBLE, skew_close DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO vol_indices_daily VALUES
                (DATE '2024-01-02', 13.0, 14.0, 12.8, 13.2, 15.0, 15.5, 14.8, 15.1, 85.0, 145.0),
                (DATE '2024-01-03', 13.5, 14.5, 13.1, 14.0, 15.2, 15.8, 15.0, 15.6, 87.5, 144.0)
            """
        )


class TestLoaderSynthetic(unittest.TestCase):
    """基于临时合成 DuckDB 验证全部读取器的 PIT 语义与契约"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_lab.duckdb"
        _build_fixture_db(self.db_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_load_prices_pit_sp500_filter(self) -> None:
        df = load_prices("2024-01-02", "2024-01-05", sp500_only=True, db_path=self.db_path)
        validate_panel(df, required_cols=("open", "high", "low", "close", "adj_close", "volume"))

        self.assertEqual(df.index.levels[0].dtype, "datetime64[ns]")
        keys = set(df.index.tolist())
        # 2024-01-02 与 01-03 仅含 AAPL, OLDX (不含 NEWX 和 NONSP)
        self.assertIn((pd.Timestamp("2024-01-02"), "AAPL"), keys)
        self.assertIn((pd.Timestamp("2024-01-02"), "OLDX"), keys)
        self.assertNotIn((pd.Timestamp("2024-01-02"), "NEWX"), keys)
        self.assertNotIn((pd.Timestamp("2024-01-02"), "NONSP"), keys)
        # 2024-01-04 起剔除 OLDX 并纳入 NEWX
        self.assertNotIn((pd.Timestamp("2024-01-04"), "OLDX"), keys)
        self.assertIn((pd.Timestamp("2024-01-04"), "NEWX"), keys)
        self.assertIn((pd.Timestamp("2024-01-05"), "NEWX"), keys)

    def test_load_prices_all_market_and_filters(self) -> None:
        df_all = load_prices(
            date(2024, 1, 2),
            pd.Timestamp("2024-01-02"),
            sp500_only=False,
            columns=("close", "adj_close"),
            db_path=self.db_path,
        )
        self.assertEqual(list(df_all.columns), ["close", "adj_close"])
        self.assertEqual(
            set(df_all.index.get_level_values("ticker")),
            {"AAPL", "NEWX", "NONSP", "OLDX"},
        )

        df_sub = load_prices(
            sp500_only=False,
            tickers=["AAPL", "NONSP"],
            columns=("close",),
            db_path=self.db_path,
        )
        self.assertEqual(set(df_sub.index.get_level_values("ticker")), {"AAPL", "NONSP"})

        df_empty = load_prices(tickers=[], columns=("close", "volume"), db_path=self.db_path)
        self.assertTrue(df_empty.empty)
        self.assertEqual(list(df_empty.columns), ["close", "volume"])
        validate_panel(df_empty, required_cols=("close", "volume"))

    def test_load_universe_panel_and_timeseries(self) -> None:
        univ = load_universe_panel("2024-01-02", "2024-01-04", columns=("cik", "sub_industry"), db_path=self.db_path)
        validate_panel(univ, required_cols=("cik", "sub_industry"))
        self.assertEqual(len(univ), 6)
        self.assertEqual(univ.loc[(pd.Timestamp("2024-01-04"), "NEWX"), "sub_industry"], "Software")

        cal = load_calendar("2024-01-03", "2024-01-05", db_path=self.db_path)
        self.assertEqual(cal.name, "date")
        self.assertEqual(len(cal), 3)

        ff = load_ff_factors("2024-01-02", "2024-01-03", columns=("mkt_rf", "rf"), db_path=self.db_path)
        validate_timeseries(ff, required_cols=("mkt_rf", "rf"))
        self.assertEqual(len(ff), 2)

        aqr = load_aqr_factors(db_path=self.db_path)
        validate_timeseries(aqr, required_cols=("aqr_bab_usa", "aqr_qmj_usa", "aqr_hml_devil_usa"))
        self.assertEqual(len(aqr), 2)

        vol = load_vol_indices(columns=("vix_close", "vix3m_close"), db_path=self.db_path)
        validate_timeseries(vol, required_cols=("vix_close", "vix3m_close"))
        self.assertEqual(len(vol), 2)

    def test_validation_errors(self) -> None:
        with self.assertRaises(ValueError):
            load_prices("2024-01-05", "2024-01-02", db_path=self.db_path)
        with self.assertRaises(ValueError):
            load_prices(pd.Timestamp("2024-01-02", tz="UTC"), db_path=self.db_path)
        with self.assertRaises(ValueError):
            load_prices(columns=("not_a_col",), db_path=self.db_path)
        with self.assertRaises(ValueError):
            load_prices(columns=(), db_path=self.db_path)
        with self.assertRaises(FileNotFoundError):
            load_prices(db_path=self.db_path.parent / "missing.duckdb")


@unittest.skipUnless(DEFAULT_DB_PATH.exists(), "本地 data/lab.duckdb 不存在时跳过集成冒烟测试")
class TestLoaderLiveLabDuckDB(unittest.TestCase):
    """针对本地 data/lab.duckdb 的真实数据冒烟测试"""

    def test_live_loaders_satisfy_contracts(self) -> None:
        px = load_prices("2024-01-02", "2024-01-10", sp500_only=True)
        validate_panel(px, required_cols=("open", "high", "low", "close", "adj_close", "volume"))
        self.assertGreater(len(px), 2500)

        univ = load_universe_panel("2024-01-02", "2024-01-05")
        validate_panel(univ, required_cols=("cik", "sub_industry"))
        self.assertGreater(len(univ), 1500)

        cal = load_calendar("2024-01-02", "2024-01-10")
        self.assertGreaterEqual(len(cal), 6)

        ff = load_ff_factors("2024-01-02", "2024-01-10")
        validate_timeseries(ff, required_cols=("mkt_rf", "rf"))
        self.assertGreaterEqual(len(ff), 6)

        aqr = load_aqr_factors("2024-01-02", "2024-01-10")
        validate_timeseries(aqr, required_cols=("aqr_bab_usa",))
        self.assertGreaterEqual(len(aqr), 6)

        vol = load_vol_indices("2024-01-02", "2024-01-10")
        validate_timeseries(vol, required_cols=("vix_close", "vix3m_close"))
        self.assertGreaterEqual(len(vol), 6)


if __name__ == "__main__":
    unittest.main()
