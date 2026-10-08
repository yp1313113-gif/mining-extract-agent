"""集中配置：所有参数从环境变量 / .env 读取，代码里不出现任何密钥。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PDF_DIR = DATA_DIR / "pdfs"
OUTPUT_DIR = ROOT / "outputs"
EVOLUTION_LOG = ROOT / "evolution.jsonl"
GROUND_TRUTH = DATA_DIR / "ground_truth.json"


class Config:
    """运行期配置。构造时读取环境变量，方便测试里 monkeypatch。"""

    def __init__(self) -> None:
        # ---- 抽取模型 ----
        self.extractor_base_url = os.getenv("EXTRACTOR_BASE_URL", "https://api.deepseek.com")
        self.extractor_api_key = os.getenv("EXTRACTOR_API_KEY", "")
        self.extractor_model = os.getenv("EXTRACTOR_MODEL", "deepseek-flash")

        # ---- 审核模型 ----
        self.critic_base_url = os.getenv("CRITIC_BASE_URL", "https://api.deepseek.com")
        self.critic_api_key = os.getenv("CRITIC_API_KEY", "")
        self.critic_model = os.getenv("CRITIC_MODEL", "deepseek-v4-pro")

        # ---- 对抗循环 ----
        self.max_rounds = int(os.getenv("MAX_ROUNDS", "3"))
        self.pass_score = int(os.getenv("PASS_SCORE", "8"))
        self.tolerance = float(os.getenv("ACCURACY_TOLERANCE", "0.05"))

        # ---- 成本控制 ----
        # 思考模式会让模型先花掉大量推理 token（实测单次 16000+），
        # 对「结构化抽取」这类任务收益很低，默认关闭。
        self.thinking_enabled = os.getenv("THINKING_ENABLED", "false").lower() == "true"
        # 喂给模型的页数上限与上下文字符上限 —— 直接决定每次调用的成本
        self.top_k_pages = int(os.getenv("TOP_K_PAGES", "3"))
        self.max_context_chars = int(os.getenv("MAX_CONTEXT_CHARS", "30000"))

        # ---- 路径 ----
        self.pdf_dir = PDF_DIR
        self.output_dir = OUTPUT_DIR

    def require_keys(self) -> None:
        """开跑前检查 key，缺失时给出清晰报错而不是半路失败。"""
        missing = []
        if not self.extractor_api_key:
            missing.append("EXTRACTOR_API_KEY")
        if not self.critic_api_key:
            missing.append("CRITIC_API_KEY")
        if missing:
            raise SystemExit(
                "缺少环境变量：" + ", ".join(missing) + "\n"
                "请复制 .env.example 为 .env 并填入密钥。"
            )


config = Config()
