"""实验 YAML 配置文件强校验 Schema 与加载器单元测试"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from quant_research_lab.experiments import (
    ConfigLoadError,
    config_sha256,
    load_experiment_config,
    resolve_config_path,
)


def _sample_config_dict() -> dict[str, object]:
    return {
        "meta": {
            "card_id": "eq-cs-001",
            "name": "test_run",
            "seed": 42,
            "notes": "unit test",
        },
        "data": {
            "dataset_version": "v1.0.0",
            "db_path": "data/lab.duckdb",
            "start_date": "2011-01-03",
            "end_date": "2026-08-18",
            "universe": "SP500",
            "tables": ["prices", "universe", "prices"],
            "benchmark": {"market_ticker": "SPY", "risk_free_col": "rf"},
        },
        "split": {
            "method": "holdout",
            "is_end_date": "2020-12-31",
            "oos_start_date": "2021-01-01",
            "purge_days": 21,
            "embargo_days": 5,
        },
        "execution": {
            "rebalance_freq": "monthly",
            "signal_lag_days": 1,
            "price_field": "adj_close",
            "weighting": "equal",
            "long_short": {"enabled": True, "n_quantiles": 10},
            "cost_bps_default": 10.0,
            "cost_bps_grid": [20.0, 0.0, 10.0, 10.0],
            "min_history_days": 252,
        },
        "audit": {
            "n_trials": 1,
            "alpha": 0.05,
            "p_adjust_method": "bh",
            "nw_lags": 6,
            "annualization_factor": 12,
        },
        "model": {
            "family": "factor_residual",
            "params": {"regression_window_months": 36},
        },
        "output": {
            "dir": "outputs/eq-cs-001",
            "save_returns": True,
            "save_weights": False,
            "save_report_md": True,
        },
    }


class TestExperimentConfig(unittest.TestCase):
    """验证 YAML 配置解析, 契约拦截与复现哈希"""

    def test_load_repo_baseline_config(self) -> None:
        path = resolve_config_path("eq-cs-001_residual_momentum.yaml")
        cfg = load_experiment_config(path)
        self.assertEqual(cfg.meta.card_id, "eq-cs-001")
        self.assertEqual(cfg.meta.name, "residual_momentum_baseline")
        self.assertEqual(
            cfg.run_output_dir().as_posix(),
            "outputs/eq-cs-001/residual_momentum_baseline",
        )
        self.assertEqual(len(config_sha256(path)), 64)

    def test_deduplication_and_sorting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "valid.yaml"
            cfg_path.write_text(yaml.safe_dump(_sample_config_dict()), encoding="utf-8")
            cfg = load_experiment_config(cfg_path)
            self.assertEqual(cfg.data.tables, ["prices", "universe"])
            self.assertEqual(cfg.execution.cost_bps_grid, [0.0, 10.0, 20.0])

    def test_reject_lookahead_signal_lag(self) -> None:
        raw = _sample_config_dict()
        raw["execution"]["signal_lag_days"] = 0  # type: ignore[index]
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "bad_lag.yaml"
            cfg_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
            with self.assertRaises(ConfigLoadError):
                load_experiment_config(cfg_path)

    def test_reject_unknown_extra_field(self) -> None:
        raw = _sample_config_dict()
        raw["unexpected_section"] = {"x": 1}
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "bad_extra.yaml"
            cfg_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
            with self.assertRaises(ConfigLoadError):
                load_experiment_config(cfg_path)

    def test_reject_invalid_holdout_split(self) -> None:
        raw = _sample_config_dict()
        raw["split"]["is_end_date"] = "2022-01-01"  # type: ignore[index]
        raw["split"]["oos_start_date"] = "2021-01-01"  # type: ignore[index]
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "bad_split.yaml"
            cfg_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
            with self.assertRaises(ConfigLoadError):
                load_experiment_config(cfg_path)

    def test_reject_missing_walk_forward_params(self) -> None:
        raw = _sample_config_dict()
        raw["split"] = {"method": "walk_forward", "purge_days": 5, "embargo_days": 0}
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "bad_wf.yaml"
            cfg_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
            with self.assertRaises(ConfigLoadError):
                load_experiment_config(cfg_path)


if __name__ == "__main__":
    unittest.main()
