"""
Miner DFS 启发式规则 — 内置默认 + Skill YAML 覆盖。

激活 MA4CD_SKILL 时读取 skills/<id>/rules/miner_heuristics.yaml。
环境变量（MA4CD_EVOLVE_*）仍优先于 Skill 默认值。
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

_COMPILED: Optional[Dict[str, Any]] = None


def _builtin_heuristics() -> Dict[str, Any]:
    return {
        "invalid_path_suffixes": [
            "/home", "/index", "/index.html", "/index.php",
            "/en", "/zh", "/en-us", "/about", "/contact",
            "/search", "/login", "/register",
        ],
        "link_noise_patterns": [
            r"facebook\.com", r"twitter\.com", r"x\.com", r"linkedin\.com",
            r"youtube\.com", r"vimeo\.com", r"reddit\.com", r"medium\.com",
            r"/login", r"/signup", r"/cart", r"/password",
        ],
        "junk_file_extensions": [
            "png", "jpg", "jpeg", "gif", "css", "js", "mp4", "avi", "mp3",
            "wav", "woff", "woff2", "ttf", "svg", "ico",
        ],
        "evolve_gates": {
            "min_recall_score_to_activate": 0.45,
            "min_topology_score_to_activate": 0.35,
            "min_recall_for_stability": 0.35,
            "positive_evolve_min_assets": 20,
            "positive_evolve_min_topology": 0.75,
            "positive_evolve_cooldown_sec": 600,
            "evolve_min_interval_sec": 8,
            "evolve_domain_cooldown_sec": 90,
            "evolve_max_per_batch": 10,
            "evolve_max_per_domain_per_batch": 3,
        },
    }


def _merge_heuristics(skill_data: Dict[str, Any]) -> Dict[str, Any]:
    base = _builtin_heuristics()
    if not skill_data:
        return base
    merged = dict(base)
    for key, value in skill_data.items():
        if key == "version":
            continue
        if key == "evolve_gates" and isinstance(value, dict):
            gates = dict(base.get("evolve_gates") or {})
            gates.update(value)
            merged["evolve_gates"] = gates
        elif value is not None:
            merged[key] = value
    return merged


def _load_skill_heuristics() -> Dict[str, Any]:
    try:
        from utils.skill_loader import get_active_skill_id, load_miner_heuristics
        if get_active_skill_id():
            return load_miner_heuristics()
    except Exception:
        pass
    return {}


def _compile_heuristics(rules: Dict[str, Any]) -> Dict[str, Any]:
    suffixes = [str(s) for s in (rules.get("invalid_path_suffixes") or []) if str(s).strip()]
    noise_alts = [str(p) for p in (rules.get("link_noise_patterns") or []) if str(p).strip()]
    junk_exts = [str(e).lstrip(".") for e in (rules.get("junk_file_extensions") or []) if str(e).strip()]

    link_noise_re = (
        re.compile("|".join(f"(?:{p})" for p in noise_alts), re.I)
        if noise_alts else re.compile(r"$^")
    )
    junk_ext_re = (
        re.compile(r"\.(?:" + "|".join(re.escape(e) for e in junk_exts) + r")$", re.I)
        if junk_exts else re.compile(r"$^")
    )

    gates_raw = rules.get("evolve_gates") or {}
    evolve_gates = {
        k: (float(v) if isinstance(v, (int, float)) else v)
        for k, v in gates_raw.items()
    }

    return {
        "invalid_path_suffixes": suffixes,
        "link_noise_re": link_noise_re,
        "junk_ext_re": junk_ext_re,
        "evolve_gates": evolve_gates,
    }


def _heuristics() -> Dict[str, Any]:
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = _compile_heuristics(_merge_heuristics(_load_skill_heuristics()))
    return _COMPILED


def reset_miner_heuristics_cache() -> None:
    global _COMPILED
    _COMPILED = None


def get_invalid_path_suffixes() -> List[str]:
    return list(_heuristics()["invalid_path_suffixes"])


def get_link_noise_re() -> re.Pattern:
    return _heuristics()["link_noise_re"]


def get_junk_ext_re() -> re.Pattern:
    return _heuristics()["junk_ext_re"]


def get_evolve_gates() -> Dict[str, Any]:
    return dict(_heuristics()["evolve_gates"])


def resolve_evolve_int(
    env_name: str,
    *,
    config_value: Any = None,
    gate_key: str,
    default: int,
) -> int:
    raw = os.getenv(env_name, "").strip()
    if raw:
        return int(raw)
    if config_value is not None:
        return int(config_value)
    return int(get_evolve_gates().get(gate_key, default))


def resolve_evolve_float(
    env_name: str,
    *,
    config_value: Any = None,
    gate_key: str,
    default: float,
) -> float:
    raw = os.getenv(env_name, "").strip()
    if raw:
        return float(raw)
    if config_value is not None:
        return float(config_value)
    return float(get_evolve_gates().get(gate_key, default))
