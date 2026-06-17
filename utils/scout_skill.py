"""
Scout skill helpers: load scout_search.yaml and expose prompt append blocks.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _load_raw() -> Dict[str, Any]:
    try:
        from utils.skill_loader import get_active_skill_id, load_scout_search
        if get_active_skill_id():
            return load_scout_search()
    except Exception:
        pass
    return {}


def get_scout_prompt_append() -> str:
    raw = _load_raw()
    return str(raw.get("prompt_append") or "").strip()


def get_scout_site_preferences() -> Dict[str, Any]:
    raw = _load_raw()
    prefs = raw.get("site_preferences") or {}
    return prefs if isinstance(prefs, dict) else {}


def get_scout_language_strategy() -> Dict[str, Any]:
    raw = _load_raw()
    st = raw.get("language_strategy") or {}
    return st if isinstance(st, dict) else {}


def get_scout_tier_distribution() -> Dict[str, int]:
    raw = _load_raw()
    td = raw.get("tier_distribution") or {}
    if not isinstance(td, dict):
        return {}
    out: Dict[str, int] = {}
    for k, v in td.items():
        try:
            out[str(k)] = int(v)
        except Exception:
            continue
    return out


def get_noise_rewrite_rules() -> Dict[str, List[str]]:
    raw = _load_raw()
    nr = raw.get("noise_rewrite") or {}
    if not isinstance(nr, dict):
        return {"container_tokens": [], "hard_noise_tokens": []}
    ct = nr.get("container_tokens") or []
    ht = nr.get("hard_noise_tokens") or []
    if not isinstance(ct, list):
        ct = []
    if not isinstance(ht, list):
        ht = []
    return {
        "container_tokens": [str(x).strip() for x in ct if str(x).strip()],
        "hard_noise_tokens": [str(x).strip() for x in ht if str(x).strip()],
    }

