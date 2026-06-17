"""Inspector 状态后端工厂。"""
from __future__ import annotations

import os
from typing import Optional

from agents.inspector.backends.base import InspectorStateBackend


def get_inspector_state(session_id: Optional[str] = None) -> InspectorStateBackend:
    """
    按 MA4CD_MEMORY_BACKEND 返回 File 或 Redis Inspector 状态。

    Redis 模式：
    - reports：全局 HASH（跨 session URL 审计缓存）
    - remine：按 session_id 隔离的 SET
    """
    backend = os.getenv("MA4CD_MEMORY_BACKEND", "file").strip().lower()
    if backend == "redis":
        from agents.miner.memory.backends.factory import get_memory_backend
        bundle = get_memory_backend()
        if bundle is None:
            raise RuntimeError("MA4CD_MEMORY_BACKEND=redis 但 Redis bundle 未初始化")
        sid = session_id or os.getenv("MA4CD_INSPECTOR_SESSION_ID") or "global"
        return bundle.inspector_state(sid)

    from agents.inspector.state.inspector_state import InspectorState
    state = InspectorState()
    if session_id:
        state.bind_session(session_id)
    return state
