"""搜罗架构与研究卡片管理模块 (强校验 Schema, 模板写入, 查重与自动索引)"""

from quant_research_lab.cards.index import (
    build_index,
    check_duplicate,
    load_all_cards,
    query_catalog,
)
from quant_research_lab.cards.io import (
    CardValidationError,
    parse_card,
    render_card,
    resolve_card_path,
    write_card,
)
from quant_research_lab.cards.schema import (
    READY_TABLES,
    REQUIRED_BODY_SECTIONS,
    ExperimentRecord,
    ResearchCard,
)

__all__ = [
    "READY_TABLES",
    "REQUIRED_BODY_SECTIONS",
    "CardValidationError",
    "ExperimentRecord",
    "ResearchCard",
    "build_index",
    "check_duplicate",
    "load_all_cards",
    "parse_card",
    "query_catalog",
    "render_card",
    "resolve_card_path",
    "write_card",
]
