"""
Inspector fallback rule audit config — skills/<id>/rules/inspector_fallback_audit.yaml.
"""
from __future__ import annotations

from typing import Any, Dict, FrozenSet, Set

_BUILTIN: Dict[str, Any] = {
    "positive_signals": [
        "data", "dataset", "database", "archive", "repository", "portal", "api",
        "download", "catalog", "search", "export", "bulk", "registry", "metadata",
    ],
    "mission_keywords": [],
    "noise_signals": [
        "news", "blog", "career", "careers", "jobs", "login", "signup",
        "contact", "about", "privacy", "terms", "policy", "forum", "event", "events",
    ],
    "score_weights": {
        "base": 0.35,
        "positive_per_hit": 0.08,
        "mission_per_hit": 0.05,
        "negative_per_hit": 0.10,
        "topology_max_bias": 0.20,
        "max_score": 0.95,
        "binary_url_max_score": 0.25,
    },
}

_CACHE: Dict[str, Any] | None = None


def _load_raw() -> Dict[str, Any]:
    try:
        from utils.skill_loader import get_active_skill_id, load_inspector_fallback_audit
        if get_active_skill_id():
            return load_inspector_fallback_audit()
    except Exception:
        pass
    return {}


def reset_inspector_fallback_audit_cache() -> None:
    global _CACHE
    _CACHE = None


def get_fallback_audit_config() -> Dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    raw = _load_raw()
    if not raw:
        _CACHE = dict(_BUILTIN)
        return _CACHE
    weights = dict(_BUILTIN.get("score_weights") or {})
    if isinstance(raw.get("score_weights"), dict):
        weights.update(raw["score_weights"])
    _CACHE = {
        "positive_signals": list(raw.get("positive_signals") or _BUILTIN["positive_signals"]),
        "mission_keywords": list(raw.get("mission_keywords") or _BUILTIN["mission_keywords"]),
        "noise_signals": list(raw.get("noise_signals") or _BUILTIN["noise_signals"]),
        "score_weights": weights,
    }
    return _CACHE


def _signal_set(key: str) -> FrozenSet[str]:
    cfg = get_fallback_audit_config()
    return frozenset(str(x).strip().lower() for x in (cfg.get(key) or []) if str(x).strip())


def count_signal_hits(haystack: str, tokens: Set[str], signals: FrozenSet[str]) -> int:
    hits = 0
    for sig in signals:
        if sig in tokens or sig in haystack:
            hits += 1
    return hits


def compute_fallback_score(
    *,
    haystack: str,
    tokens: Set[str],
    mission_text: str,
    topology_score: float,
    is_binary: bool,
) -> tuple[float, int, int, int]:
    cfg = get_fallback_audit_config()
    w = cfg.get("score_weights") or {}
    pos = count_signal_hits(haystack, tokens, _signal_set("positive_signals"))
    neg = count_signal_hits(haystack, tokens, _signal_set("noise_signals"))
    mission_hits = 0
    mt = (mission_text or "").lower()
    if mt:
        for kw in _signal_set("mission_keywords"):
            if kw in mt and kw in haystack:
                mission_hits += 1
    topo_bias = max(
        0.0,
        min(float(w.get("topology_max_bias", 0.2)), float(topology_score or 0.0) * float(w.get("topology_max_bias", 0.2))),
    )
    raw = (
        float(w.get("base", 0.35))
        + float(w.get("positive_per_hit", 0.08)) * pos
        + float(w.get("mission_per_hit", 0.05)) * mission_hits
        - float(w.get("negative_per_hit", 0.10)) * neg
        + topo_bias
    )
    score = max(0.0, min(float(w.get("max_score", 0.95)), raw))
    if is_binary:
        score = min(score, float(w.get("binary_url_max_score", 0.25)))
    return score, pos, mission_hits, neg
