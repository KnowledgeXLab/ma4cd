#!/usr/bin/env python3
"""
MA4CD 军事史批量挖掘（非交互）

任务目录见 scripts/military_history_catalog.py（18 个子主题）。

用法示例（在 ma4cd_now 根目录执行）::

    # 列出全部任务
    python scripts/run_military_history_batch.py --list

    # 跑完全部 18 题（预计数小时，建议 nohup / tmux）
    python scripts/run_military_history_batch.py --all

    # 只跑战争史 14 题 / 只跑技术发展史 4 题
    python scripts/run_military_history_batch.py --category war
    python scripts/run_military_history_batch.py --category tech

    # 指定子主题（中文名，逗号分隔）
    python scripts/run_military_history_batch.py --topics 中东战争,坦克进化史,俄乌战争

    # 随机抽 5 题（可复现）
    python scripts/run_military_history_batch.py --sample 5 --seed 20260519

    # 从第 3 题继续（断点续跑，配合 --all 或 --category）
    python scripts/run_military_history_batch.py --all --start-from 3

    # 只看将执行哪些任务，不调用流水线
    python scripts/run_military_history_batch.py --all --dry-run

环境变量（可选）::

    MA4CD_BATCH_SEED=20260519          # --sample 时默认种子
    MA4CD_INSPECTOR_STRICT=1           # Inspector 严格模式（默认建议开启）
    PLAYWRIGHT_BROWSERS_PATH=...       # Miner 浏览器路径

输出::

    reports/batch_military_history_<时间戳>.json   # 增量写入，中断可保留已完成任务
    reports/military_history_batch.log             # 简要文本日志
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from datetime import datetime
from typing import Iterable

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import utils.env  # noqa: F401

from main_workflow import MA4CDPipeline
from scripts.military_history_catalog import (
    MILITARY_HISTORY_CATALOG,
    TASK_BY_ID,
    TASK_BY_SUBTOPIC,
    MilitaryHistoryTask,
)


def _select_tasks(
    *,
    run_all: bool,
    category: str | None,
    topics: list[str] | None,
    sample: int | None,
    seed: int | None,
    task_ids: list[str] | None,
) -> list[MilitaryHistoryTask]:
    pool = list(MILITARY_HISTORY_CATALOG)

    if task_ids:
        out: list[MilitaryHistoryTask] = []
        for tid in task_ids:
            if tid not in TASK_BY_ID:
                raise SystemExit(f"未知 task_id: {tid}，可用: {', '.join(TASK_BY_ID)}")
            out.append(TASK_BY_ID[tid])
        return out

    if topics:
        out = []
        for name in topics:
            name = name.strip()
            if not name:
                continue
            if name not in TASK_BY_SUBTOPIC:
                raise SystemExit(
                    f"未知子主题: {name}\n"
                    f"可用: {', '.join(TASK_BY_SUBTOPIC)}"
                )
            out.append(TASK_BY_SUBTOPIC[name])
        return out

    if category:
        ck = category.strip().lower()
        alias = {"战争史": "war", "war": "war", "w": "war",
                 "技术发展史": "tech", "tech": "tech", "t": "tech"}
        if ck not in alias:
            raise SystemExit("--category 应为 war / tech（或 战争史 / 技术发展史）")
        pool = [t for t in pool if t.category_kind == alias[ck]]

    if sample is not None and sample > 0:
        if not run_all and not category and not topics:
            rng = random.Random(seed)
            return rng.sample(pool, min(sample, len(pool)))
        # --all/--category 与 --sample 同时出现时，sample 表示从已选池中再抽 N 题
        rng = random.Random(seed)
        return rng.sample(pool, min(sample, len(pool)))

    if run_all or category:
        return pool

    return []


def _print_task_list(tasks: Iterable[MilitaryHistoryTask]) -> None:
    print(f"\n{'='*72}")
    print(f"军事史任务目录 | 共 {len(MILITARY_HISTORY_CATALOG)} 题 | 本次选中 {len(list(tasks))} 题")
    print(f"{'='*72}")
    tasks = list(tasks)
    for i, t in enumerate(tasks, 1):
        print(f"  {i:2d}. [{t.category_kind}] {t.subtopic}  ({t.task_id})")
        print(f"      {t.query}")
    print()


def _append_log(log_path: str, line: str) -> None:
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")


def _save_summary(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


async def run_batch(
    tasks: list[MilitaryHistoryTask],
    *,
    start_from: int = 1,
    dry_run: bool = False,
    summary_path: str | None = None,
    log_path: str | None = None,
    seed: int | None = None,
) -> list[dict]:
    if start_from < 1:
        raise SystemExit("--start-from 必须 >= 1")
    if start_from > len(tasks):
        raise SystemExit(f"--start-from={start_from} 超过任务数 {len(tasks)}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if summary_path is None:
        summary_path = os.path.join(
            project_root, "reports", f"batch_military_history_{stamp}.json"
        )
    if log_path is None:
        log_path = os.path.join(project_root, "reports", "military_history_batch.log")

    payload: dict = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "project_root": project_root,
        "seed": seed,
        "total_planned": len(tasks),
        "start_from": start_from,
        "tasks": [],
    }

    _print_task_list(tasks)
    if dry_run:
        print("(--dry-run) 未执行流水线\n")
        return []

    print(f"摘要 JSON: {summary_path}")
    print(f"文本日志: {log_path}\n")

    pipeline = MA4CDPipeline()
    results: list[dict] = []

    try:
        for i, task in enumerate(tasks, 1):
            if i < start_from:
                continue

            header = f"[{i}/{len(tasks)}] {task.category_zh} / {task.subtopic}"
            print(f"\n{'='*60}\n{header}\n查询: {task.query}\n{'='*60}\n")
            _append_log(log_path, f"{datetime.now().isoformat()} START {header}")

            t0 = datetime.now()
            try:
                audited = await pipeline._run_pipeline_once(
                    task.query,
                    show_history_related=False,
                    history_max_total=0,
                    history_include_current_run=False,
                )
                elapsed = (datetime.now() - t0).total_seconds()
                report_guess = os.path.join(
                    project_root,
                    "reports",
                )
                row = {
                    "index": i,
                    "task_id": task.task_id,
                    "domain_zh": task.domain_zh,
                    "domain_en": task.domain_en,
                    "category": task.category_zh,
                    "category_en": task.category_en,
                    "category_kind": task.category_kind,
                    "subtopic": task.subtopic,
                    "query": task.query,
                    "scout": pipeline.last_stats.get("scout", 0),
                    "miner": pipeline.last_stats.get("miner", 0),
                    "inspector_passed": len(audited or []),
                    "elapsed_sec": round(elapsed, 1),
                    "passed_urls": [
                        (a.get("url") or "") for a in (audited or []) if a.get("url")
                    ],
                    "sample_urls": [
                        (a.get("url") or "")[:200] for a in (audited or [])[:8]
                    ],
                    "error": None,
                }
            except Exception as e:
                elapsed = (datetime.now() - t0).total_seconds()
                row = {
                    "index": i,
                    "task_id": task.task_id,
                    "domain_zh": task.domain_zh,
                    "domain_en": task.domain_en,
                    "category": task.category_zh,
                    "category_en": task.category_en,
                    "category_kind": task.category_kind,
                    "subtopic": task.subtopic,
                    "query": task.query,
                    "scout": pipeline.last_stats.get("scout", 0),
                    "miner": pipeline.last_stats.get("miner", 0),
                    "inspector_passed": 0,
                    "elapsed_sec": round(elapsed, 1),
                    "passed_urls": [],
                    "sample_urls": [],
                    "error": str(e),
                }
                print(f"❌ 任务失败: {e}")

            results.append(row)
            payload["tasks"] = results
            payload["last_updated"] = datetime.now().isoformat(timespec="seconds")
            _save_summary(summary_path, payload)

            line = (
                f"完成: Scout({row['scout']}) -> Miner({row['miner']}) -> "
                f"Inspector({row['inspector_passed']}) | {row['elapsed_sec']}s"
            )
            print(line)
            _append_log(log_path, f"{datetime.now().isoformat()} DONE {header} | {line}")

    finally:
        await pipeline.close()

    payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
    payload["completed"] = len(results)
    _save_summary(summary_path, payload)

    total_passed = sum(r.get("inspector_passed", 0) for r in results)
    print(f"\n{'='*60}")
    print(f"批量结束 | 完成 {len(results)} 题 | Inspector 入库合计 {total_passed} 条")
    print(f"📄 {summary_path}")
    print(f"{'='*60}\n")
    return results


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="MA4CD 军事史批量挖掘（18 子主题，非交互）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--list", action="store_true", help="列出 catalog 中全部 18 题并退出"
    )
    mode.add_argument(
        "--all", action="store_true", help="运行全部 18 题"
    )
    mode.add_argument(
        "--category",
        choices=["war", "tech", "战争史", "技术发展史"],
        help="只跑战争史(14)或技术发展史(4)",
    )
    mode.add_argument(
        "--topics",
        metavar="NAME",
        help="指定子主题，逗号分隔，如: 中东战争,坦克进化史",
    )
    mode.add_argument(
        "--task-ids",
        metavar="ID",
        help="指定 task_id，逗号分隔，如: middle_east_wars,tank_evolution",
    )
    mode.add_argument(
        "--sample",
        type=int,
        metavar="N",
        help="从当前池中随机抽 N 题（配合 --seed）",
    )

    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="随机种子（默认 MA4CD_BATCH_SEED 或 20260519）",
    )
    p.add_argument(
        "--start-from",
        type=int,
        default=1,
        metavar="K",
        help="从第 K 题开始（断点续跑，按本次任务列表序号）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将执行的任务，不调用 MA4CD",
    )
    p.add_argument(
        "--output",
        metavar="PATH",
        help="指定摘要 JSON 路径（默认 reports/batch_military_history_<时间戳>.json）",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    seed = args.seed
    if seed is None and os.getenv("MA4CD_BATCH_SEED"):
        try:
            seed = int(os.getenv("MA4CD_BATCH_SEED", ""))
        except ValueError:
            seed = None

    if args.list:
        _print_task_list(MILITARY_HISTORY_CATALOG)
        return

    topics = None
    if args.topics:
        topics = [x.strip() for x in args.topics.split(",") if x.strip()]

    task_ids = None
    if args.task_ids:
        task_ids = [x.strip() for x in args.task_ids.split(",") if x.strip()]

    run_all = bool(args.all)
    if not run_all and not args.category and not topics and not task_ids and not args.sample:
        build_parser().print_help()
        print(
            "\n提示: 请指定 --all、--category、--topics、--task-ids 或 --sample N\n"
            "示例: python scripts/run_military_history_batch.py --all\n"
        )
        sys.exit(1)

    tasks = _select_tasks(
        run_all=run_all,
        category=args.category,
        topics=topics,
        sample=args.sample,
        seed=seed,
        task_ids=task_ids,
    )
    if not tasks:
        print("未选中任何任务。")
        sys.exit(1)

    asyncio.run(
        run_batch(
            tasks,
            start_from=args.start_from,
            dry_run=args.dry_run,
            summary_path=args.output,
            seed=seed,
        )
    )


if __name__ == "__main__":
    main()
