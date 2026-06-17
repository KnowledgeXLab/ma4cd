"""
Rejection bucketing skill rules — load from skills/<id>/rules/rejection_buckets.yaml.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

_BUILTIN_RULES: List[Tuple[str, str, List[str]]] = [
    ("prefilter", "预拦截/结构闸门", ["pre-filter", "pre filter", "预拦截"]),
    ("prefilter_noise", "噪声/UGC", ["噪声", "ugc"]),
    ("leaf_or_single_content", "叶子页/单篇内容", ["叶子页", "/doi/", "/abs/", "pdf"]),
    ("infra_or_rate_limit", "基础设施/限流", ["基础设施异常", "429", "timeout", "拥堵"]),
    ("llm_action", "LLM 动作拒绝", ["LLM action="]),
    ("llm_status", "LLM 状态拒绝", ["LLM status="]),
    ("score_threshold", "分数低于阈值", ["分数低于阈值"]),
    ("tier_hard_constraints", "L 层级硬约束", ["硬约束"]),
    ("candidate_type_block", "候选类型拦截", ["exploration_target"]),
    ("secondary_verification", "二次复核拦截", ["LLM复核拦截"]),
    ("rule_gate", "规则/质量闸门", ["规则拦截", "闸门"]),
    ("other", "其他", []),
]

_COMPILED: Optional[List[Tuple[str, str, List[str]]]] = None
_LABELS: Optional[Dict[str, str]] = None
_MAX_SAMPLES = 5


def _load_skill_rules() -> List[Tuple[str, str, List[str]]]:
    try:
        from utils.skill_loader import get_active_skill_id, load_rejection_buckets
        if not get_active_skill_id():
            return []
        raw = load_rejection_buckets()
        rules = raw.get("bucket_rules") if isinstance(raw, dict) else []
        if not isinstance(rules, list):
            return []
        out: List[Tuple[str, str, List[str]]] = []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            bid = str(rule.get("id") or "").strip() or "other"
            label = str(rule.get("label") or bid).strip()
            patterns = [str(p).strip() for p in (rule.get("match_any") or []) if str(p).strip()]
            out.append((bid, label, patterns))
        return out or []
    except Exception:
        return []


def _compiled() -> List[Tuple[str, str, List[str]]]:
    global _COMPILED, _LABELS, _MAX_SAMPLES
    if _COMPILED is not None:
        return _COMPILED
    skill_rules = _load_skill_rules()
    _COMPILED = skill_rules if skill_rules else list(_BUILTIN_RULES)
    _LABELS = {bid: label for bid, label, _ in _COMPILED}
    try:
        from utils.skill_loader import get_active_skill_id, load_rejection_buckets
        if get_active_skill_id():
            raw = load_rejection_buckets()
            _MAX_SAMPLES = int(raw.get("max_samples_per_bucket", 5) or 5)
    except Exception:
        pass
    return _COMPILED


def reset_rejection_buckets_cache() -> None:
    global _COMPILED, _LABELS, _MAX_SAMPLES
    _COMPILED = None
    _LABELS = None
    _MAX_SAMPLES = 5


def bucket_rejection_reason(reason: Any) -> str:
    r = str(reason or "").strip()
    rl = r.lower()
    for bid, _label, patterns in _compiled():
        if bid == "other":
            continue
        if bid == "score_threshold":
            if "分数低于阈值" in r or ("review" in rl and "分数不足" in r):
                return bid
            continue
        for pat in patterns:
            pl = pat.lower()
            if pl in rl or pl in r:
                return bid
    return "other"


def bucket_label(bucket_id: str) -> str:
    _compiled()
    labels = _LABELS or {}
    return labels.get(bucket_id, bucket_id)


def bucket_labels() -> Dict[str, str]:
    _compiled()
    return dict(_LABELS or {})


def max_samples_per_bucket() -> int:
    _compiled()
    return max(1, int(_MAX_SAMPLES or 5))


def summarize_rejections(rejected_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    max_n = max_samples_per_bucket()
    bucket_counts: Dict[str, int] = {}
    bucket_samples: Dict[str, List[Dict[str, Any]]] = {}
    for it in rejected_items or []:
        b = bucket_rejection_reason(it.get("reason", ""))
        bucket_counts[b] = bucket_counts.get(b, 0) + 1
        if b not in bucket_samples:
            bucket_samples[b] = []
        if len(bucket_samples[b]) < max_n:
            bucket_samples[b].append(
                {
                    "url": it.get("url", ""),
                    "title": it.get("title", ""),
                    "score": it.get("score", None),
                    "reason": it.get("reason", ""),
                }
            )
    return {
        "total_rejected": len(rejected_items or []),
        "buckets": dict(sorted(bucket_counts.items(), key=lambda kv: kv[1], reverse=True)),
        "bucket_labels": bucket_labels(),
        "top_samples": bucket_samples,
    }
