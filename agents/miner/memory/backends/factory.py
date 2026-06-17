"""
记忆后端工厂 — 草案。

接入 UnifiedMemoryManager 的改法（示意，尚未接线）：

    # memory_manager.py
    def _get_memory_bundle():
        backend = os.getenv("MA4CD_MEMORY_BACKEND", "file").lower()
        if backend == "redis":
            from agents.miner.memory.backends.redis_backend import create_redis_backend_from_env
            return create_redis_backend_from_env()
        return None  # file 模式走现有 WorkingMemoryStorage / SessionMemoryStorage

    class UnifiedMemoryManager:
        def __init__(self, db_path=None):
            self._bundle = _get_memory_bundle()
            ...

        @property
        def working_memory(self):
            if self._bundle:
                return self._bundle.working
            ...

        @property
        def session_memory(self):
            if self._bundle:
                return self._bundle.session
            ...

Miner Agent 额外改造点：
    - shared_visited_urls → coordination.mark_visited / is_visited
    - shared_processing_urls → coordination.try_acquire_processing / release_processing
    - WorkingMemory 实例 → 从 bundle.working 读取，并传入 session_id
"""
from __future__ import annotations

import os
from typing import Optional

from agents.miner.memory.backends.base import MemoryBackendBundle


_redis_bundle = None


def get_memory_backend() -> Optional[MemoryBackendBundle]:
    global _redis_bundle
    backend = os.getenv("MA4CD_MEMORY_BACKEND", "file").strip().lower()
    if backend in ("file", "", "local"):
        return None
    if backend == "redis":
        if _redis_bundle is not None:
            return _redis_bundle
        from agents.miner.memory.backends.redis_backend import create_redis_backend_from_env
        _redis_bundle = create_redis_backend_from_env()
        return _redis_bundle
    raise ValueError(f"未知 MA4CD_MEMORY_BACKEND={backend!r}，支持: file, redis")
