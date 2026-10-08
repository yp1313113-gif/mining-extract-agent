"""Evolution Log：把每一次尝试（成功 / 失败 / 降级）追加到 evolution.jsonl。

用途有两个：
  1. 事后复盘：哪些报告容易抽错、错在哪些字段；
  2. few-shot 改进：把「失败案例 + 正确做法」挑出来，回填进抽取提示。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import EVOLUTION_LOG


def append(record: dict[str, Any], path: Path | None = None) -> None:
    """追加一条记录（JSON Lines，每行一个 JSON 对象）。"""
    target = Path(path or EVOLUTION_LOG)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": datetime.now().isoformat(timespec="seconds"), **record}
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load(path: Path | None = None) -> list[dict[str, Any]]:
    """读回全部记录，供改进分析使用。"""
    target = Path(path or EVOLUTION_LOG)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def summarize(path: Path | None = None) -> dict[str, Any]:
    """给出一份简单的自我复盘统计。"""
    rows = load(path)
    total = len(rows)
    passed = sum(1 for r in rows if r.get("passed"))
    abstained = sum(1 for r in rows if r.get("abstained"))
    return {
        "total_attempts": total,
        "passed": passed,
        "abstained": abstained,
        "pass_rate": round(passed / total, 3) if total else 0.0,
    }
