"""CriticMaster Agent：用「另一个模型」对抽取结果挑刺并打分。

为什么必须换一个模型：
    同一个模型既当运动员又当裁判，会倾向于给自己打高分。
    跨模型审核能显著暴露「看起来合理、其实数字从别处抄来」的错误。

评分口径（1-10）：
    9-10  所有字段都能在原文找到，数值一致，单位正确
    7-8   主字段正确，个别次要字段缺失或单位不规范
    4-6   有字段错误（数值不符 / 单位错 / 串行）
    1-3   大面积错误，或引用了不存在的原文
"""
from __future__ import annotations

import json

from .config import config
from .llm import LLMError, chat_json, critic_client
from .schemas import Critique, Extraction

SYSTEM_PROMPT = """你是一名极其严格的矿业数据审核员（CriticMaster）。
你的职责是**找出别人抽取结果里的错误**，而不是帮他圆场。

你会拿到两份材料：
  A. 报告原文片段（页码标记为 <<<PAGE n>>>）
  B. 另一个模型抽取出的结构化数据（含每行的 page 与 quote）

请逐行核对，重点检查以下几类错误：

1. **数值不一致**：抽取的 tonnage / grade / contained_metal 与原文是否一致（注意单位换算，Mt 与 t、oz 与 t 不要混淆）。
2. **引用造假**：quote 是否真的出现在原文里？有没有把没有的句子编出来？
3. **串行/错位**：是否把 Indicated 的数字填到了 Inferred，或把相邻项目的数字混进来。
4. **无证据硬填**：原文里根本没有该字段，却被填了一个具体数字（这种情况比填 null 严重得多）。
5. **单位错误**：单位漏填、写错或与原文不符。

评分规则（1-10）：
  9-10  所有字段均可在原文核对上，无造假引用
  7-8   主字段正确，个别次要字段缺失或单位不规范
  4-6   存在字段级错误（数值不符 / 单位错 / 串行）
  1-3   大面积错误，或存在编造的原文引用

如果**通篇找不到可靠的资源量数据**，而抽取结果却给了一堆具体数字，请直接把分数打到 3 分以下，
并把 should_abstain 置为 true。

只输出 JSON：
{
  "score": 7,
  "issues": ["具体问题1", "具体问题2"],
  "suggestions": ["可执行的修改建议1"],
  "should_abstain": false
}""" 


def build_user_prompt(source_name: str, context: str, extraction: Extraction) -> str:
    payload = json.dumps(extraction.to_dict(), ensure_ascii=False, indent=2)
    return "\n".join([
        f"报告名称：{source_name}",
        "",
        "=== A. 报告原文片段 ===",
        context,
        "",
        "=== B. 待审核的抽取结果 ===",
        payload,
        "",
        "请按系统提示逐行核对并打分，只输出 JSON。",
    ])


def parse_critique(data: dict) -> Critique:
    def as_list(value) -> list[str]:
        if isinstance(value, list):
            return [str(v) for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0

    return Critique(
        score=max(0, min(10, score)),
        issues=as_list(data.get("issues")),
        suggestions=as_list(data.get("suggestions")),
        should_abstain=bool(data.get("should_abstain")),
        raw_response=json.dumps(data, ensure_ascii=False),
    )


def critique(source_name: str, context: str, extraction: Extraction) -> Critique:
    """执行一次审核。调用失败时保守处理：给 0 分并置 abstain。"""
    client = critic_client()
    user = build_user_prompt(source_name, context, extraction)
    try:
        data = chat_json(client, config.critic_model, SYSTEM_PROMPT, user)
    except LLMError as exc:
        return Critique(score=0, issues=[f"审核失败：{exc}"], should_abstain=True)
    return parse_critique(data)


def format_feedback(c: Critique) -> str:
    """把审核意见拼成给抽取模型的反馈文本。"""
    lines = [f"审核得分：{c.score}/10"]
    if c.issues:
        lines.append("发现的问题：")
        lines += [f"  - {i}" for i in c.issues]
    if c.suggestions:
        lines.append("修改建议：")
        lines += [f"  - {s}" for s in c.suggestions]
    lines.append("注意：核对不上的字段请改为 null，不要保留猜测值。")
    return "\n".join(lines)
