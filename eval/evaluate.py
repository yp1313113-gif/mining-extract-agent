"""评测：字段级 accuracy（容差 ±5%）+ abstain 判定正确性。

评测口径：
  1. 把抽取结果与 ground truth 按 (category) 对齐成行；
  2. 对每个数值字段计算相对误差，误差 <= TOLERANCE 记为命中；
     grade_unit / contained_unit 这类文本字段要求完全一致（去空格、统一大小写）；
  3. field_accuracy = 命中字段数 / ground truth 字段总数；
  4. abstain 正确性单独统计 ——
        ground truth 有数据、系统 abstain  -> 漏报（miss）
        ground truth 无数据、系统给了数字  -> 幻觉（hallucination，最严重）
        ground truth 无数据、系统 abstain  -> 正确拒答
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import GROUND_TRUTH, config  # noqa: E402

# 需要按数值比较的字段
NUMERIC_FIELDS = ["tonnage_Mt", "grade_value", "contained_metal"]
# 需要按文本比较的字段
TEXT_FIELDS = ["grade_unit", "contained_unit"]


def load_ground_truth(path: Path | None = None) -> dict:
    p = Path(path or GROUND_TRUTH)
    if not p.exists():
        raise SystemExit(f"找不到 ground truth 文件：{p}")
    return json.loads(p.read_text(encoding="utf-8"))


def rel_ok(expected: float, actual: float | None, tol: float) -> bool:
    """相对误差在容差内记为命中。expected 为 0 时退化用绝对误差。"""
    if actual is None:
        return False
    if expected == 0:
        return abs(actual) <= tol
    return abs(actual - expected) / abs(expected) <= tol


# 单位里常见的「矿种后缀」——比对时应忽略，否则 "Moz" 与 "Moz Au" 会被判为不一致。
# 注意用「剥尾部」而不是「词边界匹配」：去空格后得到的是 "mozau"，矿种是紧贴的。
_COMMODITY_SUFFIX = re.compile(r"(au|ag|cu|li|fe|zn|pb|ni|sn|mo|co)$", re.I)


def normalize_text(value) -> str:
    """规范化单位文本：去空格、小写、剥掉矿种后缀。

    真实报告里同一个单位有 "Moz" / "Moz Au" / "million ounces Au" 等多种写法，
    严格字符串比对会把语义相同的写法判成错误 —— 那是评测器的缺陷，不是抽取的缺陷。
    """
    text = str(value or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    if not text:
        return ""
    # 反复剥尾部矿种（"mozau" -> "moz"；"g/tau" -> "g/t"）
    for _ in range(3):
        new = _COMMODITY_SUFFIX.sub("", text)
        if new == text or not new:
            break
        text = new
    return text


def compare_rows(expected_rows: list[dict], actual_rows: list[dict], tol: float) -> dict:
    """按 category 对齐行，逐字段比对。"""
    def by_cat(rows: list[dict]) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for r in rows:
            key = str(r.get("category", "")).strip().lower()
            out.setdefault(key, []).append(r)
        return out

    exp_map = by_cat(expected_rows)
    act_map = by_cat(actual_rows)

    hits = 0
    total = 0
    details: list[dict] = []

    for cat, exp_list in exp_map.items():
        act_list = act_map.get(cat, [])
        # 同一类别内按出现顺序配对（典型的报告每类只有一行）
        for i, exp in enumerate(exp_list):
            act = act_list[i] if i < len(act_list) else {}
            for f in NUMERIC_FIELDS:
                if exp.get(f) is None:
                    continue
                total += 1
                ok = rel_ok(float(exp[f]), act.get(f), tol)
                hits += int(ok)
                details.append({"category": cat, "field": f, "expected": exp[f],
                                "actual": act.get(f), "hit": ok})
            for f in TEXT_FIELDS:
                if not exp.get(f):
                    continue
                total += 1
                ok = normalize_text(exp[f]) == normalize_text(act.get(f))
                hits += int(ok)
                details.append({"category": cat, "field": f, "expected": exp[f],
                                "actual": act.get(f), "hit": ok})

    # 多抽的行（ground truth 里没有的类别）也算错误
    for cat in act_map:
        if cat not in exp_map:
            total += 1 * len(NUMERIC_FIELDS)
            details.append({"category": cat, "field": "*", "expected": "该类别不存在",
                            "actual": "模型自行新增", "hit": False})

    return {
        "fields_total": total,
        "fields_hit": hits,
        "field_accuracy": round(hits / total, 4) if total else 0.0,
        "details": details,
    }


def run_eval(gt_path: Path | None = None, result_path: Path | None = None,
             tolerance: float | None = None) -> dict:
    tol = tolerance if tolerance is not None else config.tolerance
    gt = load_ground_truth(gt_path)

    rp = Path(result_path or (config.output_dir / "result.json"))
    if not rp.exists():
        raise SystemExit(f"找不到抽取结果：{rp}（先跑 python main.py run）")
    results = {r["report_id"]: r for r in json.loads(rp.read_text(encoding="utf-8"))}

    per_report: list[dict] = []
    abstain_stats = {"correct_abstain": 0, "miss": 0, "hallucination": 0}

    for report_id, truth in gt.items():
        # 跳过以下划线开头的说明性字段（如 _说明），它们不是报告
        if report_id.startswith("_") or not isinstance(truth, dict):
            continue
        got = results.get(report_id)
        expected_rows = truth.get("rows", [])
        if got is None:
            per_report.append({"report_id": report_id, "error": "没有抽取结果"})
            continue

        system_abstained = bool(got.get("abstained"))
        has_truth = len(expected_rows) > 0

        # abstain 正确性
        if not has_truth and system_abstained:
            abstain_stats["correct_abstain"] += 1
        elif has_truth and system_abstained:
            abstain_stats["miss"] += 1
        elif not has_truth and not system_abstained:
            abstain_stats["hallucination"] += 1

        cmp = compare_rows(expected_rows, got["extraction"].get("rows", []), tol)
        per_report.append({
            "report_id": report_id,
            "passed": got.get("passed"),
            "system_abstained": system_abstained,
            "rounds": got.get("rounds"),
            "scores": got.get("scores"),
            **cmp,
        })

    # 正确 abstain 的用例（ground truth 无数据、系统也拒答）没有字段可比，
    # 不应拉低字段级 accuracy，单独用 abstain 指标衡量即可。
    scored = [
        r for r in per_report
        if "field_accuracy" in r and not (r.get("system_abstained") and r.get("fields_total", 0) == 0)
    ]
    overall = round(sum(r["field_accuracy"] for r in scored) / len(scored), 4) if scored else 0.0

    return {
        "tolerance": tol,
        "overall_field_accuracy": overall,
        "abstain": abstain_stats,
        "per_report": per_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="评测抽取结果")
    parser.add_argument("--gt", type=str, default=None, help="ground truth JSON 路径")
    parser.add_argument("--result", type=str, default=None, help="result.json 路径")
    args = parser.parse_args()

    report = run_eval(Path(args.gt) if args.gt else None,
                      Path(args.result) if args.result else None)

    print("=" * 60)
    print("评测报告")
    print("=" * 60)
    print(f"容差            : ±{report['tolerance'] * 100:.0f}%")
    print(f"字段级 accuracy : {report['overall_field_accuracy'] * 100:.2f}%")
    print(f"abstain 统计     : 正确拒答 {report['abstain']['correct_abstain']} | "
          f"漏报 {report['abstain']['miss']} | 幻觉 {report['abstain']['hallucination']}")
    print("-" * 60)
    for r in report["per_report"]:
        if "field_accuracy" in r:
            print(f"  {r['report_id']:<38} acc={r['field_accuracy'] * 100:6.2f}%  "
                  f"轮数={r['rounds']} 分数={r['scores']}")
        else:
            print(f"  {r['report_id']:<38} {r.get('error')}")
    print("=" * 60)

    out = config.output_dir / "eval_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"明细已写入：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
