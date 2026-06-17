"""
Miner signals skill rules — load miner_signals.yaml and provide helpers.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Pattern


def _load_raw() -> Dict[str, Any]:
    try:
        from utils.skill_loader import get_active_skill_id, load_miner_signals
        if get_active_skill_id():
            return load_miner_signals()
    except Exception:
        pass
    return {}


def _as_list(v: Any) -> List[str]:
    if not v:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return []


def domain_keywords() -> List[str]:
    return _as_list(_load_raw().get("domain_keywords"))


def dataset_access_tokens() -> List[str]:
    return _as_list(_load_raw().get("dataset_access_tokens"))


def negative_keywords() -> List[str]:
    return _as_list(_load_raw().get("negative_keywords"))


def search_templates() -> List[str]:
    return _as_list(_load_raw().get("search_templates"))


def negative_kw_re() -> Pattern:
    kws = negative_keywords()
    if not kws:
        return re.compile(r"$^")
    inner = "|".join(re.escape(k.lower()) for k in kws)
    return re.compile(rf"(?:^|[/?#._-])(?:{inner})(?:$|[/?#._-])", re.I)

