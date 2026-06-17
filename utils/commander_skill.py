"""
Commander task skill defaults — scout config, rubric, planning guidance.

Loaded from skills/<id>/rules/commander_task.yaml when MA4CD_SKILL is active.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from utils.prompt_contracts import (
    DEFAULT_SCOUT_CONFIG,
    normalize_scoring_rubric,
    normalize_scout_config,
)


def _load_raw() -> Dict[str, Any]:
    try:
        from utils.skill_loader import get_active_skill_id, load_commander_task
        if get_active_skill_id():
            return load_commander_task()
    except Exception:
        pass
    return {}


def get_commander_skill_task() -> Dict[str, Any]:
    return _load_raw()


def get_planning_guidance_block() -> str:
    raw = _load_raw()
    parts: List[str] = []
    guidance = str(raw.get("planning_guidance") or "").strip()
    if guidance:
        parts.append(guidance)
    hints = raw.get("sub_discipline_hints") or []
    if isinstance(hints, list) and hints:
        bullet = "\n".join(f"- {str(h).strip()}" for h in hints if str(h).strip())
        if bullet:
            parts.append("### 子领域拆解参考\n" + bullet)
    examples = raw.get("seed_query_examples") or []
    if isinstance(examples, list) and examples:
        lines = []
        for ex in examples[:6]:
            if not isinstance(ex, dict):
                continue
            q = str(ex.get("search_query") or "").strip()
            tier = str(ex.get("tier") or "").strip()
            desc = str(ex.get("description") or "").strip()
            if q:
                lines.append(f"- [{tier}] {q}" + (f" — {desc}" if desc else ""))
        if lines:
            parts.append("### 查询示例（供参考，勿照抄进输出）\n" + "\n".join(lines))
    return "\n\n".join(parts).strip()


def apply_commander_skill_defaults(
    normalized_plan: Dict[str, Any],
    user_request: str = "",
) -> Dict[str, Any]:
    """Merge skill defaults into Commander output without overwriting LLM fields."""
    raw = _load_raw()
    if not raw:
        return normalized_plan

    out = dict(normalized_plan)
    template = str(raw.get("core_intent_template") or "").strip()
    if template and not str(out.get("core_intent") or "").strip():
        out["core_intent"] = template

    skill_profile = raw.get("task_profile")
    if isinstance(skill_profile, dict):
        profile = dict(out.get("task_profile") or {})
        for key in ("goal", "scope"):
            if not str(profile.get(key) or "").strip() and skill_profile.get(key):
                profile[key] = skill_profile[key]
        skill_constraints = skill_profile.get("constraints")
        if isinstance(skill_constraints, list) and skill_constraints:
            existing = profile.get("constraints") or []
            if not isinstance(existing, list):
                existing = [str(existing)] if existing else []
            merged_c = list(existing)
            for c in skill_constraints:
                cs = str(c).strip()
                if cs and cs not in merged_c:
                    merged_c.append(cs)
            profile["constraints"] = merged_c
        out["task_profile"] = profile

    skill_rubric = raw.get("scoring_rubric")
    if isinstance(skill_rubric, dict):
        current = out.get("scoring_rubric")
        if not isinstance(current, dict) or not current.get("positive_signals"):
            out["scoring_rubric"] = normalize_scoring_rubric(skill_rubric)
        else:
            merged = normalize_scoring_rubric(current)
            skill_norm = normalize_scoring_rubric(skill_rubric)
            for sig in skill_norm.get("positive_signals", []):
                if sig not in merged["positive_signals"]:
                    merged["positive_signals"].append(sig)
            for sig in skill_norm.get("negative_signals", []):
                if sig not in merged["negative_signals"]:
                    merged["negative_signals"].append(sig)
            out["scoring_rubric"] = merged

    skill_scout = raw.get("scout_config")
    if isinstance(skill_scout, dict):
        base_scout = normalize_scout_config(out.get("scout_config"))
        skill_norm = normalize_scout_config(skill_scout)
        for key, val in skill_norm.items():
            if key not in base_scout or base_scout.get(key) in (None, "", DEFAULT_SCOUT_CONFIG.get(key)):
                base_scout[key] = val
        out["scout_config"] = base_scout

    queries = out.get("search_queries") or []
    if not isinstance(queries, list):
        queries = []
    if len(queries) < 3:
        for ex in raw.get("seed_query_examples") or []:
            if not isinstance(ex, dict):
                continue
            q = str(ex.get("search_query") or "").strip()
            if not q:
                continue
            if any(str(item.get("search_query", "")).strip() == q for item in queries if isinstance(item, dict)):
                continue
            queries.append({
                "search_query": q,
                "tier": str(ex.get("tier", "L3_Database")).strip() or "L3_Database",
                "language": str(ex.get("language", "en")).strip() or "en",
                "description": str(ex.get("description") or "Skill seed query").strip(),
                "score_hint": ex.get("score_hint") if isinstance(ex.get("score_hint"), dict) else {
                    "expected_recall": 0.7,
                    "expected_precision": 0.5,
                },
            })
            if len(queries) >= 8:
                break
        out["search_queries"] = queries

    if user_request.strip() and not str(out.get("core_intent") or "").strip():
        out["core_intent"] = user_request.strip()

    return out
