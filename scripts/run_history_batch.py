#!/usr/bin/env python3
"""
兼容入口：随机抽取 N 个军事史子主题批量挖掘。

推荐改用功能更全的 run_military_history_batch.py，例如::

    python scripts/run_military_history_batch.py --sample 5 --seed 20260519
"""
from __future__ import annotations

import asyncio
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scripts.run_military_history_batch import run_batch, _select_tasks


async def _legacy_random_batch(seed: int, count: int):
    tasks = _select_tasks(
        run_all=False,
        category=None,
        topics=None,
        sample=count,
        seed=seed,
        task_ids=None,
    )
    return await run_batch(tasks, seed=seed)


if __name__ == "__main__":
    seed = int(os.getenv("MA4CD_BATCH_SEED", "20260519"))
    count = int(os.getenv("MA4CD_BATCH_COUNT", "5"))
    asyncio.run(_legacy_random_batch(seed=seed, count=count))
