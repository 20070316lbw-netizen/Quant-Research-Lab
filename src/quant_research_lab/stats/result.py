"""统计学检验与绩效评估的统一返回对象"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StatResult:
    """所有统计学检验与核心绩效指标的标准化返回结构"""

    name: str
    estimate: float
    se: float | None = None
    t_stat: float | None = None
    p_value: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    n_obs: int = 0
    meta: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def is_significant_05(self) -> bool | None:
        """双侧 5% 显著性水平判断, 无 p_value 时返回 None"""
        return None if self.p_value is None else self.p_value < 0.05

    def to_dict(self) -> dict[str, Any]:
        """转换为扁平字典, 便于日志记录或汇总为 DataFrame 行

        Args:
            无

        Returns:
            dict[str, Any]: 包含核心统计量, warnings 列表及 meta 展开字段的字典

        Raises:
            无

        Example:
            >>> res = StatResult(name="mean_ic", estimate=0.04, p_value=0.01, n_obs=120)
            >>> res.to_dict()["estimate"]
            0.04
        """
        return {
            "name": self.name,
            "estimate": self.estimate,
            "se": self.se,
            "t_stat": self.t_stat,
            "p_value": self.p_value,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "n_obs": self.n_obs,
            "warnings": list(self.warnings),
            **self.meta,
        }
