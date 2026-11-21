"""研究卡片 YAML Frontmatter 强校验模型与正文结构规范"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SourceType = Literal["paper", "github", "blog", "book", "macro_report"]
Sector = Literal["equities", "macro", "cross_asset"]
Domain = Literal[
    "cross_sectional",
    "stat_arb",
    "event_driven",
    "fundamental",
    "portfolio_risk",
    "macro_regime",
    "macro_indicator",
    "cross_asset",
]
Horizon = Literal["intraday", "daily", "weekly", "monthly", "quarterly", "macro_cycle"]
ModelFamily = Literal[
    "factor_residual",
    "stat_arb_ou",
    "pca_stat_factor",
    "regime_hmm",
    "event_study",
    "panel_regression",
    "ml_tree",
    "portfolio_opt",
    "macro_var",
    "volatility_timing",
    "other",
]
Feasibility = Literal["ready", "needs_fundamental", "needs_macro", "blocked_data_missing"]
CardStatus = Literal["scouted", "reviewed", "queued", "in_progress", "promoted", "refuted", "parked"]

# v1.0.0 锁定数据集中已实际就绪的数据表
READY_TABLES: frozenset[str] = frozenset(
    {
        "prices",
        "universe",
        "fundamental_instant",
        "fundamental_period",
        "ticker_segment",
        "market_calendar",
        "calendar",
        "ff_factors_daily",
        "vol_indices_daily",
        "aqr_factors_daily",
    }
)

REQUIRED_BODY_SECTIONS: tuple[str, ...] = (
    "## 1. 核心直觉",
    "## 2. 研究对象的核心建模",
    "## 3. 数据映射与复现改造",
    "## 4. 亮点, 假设与失效边界",
    "## 5. 实证结论",
)


class ResearchCard(BaseModel):
    """单篇研究卡片的强约束元数据模型"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # 基础标识
    id: str = Field(..., min_length=3, pattern=r"^[a-z0-9]+(-[a-z0-9]+)+$")
    title: str = Field(..., min_length=2)
    source_type: SourceType
    source_url: str = Field(..., min_length=4)
    year: int = Field(..., ge=1900, le=2100)
    authors: list[str] = Field(..., min_length=1)

    # 领域与研究对象
    sector: Sector
    domain: Domain
    universe: str = Field(..., min_length=2)
    horizon: Horizon

    # 核心建模元数据
    target_object: str = Field(..., min_length=2)
    model_family: ModelFamily
    estimation_method: str = Field(..., min_length=2)

    # 数据对标与可行性
    data_required: list[str] = Field(..., min_length=1)
    feasibility: Feasibility

    # 核心提炼与生命周期
    one_liner: str = Field(..., min_length=5, max_length=200)
    key_highlight: str = Field(..., min_length=5, max_length=300)
    key_risk: str = Field(..., min_length=5, max_length=300)
    tags: list[str] = Field(..., min_length=1)
    status: CardStatus = "scouted"
    scouted_at: date
    experiment_ref: str | None = None

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        cleaned = [t.strip().lower() for t in value if t.strip()]
        if not cleaned:
            raise ValueError("tags 不能为空")
        return list(dict.fromkeys(cleaned))

    @field_validator("data_required")
    @classmethod
    def _normalize_data_required(cls, value: list[str]) -> list[str]:
        cleaned = [d.strip() for d in value if d.strip()]
        if not cleaned:
            raise ValueError("data_required 不能为空")
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def _check_feasibility_against_ready_tables(self) -> ResearchCard:
        if self.feasibility == "ready":
            missing = [t for t in self.data_required if t not in READY_TABLES]
            if missing:
                raise ValueError(
                    f"feasibility 为 ready, 但 data_required 包含当前未就绪表: {missing}"
                )
        return self
