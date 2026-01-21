# memory/storage/working_memory.py
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from collections import defaultdict
from loguru import logger

from ..models.memory_models import MemoryItem, ImportanceLevel


class WorkingMemoryStorage:
    """
    短期记忆存储 - 纯内存实现
    用于存储当前任务的临时状态和快速访问的数据
    """
    
    def __init__(self, max_items: int = 1000, cleanup_interval: int = 300):
        self._storage: Dict[str, MemoryItem] = {}
        self._lock = threading.RLock()
        self._max_items = max_items
        self._cleanup_interval = cleanup_interval
        
        # 按标签索引
        self._tag_index: Dict[str, set] = defaultdict(set)
        
        # 启动清理线程
        self._start_cleanup_thread()
        
        logger.info(f"WorkingMemoryStorage 初始化完成 (最大项目: {max_items})")
    
    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = 3600,
            importance: float = ImportanceLevel.MEDIUM.value, 
            tags: List[str] = None) -> bool:
        """设置短期记忆项"""
        
        with self._lock:
            # 检查容量限制
            if len(self._storage) >= self._max_items and key not in self._storage:
                self._evict_least_important()
            
            # 创建记忆项
            item = MemoryItem(
                key=key,
                value=value,
                importance=importance,
                tags=tags or [],
                ttl_seconds=ttl_seconds
            )
            
            # 更新标签索引
            if key in self._storage:
                self._remove_from_tag_index(key, self._storage[key].tags)
            
            self._storage[key] = item
            self._add_to_tag_index(key, item.tags)
            
            logger.debug(f"短期记忆已设置: {key} (TTL: {ttl_seconds}s, 重要性: {importance})")
            return True
    
    def get(self, key: str) -> Optional[Any]:
        """获取短期记忆项"""
        
        with self._lock:
            if key not in self._storage:
                return None
            
            item = self._storage[key]
            
            # 检查是否过期
            if item.is_expired():
                self._remove_item(key)
                return None
            
            # 记录访问
            item.access()
            return item.value
    
    def get_by_tags(self, tags: List[str], match_all: bool = False) -> Dict[str, Any]:
        """根据标签获取记忆项"""
        
        with self._lock:
            result = {}
            
            if match_all:
                # 必须匹配所有标签
                candidate_keys = None
                for tag in tags:
                    tag_keys = self._tag_index.get(tag, set())
                    if candidate_keys is None:
                        candidate_keys = tag_keys.copy()
                    else:
                        candidate_keys &= tag_keys
                
                if candidate_keys:
                    for key in candidate_keys:
                        value = self.get(key)  # 使用 get 方法检查过期
                        if value is not None:
                            result[key] = value
            else:
                # 匹配任一标签
                candidate_keys = set()
                for tag in tags:
                    candidate_keys.update(self._tag_index.get(tag, set()))
                
                for key in candidate_keys:
                    value = self.get(key)
                    if value is not None:
                        result[key] = value
            
            return result
    
    def update_importance(self, key: str, importance_delta: float) -> bool:
        """更新重要性"""
        
        with self._lock:
            if key not in self._storage:
                return False
            
            item = self._storage[key]
            item.importance = max(0.0, min(1.0, item.importance + importance_delta))
            
            logger.debug(f"重要性已更新: {key} -> {item.importance}")
            return True
    
    def remove(self, key: str) -> bool:
        """删除记忆项"""
        
        with self._lock:
            return self._remove_item(key)
    
    def clear_by_tags(self, tags: List[str]) -> int:
        """根据标签清除记忆项"""
        
        with self._lock:
            items_to_remove = set()
            
            for tag in tags:
                items_to_remove.update(self._tag_index.get(tag, set()))
            
            removed_count = 0
            for key in items_to_remove:
                if self._remove_item(key):
                    removed_count += 1
            
            logger.info(f"根据标签清除了 {removed_count} 个记忆项: {tags}")
            return removed_count
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        
        with self._lock:
            total_items = len(self._storage)
            high_importance = sum(1 for item in self._storage.values() 
                                if item.importance > ImportanceLevel.HIGH.value)
            frequently_accessed = sum(1 for item in self._storage.values() 
                                    if item.access_count > 5)
            
            # 按标签统计
            tag_stats = {tag: len(keys) for tag, keys in self._tag_index.items()}
            
            return {
                "total_items": total_items,
                "high_importance_items": high_importance,
                "frequently_accessed_items": frequently_accessed,
                "tag_distribution": tag_stats,
                "capacity_usage": f"{total_items}/{self._max_items}"
            }
    
    def _remove_item(self, key: str) -> bool:
        """内部删除方法"""
        
        if key not in self._storage:
            return False
        
        item = self._storage[key]
        self._remove_from_tag_index(key, item.tags)
        del self._storage[key]
        
        return True
    
    def _add_to_tag_index(self, key: str, tags: List[str]):
        """添加到标签索引"""
        for tag in tags:
            self._tag_index[tag].add(key)
    
    def _remove_from_tag_index(self, key: str, tags: List[str]):
        """从标签索引中移除"""
        for tag in tags:
            self._tag_index[tag].discard(key)
            if not self._tag_index[tag]:
                del self._tag_index[tag]
    
    def _evict_least_important(self):
        """驱逐最不重要的项目"""
        
        if not self._storage:
            return
        
        # 找到重要性最低且访问次数最少的项目
        least_important_key = min(
            self._storage.keys(),
            key=lambda k: (self._storage[k].importance, self._storage[k].access_count)
        )
        
        self._remove_item(least_important_key)
        logger.debug(f"驱逐最不重要的项目: {least_important_key}")
    
    def _cleanup_expired(self):
        """清理过期项目"""
        
        with self._lock:
            expired_keys = [
                key for key, item in self._storage.items() 
                if item.is_expired()
            ]
            
            for key in expired_keys:
                self._remove_item(key)
            
            if expired_keys:
                logger.debug(f"清理了 {len(expired_keys)} 个过期项目")
    
    def _start_cleanup_thread(self):
        """启动清理线程"""
        
        def cleanup_worker():
            import time
            while True:
                try:
                    self._cleanup_expired()
                    time.sleep(self._cleanup_interval)
                except Exception as e:
                    logger.error(f"短期记忆清理异常: {e}")
                    time.sleep(60)
        
        import threading
        cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        cleanup_thread.start()
