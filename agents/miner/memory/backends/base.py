"""
MA4CD 记忆存储后端抽象层。

设计目标：
- 与现有 WorkingMemoryStorage / SessionMemoryStorage 方法签名对齐
- UnifiedMemoryManager 通过工厂按 MA4CD_MEMORY_BACKEND 切换 file | redis
- Persistent / Chroma 仍走 SQLite / ChromaDB；Redis 仅做热层 + 协调
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from agents.miner.memory.models.memory_models import LearningEvent, SessionSummary


# ---------------------------------------------------------------------------
# Working（短期 + 轨迹）
# ---------------------------------------------------------------------------

@runtime_checkable
class WorkingMemoryBackend(Protocol):
    """对齐 WorkingMemoryStorage + WorkingMemory 轨迹 API。"""

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = 3600,
        importance: float = 0.5,
        tags: Optional[List[str]] = None,
        *,
        session_id: Optional[str] = None,
    ) -> bool: ...

    def get(self, key: str, *, session_id: Optional[str] = None) -> Any: ...

    def delete(self, key: str, *, session_id: Optional[str] = None) -> bool: ...

    def get_stats(self, *, session_id: Optional[str] = None) -> Dict[str, Any]: ...

    # --- 轨迹追踪（WorkingMemory 业务层）---

    def check_url_status(self, url: str, *, session_id: Optional[str] = None) -> Optional[str]: ...

    def record_step(
        self,
        url: str,
        action_state: str,
        depth: int,
        reason: str = "",
        *,
        session_id: Optional[str] = None,
    ) -> None: ...

    def get_recent_trajectory_context(
        self, steps: int = 4, *, session_id: Optional[str] = None
    ) -> str: ...

    def is_looping(self, drop_threshold: int = 3, *, session_id: Optional[str] = None) -> bool: ...

    def reset_session(self, session_id: str) -> None: ...


# ---------------------------------------------------------------------------
# Session（中期）
# ---------------------------------------------------------------------------

@runtime_checkable
class SessionMemoryBackend(Protocol):
    """对齐 SessionMemoryStorage 公开方法。"""

    def create_session(
        self, session_id: str, session_info: Optional[Dict[str, Any]] = None
    ) -> SessionSummary: ...

    def get_session(self, session_id: str) -> Optional[SessionSummary]: ...

    def record_extraction(
        self,
        session_id: str,
        domain: str,
        url: str,
        site_profile: Dict,
        strategy_used: Dict,
        success: bool,
        l3_candidates: List[Dict],
        execution_time: float,
        error_message: Optional[str] = None,
    ) -> bool: ...

    def add_learning_event(self, session_id: str, event: LearningEvent) -> bool: ...

    def close_session(self, session_id: str) -> bool: ...

    def end_session(self, session_id: str) -> bool: ...

    def update_session(self, session_id: str, **updates) -> bool: ...

    def list_sessions(self, days_back: int = 7) -> List[Dict[str, Any]]: ...

    def get_session_stats(self, session_id: str) -> Dict[str, Any]: ...

    def get_stats(self) -> Dict[str, Any]: ...

    def export_session(self, session_id: str) -> Optional[Dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# Coordination（跨协程 / 跨进程协调，UnifiedMemoryManager + Miner 共用）
# ---------------------------------------------------------------------------

@runtime_checkable
class CoordinationBackend(Protocol):
    """
    管理 active_session、URL 去重锁、域名熔断计数。
    对应 UniversalMinerAgent.shared_* 与 SessionMemoryStorage._last_active_id。
    """

    def get_active_session_id(self) -> Optional[str]: ...

    def set_active_session_id(self, session_id: Optional[str]) -> None: ...

    def mark_visited(self, session_id: str, url: str) -> bool:
        """返回 True 表示首次访问；False 表示已访问过。"""
        ...

    def is_visited(self, session_id: str, url: str) -> bool: ...

    def try_acquire_processing(self, session_id: str, url: str, ttl_seconds: int = 600) -> bool:
        """SETNX 风格排他锁；获取失败说明其他 worker 正在处理。"""
        ...

    def release_processing(self, session_id: str, url: str) -> None: ...

    def incr_domain_fail(self, session_id: str, domain: str) -> int: ...

    def get_domain_fail(self, session_id: str, domain: str) -> int: ...

    def incr_url_retry(self, session_id: str, url: str) -> int: ...

    def get_url_retry(self, session_id: str, url: str) -> int: ...

    def reset_batch(self, session_id: str) -> None:
        """新一轮 mine_urls 开始前清空本 session 的 miner 协调状态。"""
        ...

    def sync_runtime(
        self,
        session_id: str,
        *,
        task_info: Optional[Dict[str, Any]] = None,
        extraction_count: Optional[int] = None,
    ) -> None: ...


class MemoryBackendBundle(ABC):
    """一次注入 Working + Session + Coordination 三个后端。"""

    @property
    @abstractmethod
    def working(self) -> WorkingMemoryBackend: ...

    @property
    @abstractmethod
    def session(self) -> SessionMemoryBackend: ...

    @property
    @abstractmethod
    def coordination(self) -> CoordinationBackend: ...

    def ping(self) -> bool:
        """健康检查，供启动时探测 Redis 连通性。"""
        return True

    def close(self) -> None:
        """释放连接池。"""
