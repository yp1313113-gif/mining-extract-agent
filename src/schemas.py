"""数据模型：抽取结果与审核结果的结构定义。

用 dataclass 而不是裸 dict，是为了让「字段缺失」和「字段为零」能被区分开 ——
这是本题的关键：抽不到就该 abstain，而不是填 0。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class ResourceRow:
    """一行资源量数据（Indicated 或 Inferred）。"""

    category: str = ""                    # "Indicated" / "Inferred"
    tonnage_Mt: Optional[float] = None    # 矿石量，百万吨
    grade_value: Optional[float] = None   # 品位数值
    grade_unit: Optional[str] = None      # 单位，如 "g/t Au" / "% Cu"
    contained_metal: Optional[float] = None
    contained_unit: Optional[str] = None  # "oz" / "t"
    page: Optional[int] = None            # 出处页码
    quote: Optional[str] = None           # 原文引用（用于核对）

    def filled_fields(self) -> dict[str, Any]:
        """只返回有值的字段，便于对比与打分。"""
        return {k: v for k, v in asdict(self).items()
                if v is not None and v != "" and k not in ("page", "quote")}


@dataclass
class Extraction:
    """一次抽取的完整结果。"""

    project_name: str = ""
    rows: list[ResourceRow] = field(default_factory=list)
    abstain: bool = False                 # 证据不足时置 True
    reason: str = ""                      # abstain 或存疑的原因
    raw_response: str = ""                # 保留原始输出，便于排查

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "rows": [asdict(r) for r in self.rows],
            "abstain": self.abstain,
            "reason": self.reason,
        }


@dataclass
class Critique:
    """一次审核的结果。"""

    score: int = 0                        # 1-10
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    should_abstain: bool = False
    raw_response: str = ""

    @property
    def passed(self) -> bool:
        return self.score >= 8 and not self.should_abstain
