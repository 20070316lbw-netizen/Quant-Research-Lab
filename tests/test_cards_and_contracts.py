"""研究卡片模块, 内存数据契约与 StatResult 单元测试"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import ValidationError

from quant_research_lab.cards import (
    CardValidationError,
    ResearchCard,
    build_index,
    check_duplicate,
    load_all_cards,
    parse_card,
    query_catalog,
    write_card,
)
from quant_research_lab.data import (
    DataContractError,
    require_panel,
    validate_panel,
    validate_signal,
    validate_timeseries,
)
from quant_research_lab.stats import StatResult


def _make_sample_card(**overrides: object) -> ResearchCard:
    base: dict[str, object] = {
        "id": "eq-cs-101",
        "title": "Sample Factor Study",
        "source_type": "paper",
        "source_url": "https://example.com/sample-101",
        "year": 2022,
        "authors": ["Jane Doe"],
        "sector": "equities",
        "domain": "cross_sectional",
        "universe": "SP500",
        "horizon": "monthly",
        "target_object": "单股月度超额收益率",
        "model_family": "factor_residual",
        "estimation_method": "rolling_ols_36m",
        "data_required": ["prices", "universe"],
        "feasibility": "ready",
        "one_liner": "用于测试研究卡片 Schema 与索引编译管道",
        "key_highlight": "强类型校验与自动生成总览表",
        "key_risk": "示例卡片仅用于单元测试",
        "tags": ["Momentum", "Test", "momentum"],
        "status": "scouted",
        "scouted_at": date(2026, 11, 22),
    }
    base.update(overrides)
    return ResearchCard(**base)


class TestCardsModule(unittest.TestCase):
    """验证 ResearchCard 强校验, 写入去重与自动索引编译"""

    def test_feasibility_guard_blocks_unready_tables(self) -> None:
        with self.assertRaises(ValidationError):
            _make_sample_card(data_required=["prices", "macro_series"], feasibility="ready")

        # 标明 needs_macro 时允许引用未就绪宏观表
        card = _make_sample_card(data_required=["prices", "macro_series"], feasibility="needs_macro")
        self.assertEqual(card.feasibility, "needs_macro")

    def test_tags_normalized_and_deduplicated(self) -> None:
        card = _make_sample_card()
        self.assertEqual(card.tags, ["momentum", "test"])

    def test_write_parse_duplicate_and_index_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "research"
            card = _make_sample_card()
            written = write_card(card, research_root=root)
            self.assertTrue(written.exists())

            parsed, body = parse_card(written)
            self.assertEqual(parsed.id, card.id)
            self.assertIn("## 2. 研究对象的核心建模", body)

            # 重复 id 或 source_url 必须被拦截
            self.assertEqual(len(check_duplicate(root, card_id=card.id)), 1)
            with self.assertRaises(CardValidationError):
                write_card(
                    _make_sample_card(id="eq-cs-102", title="Another Title", source_url=card.source_url),
                    research_root=root,
                )

            index_md, catalog_jsonl = build_index(root)
            self.assertTrue(index_md.exists())
            self.assertTrue(catalog_jsonl.exists())
            self.assertEqual(len(load_all_cards(root)), 1)
            self.assertEqual(len(query_catalog(root, feasibility="ready", tag="MOMENTUM")), 1)
            self.assertEqual(len(query_catalog(root, status="promoted")), 0)


class TestDataContractsAndStatResult(unittest.TestCase):
    """验证 PanelFrame, SignalSeries, TimeSeriesFrame 契约与 StatResult"""

    def test_panel_and_signal_contracts(self) -> None:
        idx = pd.MultiIndex.from_tuples(
            [
                (pd.Timestamp("2024-01-02"), "AAPL"),
                (pd.Timestamp("2024-01-02"), "MSFT"),
                (pd.Timestamp("2024-01-03"), "AAPL"),
            ],
            names=["date", "ticker"],
        )
        df = pd.DataFrame({"close": [185.0, 370.0, 184.0]}, index=idx)
        validate_panel(df, required_cols=("close",))

        # 未排序必须报错
        with self.assertRaises(DataContractError):
            validate_panel(df.iloc[::-1])

        # 含 +/-inf 必须报错
        bad_sig = pd.Series([0.1, np.inf, -0.2], index=idx, name="sig")
        with self.assertRaises(DataContractError):
            validate_signal(bad_sig)

        @require_panel("prices", required_cols=("close",))
        def count_rows(prices: pd.DataFrame) -> int:
            return len(prices)

        self.assertEqual(count_rows(df), 3)

    def test_timeseries_and_stat_result(self) -> None:
        ts = pd.Series([0.01, -0.02], index=pd.DatetimeIndex(["2024-01-02", "2024-01-03"], name="date"))
        validate_timeseries(ts)

        res = StatResult(name="IC", estimate=0.05, p_value=0.01, n_obs=100)
        self.assertTrue(res.is_significant_05)
        self.assertEqual(res.to_dict()["n_obs"], 100)


if __name__ == "__main__":
    unittest.main()
