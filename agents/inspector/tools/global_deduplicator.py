import logging
import os
import sys

# ==========================================
# 🔥 路径修复
# ==========================================
current_file = os.path.abspath(__file__)
tools_dir = os.path.dirname(current_file)
inspector_dir = os.path.dirname(tools_dir)
agents_dir = os.path.dirname(inspector_dir)
root_dir = os.path.dirname(agents_dir)

if root_dir not in sys.path:
    sys.path.append(root_dir)

from data_memory_center.manager import DataMemoryCenter

logger = logging.getLogger("inspector.tools.deduplicator")

# ⚡ [核心修改 1] 定义一个模块级的全局变量来缓存数据库连接
# 这样无论 GlobalDeduplicator 被实例化多少次，数据库只连一次
_SHARED_DB_INSTANCE = None

class GlobalDeduplicator:
    """
    Inspector 的全局去重工具。
    🔥 已优化：使用单例模式，彻底解决循环初始化数据库导致的卡顿问题。
    🟢 新增优化：彻底切除 URL 锚点（#），防止同源多级分身术。
    """
    
    def __init__(self):
        global _SHARED_DB_INSTANCE
        
        self.dm = None
        try:
            # ⚡ [核心修改 2] 检查是否有缓存的连接
            if _SHARED_DB_INSTANCE is not None:
                # logger.debug("GlobalDeduplicator: 复用现有数据库连接 ⚡") 
                self.dm = _SHARED_DB_INSTANCE
            else:
                logger.info("🔌 GlobalDeduplicator: 正在建立新的 DataMemoryCenter 连接...")
                self.dm = DataMemoryCenter()
                _SHARED_DB_INSTANCE = self.dm
                logger.info("✅ GlobalDeduplicator: 数据库连接已缓存")
                
        except Exception as e:
            logger.error(f"❌ 连接 Data Memory Center 失败: {e}")
            self.dm = None

    def is_duplicate(self, url: str) -> bool:
        """
        检查 URL 是否重复。
        """
        if not url or not self.dm:
            return False 
            
        # ⚡ [核心修改 3] 彻底清理 URL，切除锚点 (#) 以防止同源页面被重复抓取
        base_url = url.strip()
        if '#' in base_url:
            base_url = base_url.split('#')[0]
            
        normalized_url = base_url.lower().rstrip('/')
        
        try:
            # 1. 检查黑名单 (最快)
            # 同时检查原始输入、去除了锚点的 base_url 以及归一化后的 normalized_url
            if self.dm.is_blacklisted(url) or \
               self.dm.is_blacklisted(base_url) or \
               self.dm.is_blacklisted(normalized_url):
                logger.debug(f"🚫 黑名单拦截: {url}")
                return True

            # 2. 检查各级数据库 (L3 -> L2 -> L1 -> L4)
            # 防御性编程：确保 collection 已加载
            collections_map = [
                (getattr(self.dm, 'l3_collection', None), "L3"),
                (getattr(self.dm, 'l2_collection', None), "L2"),
                (getattr(self.dm, 'l1_collection', None), "L1"),
                (getattr(self.dm, 'l4_collection', None), "L4")
            ]
            
            # ⚡ [核心修改 4] 扩充 query_ids 矩阵，确保各种 URL 形态都能在库中被狙击
            # 使用 set 去重，防止向数据库发送重复的查询 ID
            query_ids = list(set([
                url,                     # 原始形式 (如 https://.../#toc)
                base_url,                # 无锚点形式 (如 https://.../)
                normalized_url,          # 全小写且无末尾斜杠形式
                base_url.rstrip('/'),    # 仅去掉末尾斜杠
                url.rstrip('/')          # 原始形式去掉末尾斜杠
            ]))

            for col, level_name in collections_map:
                if col is None: continue
                
                # 只查询 ID，极速模式
                result = col.get(ids=query_ids, include=[])
                if result and result.get('ids'):
                    logger.debug(f"♻️ 发现重复 ({level_name}): {url}")
                    return True
            
            return False

        except Exception as e:
            logger.error(f"⚠️ 去重检查出错 {url}: {e}")
            return False