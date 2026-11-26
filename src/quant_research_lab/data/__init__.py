"""数据同步 (DuckDB <-> Parquet <-> Hugging Face), 标准数据读取器, 契约校验与 P0 基准拉取模块"""

from quant_research_lab.data.contracts import (
    DataContractError,
    require_panel,
    validate_panel,
    validate_signal,
    validate_timeseries,
)
from quant_research_lab.data.loader import (
    AQR_FACTOR_COLUMNS,
    DEFAULT_DB_PATH,
    FF_FACTOR_COLUMNS,
    PRICE_COLUMNS,
    UNIVERSE_COLUMNS,
    VOL_INDEX_COLUMNS,
    load_aqr_factors,
    load_calendar,
    load_ff_factors,
    load_prices,
    load_universe_panel,
    load_vol_indices,
)
from quant_research_lab.data.p0_fetch import (
    fetch_all_p0,
    fetch_aqr_factors_daily,
    fetch_cboe_vol_indices,
    fetch_ken_french_daily,
)
from quant_research_lab.data.qlib import read_qlib_feature
from quant_research_lab.data.sync import (
    DEFAULT_GH_REPO,
    DEFAULT_HF_REPO_ID,
    export_duckdb_to_parquet,
    import_parquet_to_duckdb,
    pull_from_github_release,
    pull_from_hf,
    push_to_hf,
)

__all__ = [
    "AQR_FACTOR_COLUMNS",
    "DEFAULT_DB_PATH",
    "DEFAULT_GH_REPO",
    "DEFAULT_HF_REPO_ID",
    "FF_FACTOR_COLUMNS",
    "PRICE_COLUMNS",
    "UNIVERSE_COLUMNS",
    "VOL_INDEX_COLUMNS",
    "DataContractError",
    "export_duckdb_to_parquet",
    "fetch_all_p0",
    "fetch_aqr_factors_daily",
    "fetch_cboe_vol_indices",
    "fetch_ken_french_daily",
    "import_parquet_to_duckdb",
    "load_aqr_factors",
    "load_calendar",
    "load_ff_factors",
    "load_prices",
    "load_universe_panel",
    "load_vol_indices",
    "pull_from_github_release",
    "pull_from_hf",
    "push_to_hf",
    "read_qlib_feature",
    "require_panel",
    "validate_panel",
    "validate_signal",
    "validate_timeseries",
]
