"""数据同步 (DuckDB <-> Parquet <-> Hugging Face), 契约校验与 P0 基准拉取模块"""

from quant_research_lab.data.contracts import (
    DataContractError,
    require_panel,
    validate_panel,
    validate_signal,
    validate_timeseries,
)
from quant_research_lab.data.p0_fetch import (
    fetch_all_p0,
    fetch_aqr_factors_daily,
    fetch_cboe_vol_indices,
    fetch_ken_french_daily,
)
from quant_research_lab.data.sync import (
    DEFAULT_HF_REPO_ID,
    export_duckdb_to_parquet,
    import_parquet_to_duckdb,
    pull_from_hf,
    push_to_hf,
)

__all__ = [
    "DEFAULT_HF_REPO_ID",
    "DataContractError",
    "export_duckdb_to_parquet",
    "fetch_all_p0",
    "fetch_aqr_factors_daily",
    "fetch_cboe_vol_indices",
    "fetch_ken_french_daily",
    "import_parquet_to_duckdb",
    "pull_from_hf",
    "push_to_hf",
    "require_panel",
    "validate_panel",
    "validate_signal",
    "validate_timeseries",
]
