"""
Curator skill helpers: load curator_chain_model.yaml and expose prompt / fuse / gap seeds.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Set


def _load_raw() -> Dict[str, Any]:
    try:
        from utils.skill_loader import get_active_skill_id, load_curator_chain_model
        if get_active_skill_id():
            return load_curator_chain_model()
    except Exception:
        pass
    return {}


def get_curator_prompt_append() -> str:
    raw = _load_raw()
    return str(raw.get("prompt_append") or "").strip()


def get_curator_fuse_rules() -> Dict[str, Any]:
    raw = _load_raw()
    fuse = raw.get("fuse_rules") if isinstance(raw, dict) else {}
    return fuse if isinstance(fuse, dict) else {}


def get_curator_max_rounds(default: int = 3) -> int:
    fuse = get_curator_fuse_rules()
    try:
        return max(1, int(fuse.get("max_rounds", default) or default))
    except (TypeError, ValueError):
        return default


def _portal_seeds() -> Dict[str, str]:
    raw = _load_raw()
    seeds = raw.get("portal_seeds") if isinstance(raw, dict) else {}
    if not isinstance(seeds, dict):
        return {}
    out: Dict[str, str] = {}
    for k, v in seeds.items():
        key = str(k).strip().lower()
        url = str(v).strip()
        if key and url.startswith("http"):
            out[key] = url
    return out


def build_curator_gap_seed_urls(
    gaps: List[str],
    directives: str = "",
    seen_urls: Set[str] | None = None,
    *,
    max_urls: int = 8,
) -> List[str]:
    """
    Map Curator strategic gaps/directives to authoritative portal entry URLs.
    Used when Curator→Scout supplement returns no new URLs.
    """
    seen = seen_urls or set()
    seeds = _portal_seeds()
    if not seeds or not gaps:
        return []

    haystack = " ".join(str(g) for g in gaps) + " " + str(directives or "")
    haystack_l = haystack.lower()

    matched: List[str] = []
    for marker, url in seeds.items():
        if marker in haystack_l and url not in seen:
            matched.append(url)

    if not matched:
        # Fallback: tokenize gap lines for partial marker hits (e.g. UniProt in Chinese text)
        tokens = set(re.findall(r"[a-z0-9][a-z0-9_-]{2,}", haystack_l))
        for marker, url in seeds.items():
            if marker in tokens and url not in seen:
                matched.append(url)

    out: List[str] = []
    for u in matched:
        if u not in seen and u not in out:
            out.append(u)
        if len(out) >= max_urls:
            break
    return out
