"""
Inspector audit skill rules — gate thresholds, trusted paths, LLM protocol append.

Loaded from skills/<id>/rules/inspector_audit.yaml when MA4CD_SKILL is active.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Pattern

_COMPILED: Optional[Dict[str, Any]] = None


def _builtin_audit() -> Dict[str, Any]:
    return {
        "gate_thresholds": {},
        "trusted_path_signals": [],
        "soft_ignore_path_patterns": [],
        "l3_trusted_host_patterns": [],
        "audit_protocol_append": "",
        "four_dimensional_defaults": {},
    }


def _merge_audit(skill_data: Dict[str, Any]) -> Dict[str, Any]:
    base = _builtin_audit()
    if not skill_data:
        return base
    merged = dict(base)
    for key, value in skill_data.items():
        if key == "version":
            continue
        if key == "gate_thresholds" and isinstance(value, dict):
            gates = dict(base.get("gate_thresholds") or {})
            gates.update(value)
            merged["gate_thresholds"] = gates
        elif value is not None:
            merged[key] = value
    return merged


def _load_skill_audit() -> Dict[str, Any]:
    try:
        from utils.skill_loader import get_active_skill_id, load_inspector_audit
        if get_active_skill_id():
            return load_inspector_audit()
    except Exception:
        pass
    return {}


def _compile_patterns(patterns: List[str], *, flags: int = re.I) -> List[Pattern]:
    out: List[Pattern] = []
    for raw in patterns or []:
        text = str(raw).strip()
        if not text:
            continue
        try:
            out.append(re.compile(text, flags))
        except re.error:
            escaped = re.escape(text)
            out.append(re.compile(escaped, flags))
    return out


def _compile_audit(rules: Dict[str, Any]) -> Dict[str, Any]:
    path_signals = [str(s) for s in (rules.get("trusted_path_signals") or []) if str(s).strip()]
    soft_ignore = [str(s) for s in (rules.get("soft_ignore_path_patterns") or []) if str(s).strip()]
    l3_hosts = [str(s) for s in (rules.get("l3_trusted_host_patterns") or []) if str(s).strip()]

    path_res: List[Pattern] = []
    for sig in path_signals:
        if sig.startswith("/") or sig.startswith("("):
            path_res.extend(_compile_patterns([sig]))
        else:
            path_res.extend(_compile_patterns([re.escape(sig)]))

    return {
        "gate_thresholds": dict(rules.get("gate_thresholds") or {}),
        "trusted_path_res": path_res,
        "soft_ignore_path_res": _compile_patterns(soft_ignore),
        "l3_trusted_host_res": _compile_patterns(l3_hosts),
        "audit_protocol_append": str(rules.get("audit_protocol_append") or "").strip(),
        "four_dimensional_defaults": dict(rules.get("four_dimensional_defaults") or {}),
    }


def _audit() -> Dict[str, Any]:
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = _compile_audit(_merge_audit(_load_skill_audit()))
    return _COMPILED


def reset_inspector_audit_cache() -> None:
    global _COMPILED
    _COMPILED = None


def get_audit_protocol_append() -> str:
    return _audit()["audit_protocol_append"]


def get_gate_thresholds() -> Dict[str, Any]:
    return dict(_audit()["gate_thresholds"])


def resolve_inspector_min_score() -> float:
    raw = os.getenv("MA4CD_INSPECTOR_MIN_SCORE", "").strip()
    if raw:
        return float(raw)
    skill_min = get_gate_thresholds().get("min_score")
    if skill_min is not None:
        return float(skill_min)
    return 0.62


def resolve_inspector_strict() -> bool:
    raw = os.getenv("MA4CD_INSPECTOR_STRICT", "").strip()
    if raw:
        return raw.lower() not in ("0", "false", "no")
    skill_strict = get_gate_thresholds().get("strict_default")
    if skill_strict is not None:
        return bool(skill_strict)
    return True


def has_trusted_path_signal(url: str) -> bool:
    hay = (url or "").lower()
    for pat in _audit()["trusted_path_res"]:
        if pat.search(hay):
            return True
    return False


def is_l3_trusted_host(url: str) -> bool:
    hay = (url or "").lower()
    for pat in _audit()["l3_trusted_host_res"]:
        if pat.search(hay):
            return True
    return False


def is_soft_ignore_path(url: str) -> bool:
    hay = (url or "").lower()
    for pat in _audit()["soft_ignore_path_res"]:
        if pat.search(hay):
            return True
    return False


def trusted_domain_bypass_alignment() -> bool:
    return bool(get_gate_thresholds().get("trusted_domain_bypass_alignment", False))


def min_alignment_for_untrusted() -> float:
    return float(get_gate_thresholds().get("min_alignment_for_untrusted", 0.7))
