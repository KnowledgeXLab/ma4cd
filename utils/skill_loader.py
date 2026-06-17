"""
MA4CD Skill loader — domain-agnostic rule pack loader.

Skills live under skills/<skill-id>/ with manifest.yaml + rules/*.yaml.
Activate via MA4CD_SKILL=<skill-id> or --skill <skill-id>.
Engine code reads rule *schemas*; domain knowledge stays in YAML only.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _PROJECT_ROOT / "skills"

_active_skill_id: Optional[str] = None


def project_root() -> Path:
    return _PROJECT_ROOT


def skills_dir() -> Path:
    return _SKILLS_DIR


def set_active_skill(skill_id: Optional[str]) -> None:
    """Set active skill for this process (clears cached rule loads)."""
    global _active_skill_id
    _active_skill_id = (skill_id or "").strip() or None
    _load_manifest.cache_clear()
    _load_yaml.cache_clear()
    try:
        from agents.inspector.tools.quality_gates import reset_quality_gates_cache
        reset_quality_gates_cache()
    except ImportError:
        pass
    try:
        from utils.miner_heuristics import reset_miner_heuristics_cache
        reset_miner_heuristics_cache()
    except ImportError:
        pass
    try:
        from utils.inspector_audit import reset_inspector_audit_cache
        reset_inspector_audit_cache()
    except ImportError:
        pass
    try:
        from utils.rejection_buckets import reset_rejection_buckets_cache
        reset_rejection_buckets_cache()
    except ImportError:
        pass
    try:
        from utils.inspector_fallback_audit import reset_inspector_fallback_audit_cache
        reset_inspector_fallback_audit_cache()
    except ImportError:
        pass
    try:
        from utils.search_discovery import reset_search_discovery_cache
        reset_search_discovery_cache()
    except ImportError:
        pass
    try:
        from utils.report_taxonomy import reset_report_taxonomy_cache
        reset_report_taxonomy_cache()
    except ImportError:
        pass


def get_active_skill_id() -> Optional[str]:
    if _active_skill_id is not None:
        return _active_skill_id or None
    raw = os.getenv("MA4CD_SKILL", "").strip()
    return raw or None


def resolve_skill_dir(skill_id: Optional[str] = None) -> Optional[Path]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return None
    path = _SKILLS_DIR / sid
    if not path.is_dir():
        raise FileNotFoundError(f"Skill not found: {sid} (expected {path})")
    return path


@lru_cache(maxsize=8)
def _load_manifest(skill_id: str) -> Dict[str, Any]:
    path = _SKILLS_DIR / skill_id / "manifest.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Skill manifest missing: {path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid manifest.yaml for skill {skill_id}")
    return data


@lru_cache(maxsize=16)
def _load_yaml(skill_id: str, relative_path: str) -> Dict[str, Any]:
    path = _SKILLS_DIR / skill_id / relative_path
    if not path.is_file():
        raise FileNotFoundError(f"Skill rule file missing: {path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML rule file: {path}")
    return data


def _rule_rel_path(manifest: Dict[str, Any], key: str) -> str:
    rules = manifest.get("rules") or {}
    rel = rules.get(key)
    if not rel:
        raise KeyError(f"Skill manifest missing rules.{key}")
    return str(rel)


def _load_rule_pack(skill_id: str, rule_key: str) -> Dict[str, Any]:
    """Load one rule file; return {} if manifest omits the key (optional packs)."""
    manifest = _load_manifest(skill_id)
    rel = (manifest.get("rules") or {}).get(rule_key)
    if not rel:
        return {}
    return _load_yaml(skill_id, str(rel))


def load_inspector_quality_gates(skill_id: Optional[str] = None) -> Dict[str, Any]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return {}
    return _load_rule_pack(sid, "inspector_quality_gates")


def load_miner_evolve_domains(skill_id: Optional[str] = None) -> Dict[str, Any]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return {}
    return _load_rule_pack(sid, "miner_evolve_domains")


def load_miner_heuristics(skill_id: Optional[str] = None) -> Dict[str, Any]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return {}
    return _load_rule_pack(sid, "miner_heuristics")


def load_commander_task(skill_id: Optional[str] = None) -> Dict[str, Any]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return {}
    return _load_rule_pack(sid, "commander_task")


def load_inspector_audit(skill_id: Optional[str] = None) -> Dict[str, Any]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return {}
    return _load_rule_pack(sid, "inspector_audit")


def load_scout_search(skill_id: Optional[str] = None) -> Dict[str, Any]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return {}
    return _load_rule_pack(sid, "scout_search")


def load_miner_signals(skill_id: Optional[str] = None) -> Dict[str, Any]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return {}
    return _load_rule_pack(sid, "miner_signals")


def load_curator_chain_model(skill_id: Optional[str] = None) -> Dict[str, Any]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return {}
    return _load_rule_pack(sid, "curator_chain_model")


def load_runtime_profile(skill_id: Optional[str] = None) -> Dict[str, Any]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return {}
    return _load_rule_pack(sid, "runtime_profile")


def load_rejection_buckets(skill_id: Optional[str] = None) -> Dict[str, Any]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return {}
    return _load_rule_pack(sid, "rejection_buckets")


def load_inspector_fallback_audit(skill_id: Optional[str] = None) -> Dict[str, Any]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return {}
    return _load_rule_pack(sid, "inspector_fallback_audit")


def load_miner_prompts(skill_id: Optional[str] = None) -> Dict[str, Any]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return {}
    return _load_rule_pack(sid, "miner_prompts")


def load_search_discovery(skill_id: Optional[str] = None) -> Dict[str, Any]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return {}
    return _load_rule_pack(sid, "search_discovery")


def load_report_taxonomy(skill_id: Optional[str] = None) -> Dict[str, Any]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return {}
    return _load_rule_pack(sid, "report_taxonomy")


def load_curator_supplement(skill_id: Optional[str] = None) -> Dict[str, Any]:
    sid = skill_id or get_active_skill_id()
    if not sid:
        return {}
    return _load_rule_pack(sid, "curator_supplement")


def get_miner_evolve_domain_patterns(
    skill_id: Optional[str] = None,
) -> Tuple[Optional[List[str]], Optional[List[str]]]:
    """Return (trusted_patterns, noise_patterns) from active skill, or (None, None)."""
    data = load_miner_evolve_domains(skill_id)
    if not data:
        return None, None
    trusted = _as_str_list(data.get("trusted_domain_patterns"))
    noise = _as_str_list(data.get("noise_domain_patterns"))
    return trusted or None, noise or None


def list_skills() -> List[str]:
    if not _SKILLS_DIR.is_dir():
        return []
    out: List[str] = []
    for child in sorted(_SKILLS_DIR.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        if (child / "manifest.yaml").is_file():
            out.append(child.name)
    return out


def _as_str_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def compile_alternation_pattern(
    alternatives: List[str],
    *,
    prefix: str = r"(?:^|\.)(",
    suffix: str = r")(?:/|$)",
    flags: int = re.I,
) -> re.Pattern:
    inner = "|".join(alternatives)
    return re.compile(f"{prefix}{inner}{suffix}", flags)


def compile_path_segment_pattern(
    segments: List[str],
    flags: int = re.I,
) -> re.Pattern:
    inner = "|".join(segments)
    return re.compile(rf"/(?:{inner})(?:/|$|[?#])", flags)


def compile_token_pattern(
    tokens: List[str],
    flags: int = re.I,
) -> re.Pattern:
    inner = "|".join(tokens)
    return re.compile(rf"(?:^|[/.?&=_-])({inner})(?:[/.?&=_-]|$)", flags)
