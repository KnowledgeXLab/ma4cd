#!/usr/bin/env python3
"""
MA4CD 军事分类表批量挖掘（三级关键词，携带一级/二级标题）

默认跑 TSV 中**前 100 个**三级关键词（按文件顺序，从「主战坦克」起）。

用法（在 ma4cd_now 根目录）::

    # 预览前 100 题（不跑流水线）
    python scripts/run_taxonomy_batch.py --dry-run

    # 列出前 100 题
    python scripts/run_taxonomy_batch.py --list

    # 正式开跑（建议 tmux / nohup）
    python scripts/run_taxonomy_batch.py

    # 从第 20 题续跑
    python scripts/run_taxonomy_batch.py --start-from 20

    # 改数量：前 50 题 / 跳过前 10 条再取 20 条
    python scripts/run_taxonomy_batch.py --limit 50
    python scripts/run_taxonomy_batch.py --offset 10 --limit 20

    # 导出任务清单 JSON（不跑流水线）
    python scripts/run_taxonomy_batch.py --export-manifest

环境变量::

    MA4CD_INSPECTOR_STRICT=1
    PLAYWRIGHT_BROWSERS_PATH=/home/zhuyao/.cache/ms-playwright

输出::

    reports/batch_taxonomy_<时间戳>.json
    reports/taxonomy_batch.log
    data/taxonomy_batch_manifest.json  （--export-manifest 时写入）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Iterable

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import utils.env  # noqa: F401

from main_workflow import MA4CDPipeline
from scripts.military_taxonomy_loader import (
    DEFAULT_TSV,
    TaxonomyTask,
    load_taxonomy_tasks,
)


def _print_task_list(tasks: Iterable[TaxonomyTask], *, total_in_tsv: int) -> None:
    tasks = list(tasks)
    print(f"\n{'='*78}")
    print(f"军事分类表批量任务 | TSV 共 {total_in_tsv} 条三级词 | 本次选中 {len(tasks)} 条")
    print(f"{'='*78}")
    for i, t in enumerate(tasks, 1):
        print(f"  {i:3d}. [seq={t.seq}] {t.l1_zh} / {t.l2_zh} / {t.kw_zh}")
        print(f"       id={t.task_id} | en={t.kw_en}")
    print()


def _append_log(log_path: str, line: str) -> None:
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")


def _save_summary(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _task_row(i: int, task: TaxonomyTask, pipeline, audited, elapsed: float, error: str | None) -> dict:
    return {
        "batch_index": i,
        "seq": task.seq,
        "task_id": task.task_id,
        "l1_zh": task.l1_zh,
        "l1_en": task.l1_en,
        "l2_zh": task.l2_zh,
        "l2_en": task.l2_en,
        "kw_zh": task.kw_zh,
        "kw_en": task.kw_en,
        "query": task.query,
        "scout": pipeline.last_stats.get("scout", 0),
        "miner": pipeline.last_stats.get("miner", 0),
        "inspector_passed": len(audited or []),
        "elapsed_sec": round(elapsed, 1),
        "passed_urls": [(a.get("url") or "") for a in (audited or []) if a.get("url")],
        "sample_urls": [(a.get("url") or "")[:200] for a in (audited or [])[:8]],
        "error": error,
    }


async def run_batch(
    tasks: list[TaxonomyTask],
    *,
    start_from: int = 1,
    dry_run: bool = False,
    summary_path: str | None = None,
    log_path: str | None = None,
    tsv_path: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[dict]:
    if start_from < 1:
        raise SystemExit("--start-from 必须 >= 1")
    if start_from > len(tasks):
        raise SystemExit(f"--start-from={start_from} 超过任务数 {len(tasks)}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if summary_path is None:
        summary_path = os.path.join(project_root, "reports", f"batch_taxonomy_{stamp}.json")
    if log_path is None:
        log_path = os.path.join(project_root, "reports", "taxonomy_batch.log")

    payload: dict = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "project_root": project_root,
        "tsv_path": str(tsv_path or DEFAULT_TSV),
        "offset": offset,
        "limit": limit,
        "total_planned": len(tasks),
        "start_from": start_from,
        "tasks": [],
    }

    _print_task_list(tasks, total_in_tsv=337)
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

            header = (
                f"[{i}/{len(tasks)}] seq={task.seq} | "
                f"{task.l1_zh} / {task.l2_zh} / {task.kw_zh}"
            )
            print(f"\n{'='*60}\n{header}\n{'='*60}")
            print(task.query)
            print(f"{'='*60}\n")
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
                row = _task_row(i, task, pipeline, audited, elapsed, None)
            except Exception as e:
                elapsed = (datetime.now() - t0).total_seconds()
                row = _task_row(i, task, pipeline, [], elapsed, str(e))
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


def _export_manifest(tasks: list[TaxonomyTask], path: str) -> None:
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(tasks),
        "tasks": [t.to_dict() for t in tasks],
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"📄 任务清单已写入: {path}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="MA4CD 军事分类表批量挖掘（默认前 100 个三级关键词）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--tsv",
        default=str(DEFAULT_TSV),
        help=f"分类表 TSV 路径（默认 {DEFAULT_TSV}）",
    )
    p.add_argument(
        "--offset",
        type=int,
        default=0,
        help="跳过 TSV 中前 N 条三级关键词（默认 0）",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=100,
        help="最多运行条数（默认 100）",
    )
    p.add_argument(
        "--start-from",
        type=int,
        default=1,
        metavar="K",
        help="从本次任务列表第 K 题开始（断点续跑）",
    )
    p.add_argument("--list", action="store_true", help="列出将执行的任务并退出")
    p.add_argument("--dry-run", action="store_true", help="只打印任务，不调用 MA4CD")
    p.add_argument(
        "--export-manifest",
        action="store_true",
        help="将任务清单写入 data/taxonomy_batch_manifest.json 后退出",
    )
    p.add_argument("--output", metavar="PATH", help="指定摘要 JSON 路径")
    return p


def main() -> None:
    args = build_parser().parse_args()
    tasks = load_taxonomy_tasks(args.tsv, offset=args.offset, limit=args.limit)

    if not tasks:
        print("未加载到任何任务，请检查 --offset / --limit / --tsv")
        sys.exit(1)

    manifest_path = os.path.join(project_root, "data", "taxonomy_batch_manifest.json")

    if args.export_manifest:
        _export_manifest(tasks, manifest_path)
        return

    if args.list or args.dry_run:
        _print_task_list(tasks, total_in_tsv=337)
        if args.dry_run:
            print("(--dry-run) 未执行流水线\n")
            _export_manifest(tasks, manifest_path)
        return

    asyncio.run(
        run_batch(
            tasks,
            start_from=args.start_from,
            dry_run=False,
            summary_path=args.output,
            tsv_path=args.tsv,
            offset=args.offset,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
