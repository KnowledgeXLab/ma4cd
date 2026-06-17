import sys
import os
import time
import threading
from typing import Dict, Any, List, Optional
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger
from enum import Enum

# =============================================================================
# 🛠️ 路径暴力修正
# =============================================================================
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    # 尝试导入你提供的 memory_models
    from agents.miner.memory.models.memory_models import MemoryItem, ImportanceLevel
except ImportError:
    logger.warning("⚠️ memory_models 模块未找到，使用内置定义 (WorkingMemory)")
    
    class ImportanceLevel(Enum):
        LOW = 0.2
        MEDIUM = 0.5
        HIGH = 0.8
        CRITICAL = 1.0

    # 兜底定义：必须包含代码中用到的所有字段 (tags, ttl_seconds)
    @dataclass
    class MemoryItem:
        key: str
        value: Any
        importance: float = 0.5
        created_at: datetime = field(default_factory=datetime.now)
        access_count: int = 0
        tags: List[str] = field(default_factory=list)
        ttl_seconds: Optional[int] = None

        def access(self): 
            self.access_count += 1
        
        def is_expired(self) -> bool:
            if self.ttl_seconds is None:
                return False
            return (datetime.now() - self.created_at).total_seconds() > self.ttl_seconds


# =============================================================================
# 🧠 新增：认知轨迹节点 (DeepResearch 核心概念)
# =============================================================================
@dataclass
class TrajectoryNode:
    """记录 Agent 的单步探索轨迹与研判结果"""
    url: str
    action_state: str  # 状态标签: 如 'PARSED_L1', 'L3_EXTRACTED', 'DROP_IRRELEVANT', 'L4_FOUND'
    depth: int         # 当前所处的探索深度
    timestamp: float = field(default_factory=time.time)
    reason: str = ""   # 记录大模型做出判决的原因（用于上下文注入和反思）


# =============================================================================
# 📦 底层：短期记忆物理存储 (保留原有优秀实现)
# =============================================================================
class WorkingMemoryStorage:
    """
    短期记忆存储 - 纯内存实现
    用于存储当前任务的临时状态和快速访问的数据 (带线程锁和 TTL 机制)
    """
    def __init__(self, max_items: int = 1000, cleanup_interval: int = 300):
        self._storage: Dict[str, MemoryItem] = {}
        self._lock = threading.RLock()
        self._max_items = max_items
        self._cleanup_interval = cleanup_interval
        self._tag_index: Dict[str, set] = defaultdict(set)
        self._start_cleanup_thread()
        logger.info(f"WorkingMemoryStorage 初始化完成 (最大项目: {max_items})")
    
    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = 3600,
            importance: float = ImportanceLevel.MEDIUM.value, 
            tags: List[str] = None, *, session_id: Optional[str] = None) -> bool:
        with self._lock:
            if len(self._storage) >= self._max_items and key not in self._storage:
                self._evict_least_important()
            
            item = MemoryItem(
                key=key, value=value, importance=importance,
                tags=tags or [], ttl_seconds=ttl_seconds
            )
            
            if key in self._storage:
                self._remove_from_tag_index(key, self._storage[key].tags)
            
            self._storage[key] = item
            self._add_to_tag_index(key, item.tags)
            return True
    
    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._storage: return None
            item = self._storage[key]
            if item.is_expired():
                self._remove_item(key)
                return None
            item.access()
            return item.value
    
    def get_by_tags(self, tags: List[str], match_all: bool = False) -> Dict[str, Any]:
        with self._lock:
            result = {}
            if match_all:
                candidate_keys = None
                for tag in tags:
                    tag_keys = self._tag_index.get(tag, set())
                    if candidate_keys is None:
                        candidate_keys = tag_keys.copy()
                    else:
                        candidate_keys &= tag_keys
                if candidate_keys:
                    for key in candidate_keys:
                        value = self.get(key)
                        if value is not None: result[key] = value
            else:
                candidate_keys = set()
                for tag in tags:
                    candidate_keys.update(self._tag_index.get(tag, set()))
                for key in candidate_keys:
                    value = self.get(key)
                    if value is not None: result[key] = value
            return result
    
    def update_importance(self, key: str, importance_delta: float) -> bool:
        with self._lock:
            if key not in self._storage: return False
            item = self._storage[key]
            item.importance = max(0.0, min(1.0, item.importance + importance_delta))
            return True
    
    def remove(self, key: str) -> bool:
        with self._lock:
            return self._remove_item(key)
    
    def clear_by_tags(self, tags: List[str]) -> int:
        with self._lock:
            items_to_remove = set()
            for tag in tags:
                items_to_remove.update(self._tag_index.get(tag, set()))
            removed_count = sum(1 for key in items_to_remove if self._remove_item(key))
            return removed_count
    
    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total_items = len(self._storage)
            high_importance = sum(1 for item in self._storage.values() if item.importance > ImportanceLevel.HIGH.value)
            frequently_accessed = sum(1 for item in self._storage.values() if item.access_count > 5)
            tag_stats = {tag: len(keys) for tag, keys in self._tag_index.items()}
            return {
                "total_items": total_items,
                "high_importance_items": high_importance,
                "frequently_accessed_items": frequently_accessed,
                "tag_distribution": tag_stats,
                "capacity_usage": f"{total_items}/{self._max_items}"
            }
    
    def _remove_item(self, key: str) -> bool:
        if key not in self._storage: return False
        item = self._storage[key]
        self._remove_from_tag_index(key, item.tags)
        del self._storage[key]
        return True
    
    def _add_to_tag_index(self, key: str, tags: List[str]):
        for tag in tags: self._tag_index[tag].add(key)
    
    def _remove_from_tag_index(self, key: str, tags: List[str]):
        for tag in tags:
            self._tag_index[tag].discard(key)
            if not self._tag_index[tag]: del self._tag_index[tag]
    
    def _evict_least_important(self):
        if not self._storage: return
        least_important_key = min(
            self._storage.keys(),
            key=lambda k: (self._storage[k].importance, self._storage[k].access_count)
        )
        self._remove_item(least_important_key)
    
    def _cleanup_expired(self):
        with self._lock:
            expired_keys = [key for key, item in self._storage.items() if item.is_expired()]
            for key in expired_keys: self._remove_item(key)
    
    def _start_cleanup_thread(self):
        def cleanup_worker():
            while True:
                try:
                    self._cleanup_expired()
                    time.sleep(self._cleanup_interval)
                except Exception as e:
                    logger.error(f"短期记忆清理异常: {e}")
                    time.sleep(60)
        cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        cleanup_thread.start()


# =============================================================================
# 🚀 业务层：工作记忆与轨迹追踪器 (全面升级)
# =============================================================================
class WorkingMemory:
    """工作记忆 - 存储当前会话的实时数据 & 认知轨迹 (Trajectory Tracker)"""

    def __init__(self, backend=None, session_id: Optional[str] = None):
        self._backend = backend
        self._session_id = session_id
        # 1. 原有监控字段（file 模式本地）
        self.current_performance = {}
        self.prompt_feedback = []
        self.real_time_metrics = {}
        self.session_start_time = time.time()

        # 2. 轨迹追踪（file 模式本地）
        self.visited_urls: Dict[str, TrajectoryNode] = {}
        self.path_history: List[TrajectoryNode] = []
        self.max_trajectory_nodes = int(os.getenv("MA4CD_WORKING_MAX_TRAJECTORY", "5000"))
        self.url_status_ttl_seconds = int(os.getenv("MA4CD_WORKING_URL_STATUS_TTL", "7200"))

    def bind_session(self, session_id: Optional[str]) -> None:
        self._session_id = session_id

    def uses_remote_backend(self) -> bool:
        return bool(self._backend and self._session_id)

    def reset_session(self) -> None:
        """新一轮 mine_urls 前重置本 session 的 working / 轨迹状态。"""
        if self._backend and self._session_id and hasattr(self._backend, "reset_session"):
            self._backend.reset_session(self._session_id)
        self.clear()
        
    # ==========================================
    # 🕵️‍♂️ 轨迹追踪器核心逻辑
    # ==========================================
    
    def check_url_status(self, url: str) -> Optional[str]:
        if self._backend and self._session_id:
            return self._backend.check_url_status(url, session_id=self._session_id)
        normalized_url = self._normalize_url(url)
        self._prune_expired_status()
        if normalized_url in self.visited_urls:
            return self.visited_urls[normalized_url].action_state
        return None

    def record_step(self, url: str, action_state: str, depth: int, reason: str = ""):
        if self._backend and self._session_id:
            self._backend.record_step(
                url, action_state, depth, reason=reason, session_id=self._session_id
            )
            return
        normalized_url = self._normalize_url(url)
        node = TrajectoryNode(
            url=normalized_url,
            action_state=action_state,
            depth=depth,
            reason=reason
        )
        self.visited_urls[normalized_url] = node
        self.path_history.append(node)
        self._trim_trajectory_capacity()
        logger.debug(f"📍 轨迹已记录: [{action_state}] {url} (Depth: {depth})")

    def _normalize_url(self, url: str) -> str:
        if not url:
            return ""
        return str(url).split("#")[0].rstrip("/")

    def _prune_expired_status(self):
        if self.url_status_ttl_seconds <= 0:
            return
        now = time.time()
        expire_before = now - self.url_status_ttl_seconds
        expired_urls = [
            k for k, v in self.visited_urls.items()
            if v.timestamp < expire_before
        ]
        if expired_urls:
            for key in expired_urls:
                del self.visited_urls[key]
            # path_history 也同步剔除，避免上下文污染
            self.path_history = [
                n for n in self.path_history if n.timestamp >= expire_before
            ]

    def _trim_trajectory_capacity(self):
        if self.max_trajectory_nodes <= 0:
            return
        overflow = len(self.path_history) - self.max_trajectory_nodes
        if overflow <= 0:
            return
        dropped_nodes = self.path_history[:overflow]
        self.path_history = self.path_history[overflow:]
        for node in dropped_nodes:
            # 仅在 visited_urls 中仍指向被裁掉的那条记录时删除，避免误删新状态
            latest = self.visited_urls.get(node.url)
            if latest and latest.timestamp == node.timestamp:
                del self.visited_urls[node.url]

    def get_recent_trajectory_context(self, steps: int = 4) -> str:
        if self._backend and self._session_id:
            return self._backend.get_recent_trajectory_context(
                steps, session_id=self._session_id
            )
        if not self.path_history:
            return "尚无探索轨迹。"
        
        self._prune_expired_status()
        recent_nodes = self.path_history[-steps:]
        context_lines = []
        for i, node in enumerate(recent_nodes):
            step_num = len(recent_nodes) - i
            context_lines.append(
                f"Step -{step_num}:\n"
                f"  - 访问 URL: {node.url}\n"
                f"  - 判定结果: {node.action_state}\n"
                f"  - 结论依据: {node.reason}"
            )
        return "\n".join(context_lines)

    def is_looping(self, drop_threshold: int = 3) -> bool:
        if self._backend and self._session_id:
            return self._backend.is_looping(drop_threshold, session_id=self._session_id)
        self._prune_expired_status()
        if len(self.path_history) < drop_threshold:
            return False
            
        recent_states = [node.action_state for node in self.path_history[-drop_threshold:]]
        
        # 定义属于“无效打转”的状态标签
        stuck_states = {"DROP", "DROP_IRRELEVANT", "ERROR", "BLOCKED", "DUPLICATE"}
        
        return all(state in stuck_states for state in recent_states)

    # ==========================================
    # 原有基础方法 (功能保留)
    # ==========================================
    
    def get_current_performance(self) -> Dict:
        """获取当前性能数据"""
        return self.current_performance.copy()
    
    def store_prompt_feedback(self, feedback: Dict):
        """存储 prompt 反馈 (最多保留10条)"""
        feedback['timestamp'] = time.time()
        self.prompt_feedback.append(feedback)
        if len(self.prompt_feedback) > 10:
            self.prompt_feedback = self.prompt_feedback[-10:]
            
    def get_recent_feedback(self, count: int = 5) -> List[Dict]:
        """获取最近的反馈"""
        return self.prompt_feedback[-count:] if self.prompt_feedback else []
        
    def update_performance(self, metrics: Dict):
        """更新性能指标"""
        self.current_performance.update(metrics)
        self.current_performance['last_update'] = time.time()
        
    def clear(self):
        """清空 file 模式本地工作记忆；Redis 模式由 reset_session 处理远端。"""
        self.current_performance = {}
        self.prompt_feedback = []
        self.real_time_metrics = {}
        if not self.uses_remote_backend():
            self.visited_urls.clear()
            self.path_history.clear()
        logger.info("🧹 WorkingMemory 已完全清空重置。")
