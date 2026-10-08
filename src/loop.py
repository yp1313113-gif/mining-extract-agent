"""Revise Loop：抽取 -> 审核 -> 不满分就带着意见重抽 -> 最多 N 轮。

终止条件（三者之一）：
  1. 审核得分 >= PASS_SCORE（默认 8）且审核未要求 abstain  -> passed
  2. 抽取模型主动 abstain                                  -> abstained
  3. 轮数耗尽仍未达标                                      -> abstained（转人工）

关键设计：**轮数耗尽时返回 abstain，而不是返回「最后一次的抽取结果」。**
题目明确说了最看重这一点 —— 证据不足时宁可交白卷，也不要硬给一个看起来像样的数字。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import evolution
from .config import config
from .critic import critique, format_feedback
from .extractor import extract
from .pdf_utils import build_context, extract_pages, locate_resource_pages, pdf_name_to_id
from .schemas import Critique, Extraction


@dataclass
class LoopResult:
    """一次完整对抗循环的结果。"""

    report_id: str
    rounds: int = 0
    passed: bool = False
    abstained: bool = False
    extraction: Extraction = field(default_factory=Extraction)
    critiques: list[Critique] = field(default_factory=list)
    best_score: int = 0

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "rounds": self.rounds,
            "passed": self.passed,
            "abstained": self.abstained,
            "best_score": self.best_score,
            "extraction": self.extraction.to_dict(),
            "scores": [c.score for c in self.critiques],
        }


def run_one(pdf_path: str | Path, verbose: bool = True) -> LoopResult:
    """对单个 PDF 跑一遍完整流程。"""
    pdf_path = Path(pdf_path)
    report_id = pdf_name_to_id(pdf_path)

    # ---- 1) 解析 + 定位资源量页 ----
    # 页数与字符数上限直接决定每次调用的成本，集中在 config 里便于调参
    pages = extract_pages(pdf_path)
    page_nums = locate_resource_pages(pages, top_k=config.top_k_pages)
    context = build_context(pages, page_nums, max_chars=config.max_context_chars)
    if verbose:
        print(f"[{report_id}] 共 {len(pages)} 页，喂给模型的页数 {len(page_nums)}"
              f"，上下文 {len(context)} 字")

    result = LoopResult(report_id=report_id)
    feedback: str | None = None

    # ---- 2) 对抗循环 ----
    for round_no in range(1, config.max_rounds + 1):
        result.rounds = round_no
        if verbose:
            print(f"[{report_id}] 第 {round_no}/{config.max_rounds} 轮抽取 ...")

        extraction = extract(report_id, context, feedback)
        result.extraction = extraction

        # 抽取模型自己认怂 -> 直接 abstain，不再浪费审核轮次
        if extraction.abstain:
            result.abstained = True
            evolution.append({
                "report_id": report_id, "round": round_no, "event": "extractor_abstain",
                "passed": False, "abstained": True, "reason": extraction.reason,
            })
            if verbose:
                print(f"[{report_id}] 抽取模型放弃：{extraction.reason}")
            return result

        if verbose:
            print(f"[{report_id}] 抽到 {len(extraction.rows)} 行，送审核 ...")

        c = critique(report_id, context, extraction)
        result.critiques.append(c)
        result.best_score = max(result.best_score, c.score)

        evolution.append({
            "report_id": report_id, "round": round_no, "event": "critique",
            "score": c.score, "passed": c.passed, "abstained": c.should_abstain,
            "issues": c.issues, "row_count": len(extraction.rows),
        })
        if verbose:
            print(f"[{report_id}] 审核得分 {c.score}/10，问题 {len(c.issues)} 条")

        # 达标 -> 收工
        if c.passed:
            result.passed = True
            return result

        # 未达标 -> 带着意见进入下一轮
        feedback = format_feedback(c)

    # ---- 3) 轮数耗尽 ----
    result.abstained = True
    result.extraction.abstain = True
    result.extraction.reason = (
        f"经过 {config.max_rounds} 轮仍未达到 {config.pass_score} 分"
        f"（最高 {result.best_score} 分），转人工复核"
    )
    evolution.append({
        "report_id": report_id, "round": result.rounds, "event": "exhausted",
        "passed": False, "abstained": True, "best_score": result.best_score,
    })
    if verbose:
        print(f"[{report_id}] {config.max_rounds} 轮未达标，abstain（转人工）")
    return result


def run_all(pdf_dir: str | Path | None = None, verbose: bool = True) -> list[LoopResult]:
    """对目录下所有 PDF 依次执行。"""
    from .config import PDF_DIR

    folder = Path(pdf_dir or PDF_DIR)
    files = sorted(folder.glob("*.pdf"))
    if not files:
        print(f"目录 {folder} 下没有 PDF，请先把 NI 43-101 报告放进去。")
        return []
    return [run_one(f, verbose=verbose) for f in files]
