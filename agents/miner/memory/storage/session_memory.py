# memory/storage/session_memory.py
import time
import json
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger

from ..models.memory_models import SessionSummary, LearningEvent, ExtractionContext, ExtractionResult


class SessionMemoryStorage:
    """
    中期记忆存储 - 文件+内存混合实现
    用于存储单次挖掘任务的完整上下文和学习轨迹
    """
    
    def __init__(self, storage_dir: str = "./memory_data/sessions"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存缓存活跃会话
        self._active_sessions: Dict[str, SessionSummary] = {}
        self._max_active_sessions = 10
        
        # 加载最近的活跃会话
        self._load_recent_sessions()
        
        logger.info(f"SessionMemoryStorage 初始化完成: {self.storage_dir}")
    
    def create_session(self, session_id: str, session_info: Dict[str, Any]) -> SessionSummary:
        """创建新会话"""
        
        session = SessionSummary(
            session_id=session_id,
            start_time=datetime.now()
        )
        
        # 添加到活跃会话
        self._active_sessions[session_id] = session
        
        # 管理活跃会话数量
        self._manage_active_sessions()
        
        # 保存到文件
        self._save_session(session)
        
        logger.info(f"会话已创建: {session_id}")
        return session
    
    def get_session(self, session_id: str) -> Optional[SessionSummary]:
        """获取会话"""
        
        # 先从内存缓存查找
        if session_id in self._active_sessions:
            return self._active_sessions[session_id]
        
        # 从文件加载
        session = self._load_session(session_id)
        if session:
            # 加入活跃会话
            self._active_sessions[session_id] = session
            self._manage_active_sessions()
        
        return session
    
    def update_session(self, session_id: str, **updates) -> bool:
        """更新会话信息"""
        
        session = self.get_session(session_id)
        if not session:
            logger.warning(f"会话不存在: {session_id}")
            return False
        
        # 更新字段
        for key, value in updates.items():
            if hasattr(session, key):
                setattr(session, key, value)
        
        # 保存更新
        self._save_session(session)
        
        logger.debug(f"会话已更新: {session_id}")
        return True
    
    def add_learning_event(self, session_id: str, event: LearningEvent) -> bool:
        """添加学习事件"""
        
        session = self.get_session(session_id)
        if not session:
            logger.warning(f"会话不存在: {session_id}")
            return False
        
        # 添加事件
        session.learning_events.append(event)
        
        # 更新统计
        session.total_extractions += 1
        if event.result.success:
            session.successful_extractions += 1
            session.total_l3_found += event.result.l3_count
        
        # 更新域名列表
        if event.context.domain not in session.domains_processed:
            session.domains_processed.append(event.context.domain)
        
        # 保存更新
        self._save_session(session)
        
        logger.debug(f"学习事件已添加: {session_id} - {event.event_type}")
        return True
    
    def get_learning_events(self, session_id: str, 
                           event_type: Optional[str] = None,
                           limit: Optional[int] = None) -> List[LearningEvent]:
        """获取学习事件"""
        
        session = self.get_session(session_id)
        if not session:
            return []
        
        events = session.learning_events
        
        # 按类型过滤
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        # 限制数量（返回最新的）
        if limit:
            events = events[-limit:]
        
        return events
    
    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """获取会话统计"""
        
        session = self.get_session(session_id)
        if not session:
            return {}
        
        duration = None
        if session.end_time:
            duration = (session.end_time - session.start_time).total_seconds()
        else:
            duration = (datetime.now() - session.start_time).total_seconds()
        
        return {
            "session_id": session.session_id,
            "duration_seconds": duration,
            "total_extractions": session.total_extractions,
            "successful_extractions": session.successful_extractions,
            "success_rate": session.success_rate,
            "total_l3_found": session.total_l3_found,
            "avg_l3_per_extraction": session.avg_l3_per_extraction,
            "domains_processed": len(session.domains_processed),
            "learning_events_count": len(session.learning_events)
        }
    
    def close_session(self, session_id: str) -> bool:
        """关闭会话"""
        
        session = self.get_session(session_id)
        if not session:
            return False
        
        session.end_time = datetime.now()
        self._save_session(session)
        
        # 从活跃会话中移除
        if session_id in self._active_sessions:
            del self._active_sessions[session_id]
        
        logger.info(f"会话已关闭: {session_id}")
        return True
    
    def list_sessions(self, days_back: int = 7) -> List[Dict[str, Any]]:
        """列出最近的会话"""
        
        cutoff_date = datetime.now() - timedelta(days=days_back)
        sessions = []
        
        # 扫描会话文件
        for session_file in self.storage_dir.glob("session_*.json"):
            try:
                session = self._load_session_from_file(session_file)
                if session and session.start_time >= cutoff_date:
                    sessions.append({
                        "session_id": session.session_id,
                        "start_time": session.start_time,
                        "end_time": session.end_time,
                        "success_rate": session.success_rate,
                        "total_extractions": session.total_extractions,
                        "domains_count": len(session.domains_processed)
                    })
            except Exception as e:
                logger.warning(f"加载会话文件失败 {session_file}: {e}")
        
        # 按开始时间排序
        sessions.sort(key=lambda x: x["start_time"], reverse=True)
        return sessions
    
    def cleanup_old_sessions(self, days_to_keep: int = 30) -> int:
        """清理旧会话"""
        
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        removed_count = 0
        
        for session_file in self.storage_dir.glob("session_*.json"):
            try:
                # 检查文件修改时间
                file_mtime = datetime.fromtimestamp(session_file.stat().st_mtime)
                if file_mtime < cutoff_date:
                    session_file.unlink()
                    removed_count += 1
            except Exception as e:
                logger.warning(f"清理会话文件失败 {session_file}: {e}")
        
        logger.info(f"清理了 {removed_count} 个旧会话文件")
        return removed_count
    
    def _save_session(self, session: SessionSummary):
        """保存会话到文件"""
        
        session_file = self.storage_dir / f"session_{session.session_id}.json"
        
        try:
            # 转换为可序列化的格式
            session_data = {
                "session_id": session.session_id,
                "start_time": session.start_time.isoformat(),
                "end_time": session.end_time.isoformat() if session.end_time else None,
                "total_extractions": session.total_extractions,
                "successful_extractions": session.successful_extractions,
                "total_l3_found": session.total_l3_found,
                "domains_processed": session.domains_processed,
                "learning_events": [self._serialize_learning_event(e) for e in session.learning_events]
            }
            
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"保存会话失败 {session.session_id}: {e}")
    
    def _load_session(self, session_id: str) -> Optional[SessionSummary]:
        """从文件加载会话"""
        
        session_file = self.storage_dir / f"session_{session_id}.json"
        return self._load_session_from_file(session_file)
    
    def _load_session_from_file(self, session_file: Path) -> Optional[SessionSummary]:
        """从文件加载会话"""
        
        if not session_file.exists():
            return None
        
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 重构会话对象
            session = SessionSummary(
                session_id=data["session_id"],
                start_time=datetime.fromisoformat(data["start_time"]),
                end_time=datetime.fromisoformat(data["end_time"]) if data["end_time"] else None,
                total_extractions=data["total_extractions"],
                successful_extractions=data["successful_extractions"],
                total_l3_found=data["total_l3_found"],
                domains_processed=data["domains_processed"],
                learning_events=[self._deserialize_learning_event(e) for e in data["learning_events"]]
            )
            
            return session
            
        except Exception as e:
            logger.error(f"加载会话失败 {session_file}: {e}")
            return None
    
    def _serialize_learning_event(self, event: LearningEvent) -> Dict[str, Any]:
        """序列化学习事件"""
        
        return {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "context": {
                "domain": event.context.domain,
                "url": event.context.url,
                "site_profile": event.context.site_profile,
                "strategy_used": event.context.strategy_used,
                "timestamp": event.context.timestamp.isoformat()
            },
            "result": {
                "success": event.result.success,
                "l3_count": event.result.l3_count,
                "l3_candidates": event.result.l3_candidates,
                "execution_time": event.result.execution_time,
                "error_message": event.result.error_message,
                "performance_metrics": event.result.performance_metrics
            },
            "insights": event.insights,
            "importance": event.importance,
            "timestamp": event.timestamp.isoformat()
        }
    
    def _deserialize_learning_event(self, data: Dict[str, Any]) -> LearningEvent:
        """反序列化学习事件"""
        
        context = ExtractionContext(
            domain=data["context"]["domain"],
            url=data["context"]["url"],
            site_profile=data["context"]["site_profile"],
            strategy_used=data["context"]["strategy_used"],
            timestamp=datetime.fromisoformat(data["context"]["timestamp"])
        )
        
        result = ExtractionResult(
            success=data["result"]["success"],
            l3_count=data["result"]["l3_count"],
            l3_candidates=data["result"]["l3_candidates"],
            execution_time=data["result"]["execution_time"],
            error_message=data["result"]["error_message"],
            performance_metrics=data["result"]["performance_metrics"]
        )
        
        return LearningEvent(
            event_id=data["event_id"],
            event_type=data["event_type"],
            context=context,
            result=result,
            insights=data["insights"],
            importance=data["importance"],
            timestamp=datetime.fromisoformat(data["timestamp"])
        )
    
    def _load_recent_sessions(self):
        """加载最近的活跃会话"""
        
        recent_sessions = self.list_sessions(days_back=1)
        
        for session_info in recent_sessions[:self._max_active_sessions]:
            session = self._load_session(session_info["session_id"])
            if session:
                self._active_sessions[session.session_id] = session
        
        logger.info(f"加载了 {len(self._active_sessions)} 个活跃会话")
    
    def _manage_active_sessions(self):
        """管理活跃会话数量"""
        
        if len(self._active_sessions) <= self._max_active_sessions:
            return
        
        # 按最后访问时间排序，移除最旧的
        sessions_by_time = sorted(
            self._active_sessions.items(),
            key=lambda x: x[1].start_time
        )
        
        # 移除最旧的会话
        sessions_to_remove = sessions_by_time[:-self._max_active_sessions]
        for session_id, session in sessions_to_remove:
            # 确保保存到文件
            self._save_session(session)
            del self._active_sessions[session_id]
        
        logger.debug(f"管理活跃会话: 移除了 {len(sessions_to_remove)} 个会话")


class SessionMemory:
    """会话记忆 - 存储单次挖掘任务的完整经验"""
    
    def __init__(self):
        self.data = {}
        self.session_data = {}
        self.success_patterns = {}
        self.prompt_evolution_history = []
        self.site_type_performance = {}
        self.reflection_history = []  # 新增字段用于存储反思数据
        
    def get_success_patterns(self) -> Dict:
        """获取成功模式"""
        return self.success_patterns.copy()
    
    def get_success_patterns_for_site_type(self, site_type: str) -> Dict:
        """获取特定网站类型的成功模式"""
        return self.success_patterns.get(site_type, {})
    
    def store_prompt_evolution(self, evolution_data: Dict):
        """存储prompt进化数据"""
        evolution_entry = {
            'timestamp': time.time(),
            'evolution_data': evolution_data
        }
        self.prompt_evolution_history.append(evolution_entry)
    
    def record_success_pattern(self, site_type: str, pattern: Dict):
        """记录成功模式"""
        if site_type not in self.success_patterns:
            self.success_patterns[site_type] = []
        
        pattern['timestamp'] = time.time()
        self.success_patterns[site_type].append(pattern)
        
        # 只保留最近的5个模式
        if len(self.success_patterns[site_type]) > 5:
            self.success_patterns[site_type] = self.success_patterns[site_type][-5:]
    
    def update_site_performance(self, site_type: str, performance: Dict):
        """更新网站类型性能"""
        if site_type not in self.site_type_performance:
            self.site_type_performance[site_type] = []
        
        performance['timestamp'] = time.time()
        self.site_type_performance[site_type].append(performance)
    
    def get_session_summary(self) -> Dict:
        """获取会话摘要"""
        return {
            'total_patterns': len(self.success_patterns),
            'evolution_count': len(self.prompt_evolution_history),
            'site_types_processed': list(self.site_type_performance.keys())
        }

    # 新增的 Reflection 存储接口
    def store_reflection(self, reflection: Dict):
        """存储反思数据"""
        self.reflection_history.append({
            "timestamp": time.time(),
            "reflection": reflection
        })
        
    # 修改后的 add 方法
    def add(self, key: str, value: Any):
        """添加数据到会话记忆"""
        if key == 'success_patterns':
            self.record_success_pattern(value['site_type'], value['pattern'])
        elif key == 'prompt_evolution':
            self.store_prompt_evolution(value)
        elif key == 'site_performance':
            self.update_site_performance(value['site_type'], value['performance'])
        elif key == 'reflection_experience':
            self.store_reflection(value)  # 改为调用 store_reflection 方法
        else:
            logger.warning(f"Unknown key for add: {key}")
