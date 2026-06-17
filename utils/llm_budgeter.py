"""
Lightweight LLM rate budgeter & circuit-breaker.

Goal:
- Smooth out bursts that trigger 429/5xx.
- Provide a shared hook for Inspector/Miner/ReportGenerator without invasive changes.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class _BudgetState:
    cooldown_until: float = 0.0
    consecutive_429: int = 0
    consecutive_errors: int = 0


_STATE: Dict[str, _BudgetState] = {}


def _mode() -> str:
    # global switch: normal | budgeted
    return str(os.getenv("MA4CD_LLM_BUDGET_MODE", "budgeted")).strip().lower()


def _key(tag: str) -> str:
    return (tag or "global").strip().lower()


def before_call(tag: str) -> None:
    """Sleep if circuit-breaker is in cooldown for this tag."""
    if _mode() not in ("budgeted", "on", "true", "1"):
        return
    st = _STATE.get(_key(tag))
    if not st:
        return
    now = time.time()
    if st.cooldown_until > now:
        time.sleep(max(0.0, st.cooldown_until - now))


def record_success(tag: str) -> None:
    st = _STATE.setdefault(_key(tag), _BudgetState())
    st.consecutive_429 = 0
    st.consecutive_errors = 0
    st.cooldown_until = 0.0


def record_error(tag: str, err_msg: str) -> None:
    """Update cooldown based on error type."""
    if _mode() not in ("budgeted", "on", "true", "1"):
        return
    msg = str(err_msg or "").lower()
    st = _STATE.setdefault(_key(tag), _BudgetState())

    is_429 = "429" in msg or "rate limit" in msg
    st.consecutive_errors += 1
    if is_429:
        st.consecutive_429 += 1

    # cooldown strategy (simple and stable):
    # - base 0.5s on any transient error
    # - scale with 429 streak, cap at 20s
    base = float(os.getenv("MA4CD_LLM_BUDGET_BASE_DELAY", "0.5"))
    mult = float(os.getenv("MA4CD_LLM_BUDGET_429_MULT", "2.0"))
    cap = float(os.getenv("MA4CD_LLM_BUDGET_MAX_DELAY", "20"))

    delay = base
    if is_429:
        delay = min(cap, base * (mult ** max(0, st.consecutive_429 - 1)))
    else:
        delay = min(cap, base * (1.5 ** max(0, st.consecutive_errors - 1)))

    st.cooldown_until = max(st.cooldown_until, time.time() + delay)


def degrade_mode(component: str = "global") -> str:
    """
    Degrade matrix:
    - MA4CD_<COMP>_LLM_MODE overrides global
    - values: llm_preferred | rules_only
    """
    comp = (component or "global").strip().upper()
    per = os.getenv(f"MA4CD_{comp}_LLM_MODE", "").strip().lower()
    if per:
        return per
    return str(os.getenv("MA4CD_LLM_MODE", "llm_preferred")).strip().lower()


def rules_only(component: str = "global") -> bool:
    return degrade_mode(component) in ("rules_only", "rule_only", "rules", "off")

