"""实验 YAML 配置文件强校验 Schema 与加载器"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from quant_research_lab.cards.schema import ModelFamily

DEFAULT_CONFIGS_DIR: Path = Path("configs")

SplitMethod = Literal["holdout", "walk_forward", "purged_kfold"]
RebalanceFreq = Literal["daily", "weekly", "monthly", "quarterly", "event"]
PriceField = Literal["open", "close", "adj_close"]
WeightingMethod = Literal["equal", "value", "inverse_vol", "signal_proportional"]
PAdjustMethod = Literal["bh", "bonferroni", "holm"]


class ConfigLoadError(ValueError):
    """实验 YAML 配置文件读取或强校验失败时抛出的异常"""


class ExperimentMeta(BaseModel):
    """实验基础标识元数据"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    card_id: str = Field(..., min_length=3, pattern=r"^[a-z0-9]+(-[a-z0-9]+)+$")
    name: str = Field(..., min_length=2, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    seed: int = Field(default=42, ge=0)
    notes: str = ""


class BenchmarkConfig(BaseModel):
    """基准标的与无风险利率配置"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    market_ticker: str = Field(default="SPY", min_length=1)
    risk_free_col: str = Field(default="rf", min_length=1)


class DataConfig(BaseModel):
    """锁定数据版本, 样本区间与引用表配置"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    dataset_version: str = Field(..., min_length=2)
    db_path: str = Field(default="data/lab.duckdb", min_length=1)
    start_date: date
    end_date: date
    universe: str = Field(default="SP500", min_length=2)
    tables: list[str] = Field(..., min_length=1)
    benchmark: BenchmarkConfig = Field(default_factory=BenchmarkConfig)

    @field_validator("tables")
    @classmethod
    def _deduplicate_tables(cls, value: list[str]) -> list[str]:
        cleaned = [t.strip() for t in value if t.strip()]
        if not cleaned:
            raise ValueError("data.tables 不能为空")
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def _check_date_order(self) -> DataConfig:
        if self.start_date >= self.end_date:
            raise ValueError(
                f"data.start_date ({self.start_date}) 必须早于 data.end_date ({self.end_date})"
            )
        return self


class SplitConfig(BaseModel):
    """防泄漏样本内外与交叉验证切分配置"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    method: SplitMethod
    is_end_date: date | None = None
    oos_start_date: date | None = None
    train_window: int | None = Field(default=None, ge=1)
    test_window: int | None = Field(default=None, ge=1)
    step_size: int | None = Field(default=None, ge=1)
    n_splits: int | None = Field(default=None, ge=2)
    purge_days: int = Field(default=0, ge=0)
    embargo_days: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check_method_requirements(self) -> SplitConfig:
        if self.method == "holdout":
            if self.is_end_date is None or self.oos_start_date is None:
                raise ValueError("split.method 为 holdout 时必须提供 is_end_date 与 oos_start_date")
            if self.is_end_date >= self.oos_start_date:
                raise ValueError(
                    f"split.is_end_date ({self.is_end_date}) 必须早于 oos_start_date ({self.oos_start_date})"
                )
        elif self.method == "walk_forward":
            if self.train_window is None or self.test_window is None:
                raise ValueError("split.method 为 walk_forward 时必须提供 train_window 与 test_window")
        elif self.method == "purged_kfold" and self.n_splits is None:
            raise ValueError("split.method 为 purged_kfold 时必须提供 n_splits")
        return self


class LongShortConfig(BaseModel):
    """分位数多空组合配置"""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    n_quantiles: int = Field(default=10, ge=2, le=20)


class ExecutionConfig(BaseModel):
    """调仓频率, 执行滞后, 冷启动过滤与交易成本配置"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    rebalance_freq: RebalanceFreq
    signal_lag_days: int = Field(default=1, ge=1)
    price_field: PriceField = "adj_close"
    weighting: WeightingMethod = "equal"
    long_short: LongShortConfig = Field(default_factory=LongShortConfig)
    cost_bps_default: float = Field(default=10.0, ge=0.0)
    cost_bps_grid: list[float] = Field(default_factory=lambda: [0.0, 5.0, 10.0, 20.0])
    min_history_days: int = Field(default=0, ge=0)

    @field_validator("cost_bps_grid")
    @classmethod
    def _validate_cost_grid(cls, value: list[float]) -> list[float]:
        if not value:
            raise ValueError("execution.cost_bps_grid 不能为空")
        if any(c < 0.0 for c in value):
            raise ValueError("execution.cost_bps_grid 不允许负数")
        return sorted({float(c) for c in value})


class AuditConfig(BaseModel):
    """统计学审计与多重检验校正配置"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    n_trials: int = Field(default=1, ge=1)
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    p_adjust_method: PAdjustMethod = "bh"
    nw_lags: int | None = Field(default=None, ge=0)
    annualization_factor: int = Field(default=252, ge=1)


class ModelConfig(BaseModel):
    """模型范式与实验专属参数配置"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    family: ModelFamily
    params: dict[str, Any] = Field(default_factory=dict)


class OutputConfig(BaseModel):
    """实验产物落盘配置"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    dir: str = Field(..., min_length=1)
    save_returns: bool = True
    save_weights: bool = False
    save_report_md: bool = True


class ExperimentConfig(BaseModel):
    """单次实证实验的完整强校验配置模型"""

    model_config = ConfigDict(extra="forbid")

    meta: ExperimentMeta
    data: DataConfig
    split: SplitConfig
    execution: ExecutionConfig
    audit: AuditConfig = Field(default_factory=AuditConfig)
    model: ModelConfig
    output: OutputConfig

    @model_validator(mode="after")
    def _check_split_within_data_range(self) -> ExperimentConfig:
        if self.split.method == "holdout":
            assert self.split.is_end_date is not None
            assert self.split.oos_start_date is not None
            if not (self.data.start_date < self.split.is_end_date < self.data.end_date):
                raise ValueError("split.is_end_date 必须严格位于 data.start_date 与 data.end_date 之间")
            if not (self.data.start_date < self.split.oos_start_date <= self.data.end_date):
                raise ValueError("split.oos_start_date 必须位于 data 样本区间内")
        return self

    def run_output_dir(self) -> Path:
        """返回本次实验的产物输出子目录 Path(output.dir) / meta.name

        Args:
            无外部参数, 使用当前配置中的 output.dir 与 meta.name

        Returns:
            Path: 本次实验对应的输出目录路径

        Raises:
            无

        Example:
            >>> cfg = load_experiment_config("eq-cs-001_residual_momentum.yaml")
            >>> cfg.run_output_dir().as_posix()
            'outputs/eq-cs-001/residual_momentum_baseline'
        """
        return Path(self.output.dir) / self.meta.name


def resolve_config_path(
    config_file: str | Path,
    configs_dir: Path = DEFAULT_CONFIGS_DIR,
) -> Path:
    """将配置文件名或路径解析为实际存在的 YAML 文件路径

    Args:
        config_file: 配置文件名 (如 "eq-cs-001_residual_momentum.yaml") 或显式路径
        configs_dir: 默认配置目录, 默认 Path("configs")

    Returns:
        Path: 解析后的配置文件路径

    Raises:
        ConfigLoadError: 配置文件不存在或扩展名不是 .yaml / .yml

    Example:
        >>> p = resolve_config_path("eq-cs-001_residual_momentum.yaml")
        >>> p.suffix in {".yaml", ".yml"}
        True
    """
    raw = Path(config_file)
    candidate = raw if raw.is_absolute() or raw.exists() else configs_dir / raw
    if not candidate.exists():
        raise ConfigLoadError(f"未找到实验配置文件: {candidate}")
    if candidate.suffix.lower() not in {".yaml", ".yml"}:
        raise ConfigLoadError(f"配置文件必须为 .yaml 或 .yml 格式: {candidate}")
    return candidate


def config_sha256(config_path: str | Path) -> str:
    """计算配置文件原始字节的 SHA256 摘要, 用于写入轻量报告确保可复现

    Args:
        config_path: 已存在的配置文件路径

    Returns:
        str: 64 位小写十六进制 SHA256 字符串

    Raises:
        ConfigLoadError: 文件不存在

    Example:
        >>> digest = config_sha256("configs/eq-cs-001_residual_momentum.yaml")
        >>> len(digest)
        64
    """
    path = Path(config_path)
    if not path.exists():
        raise ConfigLoadError(f"未找到配置文件: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_experiment_config(
    config_file: str | Path,
    configs_dir: Path = DEFAULT_CONFIGS_DIR,
) -> ExperimentConfig:
    """读取并强校验实验 YAML 配置文件

    Args:
        config_file: 配置文件名 (相对于 configs_dir) 或完整路径
        configs_dir: 默认配置目录, 默认 Path("configs")

    Returns:
        ExperimentConfig: 通过全部契约校验的配置对象

    Raises:
        ConfigLoadError: 文件不存在, YAML 解析失败或字段未通过 Pydantic 校验

    Example:
        >>> cfg = load_experiment_config("eq-cs-001_residual_momentum.yaml")
        >>> cfg.meta.card_id
        'eq-cs-001'
    """
    path = resolve_config_path(config_file, configs_dir=configs_dir)
    try:
        raw_obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigLoadError(f"{path}: YAML 解析失败: {exc}") from exc

    if not isinstance(raw_obj, dict):
        raise ConfigLoadError(f"{path}: YAML 顶层必须是映射对象")

    try:
        return ExperimentConfig.model_validate(raw_obj)
    except Exception as exc:
        raise ConfigLoadError(f"{path}: 实验配置校验失败:\n{exc}") from exc
