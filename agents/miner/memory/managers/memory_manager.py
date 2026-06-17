import sys
import os
import uuid
import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Union
from loguru import logger

# =========================================================
# 🛠️ 核心路径锁定
# =========================================================
current_dir = os.path.dirname(os.path.abspath(__file__))
# 向上跳四级到达 ma4cd 根目录
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# =========================================================
# 📦 引入专属记忆模型 (作为数据入库前的安检门)
# =========================================================
try:
    from agents.miner.memory.models.memory_models import ExtractionContext, ExtractionResult
except ImportError as e:
    logger.error(f"❌ Miner 模型导入失败，请检查路径: {e}")
    # 动态构建兜底类，防止系统因为导入失败而彻底崩溃
    class ExtractionContext:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class ExtractionResult:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)

# =========================================================
# 🏗️ 延迟导入工厂 (升级为全路径绝对导入，彻底解决模块找不到问题)
# =========================================================

def _get_working_memory():
    """延迟获取短期记忆存储"""
    from agents.miner.memory.storage.working_memory import WorkingMemoryStorage
    return WorkingMemoryStorage()

def _get_session_memory():
    """延迟获取中期记忆存储"""
    from agents.miner.memory.storage.session_memory import SessionMemoryStorage
    return SessionMemoryStorage()

def _get_persistent_memory():
    """延迟获取长期记忆存储"""
    try:
        from agents.miner.memory.storage.persistent_memory import PersistentMemoryStorage
        return PersistentMemoryStorage()
    except Exception as e:
        logger.warning(f"长期记忆存储初始化失败，使用备用方案: {e}")
        return None

def _chroma_memory_disabled() -> bool:
    import os
    v = os.getenv("MA4CD_DISABLE_CHROMA_MEMORY", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _get_chroma_memory():
    """延迟获取向量记忆"""
    if _chroma_memory_disabled():
        return None
    try:
        from agents.miner.memory.chroma_memory import get_chroma_memory
        return get_chroma_memory()
    except Exception as e:
        logger.warning(f"向量记忆初始化失败: {e}")
        return None


def _get_memory_bundle():
    """按 MA4CD_MEMORY_BACKEND 加载 Redis 后端；file 模式返回 None。"""
    try:
        from agents.miner.memory.backends.factory import get_memory_backend
        return get_memory_backend()
    except Exception as e:
        logger.warning(f"Redis 记忆后端不可用，使用 file 模式: {e}")
        return None


class UnifiedMemoryManager:
    """
    统一记忆管理器
    协调 Working, Session, Persistent, Chroma 四层记忆架构
    """
    
    def __init__(self, db_path=None):
        self._working_memory = None
        self._session_memory = None
        self._persistent_memory = None
        self._chroma_memory = None
        self._bundle = _get_memory_bundle()
        self.active_session_id = None
        
        self.db_path = db_path
        self.current_sessions = {}
        
        backend_name = "redis" if self._bundle else "file"
        logger.info(f"UnifiedMemoryManager 初始化完成 | backend={backend_name}")
    
    @property
    def coordination(self):
        """跨 worker 协调层（仅 redis 模式可用）。"""
        if self._bundle:
            return self._bundle.coordination
        return None

    def create_working_memory(self):
        """为 Miner 创建带后端绑定的工作记忆（轨迹 + Redis 协调）。"""
        from agents.miner.memory.storage.working_memory import WorkingMemory
        if self._bundle:
            return WorkingMemory(backend=self._bundle.working)
        return WorkingMemory()
    
    # --- 属性访问器 (动态单例加载) ---
    
    @property
    def working_memory(self):
        if self._working_memory is None:
            try:
                if self._bundle:
                    self._working_memory = self._bundle.working
                else:
                    self._working_memory = _get_working_memory()
            except Exception as e:
                logger.error(f"短期记忆初始化失败: {e}")
                self._working_memory = SimpleMemoryBackup()
        return self._working_memory
    
    @property
    def session_memory(self):
        if self._session_memory is None:
            try:
                if self._bundle:
                    self._session_memory = self._bundle.session
                else:
                    self._session_memory = _get_session_memory()
            except Exception as e:
                logger.error(f"中期记忆初始化失败: {e}")
                self._session_memory = SimpleMemoryBackup()
        return self._session_memory
    
    @property
    def persistent_memory(self):
        if self._persistent_memory is None:
            self._persistent_memory = _get_persistent_memory()
        return self._persistent_memory
    
    @property
    def chroma_memory(self):
        if self._chroma_memory is None:
            self._chroma_memory = _get_chroma_memory()
        return self._chroma_memory

    @property
    def storage(self):
        """兼容 EvolutionEngine 的接口别名"""
        return self.persistent_memory
    
    # =========================================================
    # 🧬 进化与透传接口 (Memory 1 & 3)
    # =========================================================

    def get_active_instructions(self, domain: str, agent_name: str = "Miner") -> List[str]:
        """获取用户指令 (Memory 3)"""
        if self.persistent_memory and hasattr(self.persistent_memory, 'get_active_instructions'):
            return self.persistent_memory.get_active_instructions(domain, agent_name)
        return []

    def store_strategy_evolution(self, domain: str, strategy_config: Dict, performance_score: float):
        """存储进化配置 (Memory 1)"""
        if self.persistent_memory and hasattr(self.persistent_memory, 'store_strategy_evolution'):
            self.persistent_memory.store_strategy_evolution(domain, strategy_config, performance_score)

    def store_strategy_evolution_with_mode(self, domain: str, strategy_config: Dict, performance_score: float, is_active: bool):
        """存储进化配置（支持 active/shadow 灰度）"""
        if self.persistent_memory and hasattr(self.persistent_memory, 'store_strategy_evolution'):
            self.persistent_memory.store_strategy_evolution(
                domain=domain,
                strategy_config=strategy_config,
                performance_score=performance_score,
                is_active=is_active
            )

    def get_best_experience(self, domain: str) -> Optional[Dict]:
        """获取历史最佳策略"""
        try:
            if self.persistent_memory:
                if hasattr(self.persistent_memory, 'get_best_strategy'):
                    best_strat = self.persistent_memory.get_best_strategy(domain)
                    if best_strat: return best_strat

                if hasattr(self.persistent_memory, 'get_website_knowledge'):
                    knowledge = self.persistent_memory.get_website_knowledge(domain)
                    if knowledge:
                        return {
                            "config": knowledge.get("strategy_used", {}),
                            "success_rate": knowledge.get("success_rate", 0)
                        }
            return None
        except Exception as e:
            logger.warning(f"获取最佳经验失败 ({domain}): {e}")
            return None

    def get_active_strategy(self, domain: str) -> Optional[Dict]:
        """获取域名激活策略（优先用于运行时）"""
        try:
            if self.persistent_memory and hasattr(self.persistent_memory, 'get_latest_active_strategy'):
                return self.persistent_memory.get_latest_active_strategy(domain)
        except Exception as e:
            logger.warning(f"获取激活策略失败 ({domain}): {e}")
        return None

    # =========================================================
    # 📝 记录与会话管理
    # =========================================================

    def start_session(self, task_info: Dict[str, Any], session_id: str = None) -> str:
            """
            启动会话。
            默认每次任务创建独立会话；仅在显式开启复用时沿用 active_session_id。
            """
            allow_reuse = str(os.getenv("MA4CD_REUSE_ACTIVE_SESSION", "0")).strip().lower() in ("1", "true", "yes", "on")

            # 显式开启复用且外部未强制指定新 ID 时，沿用活跃会话
            if allow_reuse and self.active_session_id and not session_id:
                logger.debug(f"沿用已存在的活跃会话: {self.active_session_id}")
                return self.active_session_id

            # 确定最终要使用的 ID (优先使用传入的，其次生成新的)
            final_id = session_id or str(uuid.uuid4())
            self.active_session_id = final_id
            
            try:
                storage = self.session_memory
                exists = final_id in self.current_sessions
                if not exists and hasattr(storage, "get_session"):
                    exists = storage.get_session(final_id) is not None
                if not exists:
                    if hasattr(storage, 'create_session'):
                        storage.create_session(final_id, task_info)
                    
                    self.current_sessions[final_id] = {
                        'task_info': task_info,
                        'started_at': datetime.now().isoformat(),
                        'extraction_count': 0
                    }
                    logger.info(f"🚀 记忆会话已锁定并初始化: {final_id}")
                else:
                    self.current_sessions.setdefault(final_id, {
                        'task_info': task_info,
                        'started_at': datetime.now().isoformat(),
                        'extraction_count': 0,
                    })

                if self.coordination:
                    self.coordination.set_active_session_id(final_id)
                    self.coordination.sync_runtime(final_id, task_info=task_info, extraction_count=0)
                return final_id
            except Exception as e:
                logger.error(f"开始记忆会话失败: {e}")
                return self.active_session_id
    
    def record_extraction(self, session_id: str, domain: str, url: str,
                            site_profile: Dict, strategy_used: Dict, success: bool,
                            l3_candidates: List[Dict], execution_time: float,
                            error_message: str = None):
            """
            核心记录方法
            🔥 修复版：通过 effective_session_id 强制对齐，解决自动补票导致的碎片化问题
            """
            try:
                # 🌟 第一步：计算有效会话 ID (核心修复点)
                # 逻辑：优先使用管理器通过 start_session 锁定的 ID，如果没锁，才用传入的
                effective_id = getattr(self, 'active_session_id', None) or session_id
                
                if not effective_id:
                    # 最后的兜底，防止因为没有 ID 导致数据丢失
                    effective_id = f"RESCUE_{uuid.uuid4().hex[:8]}"
                    logger.warning(f"⚠️ 无法识别会话来源，触发紧急救援 ID: {effective_id}")

                # 统计计数更新
                if effective_id in self.current_sessions:
                    self.current_sessions[effective_id]['extraction_count'] += 1
                    if self.coordination:
                        self.coordination.sync_runtime(
                            effective_id,
                            extraction_count=self.current_sessions[effective_id]['extraction_count'],
                        )
                    
                # 🚀 1. 利用模型充当安检门，进行数据合法性校验
                safe_context = ExtractionContext(
                    domain=domain,
                    url=url,
                    site_profile=site_profile or {},
                    strategy_used=strategy_used or {}
                )
                
                safe_result = ExtractionResult(
                    success=bool(success),
                    l3_count=len(l3_candidates) if l3_candidates else 0,
                    l3_candidates=l3_candidates or [],
                    execution_time=float(execution_time),
                    error_message=str(error_message) if error_message else None
                )

                # 提取清洗后的安全数据
                clean_domain = getattr(safe_context, 'domain', domain)
                clean_url = getattr(safe_context, 'url', url)
                clean_site_profile = getattr(safe_context, 'site_profile', site_profile)
                clean_strategy = getattr(safe_context, 'strategy_used', strategy_used)
                
                clean_success = getattr(safe_result, 'success', success)
                clean_l3_candidates = getattr(safe_result, 'l3_candidates', l3_candidates)
                clean_exec_time = getattr(safe_result, 'execution_time', execution_time)
                clean_error = getattr(safe_result, 'error_message', error_message)

                # 2. 存储到短期记忆 (Working) 
                context_key = f"extraction_{clean_domain}_{int(datetime.now().timestamp())}"
                extraction_data = {
                    'domain': clean_domain, 
                    'url': clean_url, 
                    'site_profile': clean_site_profile,
                    'strategy_used': clean_strategy, 
                    'success': clean_success,
                    'l3_count': getattr(safe_result, 'l3_count', len(clean_l3_candidates)), 
                    'execution_time': clean_exec_time,
                    'error_message': clean_error, 
                    'timestamp': datetime.now().isoformat()
                }
                if hasattr(self.working_memory, 'set'):
                    set_kwargs = {
                        "importance": (0.8 if clean_success else 0.4),
                    }
                    if self._bundle:
                        set_kwargs["session_id"] = effective_id
                    self.working_memory.set(context_key, extraction_data, **set_kwargs)
                
                # 🌟 3. 存储到中期记忆 (Session) - 强制使用 effective_id
                if hasattr(self.session_memory, 'record_extraction'):
                    self.session_memory.record_extraction(
                        effective_id, clean_domain, clean_url, clean_site_profile, 
                        clean_strategy, clean_success, clean_l3_candidates, 
                        clean_exec_time, clean_error
                    )
                
                # 🌟 4. 存储到长期记忆 (Persistent) - 强制使用 effective_id
                if self.persistent_memory:
                    if hasattr(self.persistent_memory, 'record_extraction'):
                        self.persistent_memory.record_extraction(
                            effective_id, clean_domain, clean_url, clean_site_profile, 
                            clean_strategy, clean_success, clean_l3_candidates, 
                            clean_exec_time, clean_error
                        )
                
                # 5. 存储到向量记忆 (Chroma)
                if self.chroma_memory and hasattr(self.chroma_memory, 'store_website_knowledge'):
                    self.chroma_memory.store_website_knowledge(
                        clean_domain, clean_site_profile, clean_strategy, 
                        clean_l3_candidates, clean_success
                    )
                
                logger.debug(f"📊 [Session: {effective_id}] 记录入库: {clean_domain} (成功: {clean_success})")
                
            except Exception as e:
                logger.error(f"❌ 记录提取结果失败: {e}")


    def update_path_efficiency(self, domain: str, path_url: str, found_count: int):
        """
        🔥 新增：记录路径的产出效率 (连接到 Memory 2 的 path_intelligence 表)
        """
        try:
            if self.persistent_memory and hasattr(self.persistent_memory, 'update_path_efficiency'):
                self.persistent_memory.update_path_efficiency(domain, path_url, found_count)
                logger.debug(f"🛤️ 路径效率透传成功: {path_url} -> 产出 {found_count} 个")
        except Exception as e:
            logger.error(f"路径效率透传失败: {e}")

    def get_top_path_efficiency(self, domain: str, limit: int = 200) -> List[Dict[str, Any]]:
        """读取路径效率画像（用于排序/限流）"""
        try:
            if self.persistent_memory and hasattr(self.persistent_memory, 'get_top_path_efficiency'):
                return self.persistent_memory.get_top_path_efficiency(domain, limit=limit)
        except Exception as e:
            logger.error(f"读取路径效率画像失败 ({domain}): {e}")
        return []

    def record_domain_supervision(
        self,
        domain: str,
        miner_items: int,
        passed_items: int,
        rejected_items: int,
        reason_breakdown: Optional[Dict[str, int]] = None
    ):
        """写入 Inspector 客观反馈"""
        try:
            if self.persistent_memory and hasattr(self.persistent_memory, 'record_domain_supervision'):
                self.persistent_memory.record_domain_supervision(
                    domain=domain,
                    miner_items=miner_items,
                    passed_items=passed_items,
                    rejected_items=rejected_items,
                    reason_breakdown=reason_breakdown or {}
                )
        except Exception as e:
            logger.error(f"记录监督反馈失败 ({domain}): {e}")

    def get_domain_supervision(self, domain: str) -> Dict[str, Any]:
        """读取 Inspector 客观反馈"""
        try:
            if self.persistent_memory and hasattr(self.persistent_memory, 'get_domain_supervision'):
                return self.persistent_memory.get_domain_supervision(domain)
        except Exception as e:
            logger.error(f"读取监督反馈失败 ({domain}): {e}")
        return {
            "domain": domain,
            "reviewed_count": 0,
            "pass_count": 0,
            "reject_count": 0,
            "pass_rate": None,
            "last_updated": None,
            "reason_breakdown": {}
        }
    
    # =========================================================
    # 🔮 推荐系统
    # =========================================================

    def get_recommendation(self, domain: str, site_profile: Dict) -> Dict[str, Any]:
        """多维记忆交叉推荐逻辑"""
        try:
            recommendation = {
                'confidence': 0.5,
                'suggested_strategy': {'approach': 'adaptive', 'confidence_threshold': 0.4},
                'similar_sites': [], 'historical_performance': None, 'reasoning': ['使用默认策略']
            }

            if self.persistent_memory:
                best_strat = self.get_best_experience(domain)
                if best_strat and 'config' in best_strat:
                    recommendation['suggested_strategy'] = best_strat['config']
                    recommendation['confidence'] += 0.3
                    recommendation['reasoning'].append("基于历史最佳进化策略")

                instructions = self.get_active_instructions(domain)
                if instructions:
                    recommendation['reasoning'].append(f"包含 {len(instructions)} 条用户强制指令")
                    recommendation['confidence'] = 0.95 # 指令最高优先级

            # 向量记忆查找
            if self.chroma_memory and hasattr(self.chroma_memory, 'find_similar_websites'):
                similar = self.chroma_memory.find_similar_websites(site_profile, limit=3)
                if similar:
                    recommendation['similar_sites'] = similar
                    recommendation['confidence'] += 0.2
                    recommendation['reasoning'].append(f"从向量空间找到相似站点")

            recommendation['confidence'] = min(0.99, max(0.1, recommendation['confidence']))
            return recommendation
        except Exception as e:
            logger.error(f"获取记忆推荐失败: {e}")
            return {'confidence': 0.3, 'suggested_strategy': {'approach': 'adaptive'}}
    
    def end_session(self, session_id: str):
        if session_id in self.current_sessions or (
            self._bundle and hasattr(self.session_memory, "get_session")
            and self.session_memory.get_session(session_id)
        ):
            try:
                from agents.miner.memory.backends.session_archiver import archive_session
                archive_session(
                    session_id,
                    self.session_memory,
                    self.persistent_memory,
                    bundle=self._bundle,
                )
            except Exception as e:
                logger.warning(f"Session 归档失败 ({session_id}): {e}")

            try:
                if hasattr(self.session_memory, 'end_session'):
                    self.session_memory.end_session(session_id)
                elif hasattr(self.session_memory, 'close_session'):
                    self.session_memory.close_session(session_id)
            except Exception as e:
                logger.warning(f"关闭会话存储失败 ({session_id}): {e}")

            self.current_sessions.pop(session_id, None)
            logger.info(f"记忆会话已结束: {session_id}")
        if self.active_session_id == session_id:
            self.active_session_id = None
            if self.coordination:
                self.coordination.set_active_session_id(None)

    def get_memory_overview(self) -> Dict[str, Any]:
        """获取四层记忆状态概览"""
        session_stats = {'active': len(self.current_sessions)}
        if self._bundle and hasattr(self.session_memory, 'get_stats'):
            session_stats = self.session_memory.get_stats()
        return {
            'backend': 'redis' if self._bundle else 'file',
            'working': self.working_memory.get_stats() if hasattr(self.working_memory, 'get_stats') else {},
            'session': session_stats,
            'persistent': self.persistent_memory.get_stats() if self.persistent_memory and hasattr(self.persistent_memory, 'get_stats') else {},
            'chroma': self.chroma_memory.get_stats() if self.chroma_memory and hasattr(self.chroma_memory, 'get_stats') else {}
        }


class SimpleMemoryBackup:
    def __init__(self): self.data = {}
    def set(self, key, value, importance=0.5): self.data[key] = value
    def get(self, key): return self.data.get(key)
    def get_stats(self): return {'total': len(self.data)}


# --- 全局单例与便捷函数 ---
# 更改命名空间避免与 Inspector 冲突
_miner_unified_memory = None

def get_unified_memory() -> UnifiedMemoryManager:
    global _miner_unified_memory
    if _miner_unified_memory is None: 
        _miner_unified_memory = UnifiedMemoryManager()
    return _miner_unified_memory

def start_memory_session(task_info: Dict): return get_unified_memory().start_session(task_info)
def record_memory_extraction(*args, **kwargs): return get_unified_memory().record_extraction(*args, **kwargs)
def get_memory_recommendation(domain, site_profile): return get_unified_memory().get_recommendation(domain, site_profile)
def end_memory_session(session_id): return get_unified_memory().end_session(session_id)
