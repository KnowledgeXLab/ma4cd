# memory/managers/memory_manager.py
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional
from loguru import logger

# 延迟导入存储组件，避免初始化问题
def _get_working_memory():
    """延迟获取短期记忆存储"""
    from ..storage.working_memory import WorkingMemoryStorage
    return WorkingMemoryStorage()

def _get_session_memory():
    """延迟获取中期记忆存储"""
    from ..storage.session_memory import SessionMemoryStorage
    return SessionMemoryStorage()

def _get_persistent_memory():
    """延迟获取长期记忆存储"""
    try:
        from ..storage.persistent_memory import PersistentMemoryStorage
        return PersistentMemoryStorage()
    except Exception as e:
        logger.warning(f"长期记忆存储初始化失败，使用备用方案: {e}")
        return None

def _get_chroma_memory():
    """延迟获取向量记忆"""
    try:
        from ..chroma_memory import get_chroma_memory
        return get_chroma_memory()
    except Exception as e:
        logger.warning(f"向量记忆初始化失败: {e}")
        return None


class UnifiedMemoryManager:
    """
    统一记忆管理器
    协调三层记忆架构的交互
    """
    
    def __init__(self):
        # 延迟初始化存储组件
        self._working_memory = None
        self._session_memory = None
        self._persistent_memory = None
        self._chroma_memory = None
        
        # 当前会话
        self.current_sessions = {}
        
        logger.info("UnifiedMemoryManager 初始化完成")
    
    @property
    def working_memory(self):
        """获取短期记忆存储"""
        if self._working_memory is None:
            try:
                self._working_memory = _get_working_memory()
            except Exception as e:
                logger.error(f"短期记忆初始化失败: {e}")
                # 创建一个最小化的备用实现
                self._working_memory = SimpleMemoryBackup()
        return self._working_memory
    
    @property
    def session_memory(self):
        """获取中期记忆存储"""
        if self._session_memory is None:
            try:
                self._session_memory = _get_session_memory()
            except Exception as e:
                logger.error(f"中期记忆初始化失败: {e}")
                self._session_memory = SimpleMemoryBackup()
        return self._session_memory
    
    @property
    def persistent_memory(self):
        """获取长期记忆存储"""
        if self._persistent_memory is None:
            self._persistent_memory = _get_persistent_memory()
        return self._persistent_memory
    
    @property
    def chroma_memory(self):
        """获取向量记忆"""
        if self._chroma_memory is None:
            self._chroma_memory = _get_chroma_memory()
        return self._chroma_memory
    
    def start_session(self, task_info: Dict[str, Any]) -> str:
        """开始新的记忆会话"""
        
        session_id = str(uuid.uuid4())
        
        try:
            # 在中期记忆中创建会话
            if hasattr(self.session_memory, 'create_session'):
                self.session_memory.create_session(session_id, task_info)
            
            # 记录到当前会话
            self.current_sessions[session_id] = {
                'task_info': task_info,
                'started_at': datetime.now().isoformat(),
                'extraction_count': 0
            }
            
            logger.info(f"记忆会话已开始: {session_id}")
            return session_id
            
        except Exception as e:
            logger.error(f"开始记忆会话失败: {e}")
            # 即使存储失败，也返回会话ID，使用内存备份
            self.current_sessions[session_id] = {
                'task_info': task_info,
                'started_at': datetime.now().isoformat(),
                'extraction_count': 0
            }
            return session_id
    
    def record_extraction(self, session_id: str, domain: str, url: str,
                         site_profile: Dict, strategy_used: Dict, success: bool,
                         l3_candidates: List[Dict], execution_time: float,
                         error_message: str = None):
        """记录提取结果到记忆"""
        
        try:
            # 更新当前会话计数
            if session_id in self.current_sessions:
                self.current_sessions[session_id]['extraction_count'] += 1
            
            # 存储到短期记忆
            context_key = f"extraction_{domain}_{int(datetime.now().timestamp())}"
            extraction_data = {
                'domain': domain,
                'url': url,
                'site_profile': site_profile,
                'strategy_used': strategy_used,
                'success': success,
                'l3_count': len(l3_candidates),
                'execution_time': execution_time,
                'error_message': error_message,
                'timestamp': datetime.now().isoformat()
            }
            
            # 存储到短期记忆
            importance = 0.8 if success else 0.4
            if hasattr(self.working_memory, 'set'):
                self.working_memory.set(context_key, extraction_data, importance=importance)
            
            # 存储到中期记忆
            if hasattr(self.session_memory, 'record_extraction'):
                self.session_memory.record_extraction(
                    session_id, domain, url, site_profile, strategy_used,
                    success, l3_candidates, execution_time, error_message
                )
            
            # 存储到长期记忆
            if self.persistent_memory and hasattr(self.persistent_memory, 'store_website_knowledge'):
                self.persistent_memory.store_website_knowledge(
                    domain, site_profile, strategy_used, success,
                    len(l3_candidates), execution_time
                )
            
            # 存储到向量记忆
            if self.chroma_memory and hasattr(self.chroma_memory, 'store_website_knowledge'):
                self.chroma_memory.store_website_knowledge(
                    domain, site_profile, strategy_used, l3_candidates, success
                )
            
            logger.debug(f"提取结果已记录到记忆: {domain} (成功: {success})")
            
        except Exception as e:
            logger.error(f"记录提取结果失败: {e}")
    
    def get_recommendation(self, domain: str, site_profile: Dict) -> Dict[str, Any]:
        """获取记忆推荐"""
        
        try:
            recommendation = {
                'confidence': 0.3,  # 默认置信度
                'suggested_strategy': {'approach': 'adaptive', 'confidence_threshold': 0.4},
                'similar_sites': [],
                'historical_performance': None,
                'reasoning': ['使用默认策略']
            }
            
            # 从长期记忆获取历史表现
            if self.persistent_memory:
                try:
                    historical = self.persistent_memory.get_website_knowledge(domain)
                    if historical:
                        recommendation['historical_performance'] = historical
                        recommendation['confidence'] += 0.2
                        recommendation['reasoning'].append(f"找到历史记录，成功率: {historical.get('success_rate', 0):.2f}")
                except Exception as e:
                    logger.debug(f"获取历史记录失败: {e}")
            
            # 从向量记忆查找相似网站
            if self.chroma_memory:
                try:
                    similar_sites = self.chroma_memory.find_similar_websites(site_profile, limit=3)
                    if similar_sites:
                        recommendation['similar_sites'] = similar_sites
                        recommendation['confidence'] += 0.2
                        recommendation['reasoning'].append(f"找到 {len(similar_sites)} 个相似网站")
                        
                        # 基于相似网站调整策略
                        if similar_sites[0]['similarity'] > 0.7:
                            recommendation['confidence'] += 0.1
                            recommendation['reasoning'].append("高相似度网站匹配")
                except Exception as e:
                    logger.debug(f"查找相似网站失败: {e}")
            
            # 从短期记忆获取最近经验
            try:
                recent_extractions = []
                if hasattr(self.working_memory, 'get_all'):
                    all_items = self.working_memory.get_all()
                    for key, item in all_items.items():
                        if key.startswith('extraction_') and isinstance(item.value, dict):
                            recent_extractions.append(item.value)
                
                if recent_extractions:
                    success_rate = sum(1 for e in recent_extractions if e.get('success', False)) / len(recent_extractions)
                    recommendation['confidence'] += min(0.2, success_rate * 0.3)
                    recommendation['reasoning'].append(f"最近成功率: {success_rate:.2f}")
                    
            except Exception as e:
                logger.debug(f"获取最近经验失败: {e}")
            
            # 限制置信度范围
            recommendation['confidence'] = min(0.95, max(0.1, recommendation['confidence']))
            
            logger.debug(f"生成推荐 {domain}: 置信度 {recommendation['confidence']:.2f}")
            return recommendation
            
        except Exception as e:
            logger.error(f"获取记忆推荐失败: {e}")
            return {
                'confidence': 0.3,
                'suggested_strategy': {'approach': 'adaptive', 'confidence_threshold': 0.4},
                'similar_sites': [],
                'historical_performance': None,
                'reasoning': ['推荐生成失败，使用默认策略']
            }
    
    def end_session(self, session_id: str):
        """结束记忆会话"""
        
        try:
            if session_id in self.current_sessions:
                session_info = self.current_sessions[session_id]
                
                # 在中期记忆中结束会话
                if hasattr(self.session_memory, 'end_session'):
                    self.session_memory.end_session(session_id)
                
                # 清理当前会话
                del self.current_sessions[session_id]
                
                logger.info(f"记忆会话已结束: {session_id} (提取次数: {session_info['extraction_count']})")
            
        except Exception as e:
            logger.error(f"结束记忆会话失败: {e}")
    
    def get_memory_overview(self) -> Dict[str, Any]:
        """获取记忆系统概览"""
        
        try:
            overview = {
                'working_memory': {'total_items': 0, 'status': 'unavailable'},
                'session_memory': {'active_sessions': len(self.current_sessions), 'status': 'unavailable'},
                'persistent_memory': {'status': 'unavailable'},
                'chroma_memory': {'status': 'unavailable'}
            }
            
            # 短期记忆统计
            try:
                if hasattr(self.working_memory, 'get_stats'):
                    working_stats = self.working_memory.get_stats()
                    overview['working_memory'] = {**working_stats, 'status': 'available'}
            except Exception as e:
                logger.debug(f"获取短期记忆统计失败: {e}")
            
            # 中期记忆统计
            try:
                if hasattr(self.session_memory, 'get_stats'):
                    session_stats = self.session_memory.get_stats()
                    overview['session_memory'] = {**session_stats, 'status': 'available'}
                else:
                    overview['session_memory']['status'] = 'available'
            except Exception as e:
                logger.debug(f"获取中期记忆统计失败: {e}")
            
            # 长期记忆统计
            try:
                if self.persistent_memory and hasattr(self.persistent_memory, 'get_stats'):
                    persistent_stats = self.persistent_memory.get_stats()
                    overview['persistent_memory'] = {**persistent_stats, 'status': 'available'}
            except Exception as e:
                logger.debug(f"获取长期记忆统计失败: {e}")
            
            # 向量记忆统计
            try:
                if self.chroma_memory and hasattr(self.chroma_memory, 'get_stats'):
                    chroma_stats = self.chroma_memory.get_stats()
                    overview['chroma_memory'] = {**chroma_stats, 'status': 'available'}
            except Exception as e:
                logger.debug(f"获取向量记忆统计失败: {e}")
            
            return overview
            
        except Exception as e:
            logger.error(f"获取记忆概览失败: {e}")
            return {
                'working_memory': {'status': 'error'},
                'session_memory': {'status': 'error'},
                'persistent_memory': {'status': 'error'},
                'chroma_memory': {'status': 'error'}
            }


class SimpleMemoryBackup:
    """简单的内存备份实现"""
    
    def __init__(self):
        self.data = {}
    
    def set(self, key, value, importance=0.5):
        self.data[key] = {'value': value, 'importance': importance}
    
    def get(self, key):
        return self.data.get(key, {}).get('value')
    
    def get_all(self):
        return {k: type('Item', (), {'value': v['value']})() for k, v in self.data.items()}
    
    def get_stats(self):
        return {'total_items': len(self.data)}


# 全局实例
_unified_memory = None

def get_unified_memory() -> UnifiedMemoryManager:
    """获取全局统一记忆管理器"""
    global _unified_memory
    if _unified_memory is None:
        _unified_memory = UnifiedMemoryManager()
    return _unified_memory


# 便捷函数
def start_memory_session(task_info: Dict[str, Any]) -> str:
    """开始记忆会话"""
    return get_unified_memory().start_session(task_info)

def record_memory_extraction(session_id: str, domain: str, url: str,
                           site_profile: Dict, strategy_used: Dict, success: bool,
                           l3_candidates: List[Dict], execution_time: float,
                           error_message: str = None):
    """记录提取到记忆"""
    return get_unified_memory().record_extraction(
        session_id, domain, url, site_profile, strategy_used,
        success, l3_candidates, execution_time, error_message
    )

def get_memory_recommendation(domain: str, site_profile: Dict) -> Dict[str, Any]:
    """获取记忆推荐"""
    return get_unified_memory().get_recommendation(domain, site_profile)

def end_memory_session(session_id: str):
    """结束记忆会话"""
    return get_unified_memory().end_session(session_id)
