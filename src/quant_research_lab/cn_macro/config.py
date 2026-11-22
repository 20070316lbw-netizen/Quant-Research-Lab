"""中国地级市宏观与环境数据构建配置加载器"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CN_MACRO_CONFIG: Path = Path("configs/cn_macro_build.yaml")


class CnMacroPaths(BaseModel):
    """本地数据与交付物路径配置"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    yearbook_source_xlsx: str = "data/统计年鉴数据.xlsx"
    work_dir: str = "data/cn_macro"
    raw_dir: str = "data/cn_macro/raw"
    duckdb_path: str = "data/cn_macro/cn_macro.duckdb"
    parquet_dir: str = "data/cn_macro/parquet"
    deliverables_dir: str = "data/cn_macro/deliverables"


class CnMacroYears(BaseModel):
    """各数据表起止年份与基期配置"""

    model_config = ConfigDict(extra="forbid")

    base_year: int = Field(default=2000, ge=1990, le=2025)
    pm10_start: int = Field(default=2000, ge=1990, le=2026)
    pm10_end: int = Field(default=2025, ge=1990, le=2026)
    carbon_start: int = Field(default=2000, ge=1990, le=2026)
    carbon_end: int = Field(default=2024, ge=1990, le=2026)
    gdp_start: int = Field(default=2000, ge=1990, le=2026)
    gdp_end: int = Field(default=2024, ge=1990, le=2026)


class CnMacroHfConfig(BaseModel):
    """Hugging Face 托管路径配置"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    repo_id: str = "2007liuQuant/Quant-Research-Lab"
    path_in_repo: str = "cn_macro"


class CnMacroConfig(BaseModel):
    """中国地级市宏观数据构建总配置"""

    model_config = ConfigDict(extra="forbid")

    paths: CnMacroPaths = Field(default_factory=CnMacroPaths)
    years: CnMacroYears = Field(default_factory=CnMacroYears)
    hf: CnMacroHfConfig = Field(default_factory=CnMacroHfConfig)


def load_cn_macro_config(config_path: str | Path = DEFAULT_CN_MACRO_CONFIG) -> CnMacroConfig:
    """读取并校验中国地级市宏观数据构建 YAML 配置文件

    Args:
        config_path: YAML 配置文件路径, 默认 configs/cn_macro_build.yaml

    Returns:
        CnMacroConfig: 通过 Pydantic 强校验的配置对象

    Raises:
        FileNotFoundError: 配置文件不存在
        ValueError: YAML 结构非法或字段校验失败

    Example:
        >>> cfg = load_cn_macro_config()
        >>> cfg.years.base_year
        2000
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"未找到配置文件: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError(f"配置文件顶层必须为字典: {path}")
    return CnMacroConfig.model_validate(raw)
