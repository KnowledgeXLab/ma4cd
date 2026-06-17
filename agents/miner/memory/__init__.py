"""
Miner 记忆系统 (MA4CD 优化版)

提供三层记忆架构：
- 短期记忆 (Working Memory): 内存存储，用于当前任务上下文
- 中期记忆 (Session Memory): 文件存储，用于单次挖掘任务的学习轨迹  
- 长期记忆 (Persistent Memory): Chroma+SQLite，用于跨任务知识积累

修复说明：统一采用基于 project_root 的绝对路径导入，防止多 Agent 路径冲突。
"""

# =============================================================================
# 🧬 延迟导入函数：防止循环依赖，确保绝对路径正确
# =============================================================================

def get_chroma_memory():
    """获取 Chroma 记忆管理器"""
    from agents.miner.memory.chroma_memory import get_chroma_memory as _get_chroma_memory
    return _get_chroma_memory()

def store_website_to_vector_memory(domain, site_profile, strategies, l3_results, success):
    """存储网站到向量记忆"""
    from agents.miner.memory.chroma_memory import store_website_to_vector_memory as _store
    return _store(domain, site_profile, strategies, l3_results, success)

def find_similar_websites_from_memory(site_profile, task_description="", limit=3):
    """从记忆中查找相似网站"""
    from agents.miner.memory.chroma_memory import find_similar_websites_from_memory as _find
    return _find(site_profile, task_description, limit)

def get_vector_memory_stats():
    """获取向量记忆统计"""
    from agents.miner.memory.chroma_memory import get_vector_memory_stats as _get_stats
    return _get_stats()

def get_unified_memory():
    """获取统一记忆管理器"""
    from agents.miner.memory.managers.memory_manager import get_unified_memory as _get_unified
    return _get_unified()

def start_memory_session(task_info):
    """开始记忆会话"""
    from agents.miner.memory.managers.memory_manager import start_memory_session as _start
    return _start(task_info)

def record_memory_extraction(session_id, domain, url, site_profile, strategy_used,
                           success, l3_candidates, execution_time, error_message=None):
    """记录提取到记忆"""
    from agents.miner.memory.managers.memory_manager import record_memory_extraction as _record
    return _record(session_id, domain, url, site_profile, strategy_used,
                  success, l3_candidates, execution_time, error_message)

def get_memory_recommendation(domain, site_profile):
    """获取记忆推荐"""
    from agents.miner.memory.managers.memory_manager import get_memory_recommendation as _get_rec
    return _get_rec(domain, site_profile)

def end_memory_session(session_id):
    """结束记忆会话"""
    from agents.miner.memory.managers.memory_manager import end_memory_session as _end
    return _end(session_id)

# =============================================================================
# 📋 版本与元数据
# =============================================================================

__version__ = "1.1.0" # 修复了路径冲突问题
__author__ = "Miner Team"
__description__ = "智能记忆系统，支持自我学习和策略进化"

# 导出列表 (保持与原版完全一致)
__all__ = [
    'get_chroma_memory',
    'store_website_to_vector_memory', 
    'find_similar_websites_from_memory',
    'get_vector_memory_stats',
    'get_unified_memory',
    'start_memory_session',
    'record_memory_extraction',
    'get_memory_recommendation', 
    'end_memory_session'
]