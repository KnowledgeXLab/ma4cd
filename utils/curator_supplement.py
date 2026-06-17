"""
Curator supplement skill — tactical Scout search for gap closure (domain config in YAML).
"""
from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import urlparse


def _load_raw() -> Dict[str, Any]:
    try:
        from utils.skill_loader import get_active_skill_id, load_curator_supplement
        if get_active_skill_id():
            return load_curator_supplement()
    except Exception:
        pass
    return {}


def _as_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def get_priority_sites() -> List[str]:
    raw = _load_raw()
    sites = _as_list(raw.get("priority_sites"))
    if sites:
        return sites
    try:
        from utils.search_discovery import authoritative_sites
        return authoritative_sites()[:10]
    except Exception:
        return []


def get_gap_query_seeds() -> List[str]:
    return _as_list(_load_raw().get("gap_query_seeds"))


def get_scout_prompt_append() -> str:
    return str(_load_raw().get("scout_prompt_append") or "").strip()


def rank_priority_urls(urls: List[str]) -> List[str]:
    raw = _load_raw()
    if not raw.get("rank_priority_sites_first", True):
        return list(urls)
    sites = [s.lower() for s in get_priority_sites()]
    if not sites:
        return list(urls)

    def _score(u: str) -> int:
        host = (urlparse(u).netloc or "").lower()
        for i, site in enumerate(sites):
            if host == site or host.endswith("." + site) or site in host:
                return len(sites) - i
        return 0

    return sorted(urls, key=_score, reverse=True)


def build_curator_supplement_task(
    user_requirement: str,
    gaps: List[str],
    directives: str = "",
) -> str:
    lines = [
        user_requirement.strip(),
        "",
        "[Curator 战术补搜] 请针对以下数据/学科盲区补充检索，优先 L1/L2 门户与 L3 数据库入口：",
    ]
    for g in (gaps or [])[:8]:
        lines.append(f"- {g}")
    if directives:
        lines.extend(["", f"战略指导: {directives}"])

    seeds = get_gap_query_seeds()
    sites = get_priority_sites()
    if seeds or sites:
        lines.extend(["", "[优先检索种子查询]（请据此生成搜索并返回 URL）"])
        for q in seeds[:8]:
            lines.append(f"- {q}")
        if sites:
            lines.append("")
            lines.append("优先站点: " + ", ".join(sites[:12]))
    return "\n".join(lines)
