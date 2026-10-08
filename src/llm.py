"""统一的 LLM 调用层。

DeepSeek / 通义千问 / 智谱 GLM 都提供 OpenAI 兼容接口，
所以这里只需要一个客户端封装，靠 base_url 区分厂商。
"""
from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from .config import config


class LLMError(RuntimeError):
    """调用模型失败。"""


def _client(base_url: str, api_key: str) -> OpenAI:
    if not api_key:
        raise LLMError(f"缺少 API Key（base_url={base_url}）")
    return OpenAI(base_url=base_url, api_key=api_key, timeout=120.0, max_retries=2)


def extractor_client() -> OpenAI:
    return _client(config.extractor_base_url, config.extractor_api_key)


def critic_client() -> OpenAI:
    return _client(config.critic_base_url, config.critic_api_key)


def parse_json_loose(text: str) -> dict[str, Any]:
    """从模型输出里抠出 JSON。

    即使开了 json_object 模式，个别厂商仍可能把 JSON 包在 markdown 代码块里。
    这里做三级兜底：直接解析 -> 剥掉代码块围栏 -> 取第一个 { 到最后一个 }。
    """
    if not text:
        raise LLMError("模型返回为空")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"无法解析模型返回的 JSON：{exc}") from exc

    raise LLMError("模型返回中找不到 JSON")


def chat_json(
    client: OpenAI,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.0,
    max_tokens: int = 32768,
) -> dict[str, Any]:
    """调一次模型并返回解析后的 JSON。

    max_tokens 默认给到 32768：
        DeepSeek 等模型默认开启「思考模式」，推理 token 与正文 token **共用同一额度**。
        实测（Newmont Ahafo，439 页报告，18 页上下文）：
          4096  -> 推理吃光，正文为空
          16384 -> 推理仍吃光（reasoning_tokens=16384），正文为空
        这类失败会以 finish_reason=length 暴露，本模块据此给出明确报错。
    """
    extra: dict[str, Any] = {}
    if not config.thinking_enabled:
        # DeepSeek 系模型默认开启思考模式，通过非标准参数关闭（走 extra_body 透传）
        extra["extra_body"] = {"thinking": {"type": "disabled"}}

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        **extra,
    )
    choice = resp.choices[0]
    content = choice.message.content or ""
    if not content.strip():
        # 明确报出 finish_reason，避免只看到「返回为空」而无从排查
        raise LLMError(
            f"模型返回空内容（finish_reason={choice.finish_reason}，"
            f"usage={resp.usage}）。通常是 max_tokens 被推理过程耗尽。"
        )
    return parse_json_loose(content)
