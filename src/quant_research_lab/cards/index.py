"""研究卡片全量校验, 查重与自动索引编译器 (INDEX.md + catalog.jsonl)"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from quant_research_lab.cards.io import CardValidationError, parse_card
from quant_research_lab.cards.schema import ResearchCard

IGNORED_MD_NAMES: frozenset[str] = frozenset({"INDEX.md", "TEMPLATE.md", "README.md"})


def load_all_cards(research_root: Path = Path("research")) -> list[tuple[ResearchCard, Path]]:
    """扫描并校验 research 目录下所有研究卡片, 同时校验全局 id 与 source_url 唯一性

    Args:
        research_root: 研究卡片根目录, 默认 Path("research")

    Returns:
        list[tuple[ResearchCard, Path]]: 按卡片 id 升序排列的 (ResearchCard, Path) 列表

    Raises:
        CardValidationError: 任意卡片格式非法, 或存在重复 id / source_url

    Example:
        >>> from pathlib import Path
        >>> cards = load_all_cards(Path("research"))
        >>> isinstance(cards, list)
        True
    """
    if not research_root.exists():
        return []

    results: list[tuple[ResearchCard, Path]] = []
    seen_ids: dict[str, Path] = {}
    seen_urls: dict[str, Path] = {}

    for md_path in sorted(research_root.rglob("*.md")):
        if md_path.name in IGNORED_MD_NAMES:
            continue
        card, _ = parse_card(md_path)

        if card.id in seen_ids:
            raise CardValidationError(f"重复卡片 id '{card.id}': {seen_ids[card.id]} 与 {md_path}")
        if card.source_url in seen_urls:
            raise CardValidationError(
                f"重复 source_url '{card.source_url}': {seen_urls[card.source_url]} 与 {md_path}"
            )

        seen_ids[card.id] = md_path
        seen_urls[card.source_url] = md_path
        results.append((card, md_path))

    results.sort(key=lambda item: item[0].id)
    return results


def check_duplicate(
    research_root: Path = Path("research"),
    *,
    card_id: str | None = None,
    source_url: str | None = None,
) -> list[str]:
    """在写入新卡片前快速检查是否存在相同 id 或相同 source_url

    Args:
        research_root: 研究卡片根目录, 默认 Path("research")
        card_id: 待检查的卡片唯一 id, 可选
        source_url: 待检查的原始链接, 可选

    Returns:
        list[str]: 命中的冲突说明列表, 为空表示无重复

    Raises:
        CardValidationError: 现有目录中存在格式损坏的卡片

    Example:
        >>> check_duplicate(Path("research"), card_id="non-existent-id")
        []
    """
    conflicts: list[str] = []
    for card, path in load_all_cards(research_root):
        if card_id is not None and card.id == card_id:
            conflicts.append(f"id 冲突: {card.id} ({path})")
        if source_url is not None and card.source_url == source_url:
            conflicts.append(f"source_url 冲突: {card.source_url} ({path})")
    return conflicts


def build_index(research_root: Path = Path("research")) -> tuple[Path, Path]:
    """编译所有研究卡片, 自动生成 research/catalog.jsonl 与 research/INDEX.md

    Args:
        research_root: 研究卡片根目录, 默认 Path("research")

    Returns:
        tuple[Path, Path]: (INDEX.md 路径, catalog.jsonl 路径)

    Raises:
        CardValidationError: 任意卡片未通过强校验或存在重复

    Example:
        >>> index_md, catalog_jsonl = build_index(Path("research"))
        >>> index_md.name, catalog_jsonl.name
        ('INDEX.md', 'catalog.jsonl')
    """
    research_root.mkdir(parents=True, exist_ok=True)
    cards = load_all_cards(research_root)

    catalog_path = research_root / "catalog.jsonl"
    records: list[dict[str, Any]] = []
    for card, md_path in cards:
        rec = card.model_dump(mode="json")
        rec["file_path"] = md_path.relative_to(research_root).as_posix()
        records.append(rec)

    catalog_text = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    catalog_path.write_text((catalog_text + "\n") if catalog_text else "", encoding="utf-8")

    # 生成人眼速览总览表 INDEX.md
    status_counts = Counter(c.status for c, _ in cards)
    feas_counts = Counter(c.feasibility for c, _ in cards)

    lines: list[str] = [
        "# Quant Research Lab 研究总览 (自动生成, 请勿手改)",
        "",
        f"- **累计研究卡片**: {len(cards)}",
        "- **状态分布**: "
        + (", ".join(f"`{k}`: {v}" for k, v in sorted(status_counts.items())) or "暂无"),
        "- **数据可行性**: "
        + (", ".join(f"`{k}`: {v}" for k, v in sorted(feas_counts.items())) or "暂无"),
        "",
    ]

    by_domain: dict[str, list[tuple[ResearchCard, Path]]] = {}
    for card, md_path in cards:
        key = f"{card.sector} / {card.domain}"
        by_domain.setdefault(key, []).append((card, md_path))

    for group_key in sorted(by_domain):
        lines.append(f"## {group_key}")
        lines.append("")
        lines.append("| ID | 标题 | 模型范式 | 研究对象 | 可行性 | 状态 | 一句话总结 |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for card, md_path in by_domain[group_key]:
            rel = md_path.relative_to(research_root).as_posix()
            title_link = f"[{card.title} ({card.year})](./{rel})"
            lines.append(
                f"| `{card.id}` | {title_link} | `{card.model_family}` | "
                f"{card.target_object} | `{card.feasibility}` | `{card.status}` | {card.one_liner} |"
            )
        lines.append("")

    index_path = research_root / "INDEX.md"
    index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return index_path, catalog_path


def query_catalog(
    research_root: Path = Path("research"),
    *,
    sector: str | None = None,
    domain: str | None = None,
    feasibility: str | None = None,
    status: str | None = None,
    model_family: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    """按条件快速筛选 catalog.jsonl 中的研究卡片记录

    Args:
        research_root: 研究卡片根目录, 默认 Path("research")
        sector: 按大类筛选 (equities / macro / cross_asset), 可选
        domain: 按子研究域筛选, 可选
        feasibility: 按数据可行性筛选 (如 ready), 可选
        status: 按研究状态筛选 (如 scouted / queued), 可选
        model_family: 按核心建模范式筛选, 可选
        tag: 按单个标签筛选 (大小写不敏感), 可选

    Returns:
        list[dict[str, Any]]: 命中的研究卡片元数据字典列表

    Raises:
        FileNotFoundError: catalog.jsonl 尚未生成

    Example:
        >>> hits = query_catalog(Path("research"), feasibility="ready")
        >>> isinstance(hits, list)
        True
    """
    catalog_path = research_root / "catalog.jsonl"
    if not catalog_path.exists():
        raise FileNotFoundError(f"未找到索引文件, 请先运行 build_index(): {catalog_path}")

    tag_lower = tag.strip().lower() if tag else None
    matched: list[dict[str, Any]] = []
    for line in catalog_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if sector is not None and rec.get("sector") != sector:
            continue
        if domain is not None and rec.get("domain") != domain:
            continue
        if feasibility is not None and rec.get("feasibility") != feasibility:
            continue
        if status is not None and rec.get("status") != status:
            continue
        if model_family is not None and rec.get("model_family") != model_family:
            continue
        if tag_lower is not None and tag_lower not in rec.get("tags", []):
            continue
        matched.append(rec)
    return matched
