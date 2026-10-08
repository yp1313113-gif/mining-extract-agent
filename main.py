"""命令行入口。

用法：
    python main.py run                 # 对 data/pdfs/ 下所有报告跑一遍
    python main.py run --pdf xxx.pdf   # 只跑一份
    python main.py stats               # 查看 evolution.jsonl 的复盘统计
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接 python main.py 运行（把项目根加入 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import evolution  # noqa: E402
from src.config import config  # noqa: E402
from src.loop import run_all, run_one  # noqa: E402


def cmd_run(args: argparse.Namespace) -> int:
    config.require_keys()
    config.output_dir.mkdir(parents=True, exist_ok=True)

    if args.pdf:
        results = [run_one(args.pdf, verbose=True)]
    else:
        results = run_all(verbose=True)

    if not results:
        return 1

    out = config.output_dir / "result.json"
    payload = [r.to_dict() for r in results]
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print("结果汇总")
    print("=" * 60)
    for r in results:
        flag = "通过" if r.passed else ("abstain" if r.abstained else "未通过")
        print(f"  {r.report_id:<40} {flag:<8} 轮数={r.rounds} 最高分={r.best_score}")
    print(f"\n明细已写入：{out}")
    return 0


def cmd_stats(_: argparse.Namespace) -> int:
    print(json.dumps(evolution.summarize(), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NI 43-101 资源量抽取（对抗审核）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="执行抽取")
    p_run.add_argument("--pdf", type=str, default=None, help="只跑指定的 PDF")
    p_run.set_defaults(func=cmd_run)

    p_stats = sub.add_parser("stats", help="查看进化日志统计")
    p_stats.set_defaults(func=cmd_stats)

    return parser


if __name__ == "__main__":
    parser = build_parser()
    ns = parser.parse_args()
    raise SystemExit(ns.func(ns))
