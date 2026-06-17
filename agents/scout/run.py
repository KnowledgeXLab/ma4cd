#!/usr/bin/env python3
"""Scout Agent 独立测试入口（对接当前 ScoutAgent API）。"""
import argparse
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

import utils.env  # noqa: F401

from agents.scout.agent import ScoutAgent
from utils.env import get_llm_api_key, get_llm_base_url


def parse_args():
    parser = argparse.ArgumentParser(description="Scout Agent 测试运行")
    parser.add_argument(
        "task",
        nargs="?",
        default="蛋白质研究开放数据集",
        help="侦察任务描述",
    )
    parser.add_argument("--session-id", default="scout-cli-test", help="Session ID")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出 URL 列表")
    parser.add_argument("--limit", type=int, default=20, help="控制台最多展示 URL 条数")
    return parser.parse_args()


def main():
    args = parse_args()

    if not get_llm_api_key() or not get_llm_base_url():
        print("错误：请配置 OPENAI_API_KEY / OPENAI_BASE_URL（或 MA4CD_LLM_*）")
        sys.exit(1)

    print("=" * 80)
    print("MA4CD Scout Agent 测试运行")
    print("=" * 80)
    print(f"任务: {args.task}")
    print(f"Session: {args.session_id}")
    print("-" * 80)

    scout = ScoutAgent()
    urls = scout.run(args.task, config={}, session_id=args.session_id)
    urls = [u for u in urls if isinstance(u, str) and u.startswith("http")]

    if args.json:
        print(json.dumps(urls, indent=2, ensure_ascii=False))
        return

    print(f"\n找到 {len(urls)} 个 URL")
    for i, url in enumerate(urls[: args.limit], 1):
        print(f"  {i:3d}. {url}")
    if len(urls) > args.limit:
        print(f"  ... 还有 {len(urls) - args.limit} 条未显示（可用 --limit 调整）")


if __name__ == "__main__":
    main()
