"""
从 data/military_taxonomy_338.tsv 加载三级关键词任务，并生成带一级/二级语境的 Commander 查询文本。
"""
from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

DEFAULT_TSV = Path(__file__).resolve().parent.parent / "data" / "military_taxonomy_338.tsv"


@dataclass(frozen=True)
class TaxonomyTask:
    """单条三级关键词任务（含完整分类路径）。"""

    seq: int  # TSV 中的顺序号，从 1 开始
    task_id: str
    l1_zh: str
    l1_en: str
    l2_zh: str
    l2_en: str
    kw_zh: str
    kw_en: str
    query: str

    def to_dict(self) -> dict:
        return asdict(self)


def _slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return (s[:max_len] or "keyword").rstrip("_")


def build_mission_query(
    l1_zh: str,
    l1_en: str,
    l2_zh: str,
    l2_en: str,
    kw_zh: str,
    kw_en: str,
) -> str:
    """
    将一级、二级、三级分类写入 user_requirement，供 Commander / Scout / Inspector 全链路使用。
    """
    return (
        "【任务分类】\n"
        f"一级分类：{l1_zh}（{l1_en}）\n"
        f"二级分类：{l2_zh}（{l2_en}）\n"
        f"三级关键词：{kw_zh}（{kw_en}）\n"
        "\n"
        "【挖掘目标】\n"
        f"在以上分类语境下，搜索与「{kw_zh} / {kw_en}」相关的可复用军事数据容器："
        "技术参数数据库、装备档案门户、博物馆/军方开放目录、政府或研究机构数据集、"
        "Finding Aid、冲突/演训数据平台等（优先 L2–L4 线索）。\n"
        "请避免：新闻稿、电商、培训课程、招聘、百科词条首页、社交媒体帖子。"
    )


def load_taxonomy_tasks(
    tsv_path: Path | str | None = None,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> list[TaxonomyTask]:
    """
    按 TSV 文件顺序加载任务。

    :param offset: 跳过前 N 条（0 表示从第一条开始）
    :param limit: 最多加载条数；None 表示直到文件结束
    """
    path = Path(tsv_path) if tsv_path else DEFAULT_TSV
    if not path.is_file():
        raise FileNotFoundError(f"分类表不存在: {path}")

    rows: list[TaxonomyTask] = []
    l1_zh = l1_en = l2_zh = l2_en = ""
    seq = 0

    with path.open(encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        next(reader)  # header
        for r in reader:
            if len(r) < 6:
                r = r + [""] * (6 - len(r))
            if r[0].strip():
                l1_zh, l1_en = r[0].strip(), r[1].strip()
            if r[2].strip():
                l2_zh, l2_en = r[2].strip(), r[3].strip()
            kw_zh, kw_en = r[4].strip(), r[5].strip()
            if not kw_zh:
                continue
            seq += 1
            if seq <= offset:
                continue
            task_id = f"tax_{seq:03d}_{_slug(kw_en)}"
            rows.append(
                TaxonomyTask(
                    seq=seq,
                    task_id=task_id,
                    l1_zh=l1_zh,
                    l1_en=l1_en,
                    l2_zh=l2_zh,
                    l2_en=l2_en,
                    kw_zh=kw_zh,
                    kw_en=kw_en,
                    query=build_mission_query(l1_zh, l1_en, l2_zh, l2_en, kw_zh, kw_en),
                )
            )
            if limit is not None and len(rows) >= limit:
                break

    return rows


def iter_l1_counts(tasks: Iterator[TaxonomyTask]) -> dict[str, int]:
    from collections import Counter

    c: Counter[str] = Counter()
    for t in tasks:
        c[t.l1_zh] += 1
    return dict(c)
