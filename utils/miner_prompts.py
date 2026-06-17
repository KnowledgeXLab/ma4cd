"""
Miner prompt skill append blocks — skills/<id>/rules/miner_prompts.yaml.
"""
from __future__ import annotations

from typing import Any, Dict


def _load_raw() -> Dict[str, Any]:
    try:
        from utils.skill_loader import get_active_skill_id, load_miner_prompts
        if get_active_skill_id():
            return load_miner_prompts()
    except Exception:
        pass
    return {}


def get_miner_prompt_append(key: str) -> str:
    raw = _load_raw()
    return str(raw.get(key) or "").strip()


def append_to_prompt(base: str, key: str) -> str:
    block = get_miner_prompt_append(key)
    if not block:
        return base
    return base.rstrip() + "\n\n---\n\n" + block + "\n"
