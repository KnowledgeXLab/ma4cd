# agents/miner/memory/storage/session_memory.py
import time
import json
import uuid
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from loguru import logger

# 路径锁定逻辑
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入内部模型
from ..models.memory_models import SessionSummary, LearningEvent, ExtractionContext, ExtractionResult

class SessionMemoryStorage:
    """
    中期记忆存储 - 混合动力锁定版
    🎯 核心修复：
    1. 引入单例模式，确保所有 Agent 实例共享同一份内存缓存。
    2. 引入 _last_active_id，强制将子任务的“孤儿数据”归并至当前主会话。
    """
    
    _instance = None
    _last_active_id = None  # 🌟 关键：类级别变量，锁定当前进程的主 Session

    def __new__(cls, *args, **kwargs):
        """实现单例模式"""
        if not cls._instance:
            cls._instance = super(SessionMemoryStorage, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, storage_dir: str = "./memory_data/sessions"):
        # 防止单例被重复初始化清空缓存
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存缓存活跃会话
        self._active_sessions: Dict[str, SessionSummary] = {}
        self._max_active_sessions = 10
        
        # 加载最近的活跃会话
        self._load_recent_sessions()
        
        self._initialized = True
        logger.info(f"✅ SessionMemoryStorage 单例加固完成: {self.storage_dir}")
    
    def _ensure_session_attributes(self, session: SessionSummary):
        """🔥 核心修复：强制初始化所有模型属性，防止落盘时报错"""
        defaults = {
            "end_time": None,
            "total_extractions": 0,
            "successful_extractions": 0,
            "total_l3_found": 0,
            "domains_processed": [],
            "learning_events": []
        }
        for attr, value in defaults.items():
            if not hasattr(session, attr) or getattr(session, attr) is None:
                if isinstance(value, list) and getattr(session, attr, None) is None:
                    setattr(session, attr, [])
                elif not hasattr(session, attr):
                    setattr(session, attr, value)

    def create_session(self, session_id: str, session_info: Dict[str, Any] = None) -> SessionSummary:
        """创建新会话并将其锁定为主 ID"""
        session = SessionSummary(
            session_id=session_id,
            start_time=datetime.now()
        )
        
        # 补全属性
        self._ensure_session_attributes(session)
        
        # 添加到活跃会话
        self._active_sessions[session_id] = session
        
        # 🌟 强制锚定：将其标记为全局最后活跃 ID
        SessionMemoryStorage._last_active_id = session_id
        
        self._manage_active_sessions()
        
        # 保存到文件
        self._save_session(session)
        
        logger.info(f"📂 [MASTER LOCK] 记忆会话已物理锁定: {session_id}")
        return session
    
    def get_session(self, session_id: str) -> Optional[SessionSummary]:
        """获取会话"""
        if session_id in self._active_sessions:
            return self._active_sessions[session_id]
        
        session = self._load_session(session_id)
        if session:
            self._ensure_session_attributes(session)
            self._active_sessions[session_id] = session
            self._manage_active_sessions()
            return session
        
        return None

    def record_extraction(self, session_id: str, domain: str, url: str,
                        site_profile: Dict, strategy_used: Dict, success: bool,
                        l3_candidates: List[Dict], execution_time: float,
                        error_message: str = None):
        """
        [关键修复接口] 对接 UnifiedMemoryManager
        🔥 改进：增加游离 ID 强制重定向逻辑，防止产生碎片 JSON
        """
        # 🌟 1. 强制归并逻辑
        # 如果传入的 ID 在内存中不存在，且我们手里握有活跃的主 ID，则强行归并
        if session_id not in self._active_sessions:
            if self._last_active_id and session_id != self._last_active_id:
                # logger.debug(f"检测到游离数据 (ID: {session_id[:8]}), 强制重定向至主会话: {self._last_active_id[:8]}")
                session_id = self._last_active_id

        session = self.get_session(session_id)
        
        # 2. 如果主 ID 也不存在，才执行补票
        if not session:
            logger.warning(f"⚠️ 会话 {session_id} 彻底失踪，执行最后的紧急补票...")
            session = self.create_session(session_id or str(uuid.uuid4()), {"auto_created": True})
            session_id = session.session_id
        
        # 组装 Event 链路
        context = ExtractionContext(
            domain=domain, url=url, site_profile=site_profile or {}, 
            strategy_used=strategy_used or {}, timestamp=datetime.now()
        )
        result = ExtractionResult(
            success=success, l3_count=len(l3_candidates) if l3_candidates else 0, 
            l3_candidates=l3_candidates or [], execution_time=execution_time, 
            error_message=error_message
        )
        
        event = LearningEvent(
            event_id=str(uuid.uuid4()),
            event_type="extraction_flow",
            context=context,
            result=result,
            timestamp=datetime.now(),
            importance=0.8 if success else 0.2
        )
        
        return self.add_learning_event(session_id, event)

    def add_learning_event(self, session_id: str, event: LearningEvent) -> bool:
        """添加学习事件并持久化"""
        session = self.get_session(session_id)
        if not session:
            return False
        
        self._ensure_session_attributes(session)
        session.learning_events.append(event)
        
        session.total_extractions += 1
        if event.result.success:
            session.successful_extractions += 1
            session.total_l3_found += event.result.l3_count
        
        if event.context.domain not in session.domains_processed:
            session.domains_processed.append(event.context.domain)
        
        # 强制保存
        self._save_session(session)
        logger.debug(f"📊 事件已合并入会话: {session_id[:8]} - {event.context.domain}")
        return True

    def close_session(self, session_id: str) -> bool:
        """关闭会话"""
        session = self.get_session(session_id)
        if not session:
            return False
        
        session.end_time = datetime.now()
        self._save_session(session)
        
        if session_id in self._active_sessions:
            del self._active_sessions[session_id]
        
        # 如果关闭的是主会话，清除主 ID 锁定
        if SessionMemoryStorage._last_active_id == session_id:
            SessionMemoryStorage._last_active_id = None
            
        logger.info(f"会话已成功关闭: {session_id}")
        return True

    def end_session(self, session_id: str) -> bool:
        """
        兼容接口：外部管理器使用 end_session 命名时，统一转发到 close_session。
        """
        return self.close_session(session_id)

    def _save_session(self, session: SessionSummary):
        """保存会话到文件"""
        session_file = self.storage_dir / f"session_{session.session_id}.json"
        try:
            session_data = {
                "session_id": session.session_id,
                "start_time": session.start_time.isoformat(),
                "end_time": session.end_time.isoformat() if getattr(session, 'end_time', None) else None,
                "total_extractions": getattr(session, 'total_extractions', 0),
                "successful_extractions": getattr(session, 'successful_extractions', 0),
                "total_l3_found": getattr(session, 'total_l3_found', 0),
                "domains_processed": getattr(session, 'domains_processed', []),
                "learning_events": [self._serialize_learning_event(e) for e in getattr(session, 'learning_events', [])]
            }
            
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"❌ 磁盘写入严重失败 {session.session_id}: {e}")

    # --- 辅助方法完全保留 ---

    def update_session(self, session_id: str, **updates) -> bool:
        session = self.get_session(session_id)
        if not session: return False
        for key, value in updates.items():
            if hasattr(session, key): setattr(session, key, value)
        self._save_session(session)
        return True

    def list_sessions(self, days_back: int = 7) -> List[Dict[str, Any]]:
        cutoff_date = datetime.now() - timedelta(days=days_back)
        sessions = []
        for session_file in self.storage_dir.glob("session_*.json"):
            try:
                session = self._load_session_from_file(session_file)
                if session and session.start_time >= cutoff_date:
                    sessions.append({
                        "session_id": session.session_id,
                        "start_time": session.start_time,
                        "end_time": getattr(session, 'end_time', None),
                        "total_extractions": getattr(session, 'total_extractions', 0)
                    })
            except: continue
        sessions.sort(key=lambda x: x["start_time"], reverse=True)
        return sessions

    def cleanup_old_sessions(self, days_to_keep: int = 30) -> int:
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        removed_count = 0
        for session_file in self.storage_dir.glob("session_*.json"):
            try:
                file_mtime = datetime.fromtimestamp(session_file.stat().st_mtime)
                if file_mtime < cutoff_date:
                    session_file.unlink()
                    removed_count += 1
            except: continue
        return removed_count

    def _load_session(self, session_id: str) -> Optional[SessionSummary]:
        session_file = self.storage_dir / f"session_{session_id}.json"
        return self._load_session_from_file(session_file)
    
    def _load_session_from_file(self, session_file: Path) -> Optional[SessionSummary]:
        if not session_file.exists(): return None
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            session = SessionSummary(session_id=data["session_id"], start_time=datetime.fromisoformat(data["start_time"]))
            session.end_time = datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None
            session.total_extractions = data.get("total_extractions", 0)
            session.successful_extractions = data.get("successful_extractions", 0)
            session.total_l3_found = data.get("total_l3_found", 0)
            raw_domains = data.get("domains_processed")
            session.domains_processed = list(raw_domains) if raw_domains else []
            raw_events = data.get("learning_events")
            session.learning_events = [self._deserialize_learning_event(e) for e in raw_events] if raw_events else []
            self._ensure_session_attributes(session)
            return session
        except Exception as e:
            logger.warning(f"⚠️ 会话文件加载失败: {e}")
            return None

    def _serialize_learning_event(self, event: LearningEvent) -> Dict[str, Any]:
        return {
            "event_id": str(event.event_id),
            "event_type": event.event_type,
            "context": {
                "domain": event.context.domain, "url": event.context.url,
                "site_profile": event.context.site_profile, "strategy_used": event.context.strategy_used,
                "timestamp": event.context.timestamp.isoformat()
            },
            "result": {
                "success": event.result.success, "l3_count": event.result.l3_count,
                "l3_candidates": event.result.l3_candidates, "execution_time": event.result.execution_time,
                "error_message": event.result.error_message,
                "performance_metrics": getattr(event.result, 'performance_metrics', {})
            },
            "insights": event.insights, "importance": event.importance, "timestamp": event.timestamp.isoformat()
        }
    
    def _deserialize_learning_event(self, data: Dict[str, Any]) -> LearningEvent:
        context = ExtractionContext(
            domain=data["context"]["domain"], url=data["context"]["url"],
            site_profile=data["context"].get("site_profile", {}),
            strategy_used=data["context"].get("strategy_used", {}),
            timestamp=datetime.fromisoformat(data["context"]["timestamp"])
        )
        result = ExtractionResult(
            success=data["result"]["success"], l3_count=data["result"]["l3_count"],
            l3_candidates=data["result"].get("l3_candidates", []),
            execution_time=data["result"].get("execution_time", 0.0),
            error_message=data["result"].get("error_message"),
            performance_metrics=data["result"].get("performance_metrics", {})
        )
        return LearningEvent(
            event_id=data["event_id"], event_type=data["event_type"], context=context,
            result=result, insights=data.get("insights", ""), importance=data.get("importance", 0.5),
            timestamp=datetime.fromisoformat(data["timestamp"])
        )

    def _load_recent_sessions(self):
        recent_files = sorted(self.storage_dir.glob("session_*.json"), key=os.path.getmtime, reverse=True)
        for f in recent_files[:5]:
            s = self._load_session_from_file(f)
            if s: self._active_sessions[s.session_id] = s

    def _manage_active_sessions(self):
        if len(self._active_sessions) <= self._max_active_sessions: return
        oldest_id = sorted(self._active_sessions.keys(), key=lambda x: self._active_sessions[x].start_time)[0]
        self._save_session(self._active_sessions[oldest_id])
        del self._active_sessions[oldest_id]

    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        session = self.get_session(session_id)
        if not session: return {}
        duration = (getattr(session, 'end_time', datetime.now()) - session.start_time).total_seconds()
        total = getattr(session, 'total_extractions', 0)
        success = getattr(session, 'successful_extractions', 0)
        return {
            "session_id": session.session_id, "duration_seconds": duration,
            "total_extractions": total, "successful_extractions": success,
            "success_rate": (success / total) if total > 0 else 0,
            "total_l3_found": getattr(session, 'total_l3_found', 0),
            "learning_events_count": len(getattr(session, 'learning_events', []))
        }

    def export_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """导出完整 session 供 SQLite 归档。"""
        session = self.get_session(session_id)
        if not session:
            session = self._load_session(session_id)
        if not session:
            return None
        self._ensure_session_attributes(session)
        return {
            "session_id": session.session_id,
            "start_time": session.start_time.isoformat() if session.start_time else None,
            "end_time": session.end_time.isoformat() if getattr(session, "end_time", None) else None,
            "total_extractions": getattr(session, "total_extractions", 0),
            "successful_extractions": getattr(session, "successful_extractions", 0),
            "total_l3_found": getattr(session, "total_l3_found", 0),
            "domains_processed": list(getattr(session, "domains_processed", []) or []),
            "learning_events": [
                self._serialize_learning_event(e)
                for e in getattr(session, "learning_events", []) or []
            ],
        }

# =========================================================
# 💡 保持原有辅助类兼容性
# =========================================================
class SessionMemory:
    def __init__(self):
        self.data, self.session_data, self.success_patterns = {}, {}, {}
        self.prompt_evolution_history, self.site_type_performance, self.reflection_history = [], {}, []
    def record_success_pattern(self, site_type, pattern):
        if site_type not in self.success_patterns: self.success_patterns[site_type] = []
        pattern['timestamp'] = time.time()
        self.success_patterns[site_type].append(pattern)
        if len(self.success_patterns[site_type]) > 5: self.success_patterns[site_type] = self.success_patterns[site_type][-5:]
    def add(self, key, value):
        if key == 'success_patterns': self.record_success_pattern(value['site_type'], value['pattern'])
        elif key == 'reflection_experience': self.reflection_history.append({"timestamp": time.time(), "reflection": value})
