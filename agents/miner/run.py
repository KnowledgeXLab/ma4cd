#!/usr/bin/env python3
"""Miner Agent 独立测试入口（对接 UniversalMinerAgent）。"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

import utils.env  # noqa: F401  # loads `.env` before agents read env vars

from agents.miner.agent import UniversalMinerAgent
from agents.miner.memory.managers.memory_manager import get_unified_memory

TEST_CASES = {
    "1": ("世界银行开放数据", "https://data.worldbank.org/"),
    "2": ("美国人口普查局", "https://data.census.gov/"),
    "3": ("欧盟统计局 Eurostat", "https://ec.europa.eu/eurostat/data/database"),
    "4": ("联合国数据", "http://data.un.org/"),
    "5": ("经合组织 OECD", "https://data.oecd.org/"),
    "6": ("中国国家统计局", "https://data.stats.gov.cn/"),
}


def parse_args():
    parser = argparse.ArgumentParser(description="Miner Agent 单 URL 深挖测试")
    parser.add_argument(
        "--case",
        choices=sorted(TEST_CASES.keys()),
        default="1",
        help="预设测试用例编号（默认 1）",
    )
    parser.add_argument("--url", help="自定义目标 URL（指定后忽略 --case）")
    parser.add_argument("--query", default="", help="挖掘任务描述（自定义 URL 时建议填写）")
    return parser.parse_args()


async def main():
    args = parse_args()

    if args.url:
        name = args.query or f"miner-run: {args.url}"
        url = args.url.strip()
    else:
        name, url = TEST_CASES[args.case]

    print(f"开始测试: {name}")
    print(f"目标 URL: {url}")
    print("=" * 80)

    miner = UniversalMinerAgent()
    memory = get_unified_memory()
    session_id = memory.start_session({"task_intent": name})

    try:
        results = await miner.mine_urls([url], user_query=name, session_id=session_id)
        print("=" * 80)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        count = len(results) if isinstance(results, list) else 0
        print("=" * 80)
        print(f"完成：共产出 {count} 条挖掘结果")
    finally:
        memory.end_session(session_id)


if __name__ == "__main__":
    asyncio.run(main())
