'''import json
import re
import asyncio
import os
import sys
from typing import List, Dict, Any
from urllib.parse import urlparse
from loguru import logger

# =============================================================================
# 🛠️ 路径与环境配置
# =============================================================================
try:
    # 1. 确保能导入项目根目录模块 (用于 data_memory_center)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "../../"))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # 2. 🔥 [修改] 导入 Inspector 自己的 LLM
    # 假设 inspector_llm.py 中定义了 InspectorLLM 类或 create_inspector_llm 函数
    # 这里做了一个自适应尝试，优先尝试类名 InspectorLLM
    try:
        from agents.inspector.llms.inspector_llm import InspectorLLM as LLMClient
    except ImportError:
        try:
            from agents.inspector.llms.inspector_llm import InspectorLLMClient as LLMClient
        except ImportError:
            # 最后的兜底：如果找不到类，尝试找 create 函数
            from agents.inspector.llms.inspector_llm import create_inspector_llm as LLMClient
            
    # 3. 导入数据存储中心 (DataMemoryCenter)
    from data_memory_center.manager import DataMemoryCenter

except ImportError as e:
    logger.critical(f"❌ Inspector 环境导入失败: {e}")
    # Mock 防止 IDE 报错
    class LLMClient: 
        async def ainvoke(self, *args, **kwargs): return "[]"
    class DataMemoryCenter:
        def __init__(self): logger.warning("⚠️ 使用 Mock Memory Center")

class InspectorAgent:
    """
    InspectorAgent (独立 LLM 版)
    职责：使用 Inspector 专属 LLM 进行数据清洗、去重，并存入 DataMemoryCenter
    """
    def __init__(self):
        # 1. 初始化 Inspector 专属 LLM
        try:
            # 尝试实例化，如果不接受参数则无参实例化
            try:
                self.llm = LLMClient(temperature=0.1)
            except TypeError:
                self.llm = LLMClient() 
            logger.info("🧠 Inspector LLM 已就绪")
        except Exception as e:
            logger.error(f"❌ Inspector LLM 初始化失败: {e}")
            self.llm = None
        
        # 2. 初始化存储中心
        try:
            self.memory_center = DataMemoryCenter()
            logger.info("✅ 已连接 DataMemoryCenter (ChromaDB)")
        except Exception as e:
            logger.error(f"❌ 连接存储中心失败: {e}")
            self.memory_center = None
        
        # 3. 配置规则过滤器
        self.blacklist = [
            "login", "signin", "signup", "register", "subscribe", 
            "password", "cart", "checkout", "pricing", 
            "about-us", "contact-us", "privacy-policy", "terms-of-use",
            "sitemap", "search?", "lang=", "browse", "forgot-password"
        ]
        
        self.low_value_titles = [
            "home", "index", "journals", "books", "products", 
            "solutions", "services", "menu", "navigation", "search results",
            "all rights reserved", "page not found", "404"
        ]
        
        logger.info("🧐 Inspector Agent (清洗与入库引擎) 已就绪")

    async def process(self, raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """主处理管道"""
        if not raw_items: return []
        
        logger.info(f"🧐 Inspector 启动清洗流程 (输入: {len(raw_items)} 条)")
        
        # Step 1: 物理去重 (Deduplication)
        unique_items = self._deduplicate(raw_items)
        
        # Step 2: 规则清洗 (Rule-based Filter)
        rule_cleaned = self._rule_based_filter(unique_items)
        
        # Step 3: LLM 智能审计 (LLM Audit)
        final_items = await self._llm_audit_pipeline(rule_cleaned)
        
        drop_rate = (1 - len(final_items)/len(raw_items)) * 100
        logger.success(f"✅ Inspector 审计完成 | 最终保留: {len(final_items)} 条 (淘汰率: {drop_rate:.1f}%)")
        
        # Step 4: 入库 (Storage)
        if self.memory_center and final_items:
            await self._save_to_memory_center(final_items)
        
        return final_items

    async def _save_to_memory_center(self, items: List[Dict[str, Any]]):
        """将清洗后的数据分发到 L1/L2/L3/L4 数据库"""
        logger.info("📦 正在执行向量分级入库...")
        count = 0
        
        for item in items:
            try:
                level = item.get("level", "L4").upper()
                record = item.copy()
                
                # 补充打分信息
                record['inspector_score'] = item.get('confidence', 0.0)
                record['inspector_reason'] = "Passed Inspector Audit"

                # 路由到对应方法
                if "L4" in level:
                    self.memory_center.add_l4_record(record)
                elif "L3" in level:
                    self.memory_center.add_l3_dataset(record)
                elif "L2" in level:
                    self.memory_center.add_l2_portal(record)
                elif "L1" in level:
                    self.memory_center.add_l1_hub(record)
                else:
                    self.memory_center.add_l4_record(record) # 默认
                
                count += 1
            except Exception as e:
                # 忽略单条错误，保证整体流程
                pass

        logger.success(f"💾 已将 {count} 条高价值资产存入 DataMemoryCenter")

    def _deduplicate(self, items: List[Dict]) -> List[Dict]:
        """基于 URL 的强去重"""
        seen = set()
        unique = []
        for item in items:
            url = item.get('url', '').strip()
            if not url: continue
            norm_url = url.split('#')[0].rstrip('/').replace('http://', '').replace('https://', '')
            if norm_url not in seen:
                seen.add(norm_url)
                unique.append(item)
        return unique

    def _rule_based_filter(self, items: List[Dict]) -> List[Dict]:
        """基于黑名单的快速过滤"""
        valid = []
        for item in items:
            url = item.get('url', '').lower()
            title = item.get('title', '').lower()
            
            if any(bad in url for bad in self.blacklist): continue
            if len(title) < 4 or title in self.low_value_titles: continue
            if url.endswith(('.js', '.css', '.png', '.jpg', '.ico', '.woff', '.ttf')): continue

            valid.append(item)
        return valid

    async def _llm_audit_pipeline(self, items: List[Dict]) -> List[Dict]:
        """LLM 智能审计"""
        approved = []
        audit_queue = []
        
        for item in items:
            # 信任高置信度或文件类资产
            if item.get('level') == 'L4' or item.get('file_type'):
                approved.append(item)
            elif item.get('confidence', 0) > 0.85:
                approved.append(item)
            else:
                audit_queue.append(item)
        
        if not audit_queue: return approved

        # 简单抽检策略：如果 LLM 可用，可以进行批量验证
        # 考虑到性能，这里仅做限量处理
        approved.extend(audit_queue[:50]) 
        
        # 如果需要真实的 LLM 介入，可以使用 self.llm.ainvoke(...)
        # 示例：
        # if self.llm:
        #     # 构造 Prompt 让 LLM 过滤垃圾链接...
        #     pass
        
        return approved

    # 兼容接口
    async def run(self, artifacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return await self.process(artifacts)

if __name__ == "__main__":
    async def main():
        try:
            agent = InspectorAgent()
            print("✅ Inspector init success")
        except Exception as e:
            print(f"❌ Init failed: {e}")
    asyncio.run(main())
    '''
import os
import chromadb
from datetime import datetime
from loguru import logger
import uuid
import re
from typing import Any, Dict, List, Optional

try:
    from agents.miner.memory.backends.redis_aux import get_blacklist_cache
except ImportError:
    get_blacklist_cache = lambda: None  # type: ignore

class DataMemoryCenter:
    """
    数据存储中心 (ChromaDB 驱动)
    负责 L1/L2/L3/L4 各级资产的物理存储与黑名单管理
    """
    def __init__(self, root_path=None):
        # 自动定位路径 (data_memory_center 目录下)
        if not root_path:
            # 假设当前文件在 data_memory_center/manager.py
            root_path = os.path.dirname(os.path.abspath(__file__))
            
        # 定义 ChromaDB 存储路径
        self.blacklist_path = os.path.join(root_path, "blacklist_db", "chroma_db")
        self.l4_path = os.path.join(root_path, "l4_db", "chroma_db")
        self.l1_path = os.path.join(root_path, "l1_db", "chroma_db")
        self.l2_path = os.path.join(root_path, "l2_db", "chroma_db")
        self.l3_path = os.path.join(root_path, "l3_db", "chroma_db")
        
        # 确保物理目录存在
        for p in [self.blacklist_path, self.l4_path, self.l1_path, self.l2_path, self.l3_path]:
            os.makedirs(p, exist_ok=True)

        # 初始化 Chroma 客户端
        try:
            self.blacklist_client = chromadb.PersistentClient(path=self.blacklist_path)
            self.l4_client = chromadb.PersistentClient(path=self.l4_path)
            self.l1_client = chromadb.PersistentClient(path=self.l1_path)
            self.l2_client = chromadb.PersistentClient(path=self.l2_path)
            self.l3_client = chromadb.PersistentClient(path=self.l3_path)
            
            # 获取或创建集合 (Collection)
            self.blacklist_collection = self.blacklist_client.get_or_create_collection("invalid_urls")
            self.l4_collection = self.l4_client.get_or_create_collection("l4_assets")
            self.l1_collection = self.l1_client.get_or_create_collection("l1_hubs")
            self.l2_collection = self.l2_client.get_or_create_collection("l2_portals")
            self.l3_collection = self.l3_client.get_or_create_collection("l3_datasets")
            
            logger.info("💾 DataMemoryCenter (ChromaDB) 初始化成功，所有层级已挂载")
                        
        except Exception as e:
            logger.error(f"❌ DataMemoryCenter 初始化失败: {e}")
            raise e

    # --- 黑名单逻辑 ---
    def add_blacklist(self, url: str, reason: str, source: str = "inspector"):
        try:
            clean_url = url.strip()
            self.blacklist_collection.upsert(
                ids=[clean_url],
                documents=[f"Blocked: {clean_url}. Reason: {reason}"],
                metadatas=[{"url": clean_url, "reason": reason, "source": source, "timestamp": datetime.now().isoformat()}]
            )
            bl_cache = get_blacklist_cache()
            if bl_cache:
                bl_cache.mark_blacklisted(clean_url, reason)
            logger.info(f"🚫 已加入黑名单: {clean_url}")
        except Exception as e:
            logger.error(f"黑名单写入失败: {e}")

    # 🔥 黑名单查询接口 (Scout 专用)
    def is_blacklisted(self, url: str) -> bool:
        """
        检查 URL 是否存在于黑名单中
        """
        try:
            if not url:
                return False
            bl_cache = get_blacklist_cache()
            if bl_cache:
                cached = bl_cache.is_blacklisted(url)
                if cached is True:
                    return True
            clean_url = url.strip()
            result = self.blacklist_collection.get(ids=[clean_url])
            if result and result['ids']:
                if bl_cache:
                    bl_cache.mark_blacklisted(clean_url, "chroma")
                return True
            return False
        except Exception as e:
            logger.error(f"⚠️ 黑名单查询出错: {e}")
            return False

    # --- 核心存储逻辑 ---
    def add_l4_record(self, record: dict):
        self._add_to_collection(self.l4_collection, record, "L4_Asset")

    def add_l3_dataset(self, record: dict):
        self._add_to_collection(self.l3_collection, record, "L3_Dataset")

    def add_l2_portal(self, record: dict):
        self._add_to_collection(self.l2_collection, record, "L2_Portal")

    def add_l1_hub(self, record: dict):
        self._add_to_collection(self.l1_collection, record, "L1_Hub")

    def _add_to_collection(self, collection, record, type_label):
        """内部通用存储函数"""
        try:
            url = record.get('url')
            if not url: return
            
            title = record.get('title', 'Unknown')
            desc = record.get('description', '') or ''
            
            # 构建文档内容用于向量检索
            doc_content = f"Title: {title}\nDescription: {desc}\nURL: {url}"
            
            # 扁平化元数据 (ChromaDB 只接受简单类型)
            metadata = {
                "url": url,
                "title": title,
                "type": type_label,
                "score": float(record.get('inspector_score', 0.0)),
                "timestamp": datetime.now().isoformat()
            }

            collection.upsert(
                ids=[url],
                documents=[doc_content],
                metadatas=[metadata]
            )
            logger.debug(f"✅ {type_label} 已存入: {url}")
        except Exception as e:
            logger.error(f"存储失败 ({type_label}): {e}")

    def check_url_exists(self, url: str) -> bool:
        """快速检查 URL 是否已存在于任何库中"""
        clean_url = url.strip()
        try:
            for col in [self.l3_collection, self.l2_collection, self.l1_collection, self.l4_collection, self.blacklist_collection]:
                if len(col.get(ids=[clean_url])['ids']) > 0: return True
        except:
            pass
        return False

    def query_related_clues(
        self,
        query_text: str,
        per_level: int = 5,
        max_total: int = 20,
        include_levels: Optional[List[str]] = None,
        extra_keywords: Optional[List[str]] = None,
        enable_lexical_scan: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        按主题词跨 L1/L2/L3/L4 检索历史线索。
        采用“双通道”：
        1) 语义检索（collection.query）
        2) 关键词全量扫描（collection.get + 文本匹配）
        返回统一结构，便于工作流层直接展示。
        """
        q = str(query_text or "").strip()
        if not q:
            return []

        level_to_collection = {
            "L1": self.l1_collection,
            "L2": self.l2_collection,
            "L3": self.l3_collection,
            "L4": self.l4_collection,
        }

        levels = include_levels or ["L3", "L2", "L1", "L4"]
        normalized_levels = [str(l).upper() for l in levels if str(l).upper() in level_to_collection]
        if not normalized_levels:
            normalized_levels = ["L3", "L2", "L1", "L4"]

        candidates: List[Dict[str, Any]] = []

        keywords = self._build_keyword_set(q, extra_keywords or [])

        # ---------------------------------------------------------
        # 通道A：语义检索（高精度）
        # ---------------------------------------------------------
        for level in normalized_levels:
            col = level_to_collection[level]
            try:
                result = col.query(
                    query_texts=[q],
                    n_results=max(1, int(per_level)),
                    include=["metadatas", "documents", "distances"]
                )
            except Exception as e:
                logger.warning(f"⚠️ 历史检索失败 ({level}): {e}")
                continue

            ids = (result.get("ids") or [[]])[0]
            metadatas = (result.get("metadatas") or [[]])[0]
            documents = (result.get("documents") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]

            for idx, raw_id in enumerate(ids):
                meta = metadatas[idx] if idx < len(metadatas) and isinstance(metadatas[idx], dict) else {}
                doc = documents[idx] if idx < len(documents) else ""
                dist = distances[idx] if idx < len(distances) else None
                similarity = None
                if isinstance(dist, (int, float)):
                    similarity = max(0.0, min(1.0, 1.0 - float(dist)))

                url = str(meta.get("url") or raw_id or "").strip()
                title = str(meta.get("title") or "").strip()
                if not title and isinstance(doc, str):
                    first_line = doc.splitlines()[0].strip() if doc.strip() else ""
                    title = first_line.replace("Title:", "").strip() if first_line else "Unknown"

                candidates.append({
                    "level": level,
                    "url": url,
                    "title": title or "Unknown",
                    "similarity": similarity if similarity is not None else 0.0,
                    "lexical_hits": 0,
                    "score": float(meta.get("score", 0.0) or 0.0),
                    "timestamp": str(meta.get("timestamp", "")),
                })

        # ---------------------------------------------------------
        # 通道B：关键词全量扫描（高召回）
        # ---------------------------------------------------------
        if enable_lexical_scan and keywords:
            for level in normalized_levels:
                col = level_to_collection[level]
                try:
                    dump = col.get(include=["metadatas", "documents"])
                except Exception as e:
                    logger.warning(f"⚠️ 历史全量扫描失败 ({level}): {e}")
                    continue

                ids = dump.get("ids") or []
                metadatas = dump.get("metadatas") or []
                documents = dump.get("documents") or []

                for idx, raw_id in enumerate(ids):
                    meta = metadatas[idx] if idx < len(metadatas) and isinstance(metadatas[idx], dict) else {}
                    doc = documents[idx] if idx < len(documents) else ""
                    url = str(meta.get("url") or raw_id or "").strip()
                    title = str(meta.get("title") or "").strip() or "Unknown"
                    haystack = f"{url}\n{title}\n{doc}".lower()

                    hit_count = sum(1 for kw in keywords if kw in haystack)
                    if hit_count <= 0:
                        continue

                    # 词法通道没有 distance，用匹配强度映射一个“伪相似度”用于排序融合
                    lexical_similarity = min(0.99, 0.35 + 0.08 * hit_count)
                    candidates.append({
                        "level": level,
                        "url": url,
                        "title": title,
                        "similarity": lexical_similarity,
                        "lexical_hits": hit_count,
                        "score": float(meta.get("score", 0.0) or 0.0),
                        "timestamp": str(meta.get("timestamp", "")),
                    })

        # URL 去重：保留相似度更高者
        dedup: Dict[str, Dict[str, Any]] = {}
        for item in candidates:
            url = item.get("url", "")
            if not url:
                continue
            old = dedup.get(url)
            if (
                not old
                or item.get("lexical_hits", 0) > old.get("lexical_hits", 0)
                or (
                    item.get("lexical_hits", 0) == old.get("lexical_hits", 0)
                    and item.get("similarity", 0.0) > old.get("similarity", 0.0)
                )
            ):
                dedup[url] = item

        merged = list(dedup.values())
        merged.sort(
            key=lambda x: (
                int(x.get("lexical_hits", 0)),
                float(x.get("similarity", 0.0)),
                float(x.get("score", 0.0)),
                str(x.get("timestamp", "")),
            ),
            reverse=True
        )
        # max_total <= 0 表示“返回全部”
        if int(max_total) <= 0:
            return merged
        return merged[:max(1, int(max_total))]

    @staticmethod
    def _build_keyword_set(query_text: str, extra_keywords: List[str]) -> List[str]:
        """
        构建用于词法扫描的关键词集合：
        - 主题词切词
        - 额外关键词（例如 Commander 的 specific_targets）
        """
        query_raw = str(query_text or "")
        raw_chunks = [query_raw]
        raw_chunks.extend([str(k or "") for k in (extra_keywords or [])])

        tokens = set()
        for chunk in raw_chunks:
            txt = chunk.strip().lower()
            if not txt:
                continue
            # 提取英文/数字/连字符/斜杠片段
            for t in re.split(r"[^a-z0-9_./-]+", txt):
                t = t.strip()
                if not t:
                    continue
                # 过滤过短噪声词，但保留常见关键缩写
                if len(t) < 3 and t not in {"sra", "ega", "geo"}:
                    continue
                tokens.add(t)

        # 常见主题增强词（用于基因组学场景的稳定召回）
        boosters = {
            "genbank", "genome", "genomics", "sequence", "sra", "geo",
            "ncbi", "ebi", "ddbj", "ena", "gsa", "gwh"
        }
        token_haystack = " ".join(tokens)
        cn_genomics_trigger = any(k in query_raw for k in ["基因", "组学", "测序", "生物信息", "遗传", "基因组"])
        if cn_genomics_trigger or any(k in token_haystack for k in ["genome", "genomics", "gene", "omics"]):
            tokens.update(boosters)

        # 长词优先（提升匹配判别力）
        return sorted(tokens, key=lambda s: (len(s), s), reverse=True)
