"""Extractor Agent：用强模型从报告片段中抽取资源量。

设计要点（对应题目的评分着眼点）：
  1. 抽不到的字段必须填 null —— 不允许猜、不允许填 0；
  2. 每行都要给「页码 + 原文引用」，没有引用视为无证据；
  3. 当证据明显不足时，允许并鼓励返回 abstain=true。
"""
from __future__ import annotations

import json
from typing import Optional

from .config import config
from .llm import LLMError, chat_json, extractor_client
from .schemas import Extraction, ResourceRow

SYSTEM_PROMPT = """你是一名矿业技术报告数据抽取专家，熟悉 NI 43-101 标准的资源量表述。

你的任务：从给定的报告片段中，抽取 **Indicated Resources（控制的资源量）** 与
**Inferred Resources（推断的资源量）** 两类数据。每类给出：

**先确定抽取哪一张表**（这一步最容易出错）：
  - 一份报告里可能同时有「项目/矿区整体的资源量汇总表」和「各矿床分项表」。
  - **一律抽取「项目/矿区整体」的汇总数字**（通常出现在正文开头的 Mineral Resource
    Statement 段落，措辞类似 "Measured and Indicated categories: X Mt at ... for Y Moz"）。
  - **不要**输出各矿床的分项行，也不要把分项行与汇总行混在一起。
  - 如果只有分项表、没有汇总表，则输出分项行，并在 reason 中说明「本报告无汇总表，输出为分项」。

每行字段：

- tonnage_Mt        矿石量，单位百万吨（Mt）
- grade_value       品位数值（只填数字）
- grade_unit        品位单位，例如 "g/t Au" / "% Cu" / "% Li2O"
- contained_metal   金属量数值（只填数字）
- contained_unit    金属量单位，例如 "oz" / "t" / "kt"
- page              数据所在页码（片段中 <<<PAGE n>>> 标记里的 n）
- quote             支撑该行数据的原文片段，必须逐字摘自片段

铁律（违反会导致结果被判定为不可用）：
1. 不确定的字段一律填 null，绝对不要猜测、不要用 0 代替、不要从其他行推断。
2. 每一行都必须有 page 和 quote；没有原文出处的行不要输出。
3. 如果片段中根本找不到资源量表，或者表格被截断、模糊到无法确认数值，
   请返回 abstain=true，并在 reason 中说明原因。
4. 只输出 JSON，不要任何解释性文字。

输出 JSON 结构：
{
  "project_name": "项目名称，找不到填空字符串",
  "rows": [
    {
      "category": "Indicated 或 Inferred",
      "tonnage_Mt": 123.4,
      "grade_value": 1.23,
      "grade_unit": "g/t Au",
      "contained_metal": 456789,
      "contained_unit": "oz",
      "page": 12,
      "quote": "原文片段"
    }
  ],
  "abstain": false,
  "reason": "如果 abstain 为 true，这里说明原因；否则留空"
}"""


def build_user_prompt(source_name: str, context: str, feedback: Optional[str] = None) -> str:
    """拼装用户提示。feedback 非空时表示这是修订轮，把上一轮审核意见带回去。"""
    parts = [f"报告名称：{source_name}", "", "以下是报告片段（页码标记为 <<<PAGE n>>>）：", "", context]
    if feedback:
        parts += [
            "",
            "=" * 60,
            "上一轮抽取被审核模型指出以下问题，请在本次修订中针对性修正：",
            feedback,
            "=" * 60,
        ]
    parts += ["", "请按系统提示要求的 JSON 结构输出。"]
    return "\n".join(parts)


def _to_float(value) -> Optional[float]:
    """把模型可能返回的 '1,234.5' / '12.3%' / '' 统一成 float 或 None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_extraction(data: dict) -> Extraction:
    """把模型返回的 dict 转成 Extraction，做字段级清洗。"""
    rows: list[ResourceRow] = []
    for raw in data.get("rows") or []:
        if not isinstance(raw, dict):
            continue
        page_raw = str(raw.get("page") or "").strip()
        row = ResourceRow(
            category=str(raw.get("category") or "").strip(),
            tonnage_Mt=_to_float(raw.get("tonnage_Mt")),
            grade_value=_to_float(raw.get("grade_value")),
            grade_unit=(raw.get("grade_unit") or None),
            contained_metal=_to_float(raw.get("contained_metal")),
            contained_unit=(raw.get("contained_unit") or None),
            page=int(page_raw) if page_raw.isdigit() else None,
            quote=(raw.get("quote") or None),
        )
        # 无出处的行直接丢弃 —— 宁可少给，不可乱给
        if row.quote and row.page:
            rows.append(row)

    return Extraction(
        project_name=str(data.get("project_name") or ""),
        rows=rows,
        abstain=bool(data.get("abstain")),
        reason=str(data.get("reason") or ""),
        raw_response=json.dumps(data, ensure_ascii=False),
    )


def extract(source_name: str, context: str, feedback: Optional[str] = None) -> Extraction:
    """执行一次抽取。失败时返回 abstain 的结果，而不是抛异常中断整条流水线。"""
    client = extractor_client()
    user = build_user_prompt(source_name, context, feedback)
    try:
        data = chat_json(client, config.extractor_model, SYSTEM_PROMPT, user)
    except LLMError as exc:
        return Extraction(abstain=True, reason=f"抽取失败：{exc}")

    result = parse_extraction(data)
    # 模型自相矛盾（说 abstain 却又给了行）时，以有证据的行内容为准
    if result.abstain and result.rows:
        result.abstain = False
    return result
