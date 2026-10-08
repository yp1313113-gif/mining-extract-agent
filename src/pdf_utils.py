"""PDF 解析：把 NI 43-101 报告转成「带页码的文本」，并定位资源量章节。

为什么不用表格识别库直接抽表：
    NI 43-101 的资源量表格版式差异极大（跨页、合并单元格、脚注混排），
    硬解析表格的鲁棒性远不如「把相关页文本交给模型 + 要求给原文引用」。
    本模块只负责「找到对的地方」并把原文喂给模型。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF


# 资源量章节的关键词（英文报告为主，兼容少量中文）
RESOURCE_KEYWORDS = [
    "mineral resource", "indicated", "inferred", "measured",
    "tonnage", "grade", "contained metal",
    "矿产资源", "控制的", "推断的",
]


def extract_pages(pdf_path: str | Path) -> list[str]:
    """返回逐页文本，索引 i 对应第 i+1 页。"""
    doc = fitz.open(str(pdf_path))
    try:
        return [page.get_text("text") for page in doc]
    finally:
        doc.close()


# 目录页特征：大量点线引导符，或密集的 "Table x-y" 交叉引用
_TOC_DOTS = re.compile(r"\.{4,}")
_TOC_TABLEREF = re.compile(r"table\s+\d+-\d+", re.I)
# 真实数据特征：千分位数字、带小数的数值
_NUM_GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_NUM_DECIMAL = re.compile(r"\d+\.\d+")


def is_toc_page(text: str) -> bool:
    """判断一页是否为目录 / 图表清单页。

    这类页面会大量出现 "Table 1-1: ..." 这样的标题和点线引导符，
    关键词得分很高，但**不含任何真实数据** —— 是最容易骗过朴素关键词匹配的干扰项。
    """
    return len(_TOC_DOTS.findall(text)) >= 20 or len(_TOC_TABLEREF.findall(text)) >= 8


# 资源量报表的「专属措辞」—— 出现即强烈提示这页就是资源表
STATEMENT_PHRASES = [
    "mineral resource statement",
    "total inferred",
    "total indicated",
    "total measured",
    "measured and indicated",
    "at a cut-off grade",
    "at a cutoff grade",
    "contained metal",
    "contained au",
    "contained oz",
    "mineral resource estimate",
    "mineral resources are reported",
    "resources are exclusive of reserves",
]


def page_score(text: str) -> int:
    """给一页打分，目录页直接判零。

    为什么不能只数关键词，也不能只数数字：
        在真实报告上的两次失败都记在这里 ——
        (1) Newmont Ahafo：纯关键词匹配把「图表清单页」排到最高分，它含全部表名却零数字；
            加入数字密度后修复。
        (2) Barrick Pueblo Viejo：改成数字密度后，**冶金/工厂性能表**的数字比资源表还多，
            于是资源表被挤到第 8、9 名之外，直接漏掉。
        最终判据以「资源表专属措辞」为主（一页出现多个专属短语，几乎可以确定就是资源表），
        数字密度只作为次要加权。
    """
    low = text.lower()
    kws = sum(1 for kw in RESOURCE_KEYWORDS if kw in low)
    if kws == 0:
        return 0
    if is_toc_page(text):
        return 0

    # 主信号：资源表专属措辞（每个 +25）
    phrases = sum(1 for ph in STATEMENT_PHRASES if ph in low)
    # 次信号：数字密度（弱加权，避免工厂数据表喧宾夺主）
    grouped = len(_NUM_GROUPED.findall(text))
    decimals = len(_NUM_DECIMAL.findall(text))

    return phrases * 25 + kws * 2 + min(grouped, 15) + min(decimals, 15)


def locate_resource_pages(
    pages: list[str],
    top_k: int = 6,
    window: int = 1,
    min_score: int = 2,
) -> list[int]:
    """定位资源量相关页，返回 1-based 页码列表（含前后各 window 页做上下文）。

    与朴素实现的关键差别：**按得分取前 top_k 页**，而不是「所有命中页」。
    报告动辄数百页，命中页可能有几十页，全塞进去既贵又会淹掉真正的表格页。
    """
    scored = [(i, page_score(t)) for i, t in enumerate(pages)]
    ranked = sorted(((i, s) for i, s in scored if s >= min_score), key=lambda x: -x[1])

    if not ranked:
        # 兜底：关键词一个都没命中时，退化为按数字密度选页
        fallback = sorted(
            ((i, len(_NUM_GROUPED.findall(t))) for i, t in enumerate(pages)),
            key=lambda x: -x[1],
        )
        ranked = [x for x in fallback if x[1] > 0][:top_k]
        if not ranked:
            return []

    chosen: set[int] = set()
    for i, _ in ranked[:top_k]:
        for j in range(max(0, i - window), min(len(pages), i + window + 1)):
            chosen.add(j)
    return sorted(i + 1 for i in chosen)


def build_context(pages: list[str], page_numbers: list[int], max_chars: int = 60000) -> str:
    """把选中的页拼成带页码标记的上下文，超长时按页截断。"""
    chunks: list[str] = []
    used = 0
    for pno in page_numbers:
        if pno - 1 >= len(pages):
            continue
        body = pages[pno - 1].strip()
        if not body:
            continue
        block = f"\n<<<PAGE {pno}>>>\n{body}\n"
        if used + len(block) > max_chars:
            remain = max_chars - used
            if remain > 500:
                chunks.append(block[:remain] + "\n...[本页截断]")
            break
        chunks.append(block)
        used += len(block)
    return "".join(chunks)


def pdf_name_to_id(pdf_path: str | Path) -> str:
    """文件名去扩展名，作为报告 ID。"""
    return Path(pdf_path).stem
