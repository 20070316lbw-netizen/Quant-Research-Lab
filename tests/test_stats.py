"""统计学工具库 (factor, validation, timeseries, event_study) 单元测试"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd
import statsmodels.api as sm

from quant_research_lab.stats import (
    adf_test,
    adjust_pvalues,
    compute_ic_series,
    deflated_sharpe_ratio,
    engle_granger_coint,
    fama_macbeth,
    hurst_exponent,
    ic_decay,
    kpss_test,
    ledoit_wolf_cov,
    neutralize_cs,
    ou_half_life,
    performance_summary,
    probabilistic_sharpe_ratio,
    purged_kfold_splits,
    quantile_portfolio_returns,
    run_event_study,
    standardize_cs,
    summarize_ic,
    walk_forward_splits,
    winsorize_cs,
)


class TestFactorStats(unittest.TestCase):
    """横截面预处理, IC/RankIC, 分组多空与 Fama-MacBeth 检验测试"""

    def test_winsorize_and_standardize(self) -> None:
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-01-02"), f"T{i}") for i in range(6)],
            names=["date", "ticker"],
        )
        raw = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 100.0], index=idx, name="alpha")

        w_mad = winsorize_cs(raw, method="mad", n_mad=3.0)
        self.assertEqual(w_mad.name, "alpha")
        self.assertLess(float(w_mad.max()), 100.0)
        self.assertAlmostEqual(float(w_mad.iloc[2]), 3.0)

        w_q = winsorize_cs(raw, method="quantile", lower=0.1, upper=0.9)
        self.assertLess(float(w_q.max()), 100.0)

        z = standardize_cs(w_mad, method="zscore")
        self.assertAlmostEqual(float(z.mean()), 0.0, places=10)
        self.assertAlmostEqual(float(z.std(ddof=1)), 1.0, places=10)

        r = standardize_cs(raw, method="rank")
        self.assertGreater(float(r.min()), -1.0)
        self.assertLess(float(r.max()), 1.0)
        self.assertAlmostEqual(float(r.mean()), 0.0, places=10)

        rg = standardize_cs(raw, method="rank_gauss")
        self.assertAlmostEqual(float(rg.mean()), 0.0, places=10)

    def test_neutralize_cs_removes_linear_exposure(self) -> None:
        rng = np.random.default_rng(10)
        dates = pd.date_range("2024-01-02", periods=3)
        tickers = [f"T{i:02d}" for i in range(20)]
        idx = pd.MultiIndex.from_product([dates, tickers], names=["date", "ticker"])

        ind = pd.Series(["Tech" if i % 2 == 0 else "Fin" for i in range(len(idx))], index=idx, name="ind")
        size = pd.Series(rng.normal(size=len(idx)), index=idx, name="size")
        ind_effect = np.where(ind == "Tech", 3.0, -2.0)
        signal = pd.Series(ind_effect + 1.5 * size.to_numpy(), index=idx, name="sig")

        resid = neutralize_cs(signal, industry=ind, controls=size, min_obs=10)
        self.assertLess(float(resid.abs().max()), 1e-10)

    def test_ic_newey_west_matches_statsmodels(self) -> None:
        idx = pd.date_range("2024-01-02", periods=10, name="date")
        ic = pd.Series([0.02, 0.03, 0.01, 0.04, 0.02, 0.05, 0.03, 0.01, 0.02, 0.04], index=idx, name="rank_ic")
        res = summarize_ic(ic, nw_lags=2)

        sm_res = sm.OLS(ic.to_numpy(), np.ones((len(ic), 1))).fit(
            cov_type="HAC", cov_kwds={"maxlags": 2, "use_correction": True}, use_t=True
        )
        self.assertAlmostEqual(res.estimate, float(sm_res.params[0]), places=12)
        self.assertIsNotNone(res.se)
        self.assertIsNotNone(res.t_stat)
        self.assertIsNotNone(res.p_value)
        self.assertAlmostEqual(res.se, float(sm_res.bse[0]), places=12)
        self.assertAlmostEqual(res.t_stat, float(sm_res.tvalues[0]), places=12)
        self.assertAlmostEqual(res.p_value, float(sm_res.pvalues[0]), places=12)

    def test_ic_decay_quantiles_and_fama_macbeth(self) -> None:
        rng = np.random.default_rng(42)
        dates = pd.date_range("2023-01-02", periods=60, freq="B")
        tickers = [f"T{i:02d}" for i in range(30)]
        idx = pd.MultiIndex.from_product([dates, tickers], names=["date", "ticker"])

        sig = pd.Series(rng.normal(size=len(idx)), index=idx, name="mom")
        ret_1 = pd.Series(0.02 * sig.to_numpy() + rng.normal(scale=0.02, size=len(idx)), index=idx, name="r1")
        ret_5 = pd.Series(0.005 * sig.to_numpy() + rng.normal(scale=0.03, size=len(idx)), index=idx, name="r5")

        ic_s = compute_ic_series(sig, ret_1, method="spearman", min_obs=10)
        self.assertEqual(len(ic_s), 60)
        self.assertGreater(float(ic_s.mean()), 0.4)

        decay_df = ic_decay(sig, {1: ret_1, 5: ret_5}, min_obs=10)
        self.assertEqual(decay_df.index.tolist(), [1, 5])
        self.assertGreater(float(decay_df.loc[1, "mean_ic"]), float(decay_df.loc[5, "mean_ic"]))

        q_df, ls_stat = quantile_portfolio_returns(sig, ret_1, n_quantiles=5, min_obs=15)
        self.assertEqual(len(q_df), 60)
        self.assertAlmostEqual(float(ls_stat.meta["monotonicity_rho"]), 1.0, places=6)
        self.assertTrue(ls_stat.is_significant_05)
        self.assertGreater(ls_stat.estimate, 0.03)

        fm = fama_macbeth(ret_1, sig, min_obs=15)
        self.assertAlmostEqual(fm["mom"].estimate, 0.02, delta=0.005)
        self.assertTrue(fm["mom"].is_significant_05)

    def test_factor_edge_cases_column_collision_rank_deficiency_and_ties(self) -> None:
        dates = pd.date_range("2024-01-02", periods=3)
        tickers = [f"T{i:02d}" for i in range(12)]
        idx = pd.MultiIndex.from_product([dates, tickers], names=["date", "ticker"])

        # controls 名为 "_y" 时不得覆盖内部因变量列
        ctrl = pd.Series(np.tile(np.arange(12, dtype=float), 3), index=idx, name="_y")
        sig = pd.Series(2.0 * ctrl.to_numpy() + 1.0, index=idx, name="sig")
        resid = neutralize_cs(sig, controls=ctrl, min_obs=6)
        self.assertLess(float(resid.abs().max()), 1e-10)

        # fama_macbeth 暴露列名为 "_y" 且首日秩亏时应跳过秩亏日而不崩溃
        exp = pd.DataFrame({"_y": ctrl.to_numpy(), "z": np.tile(np.sin(np.arange(12, dtype=float)), 3)}, index=idx)
        exp.loc[dates[0], "z"] = 0.0
        ret = pd.Series(0.01 * exp["_y"].to_numpy() + 0.02 * exp["z"].to_numpy(), index=idx, name="ret")
        fm = fama_macbeth(ret, exp, min_obs=6)
        self.assertEqual(fm["_y"].meta["skipped_rank_deficient"], 1)
        self.assertEqual(fm["_y"].n_obs, 2)

        # 结值分组不按 ticker 字母序拆分
        one_day = pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-01-02"), t) for t in ["A", "B", "C", "D", "E", "F"]],
            names=["date", "ticker"],
        )
        tied_sig = pd.Series([1.0, 1.0, 1.0, 2.0, 2.0, 2.0], index=one_day, name="tied")
        tied_ret = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05, 0.06], index=one_day, name="ret")
        qdf, _ = quantile_portfolio_returns(tied_sig, tied_ret, n_quantiles=2, min_obs=4)
        self.assertAlmostEqual(float(qdf["Q1"].iloc[0]), 0.02, places=12)
        self.assertAlmostEqual(float(qdf["Q2"].iloc[0]), 0.05, places=12)


class TestValidationStats(unittest.TestCase):
    """绩效评估, PSR/DSR, 多重检验与防泄漏切分测试"""

    def test_performance_summary_and_lo_adjustment(self) -> None:
        idx = pd.date_range("2023-01-02", periods=252, freq="B", name="date")
        # 正自相关 AR(1) 收益序列, Lo 调整后 Sharpe 应低于未调整 Sharpe
        rng = np.random.default_rng(7)
        r = np.zeros(252)
        for t in range(1, 252):
            r[t] = 0.0008 + 0.4 * r[t - 1] + rng.normal(scale=0.008)
        ret = pd.Series(r, index=idx, name="strat")

        summary = performance_summary(ret, periods_per_year=252, lo_lags=5)
        self.assertLess(summary["max_drawdown"].estimate, 0.0)
        # 正自相关下 Lo 调整应将 Sharpe 幅度向 0 收缩
        self.assertGreater(abs(summary["sharpe"].estimate), abs(summary["sharpe"].meta["sharpe_lo_adjusted"]))
        self.assertGreater(summary["sharpe"].meta["lo_eta"], 1.0)
        self.assertTrue(np.isfinite(summary["sortino"].estimate))
        self.assertTrue(np.isfinite(summary["calmar"].estimate))

        # 首日即发生亏损时, 最大回撤必须相对初始净值 1.0 计算
        loss_idx = pd.date_range("2024-01-02", periods=3, freq="B", name="date")
        loss_ret = pd.Series([-0.50, 0.01, 0.01], index=loss_idx, name="loss")
        loss_summary = performance_summary(loss_ret, periods_per_year=252)
        self.assertAlmostEqual(loss_summary["max_drawdown"].estimate, -0.50, places=12)
        self.assertIsNone(loss_summary["max_drawdown"].meta["peak_date"])
        self.assertTrue(np.isfinite(loss_summary["calmar"].estimate))

    def test_psr_and_dsr_monotonicity(self) -> None:
        rng = np.random.default_rng(9)
        idx = pd.date_range("2020-01-02", periods=500, freq="B", name="date")
        ret = pd.Series(rng.normal(0.0006, 0.01, size=500), index=idx, name="ret")

        psr_0 = probabilistic_sharpe_ratio(ret, benchmark_sr=0.0)
        dsr_1 = deflated_sharpe_ratio(ret, n_trials=1)
        dsr_20 = deflated_sharpe_ratio(ret, n_trials=20)
        dsr_200 = deflated_sharpe_ratio(ret, n_trials=200)

        self.assertAlmostEqual(psr_0.estimate, dsr_1.estimate, places=12)
        self.assertGreater(dsr_1.estimate, dsr_20.estimate)
        self.assertGreater(dsr_20.estimate, dsr_200.estimate)

    def test_adjust_pvalues_exact_formulas(self) -> None:
        pvals = {"f1": 0.001, "f2": 0.04, "f3": 0.50}

        bh = adjust_pvalues(pvals, method="bh")
        self.assertAlmostEqual(float(bh.loc["f1", "p_adj"]), 0.003, places=12)
        self.assertAlmostEqual(float(bh.loc["f2", "p_adj"]), 0.06, places=12)
        self.assertAlmostEqual(float(bh.loc["f3", "p_adj"]), 0.50, places=12)

        bonf = adjust_pvalues(pvals, method="bonferroni")
        self.assertAlmostEqual(float(bonf.loc["f1", "p_adj"]), 0.003, places=12)
        self.assertAlmostEqual(float(bonf.loc["f2", "p_adj"]), 0.12, places=12)
        self.assertAlmostEqual(float(bonf.loc["f3", "p_adj"]), 1.0, places=12)

        holm = adjust_pvalues(pvals, method="holm")
        self.assertAlmostEqual(float(holm.loc["f1", "p_adj"]), 0.003, places=12)
        self.assertAlmostEqual(float(holm.loc["f2", "p_adj"]), 0.08, places=12)
        self.assertAlmostEqual(float(holm.loc["f3", "p_adj"]), 0.50, places=12)

    def test_purged_kfold_and_walk_forward(self) -> None:
        dates = pd.date_range("2024-01-01", periods=50, freq="D", name="date")
        # 每个样本标签向后跨越 3 天
        label_end = dates + pd.Timedelta(days=3)
        splits = purged_kfold_splits(dates, n_splits=5, label_end_dates=label_end, embargo_pct=0.04)
        self.assertEqual(len(splits), 5)

        embargo_n = int(np.ceil(50 * 0.04))
        for train_idx, test_idx in splits:
            # 确认无重叠且满足 purging 约束
            self.assertEqual(len(set(train_idx).intersection(set(test_idx))), 0)
            test_start = dates[test_idx[0]]
            test_end = label_end[test_idx].max()
            for i in train_idx:
                self.assertTrue(label_end[i] < test_start or dates[i] > test_end)
            # 确认紧跟测试折最晚标签结束日之后的 embargo 样本被剔除
            embargo_start = int(np.searchsorted(dates.to_numpy(), test_end.to_numpy(), side="right"))
            after_test = set(range(embargo_start, min(50, embargo_start + embargo_n)))
            self.assertEqual(len(set(train_idx).intersection(after_test)), 0)

        wf_roll = walk_forward_splits(dates, train_size=20, test_size=10, expanding=False, embargo=2)
        self.assertEqual(len(wf_roll), 2)
        self.assertEqual(len(wf_roll[0][0]), 20)
        self.assertEqual(int(wf_roll[0][1][0]) - int(wf_roll[0][0][-1]) - 1, 2)

        wf_exp = walk_forward_splits(dates, train_size=20, test_size=10, expanding=True)
        self.assertEqual(len(wf_exp), 3)
        self.assertEqual(len(wf_exp[0][0]), 20)
        self.assertEqual(len(wf_exp[1][0]), 30)


class TestTimeSeriesStats(unittest.TestCase):
    """平稳性, 协整, OU 半衰期, Hurst 指数与 Ledoit-Wolf 协方差收缩测试"""

    def test_adf_and_kpss_distinguish_stationary_vs_random_walk(self) -> None:
        rng = np.random.default_rng(123)
        idx = pd.date_range("2020-01-01", periods=400, freq="B", name="date")
        wn = pd.Series(rng.normal(size=400), index=idx, name="wn")
        rw = pd.Series(np.cumsum(rng.normal(0.05, 1.0, size=400)), index=idx, name="rw")

        adf_wn = adf_test(wn)
        adf_fixed = adf_test(wn, autolag=None, maxlag=4)
        kpss_wn = kpss_test(wn)
        self.assertIsNotNone(adf_wn.p_value)
        self.assertIsNotNone(adf_fixed.p_value)
        self.assertEqual(adf_fixed.meta["usedlag"], 4)
        self.assertIsNotNone(kpss_wn.p_value)
        self.assertLess(adf_wn.p_value, 0.05)
        self.assertGreaterEqual(kpss_wn.p_value, 0.05)

        adf_rw = adf_test(rw)
        kpss_rw = kpss_test(rw)
        self.assertIsNotNone(adf_rw.p_value)
        self.assertIsNotNone(kpss_rw.p_value)
        self.assertGreater(adf_rw.p_value, 0.05)
        self.assertLess(kpss_rw.p_value, 0.05)

    def test_engle_granger_ou_half_life_and_hurst(self) -> None:
        rng = np.random.default_rng(42)
        idx = pd.date_range("2020-01-01", periods=600, freq="B", name="date")
        x = pd.Series(np.cumsum(rng.normal(size=600)), index=idx, name="x")
        spread = np.zeros(600)
        for i in range(1, 600):
            spread[i] = 0.9 * spread[i - 1] + rng.normal(scale=0.3)
        y = pd.Series(2.0 * x.to_numpy() + 5.0 + spread, index=idx, name="y")

        eg = engle_granger_coint(y, x)
        self.assertLess(eg.p_value or 1.0, 0.05)
        self.assertAlmostEqual(float(eg.meta["hedge_ratio"]), 2.0, delta=0.1)

        # trend="ct" 时应包含时间趋势项且对冲比率准确
        t_trend = 0.05 * np.arange(600, dtype=float)
        y_ct = pd.Series(2.0 * x.to_numpy() + 5.0 + t_trend + spread, index=idx, name="y_ct")
        eg_ct = engle_granger_coint(y_ct, x, trend="ct")
        self.assertLess(eg_ct.p_value or 1.0, 0.05)
        self.assertAlmostEqual(float(eg_ct.meta["hedge_ratio"]), 2.0, delta=0.1)
        self.assertAlmostEqual(float(eg_ct.meta["trend_coef"]), 0.05, delta=0.01)

        hl = ou_half_life(pd.Series(spread, index=idx, name="spread"))
        # 理论半衰期 -ln(2) / ln(0.9) 约 6.58
        self.assertGreater(hl.estimate, 3.0)
        self.assertLess(hl.estimate, 12.0)
        self.assertTrue(hl.is_significant_05)
        self.assertTrue(any("Dickey-Fuller" in w for w in hl.warnings))

        h_mr = hurst_exponent(pd.Series(spread, index=idx, name="spread"))
        self.assertLess(h_mr.estimate, 0.45)
        self.assertTrue(len(h_mr.warnings) > 0)

        h_rw = hurst_exponent(x)
        self.assertGreater(h_rw.estimate, 0.35)
        self.assertLess(h_rw.estimate, 0.65)

    def test_ledoit_wolf_cov_properties(self) -> None:
        rng = np.random.default_rng(5)
        idx = pd.date_range("2023-01-02", periods=40, freq="B", name="date")
        df = pd.DataFrame(rng.normal(scale=0.01, size=(40, 10)), index=idx, columns=[f"A{i}" for i in range(10)])

        cov, delta = ledoit_wolf_cov(df)
        self.assertEqual(cov.shape, (10, 10))
        self.assertGreaterEqual(delta, 0.0)
        self.assertLessEqual(delta, 1.0)
        # 对称且正定
        np.testing.assert_allclose(cov.to_numpy(), cov.to_numpy().T, atol=1e-12)
        eigvals = np.linalg.eigvalsh(cov.to_numpy())
        self.assertGreater(float(eigvals.min()), 0.0)


class TestEventStudyStats(unittest.TestCase):
    """事件研究 AR/CAR/BHAR 与 BMP 稳健检验测试"""

    def test_run_event_study_detects_injected_abnormal_return(self) -> None:
        rng = np.random.default_rng(2026)
        dates = pd.date_range("2022-01-03", periods=220, freq="B", name="date")
        mkt = pd.Series(rng.normal(0.0004, 0.01, size=len(dates)), index=dates, name="mkt")

        tickers = [f"S{i:02d}" for i in range(30)]
        idx = pd.MultiIndex.from_product([dates, tickers], names=["date", "ticker"])
        mkt_rep = np.repeat(mkt.to_numpy(), len(tickers))
        noise = rng.normal(0.0, 0.008, size=len(idx))
        stk = pd.Series(1.1 * mkt_rep + noise, index=idx, name="ret")

        # 在第 160 个交易日注入 +5% 异常收益冲击
        ev_date = dates[160]
        for tkr in tickers:
            stk.loc[(ev_date, tkr)] += 0.05

        events = pd.DataFrame(
            {
                "event_id": [f"ev_{i}" for i in range(len(tickers))],
                "event_date": [ev_date] * len(tickers),
                "ticker": tickers,
                "event_type": ["sp500_add"] * len(tickers),
            }
        )

        ev_df, stats = run_event_study(
            events,
            stk,
            mkt,
            est_window=(-120, -21),
            event_window=(-3, 3),
            model="market_model",
            min_est_obs=30,
        )
        self.assertEqual(len(ev_df), 30)
        self.assertAlmostEqual(stats["car_mean"].estimate, 0.05, delta=0.015)
        self.assertLess(stats["car_mean"].p_value or 1.0, 0.001)
        self.assertLess(stats["car_bmp"].p_value or 1.0, 0.001)
        self.assertGreater(stats["bhar_mean"].estimate, 0.035)


if __name__ == "__main__":
    unittest.main()
