"""量化研究统计学检验与防过拟合审计工具库"""

from quant_research_lab.stats.event_study import EVENT_REQUIRED_COLS, run_event_study
from quant_research_lab.stats.factor import (
    compute_ic_series,
    fama_macbeth,
    ic_decay,
    neutralize_cs,
    quantile_portfolio_returns,
    standardize_cs,
    summarize_ic,
    winsorize_cs,
)
from quant_research_lab.stats.realized import realized_semivariance
from quant_research_lab.stats.result import StatResult
from quant_research_lab.stats.timeseries import (
    adf_test,
    engle_granger_coint,
    hurst_exponent,
    kpss_test,
    ledoit_wolf_cov,
    ou_half_life,
)
from quant_research_lab.stats.validation import (
    adjust_pvalues,
    deflated_sharpe_ratio,
    performance_summary,
    probabilistic_sharpe_ratio,
    purged_kfold_splits,
    walk_forward_splits,
)

__all__ = [
    "EVENT_REQUIRED_COLS",
    "StatResult",
    "adf_test",
    "adjust_pvalues",
    "compute_ic_series",
    "deflated_sharpe_ratio",
    "engle_granger_coint",
    "fama_macbeth",
    "hurst_exponent",
    "ic_decay",
    "kpss_test",
    "ledoit_wolf_cov",
    "neutralize_cs",
    "ou_half_life",
    "performance_summary",
    "probabilistic_sharpe_ratio",
    "purged_kfold_splits",
    "quantile_portfolio_returns",
    "realized_semivariance",
    "run_event_study",
    "standardize_cs",
    "summarize_ic",
    "walk_forward_splits",
    "winsorize_cs",
]
