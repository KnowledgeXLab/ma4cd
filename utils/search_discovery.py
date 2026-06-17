"""
Search discovery skill rules — authoritative sites, query templates, search defaults.

Domain-specific sites and templates belong in skills/<id>/rules/search_discovery.yaml only.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Domain-neutral engine defaults (no skill): general web search only.
_BUILTIN_AUTHORITATIVE: List[str] = []
_BUILTIN_ACADEMIC = ["arxiv.org", "scholar.google.com"]
_BUILTIN_L3_TEMPLATES = [
    "{keyword} site:{domain} (download OR export OR dataset)",
    "{keyword} site:{domain} filetype:csv",
    "{keyword} site:{domain} (bulk OR api)",
]

_CACHE: Dict[str, Any] | None = None


def _load_raw() -> Dict[str, Any]:
    try:
        from utils.skill_loader import get_active_skill_id, load_search_discovery
        if get_active_skill_id():
            return load_search_discovery()
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


def _scout_domains() -> List[str]:
    try:
        from utils.scout_skill import get_scout_site_preferences
        prefs = get_scout_site_preferences()
        return _as_list((prefs or {}).get("domains"))
    except Exception:
        return []


def _miner_search_templates() -> List[str]:
    try:
        from utils.miner_signals import search_templates
        return search_templates()
    except Exception:
        return []


def reset_search_discovery_cache() -> None:
    global _CACHE
    _CACHE = None


def get_search_discovery_config() -> Dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    raw = _load_raw()
    limits = raw.get("search_limits") if isinstance(raw.get("search_limits"), dict) else {}

    sites = _as_list(raw.get("authoritative_sites"))
    if raw.get("merge_scout_site_preferences", True):
        for d in _scout_domains():
            if d not in sites:
                sites.append(d)

    templates = _as_list(raw.get("site_l3_query_templates"))
    if not templates:
        templates = _miner_search_templates() or list(_BUILTIN_L3_TEMPLATES)

    default_type = str(raw.get("default_search_type") or "general").strip() or "general"
    # Backward compat: legacy skill packs may use "biomedical"
    if default_type == "biomedical":
        default_type = "authoritative"

    _CACHE = {
        "default_search_type": default_type,
        "authoritative_sites": sites if sites else list(_BUILTIN_AUTHORITATIVE),
        "academic_sites": _as_list(raw.get("academic_sites")) or list(_BUILTIN_ACADEMIC),
        "site_l3_query_templates": templates,
        "dataset_search_boost": str(
            raw.get("dataset_search_boost")
            or "(dataset OR database OR repository OR download OR export)"
        ).strip(),
        "filetype_extensions": _as_list(raw.get("filetype_extensions")) or ["csv", "xlsx", "json", "xml"],
        "max_authoritative_sites": int(limits.get("max_authoritative_sites", 5) or 5),
        "results_per_site": int(limits.get("results_per_site", 2) or 2),
        "max_l3_results": int(limits.get("max_l3_results", 20) or 20),
        "max_l3_queries_per_keyword": int(limits.get("max_l3_queries_per_keyword", 4) or 4),
    }
    return _CACHE


def default_search_type() -> str:
    return get_search_discovery_config()["default_search_type"]


def authoritative_sites() -> List[str]:
    return list(get_search_discovery_config()["authoritative_sites"])


def academic_sites() -> List[str]:
    return list(get_search_discovery_config()["academic_sites"])


def site_l3_query_templates() -> List[str]:
    return list(get_search_discovery_config()["site_l3_query_templates"])


def build_l3_site_queries(keyword: str, domain: str, *, max_queries: int | None = None) -> List[str]:
    cfg = get_search_discovery_config()
    cap = max_queries if max_queries is not None else int(cfg["max_l3_queries_per_keyword"])
    out: List[str] = []
    for tpl in site_l3_query_templates():
        q = (
            tpl.replace("{keyword}", keyword)
            .replace("{kw}", keyword)
            .replace("{domain}", domain)
        )
        if q and q not in out:
            out.append(q)
        if len(out) >= cap:
            break
    return out


def dataset_search_boost(query: str) -> str:
    boost = get_search_discovery_config()["dataset_search_boost"]
    return f"{query} {boost}".strip()


def filetype_search_queries(query: str) -> List[str]:
    exts = get_search_discovery_config()["filetype_extensions"]
    return [f"{query} filetype:{ext}" for ext in exts[:4]]


def build_authoritative_l2_queries(keywords: List[str], current_domain: str = "") -> List[str]:
    """Cross-site L2 discovery on skill-configured authoritative portals."""
    raw = _load_raw()
    l2 = raw.get("l2_discovery") if isinstance(raw.get("l2_discovery"), dict) else {}
    if not l2.get("include_authoritative_site_queries", False):
        return []

    templates = _as_list(l2.get("authoritative_query_templates")) or [
        "{keyword} site:{site} (download OR ftp OR api OR dataset)",
    ]
    max_q = int(l2.get("max_authoritative_site_queries", 4) or 4)
    dom_l = (current_domain or "").lower().strip()
    sites = [s for s in authoritative_sites() if s.lower() != dom_l]

    out: List[str] = []
    for kw in (keywords or [])[:3]:
        for site in sites[:6]:
            for tpl in templates:
                q = tpl.replace("{keyword}", kw).replace("{kw}", kw).replace("{site}", site)
                if q and q not in out:
                    out.append(q)
                if len(out) >= max_q:
                    return out
    return out[:max_q]
