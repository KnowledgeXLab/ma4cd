"""
Structural quality gates between Miner output and Inspector commit.
Goal: only pass URLs that look like sustainable data containers aligned with the mission.

When MA4CD_SKILL is set, rule packs load from skills/<id>/rules/inspector_quality_gates.yaml.
Otherwise built-in defaults apply (backward compatible).
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:
    from utils.inspector_audit import (
        has_trusted_path_signal as _audit_trusted_path,
        is_l3_trusted_host as _audit_l3_host,
        min_alignment_for_untrusted as _audit_min_align,
        resolve_inspector_min_score as _audit_min_score,
        resolve_inspector_strict as _audit_strict,
        trusted_domain_bypass_alignment as _audit_bypass_align,
    )
except ImportError:
    def _audit_trusted_path(_url: str) -> bool:
        return False

    def _audit_l3_host(_url: str) -> bool:
        return False

    def _audit_min_align() -> float:
        return 0.7

    def _audit_min_score() -> float:
        return float(os.getenv("MA4CD_INSPECTOR_MIN_SCORE", "0.62"))

    def _audit_strict() -> bool:
        return os.getenv("MA4CD_INSPECTOR_STRICT", "1").strip().lower() not in ("0", "false", "no")

    def _audit_bypass_align() -> bool:
        return False

_COMPILED: Optional[Dict[str, Any]] = None


def _builtin_rules() -> Dict[str, Any]:
    return {
        "noise_host_alternatives": [
            r"wikipedia\.org", r"wikimedia\.org", r"glosbe\.com", r"scribd\.com",
            r"academia\.edu", r"amazon\.", r"amzn\.to", r"facebook\.com",
            r"twitter\.com", r"x\.com", r"linkedin\.com", r"youtube\.com",
            r"vimeo\.com", r"service-now\.com", r"tonex\.com", r"jobsearch\.",
            r"indeed\.com", r"glassdoor\.com", r"creativecommons\.org", r"moluch\.ru",
            r"ruwiki\.ru", r"poobbc-efir\.ru", r"baesystems\.com/en/career",
            r"github\.com/topics", r"github\.com/search",
        ],
        "noise_path_segments": [
            "news", "press", "blog", "article", "articles", "training", "webinar",
            "careers", "jobs", "privacy", "terms", "cart", "checkout", "login",
            "register", "signup", "products?", "solutions?", "videos?", "about",
            "contact", "media", "category/gene-expression", "en-news", "en-media",
            "en-stories",
        ],
        "leaf_path_segments": [
            "doi/", "/abs/", "citations?/", "/pdf", "/document/", "/article/",
            r"wiki/[^/]+$", r"home\.php", r"index\.html$",
        ],
        "container_signal_tokens": [
            "database", "databases", "repository", "repositories", "archive",
            "archives", "portal", "portals", "dataset", "datasets", "catalog",
            "catalogue", "collections?", "data-portal", "dataportal", "search",
            "browse", "registry", "inventory", "sti", "genbank", "ena", "gdc",
            "ludb", "discover", "download", "ftp", "api",
            "library", "digital-library",
            "records", "finding-aid", "biomart", "martview", r"data\.gov",
        ],
        "trusted_data_domains": [
            # Keep builtin trusted domains minimal and domain-agnostic.
            # Domain-specific allowlists should live in skills/*/rules/inspector_quality_gates.yaml.
            "archive.org", "data.gov", "catalog.archives.gov", "www.archives.gov",
        ],
        "cjk_mission_markers": (
            # Minimal generic markers; domain-specific markers belong to skills.
            "数据",
        ),
        "domain_lexicon": {},
        "mission_triggers": {},
    }


def _merge_rules(skill_data: Dict[str, Any]) -> Dict[str, Any]:
    base = _builtin_rules()
    if not skill_data:
        return base
    merged = dict(base)
    for key, value in skill_data.items():
        if key == "version":
            continue
        if key in ("trusted_data_domains",) and isinstance(value, list):
            merged[key] = list(dict.fromkeys([*base.get(key, []), *value]))
        elif key in ("domain_lexicon", "mission_triggers") and isinstance(value, dict):
            out = dict(base.get(key, {}))
            for lex_key, lex_vals in value.items():
                existing = list(out.get(lex_key, []))
                out[lex_key] = list(dict.fromkeys([*existing, *lex_vals]))
            merged[key] = out
        else:
            merged[key] = value
    return merged


def _load_rules() -> Dict[str, Any]:
    try:
        from utils.skill_loader import get_active_skill_id, load_inspector_quality_gates
        if get_active_skill_id():
            return _merge_rules(load_inspector_quality_gates())
    except Exception:
        pass
    return _builtin_rules()


def _compile_rules(rules: Dict[str, Any]) -> Dict[str, Any]:
    from utils.skill_loader import compile_alternation_pattern, compile_path_segment_pattern, compile_token_pattern

    noise_hosts = rules.get("noise_host_alternatives") or []
    noise_paths = rules.get("noise_path_segments") or []
    leaf_paths = rules.get("leaf_path_segments") or []
    container_tokens = rules.get("container_signal_tokens") or []

    return {
        "noise_host_re": compile_alternation_pattern(noise_hosts) if noise_hosts else re.compile(r"$^"),
        "noise_path_re": compile_path_segment_pattern(noise_paths) if noise_paths else re.compile(r"$^"),
        "leaf_path_re": re.compile(
            r"/(?:" + "|".join(leaf_paths) + r")",
            re.I,
        ) if leaf_paths else re.compile(r"$^"),
        "container_signal_re": compile_token_pattern(container_tokens) if container_tokens else re.compile(r"$^"),
        "trusted_data_domains": frozenset(str(d).lower() for d in (rules.get("trusted_data_domains") or [])),
        "cjk_mission_markers": tuple(rules.get("cjk_mission_markers") or ()),
        "domain_lexicon": dict(rules.get("domain_lexicon") or {}),
        "mission_triggers": dict(rules.get("mission_triggers") or {}),
    }


def _gates() -> Dict[str, Any]:
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = _compile_rules(_load_rules())
    return _COMPILED


def reset_quality_gates_cache() -> None:
    """Clear cached compiled rules (for tests or skill hot-swap)."""
    global _COMPILED
    _COMPILED = None


_MISSION_TOKEN_RE = re.compile(r"[a-z0-9]{3,}", re.I)


def _registrable_host(netloc: str) -> str:
    host = (netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def mission_keywords(user_query: Any) -> List[str]:
    gates = _gates()
    if isinstance(user_query, dict):
        parts = [
            str(user_query.get("human_request", "")),
            str(user_query.get("commander_core_intent", "")),
        ]
        targets = user_query.get("specific_targets", [])
        if isinstance(targets, list):
            parts.extend(str(t) for t in targets)
        text = " ".join(parts)
    else:
        text = str(user_query or "")

    tokens = [t.lower() for t in _MISSION_TOKEN_RE.findall(text)]
    tokens = [t for t in tokens if len(t) >= 3]

    lexicon = gates.get("domain_lexicon") or {}
    triggers = gates.get("mission_triggers") or {}
    for lex_key, trigger_list in triggers.items():
        if any(str(t) in text for t in trigger_list):
            tokens.extend(lexicon.get(lex_key, []))

    blob = " ".join(tokens) + " " + text.lower()
    for lex_key, trigger_list in triggers.items():
        if any(str(t).lower() in blob for t in trigger_list):
            tokens.extend(lexicon.get(lex_key, []))

    seen = set()
    out: List[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:40]


def task_alignment_score(url: str, title: str, keywords: List[str]) -> float:
    if not keywords:
        return 0.5
    hay = f"{url} {title}".lower()
    hits = sum(1 for kw in keywords if kw in hay)
    if hits >= 2:
        return 1.0
    if hits == 1:
        return 0.7
    return 0.0


def has_container_signal(url: str, title: str = "") -> bool:
    gates = _gates()
    container_re = gates["container_signal_re"]
    trusted = gates["trusted_data_domains"]
    hay = f"{url} {title}".lower()
    if container_re.search(hay):
        return True
    if _audit_trusted_path(url):
        return True
    host = _registrable_host(urlparse(url).netloc)
    if host in trusted:
        path = urlparse(url).path.strip("/")
        if not path or container_re.search(path):
            return True
        if host == "archive.org" and "/details/" in url.lower():
            return True
    return False


def prefilter_item(item: Dict[str, Any], user_query: Any = None) -> Tuple[bool, str]:
    gates = _gates()
    noise_host_re = gates["noise_host_re"]
    noise_path_re = gates["noise_path_re"]
    leaf_path_re = gates["leaf_path_re"]

    url = str(item.get("url", "") or "").strip()
    title = str(item.get("title", "") or "").strip()
    if not url.startswith("http"):
        return False, "Invalid URL"

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    full = url.lower()

    if noise_host_re.search(host) or noise_host_re.search(full):
        return False, "[质量闸门] 噪声域名/UGC平台"

    if noise_path_re.search(parsed.path or "") or noise_path_re.search(full):
        return False, "[质量闸门] 路径为新闻/培训/营销页"

    if leaf_path_re.search(parsed.path or ""):
        return False, "[质量闸门] 单篇文献/叶子页，非数据容器"

    if "github.com/topics" in full or "github.com/search" in full:
        return False, "[质量闸门] GitHub 主题列表非数据容器"

    keywords = mission_keywords(user_query)
    align = task_alignment_score(url, title, keywords)
    strict = _audit_strict()
    host = _registrable_host(parsed.netloc)
    trusted = gates["trusted_data_domains"]
    on_trusted = host in trusted or _audit_l3_host(url)
    if strict and keywords and align < _audit_min_align():
        if not has_container_signal(url, title):
            if not (_audit_bypass_align() and on_trusted):
                return False, "[质量闸门] 与任务关键词不对齐且缺少数据库/门户特征"

    return True, ""


def post_llm_gate(
    item: Dict[str, Any],
    *,
    suggested_level: str,
    total_score: float,
    status: str,
    raw_report: Dict[str, Any],
    user_query: Any,
    min_confidence: float,
) -> Tuple[bool, str]:
    gates = _gates()
    trusted = gates["trusted_data_domains"]
    url = str(item.get("url", "") or "")
    title = str(item.get("title", "") or "")
    level = str(suggested_level or "").upper()
    st = str(status or "").upper()
    action = str(raw_report.get("action", "")).upper()

    if action in ("HARD_BLACKLIST", "SOFT_IGNORE"):
        return False, f"[质量闸门] LLM action={action}"

    if st in ("REJECT", "FAIL", "ERROR"):
        return False, f"[质量闸门] LLM status={st}"

    strict = _audit_strict()
    min_required = float(min_confidence)
    skill_min = _audit_min_score()
    if strict:
        min_required = max(min_required, skill_min)
    else:
        min_required = min(min_required, skill_min)

    if st == "REVIEW":
        if total_score < min_required + 0.05:
            return False, f"[质量闸门] REVIEW 分数不足 ({total_score:.2f} < {min_required + 0.05:.2f})"
    elif total_score < min_required:
        return False, f"[质量闸门] 分数低于阈值 ({total_score:.2f} < {min_required:.2f})"

    if not raw_report.get("is_valid", False) and total_score < min_required + 0.1:
        return False, "[质量闸门] LLM 未标记 is_valid 且分数不足"

    keywords = mission_keywords(user_query)
    align = task_alignment_score(url, title, keywords)

    if level == "L3":
        evidence = raw_report.get("evidence_signals", {}) if isinstance(raw_report, dict) else {}
        claims_db = (
            isinstance(evidence, dict)
            and evidence.get("is_database_entry_link") is True
        ) or _llm_claims_database_entry(raw_report)
        on_trusted_l3 = _audit_l3_host(url) and (
            has_container_signal(url, title) or _audit_trusted_path(url)
        )
        if not claims_db and not has_container_signal(url, title) and not on_trusted_l3:
            return False, "[质量闸门] L3 缺少子库/数据库入口特征"
        if strict and keywords and align < 0.7 and not claims_db and not on_trusted_l3:
            return False, "[质量闸门] L3 任务相关性不足"

    if level in ("L1", "L2"):
        if not has_container_signal(url, title) and align < 0.5:
            host = _registrable_host(urlparse(url).netloc)
            if host not in trusted:
                return False, "[质量闸门] L1/L2 非可信机构且缺少门户特征"

    if level == "L4":
        evidence = raw_report.get("evidence_signals", {}) if isinstance(raw_report, dict) else {}
        if isinstance(evidence, dict) and evidence.get("is_physical_asset_evidence") is not True:
            if not has_container_signal(url, title) and align < 0.5:
                return False, "[质量闸门] L4 缺少物理资产证据信号"

    return True, ""


def _llm_claims_database_entry(report: Dict[str, Any]) -> bool:
    evidence = report.get("evidence_signals", {}) if isinstance(report, dict) else {}
    if isinstance(evidence, dict) and evidence.get("is_database_entry_link") is True:
        return True
    ct = str(report.get("content_type", "")).lower()
    return "database" in ct or "sub_database" in ct
