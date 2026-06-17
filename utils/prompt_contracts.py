from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


DEFAULT_SCOUT_CONFIG: Dict[str, Any] = {
    # 每条搜索 query 返回的结果条数（历史字段名 max_concurrent，易与并行任务数混淆）
    "max_concurrent": 8,
    "results_per_query": 8,
    "max_seed_urls": 50,
    "search_depth": 3,
    "enable_translation": False,
    "country_code": "global",
}


DEFAULT_SCORING_RUBRIC: Dict[str, Any] = {
    "positive_signals": [
        "institutional_authority",
        "data_container_structure",
        "queryable_or_indexed_assets",
        "mission_relevance",
    ],
    "negative_signals": [
        "single_content_page",
        "marketing_or_news_noise",
        "pure_auth_or_cart_flow",
        "non_actionable_utility_page",
    ],
    "weights": {
        "source_authority": 0.30,
        "container_structure": 0.30,
        "mission_relevance": 0.25,
        "noise_risk_penalty": 0.15,
    },
}


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _normalize_weights(weights: Any) -> Dict[str, float]:
    base = dict(DEFAULT_SCORING_RUBRIC["weights"])
    if isinstance(weights, dict):
        for k in list(base.keys()):
            if k in weights:
                base[k] = max(0.0, min(1.0, _safe_float(weights.get(k), base[k])))

    total = sum(base.values())
    if total <= 1e-9:
        return dict(DEFAULT_SCORING_RUBRIC["weights"])
    return {k: round(v / total, 4) for k, v in base.items()}


def normalize_scoring_rubric(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return dict(DEFAULT_SCORING_RUBRIC)

    positive = raw.get("positive_signals", DEFAULT_SCORING_RUBRIC["positive_signals"])
    negative = raw.get("negative_signals", DEFAULT_SCORING_RUBRIC["negative_signals"])

    return {
        "positive_signals": [str(x).strip() for x in positive] if isinstance(positive, list) else list(DEFAULT_SCORING_RUBRIC["positive_signals"]),
        "negative_signals": [str(x).strip() for x in negative] if isinstance(negative, list) else list(DEFAULT_SCORING_RUBRIC["negative_signals"]),
        "weights": _normalize_weights(raw.get("weights")),
    }


def normalize_scout_config(raw: Any) -> Dict[str, Any]:
    cfg = dict(DEFAULT_SCOUT_CONFIG)
    if not isinstance(raw, dict):
        return cfg

    if "max_concurrent" in raw:
        cfg["max_concurrent"] = max(1, int(_safe_float(raw.get("max_concurrent"), cfg["max_concurrent"])))
    if "results_per_query" in raw:
        cfg["results_per_query"] = max(1, int(_safe_float(raw.get("results_per_query"), cfg.get("results_per_query", cfg["max_concurrent"]))))
    elif cfg.get("results_per_query") is None:
        cfg["results_per_query"] = cfg["max_concurrent"]
    if "search_depth" in raw:
        cfg["search_depth"] = max(1, int(_safe_float(raw.get("search_depth"), cfg["search_depth"])))
    if "enable_translation" in raw:
        cfg["enable_translation"] = bool(raw.get("enable_translation"))
    if "country_code" in raw and str(raw.get("country_code")).strip():
        cfg["country_code"] = str(raw.get("country_code")).strip().lower()
    if "task_type" in raw and str(raw.get("task_type")).strip():
        cfg["task_type"] = str(raw.get("task_type")).strip()
    if "max_seed_urls" in raw:
        cfg["max_seed_urls"] = max(1, int(_safe_float(raw.get("max_seed_urls"), cfg.get("max_seed_urls", 50))))
    cfg["results_per_query"] = max(
        1,
        int(_safe_float(cfg.get("results_per_query"), cfg["max_concurrent"])),
        int(cfg["max_concurrent"]),
    )
    return cfg


def scout_results_per_query(config: Dict[str, Any] | None) -> int:
    """Scout 每条 query 向 Tavily 请求的结果条数。"""
    cfg = normalize_scout_config(config or {})
    return max(1, min(int(cfg["results_per_query"]), 20))


def scout_max_seed_urls(config: Dict[str, Any] | None) -> int:
    """Scout 每题最多交给 Miner 的种子 URL 数（仍全部为 Tavily 真实结果）。"""
    cfg = normalize_scout_config(config or {})
    default = int(cfg.get("max_seed_urls", 50))
    env_cap = os.getenv("MA4CD_SCOUT_MAX_URLS")
    if env_cap is not None and str(env_cap).strip():
        default = int(_safe_float(env_cap, default))
    return max(1, min(default, 200))


def normalize_search_query_item(item: Any) -> Optional[Dict[str, Any]]:
    if isinstance(item, str):
        q = item.strip()
        if not q:
            return None
        return {
            "search_query": q,
            "tier": "L3_Database",
            "language": "en",
            "description": "Auto-normalized from plain query string.",
            "score_hint": {"expected_recall": 0.7, "expected_precision": 0.5},
        }

    if not isinstance(item, dict):
        return None

    query = str(item.get("search_query") or item.get("query") or "").strip()
    if not query:
        return None

    tier = str(item.get("tier", "L3_Database")).strip() or "L3_Database"
    language = str(item.get("language", "en")).strip() or "en"
    description = str(item.get("description") or item.get("rationale") or "").strip()

    score_hint = item.get("score_hint", {})
    if not isinstance(score_hint, dict):
        score_hint = {}
    expected_recall = max(0.0, min(1.0, _safe_float(score_hint.get("expected_recall"), 0.7)))
    expected_precision = max(0.0, min(1.0, _safe_float(score_hint.get("expected_precision"), 0.5)))

    return {
        "search_query": query,
        "tier": tier,
        "language": language,
        "description": description,
        "score_hint": {
            "expected_recall": expected_recall,
            "expected_precision": expected_precision,
        },
    }


def normalize_commander_task_config(raw_plan: Any, user_request: str = "") -> Dict[str, Any]:
    if not isinstance(raw_plan, dict):
        raw_plan = {}

    core_intent = str(
        raw_plan.get("core_intent")
        or raw_plan.get("intent")
        or raw_plan.get("reasoning")
        or user_request
    ).strip()

    task_profile = raw_plan.get("task_profile", {})
    if not isinstance(task_profile, dict):
        task_profile = {}
    normalized_profile = {
        "goal": str(task_profile.get("goal", core_intent or user_request)).strip(),
        "scope": str(task_profile.get("scope", "global")).strip(),
        "constraints": task_profile.get("constraints", []),
    }
    if not isinstance(normalized_profile["constraints"], list):
        normalized_profile["constraints"] = [str(normalized_profile["constraints"])]

    scoring_rubric = normalize_scoring_rubric(raw_plan.get("scoring_rubric", {}))

    scout_config_raw = raw_plan.get("scout_config", {})
    if not isinstance(scout_config_raw, dict):
        scout_config_raw = {}
    # Backward-compat: allow old top-level keys to fill scout config.
    for legacy_key in ["max_concurrent", "search_depth", "enable_translation", "country_code", "task_type"]:
        if legacy_key in raw_plan and legacy_key not in scout_config_raw:
            scout_config_raw[legacy_key] = raw_plan.get(legacy_key)
    scout_config = normalize_scout_config(scout_config_raw)

    raw_queries = raw_plan.get("search_queries")
    if raw_queries is None:
        raw_queries = raw_plan.get("query_plan", [])
    if not isinstance(raw_queries, list):
        raw_queries = [raw_queries] if raw_queries else []

    normalized_queries: List[Dict[str, Any]] = []
    for q in raw_queries:
        nq = normalize_search_query_item(q)
        if nq:
            normalized_queries.append(nq)

    # final fallback to avoid empty plan
    if not normalized_queries and user_request.strip():
        normalized_queries.append(
            {
                "search_query": user_request.strip(),
                "tier": "L3_Database",
                "language": "en",
                "description": "Fallback query from user request.",
                "score_hint": {"expected_recall": 0.6, "expected_precision": 0.4},
            }
        )

    return {
        "core_intent": core_intent or user_request.strip(),
        "task_profile": normalized_profile,
        "scoring_rubric": scoring_rubric,
        "scout_config": scout_config,
        "search_queries": normalized_queries,
    }


def extract_query_texts(search_queries: Any) -> List[str]:
    if not isinstance(search_queries, list):
        return []
    texts: List[str] = []
    for item in search_queries:
        if isinstance(item, dict):
            q = str(item.get("search_query") or item.get("query") or "").strip()
        else:
            q = str(item).strip()
        if q:
            texts.append(q)
    return texts


def scout_plan_from_commander_queries(
    commander_task_config: Any,
    *,
    max_queries: int = 15,
) -> List[str]:
    """
    Scout PlanningNode 失败时的兜底：从 Commander task_config 提取 search_queries。
    保持顺序并去重。
    """
    if not isinstance(commander_task_config, dict):
        return []
    texts = extract_query_texts(commander_task_config.get("search_queries", []))
    seen: set[str] = set()
    out: List[str] = []
    for q in texts:
        if q in seen:
            continue
        seen.add(q)
        out.append(q)
        if len(out) >= max_queries:
            break
    return out

