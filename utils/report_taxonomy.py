"""
Report taxonomy skill rules — five-dimension codebook for Inspector reports.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

_BUILTIN_DIMENSIONS: Dict[str, Dict[str, Any]] = {
    "domain": {
        "label": "领域维度",
        "options": ["科学与智能", "医学与健康", "经济与产业", "人文与社会", "未知"],
    },
    "format": {
        "label": "数据形态维度",
        "options": ["Structured", "Textual", "Multimedia", "Model/Code", "Knowledge", "未知"],
    },
    "source": {
        "label": "渠道来源维度",
        "options": [
            "政府机构", "国际组织", "垂直领域公司", "行业媒体", "数据服务公司",
            "咨询公司", "研究机构", "行业组织", "开源/社交平台", "未知",
        ],
    },
    "region": {
        "label": "国家和地区维度",
        "options": ["第一梯队", "第二梯队", "第三梯队", "未知"],
    },
    "level": {
        "label": "L1~L4线索分级维度",
        "options": ["L1/L2", "L3", "L4", "未知"],
    },
}

_BUILTIN_EXAMPLES = (
    "3. 严禁胡乱归类！例如：nih.gov / cdc.gov 必须是“医学与健康”及“政府机构”。"
)

_DIM_ORDER = ("domain", "format", "source", "region", "level")
_DIM_JSON_KEYS = {
    "domain": "domain_dim",
    "format": "format_dim",
    "source": "source_dim",
    "region": "region_dim",
    "level": "level_dim",
}

_CACHE: Dict[str, Any] | None = None


def _load_raw() -> Dict[str, Any]:
    try:
        from utils.skill_loader import get_active_skill_id, load_report_taxonomy
        if get_active_skill_id():
            return load_report_taxonomy()
    except Exception:
        pass
    return {}


def reset_report_taxonomy_cache() -> None:
    global _CACHE
    _CACHE = None


def _normalize_dimensions(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    dims = raw.get("dimensions") if isinstance(raw.get("dimensions"), dict) else {}
    out: Dict[str, Dict[str, Any]] = {}
    for key in _DIM_ORDER:
        src = dims.get(key) if isinstance(dims.get(key), dict) else {}
        base = _BUILTIN_DIMENSIONS[key]
        opts = src.get("options") if isinstance(src.get("options"), list) else base["options"]
        out[key] = {
            "label": str(src.get("label") or base["label"]).strip(),
            "options": [str(x).strip() for x in opts if str(x).strip()],
        }
    return out


def get_report_taxonomy_config() -> Dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    raw = _load_raw()
    hints = raw.get("host_classification_hints") if isinstance(raw.get("host_classification_hints"), list) else []
    _CACHE = {
        "dimensions": _normalize_dimensions(raw),
        "host_classification_hints": [h for h in hints if isinstance(h, dict)],
        "classification_examples": str(raw.get("classification_examples") or _BUILTIN_EXAMPLES).strip(),
    }
    return _CACHE


def dimension_label_map() -> Dict[str, str]:
    dims = get_report_taxonomy_config()["dimensions"]
    return {key: dims[key]["label"] for key in _DIM_ORDER}


def build_taxonomy_codebook_text() -> str:
    dims = get_report_taxonomy_config()["dimensions"]
    lines = ["【分类大纲 Codebook】"]
    for i, key in enumerate(_DIM_ORDER, 1):
        label = dims[key]["label"]
        opts = ", ".join(dims[key]["options"])
        lines.append(f"{i}. {label}: {opts}")
    return "\n".join(lines)


def get_classification_examples() -> str:
    return get_report_taxonomy_config()["classification_examples"]


def host_hint_block() -> str:
    hints = get_report_taxonomy_config()["host_classification_hints"]
    if not hints:
        return ""
    lines = ["【主机分类提示（优先参考）】"]
    for h in hints[:12]:
        hosts = ", ".join(str(x) for x in (h.get("match_hosts") or [])[:8])
        parts = [f"hosts: {hosts}"]
        for k in ("domain_dim", "source_dim", "region_dim", "format_dim"):
            v = str(h.get(k) or "").strip()
            if v:
                parts.append(f"{k}={v}")
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines)


def build_inspector_taxonomy_system_prompt() -> str:
    codebook = build_taxonomy_codebook_text()
    examples = get_classification_examples()
    host_hints = host_hint_block()
    extra = f"\n\n{host_hints}" if host_hints else ""
    return f"""你是一位极其严苛的首席数据资产审计官。
你需要对传入的 JSON 数据列表进行五维打标。

{codebook}
{extra}

【🔴 核心铁律】：
1. 必须输出且仅输出一个合法的 JSON 数组，严禁包含 ```json 代码块等任何 Markdown 修饰符！
2. JSON 对象必须完全遵循以下 Keys，并且 Values 必须严格从《分类大纲》中对应的选项里【一字不差】地提取：
[
  {{
    "url": "保留原始URL不变",
    "domain_dim": "选1个",
    "format_dim": "选1个",
    "source_dim": "选1个",
    "region_dim": "选1个",
    "level_dim": "选1个",
    "optimized_title": "根据URL或原标题，重写一个15字以内的专业机构或数据库背景介绍，严禁使用Traceback/Unknown等词"
  }}
]
{examples}"""


def match_host_hints(url: str) -> Optional[Dict[str, str]]:
    host = (urlparse(url or "").netloc or "").lower()
    path = (urlparse(url or "").path or "").lower()
    if not host:
        return None
    out: Dict[str, str] = {}
    for h in get_report_taxonomy_config()["host_classification_hints"]:
        for pat in h.get("match_hosts") or []:
            p = str(pat).lower().strip()
            if not p:
                continue
            if host == p or host.endswith("." + p) or p in host:
                for k in ("domain_dim", "format_dim", "source_dim", "region_dim", "level_dim"):
                    v = str(h.get(k) or "").strip()
                    if v:
                        out[k] = v
                break
        if out:
            break

    raw = _load_raw()
    for rule in raw.get("path_format_hints") or []:
        if not isinstance(rule, dict):
            continue
        tokens = [str(t).lower() for t in (rule.get("match_path_tokens") or []) if str(t).strip()]
        fmt = str(rule.get("format_dim") or "").strip()
        if not tokens or not fmt:
            continue
        hay = f"{host}{path}"
        if any(t in hay for t in tokens):
            out.setdefault("format_dim", fmt)

    return out or None


def enforce_host_hints_on_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministic post-pass: align LLM tags with skill host/path hints."""
    if not get_active_skill_id_safe():
        return list(results or [])
    raw = _load_raw()
    if raw.get("enforce_host_hints") is False:
        return list(results or [])

    out: List[Dict[str, Any]] = []
    for item in results or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        hints = match_host_hints(str(row.get("url") or ""))
        if hints:
            for k, v in hints.items():
                if v:
                    row[k] = v
        out.append(row)
    return out


def get_active_skill_id_safe() -> Optional[str]:
    try:
        from utils.skill_loader import get_active_skill_id
        return get_active_skill_id()
    except Exception:
        return None

