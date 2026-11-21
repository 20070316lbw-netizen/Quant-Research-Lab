"""研究卡片读写, 模板渲染与正文结构校验"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from quant_research_lab.cards.schema import REQUIRED_BODY_SECTIONS, ResearchCard


class CardValidationError(ValueError):
    """研究卡片 YAML 或正文模板不符合规范时抛出的异常"""


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "card"


def parse_card(path: Path) -> tuple[ResearchCard, str]:
    """解析并强校验单个研究卡片 Markdown 文件

    Args:
        path: 研究卡片 .md 文件路径

    Returns:
        tuple[ResearchCard, str]: (校验后的元数据模型, 正文 Markdown 文本)

    Raises:
        FileNotFoundError: 文件不存在
        CardValidationError: 缺少 YAML Frontmatter, YAML 语法错误, 字段校验失败或缺少必需正文章节

    Example:
        >>> from pathlib import Path
        >>> card, body = parse_card(Path("research/equities/cross_sectional/2011-blitz-residual-momentum.md"))
        >>> card.id
        'eq-cs-001'
    """
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise CardValidationError(f"{path}: 必须以 YAML Frontmatter (---) 开头")

    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        raise CardValidationError(f"{path}: 未找到 YAML Frontmatter 结束分隔符 (---)")

    raw_yaml = parts[0][4:]
    body = parts[1].strip()

    try:
        meta = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise CardValidationError(f"{path}: YAML 解析失败: {exc}") from exc

    if not isinstance(meta, dict):
        raise CardValidationError(f"{path}: YAML Frontmatter 必须是键值对映射")

    try:
        card = ResearchCard.model_validate(meta)
    except Exception as exc:
        raise CardValidationError(f"{path}: 元数据校验失败: {exc}") from exc

    missing_sections = [sec for sec in REQUIRED_BODY_SECTIONS if sec not in body]
    if missing_sections:
        raise CardValidationError(f"{path}: 正文缺少必需章节 {missing_sections}")

    return card, body


def render_card(card: ResearchCard, sections: dict[str, str] | None = None) -> str:
    """将 ResearchCard 与五段正文渲染为标准研究卡片 Markdown 文本

    Args:
        card: 已通过校验的 ResearchCard 实例
        sections: 可选章节内容映射, 键可为 intuition, modeling, data_mapping, highlights_risks, empirical

    Returns:
        str: 包含规范 YAML Frontmatter 与五段固定正文结构的 Markdown 字符串

    Raises:
        无

    Example:
        >>> from datetime import date
        >>> c = ResearchCard(
        ...     id="eq-cs-999", title="Demo", source_type="paper", source_url="https://example.com",
        ...     year=2024, authors=["Alice"], sector="equities", domain="cross_sectional",
        ...     universe="SP500", horizon="monthly", target_object="单股超额收益",
        ...     model_family="factor_residual", estimation_method="rolling_ols",
        ...     data_required=["prices", "universe"], feasibility="ready",
        ...     one_liner="示例研究卡片摘要", key_highlight="示例核心亮点", key_risk="示例主要风险",
        ...     tags=["demo"], scouted_at=date(2026, 11, 22),
        ... )
        >>> render_card(c).startswith("---\n")
        True
    """
    sec = sections or {}
    payload = card.model_dump(mode="json")
    frontmatter = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).strip()

    intuition = sec.get("intuition", "- 简述解决的痛点与经济学直觉 (3 句话内)").strip()
    modeling = sec.get(
        "modeling",
        "- **研究对象与因变量**: 待补充\n"
        "- **核心数学表达**: 待补充\n"
        "- **估计与防泄漏设定**: 待补充\n"
        "- **交易/决策映射**: 待补充",
    ).strip()
    data_mapping = sec.get(
        "data_mapping",
        "- **对应本地表**: 待补充\n- **缺失项与替代方案**: 无",
    ).strip()
    highlights_risks = sec.get(
        "highlights_risks",
        "- **为什么值得做**: 待补充\n- **致命假设与失效场景**: 待补充",
    ).strip()
    empirical = sec.get("empirical", "- 暂未实证 (待把关立项)").strip()

    return (
        f"---\n{frontmatter}\n---\n\n"
        f"# {card.title}\n\n"
        f"## 1. 核心直觉\n{intuition}\n\n"
        f"## 2. 研究对象的核心建模\n{modeling}\n\n"
        f"## 3. 数据映射与复现改造\n{data_mapping}\n\n"
        f"## 4. 亮点, 假设与失效边界\n{highlights_risks}\n\n"
        f"## 5. 实证结论\n{empirical}\n"
    )


def resolve_card_path(card: ResearchCard, research_root: Path = Path("research")) -> Path:
    """根据卡片的 sector, domain, year, 第一作者与标题生成规范保存路径

    Args:
        card: 已校验的 ResearchCard 实例
        research_root: 研究卡片根目录, 默认 Path("research")

    Returns:
        Path: 目标 .md 文件路径

    Raises:
        无

    Example:
        >>> from datetime import date
        >>> c = ResearchCard(
        ...     id="eq-cs-001", title="Residual Momentum", source_type="paper",
        ...     source_url="https://example.com/1", year=2011, authors=["David Blitz"],
        ...     sector="equities", domain="cross_sectional", universe="SP500", horizon="monthly",
        ...     target_object="单股月度超额收益", model_family="factor_residual",
        ...     estimation_method="rolling_ols_36m", data_required=["prices", "universe"],
        ...     feasibility="ready", one_liner="三因子残差动量降低崩盘风险",
        ...     key_highlight="夏普比率显著提升", key_risk="换手成本敏感",
        ...     tags=["momentum"], scouted_at=date(2026, 11, 22),
        ... )
        >>> str(resolve_card_path(c))
        'research/equities/cross_sectional/2011-blitz-residual-momentum.md'
    """
    author_last = _slugify(card.authors[0].split()[-1])
    title_slug = _slugify(card.title)
    filename = f"{card.year}-{author_last}-{title_slug}.md"

    if card.sector == "equities":
        return research_root / "equities" / card.domain / filename
    if card.sector == "macro":
        return research_root / "macro" / filename
    return research_root / "cross_asset" / filename


def write_card(
    card: ResearchCard,
    sections: dict[str, str] | None = None,
    *,
    research_root: Path = Path("research"),
    overwrite: bool = False,
) -> Path:
    """校验去重后将研究卡片写入规范目录

    Args:
        card: 已校验的 ResearchCard 实例
        sections: 五段正文内容字典, 默认使用占位模板
        research_root: 研究卡片根目录, 默认 Path("research")
        overwrite: 是否允许覆盖已存在文件, 默认 False

    Returns:
        Path: 实际写入的 .md 文件路径

    Raises:
        FileExistsError: 目标文件已存在且 overwrite=False
        CardValidationError: 发现同 id 或同 source_url 的重复卡片

    Example:
        >>> # 写入完成后建议调用 build_index(research_root) 刷新总览表与机器索引
        >>> True
        True
    """
    from quant_research_lab.cards.index import check_duplicate

    target = resolve_card_path(card, research_root)
    if target.exists() and not overwrite:
        raise FileExistsError(f"卡片文件已存在: {target}")

    if not overwrite and research_root.exists():
        dups = check_duplicate(research_root, card_id=card.id, source_url=card.source_url)
        if dups:
            raise CardValidationError(f"检测到重复研究卡片: {dups}")

    target.parent.mkdir(parents=True, exist_ok=True)
    content = render_card(card, sections)
    target.write_text(content, encoding="utf-8")
    return target
