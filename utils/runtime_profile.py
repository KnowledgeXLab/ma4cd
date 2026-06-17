"""
Runtime profile skill rules — apply env defaults non-destructively.
"""
from __future__ import annotations

import os
from typing import Any, Dict


def load_env_defaults() -> Dict[str, str]:
    try:
        from utils.skill_loader import get_active_skill_id, load_runtime_profile
        if not get_active_skill_id():
            return {}
        raw = load_runtime_profile()
        env_defaults = raw.get("env_defaults") if isinstance(raw, dict) else {}
        if not isinstance(env_defaults, dict):
            return {}
        out: Dict[str, str] = {}
        for k, v in env_defaults.items():
            ks = str(k).strip()
            if not ks:
                continue
            out[ks] = str(v).strip()
        return out
    except Exception:
        return {}


def apply_env_defaults_non_overriding() -> Dict[str, str]:
    """
    Apply defaults only when env var is missing/empty.
    Returns applied {key: value}.
    """
    defaults = load_env_defaults()
    applied: Dict[str, str] = {}
    for k, v in defaults.items():
        if not k:
            continue
        if os.getenv(k) is None or str(os.getenv(k)).strip() == "":
            os.environ[k] = str(v)
            applied[k] = str(v)
    return applied

