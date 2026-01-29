# memory/chroma_memory.py
import chromadb
from chromadb.config import Settings
from typing import Dict, List, Any, Optional
import json
import hashlib
from datetime import datetime
from loguru import logger


class ChromaMemoryManager:
    """
    基于 Chroma 的向量记忆管理器
    用于存储和检索向量化的网站知识
    """
    
    def __init__(self, persist_directory: str = "./memory_data/chroma_db"):
        try:
            # 使用持久化存储
            self.client = chromadb.PersistentClient(path=persist_directory)
            
            # 创建集合
            self.website_collection = self._get_or_create_collection(
                "website_knowledge", 
                "存储网站知识和提取策略"
            )
            
            self.pattern_collection = self._get_or_create_collection(
                "extraction_patterns",
                "存储成功的提取模式"
            )
            
            self.success_collection = self._get_or_create_collection(
                "success_cases",
                "存储成功案例"
            )
            
            logger.info(f"ChromaMemoryManager 初始化完成: {persist_directory}")
            
        except Exception as e:
            logger.error(f"ChromaMemoryManager 初始化失败: {e}")
            # 创建一个空的备用实现
            self.client = None
            self.website_collection = None
            self.pattern_collection = None
            self.success_collection = None
    
    def _get_or_create_collection(self, name: str, description: str):
        """获取或创建集合"""
        if not self.client:
            return None
            
        try:
            return self.client.get_collection(name)
        except:
            return self.client.create_collection(
                name=name,
                metadata={"description": description}
            )
    
    def store_website_knowledge(self, domain: str, site_profile: Dict, 
                               strategies: Dict, l3_results: List[Dict], 
                               success: bool):
        """存储网站知识"""
        
        if not self.website_collection:
            logger.warning("Chroma 未初始化，跳过向量存储")
            return
        
        try:
            # 构建文档内容
            doc_content = self._build_website_document(
                domain, site_profile, strategies, l3_results, success
            )
            
            # 生成唯一ID
            doc_id = hashlib.md5(domain.encode()).hexdigest()
            
            # 构建元数据
            metadata = {
                "domain": domain,
                "success": success,
                "l3_count": len(l3_results),
                "timestamp": datetime.now().isoformat(),
                **self._flatten_site_profile(site_profile)  # 展开 site_profile
            }
            
            # 存储到 Chroma
            self.website_collection.upsert(
                documents=[doc_content],
                metadatas=[metadata],
                ids=[doc_id]
            )
            
            logger.debug(f"网站知识已存储到向量库: {domain} (成功: {success})")
            
        except Exception as e:
            logger.error(f"存储网站知识到向量库失败: {e}")
    
    def find_similar_websites(self, site_profile: Dict, task_description: str = "", 
                             limit: int = 3) -> List[Dict]:
        """查找相似网站"""
        
        if not self.website_collection:
            logger.warning("Chroma 未初始化，返回空结果")
            return []
        
        try:
            # 构建查询文本
            query_text = self._build_query_text(site_profile, task_description)
            
            # 查询相似文档
            results = self.website_collection.query(
                query_texts=[query_text],
                n_results=limit,
                where={"success": True}  # 只查询成功的案例
            )
            
            similar_sites = []
            if results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    metadata = results['metadatas'][0][i]
                    distance = results['distances'][0][i] if results['distances'] else 0
                    
                    similar_sites.append({
                        "domain": metadata["domain"],
                        "similarity": 1 - distance,  # 转换为相似度
                        "l3_count": metadata.get("l3_count", 0),
                        "site_profile": self._extract_site_profile_from_metadata(metadata),
                        "document": doc
                    })
            
            logger.debug(f"找到 {len(similar_sites)} 个相似网站")
            return similar_sites
            
        except Exception as e:
            logger.error(f"查找相似网站失败: {e}")
            return []
    
    def store_extraction_pattern(self, pattern_name: str, pattern_data: Dict, 
                               success_domains: List[str]):
        """存储提取模式"""
        
        if not self.pattern_collection:
            logger.warning("Chroma 未初始化，跳过模式存储")
            return
        
        try:
            doc_content = f"""
            提取模式: {pattern_name}
            模式配置: {json.dumps(pattern_data, ensure_ascii=False, indent=2)}
            成功域名: {', '.join(success_domains)}
            """
            
            pattern_id = hashlib.md5(pattern_name.encode()).hexdigest()
            
            metadata = {
                "pattern_name": pattern_name,
                "success_count": len(success_domains),
                "domains": json.dumps(success_domains),  # 序列化列表
                "timestamp": datetime.now().isoformat()
            }
            
            self.pattern_collection.upsert(
                documents=[doc_content],
                metadatas=[metadata],
                ids=[pattern_id]
            )
            
            logger.debug(f"提取模式已存储到向量库: {pattern_name}")
            
        except Exception as e:
            logger.error(f"存储提取模式失败: {e}")
    
    def find_relevant_patterns(self, context: str, limit: int = 3) -> List[Dict]:
        """查找相关的提取模式"""
        
        if not self.pattern_collection:
            logger.warning("Chroma 未初始化，返回空模式")
            return []
        
        try:
            # 查询相关模式
            results = self.pattern_collection.query(
                query_texts=[context],
                n_results=limit
            )
            
            patterns = []
            if results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    metadata = results['metadatas'][0][i]
                    distance = results['distances'][0][i] if results['distances'] else 0
                    
                    patterns.append({
                        "pattern_name": metadata["pattern_name"],
                        "pattern_data": {},  # 需要从文档中解析
                        "relevance": 1 - distance,
                        "usage_count": metadata.get("success_count", 0)
                    })
            
            return patterns
            
        except Exception as e:
            logger.error(f"查找相关模式失败: {e}")
            return []
    
    def store_success_case(self, domain: str, task_description: str, 
                          strategy_used: Dict, l3_results: List[Dict]):
        """存储成功案例"""
        
        if not self.success_collection:
            logger.warning("Chroma 未初始化，跳过成功案例存储")
            return
        
        try:
            # 构建案例描述
            doc_content = self._build_success_case_document(
                domain, task_description, strategy_used, l3_results
            )
            
            # 生成ID
            case_id = hashlib.md5(f"{domain}_{task_description}".encode()).hexdigest()
            
            metadata = {
                "domain": domain,
                "task_description": task_description,
                "l3_count": len(l3_results),
                "timestamp": datetime.now().isoformat()
            }
            
            self.success_collection.upsert(
                documents=[doc_content],
                metadatas=[metadata],
                ids=[case_id]
            )
            
            logger.debug(f"成功案例已存储到向量库: {domain}")
            
        except Exception as e:
            logger.error(f"存储成功案例失败: {e}")
    
    def find_similar_success_cases(self, task_description: str, 
                                  site_profile: Dict, limit: int = 3) -> List[Dict]:
        """查找相似的成功案例"""
        
        if not self.success_collection:
            logger.warning("Chroma 未初始化，返回空案例")
            return []
        
        try:
            # 构建查询描述
            query_text = f"{task_description} {self._build_site_profile_description(site_profile)}"
            
            # 搜索相似案例
            results = self.success_collection.query(
                query_texts=[query_text],
                n_results=limit
            )
            
            cases = []
            if results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    metadata = results['metadatas'][0][i]
                    distance = results['distances'][0][i] if results['distances'] else 0
                    
                    cases.append({
                        "domain": metadata["domain"],
                        "similarity": 1 - distance,
                        "l3_count": metadata["l3_count"],
                        "task_description": metadata["task_description"]
                    })
            
            return cases
            
        except Exception as e:
            logger.error(f"查找相似成功案例失败: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        
        stats = {}
        
        try:
            if self.website_collection:
                website_count = self.website_collection.count()
                stats["website_knowledge"] = {"count": website_count}
            else:
                stats["website_knowledge"] = {"count": 0, "error": "collection not initialized"}
            
            if self.pattern_collection:
                pattern_count = self.pattern_collection.count()
                stats["extraction_patterns"] = {"count": pattern_count}
            else:
                stats["extraction_patterns"] = {"count": 0, "error": "collection not initialized"}
            
            if self.success_collection:
                success_count = self.success_collection.count()
                stats["success_cases"] = {"count": success_count}
            else:
                stats["success_cases"] = {"count": 0, "error": "collection not initialized"}
                
        except Exception as e:
            logger.error(f"获取向量库统计失败: {e}")
            stats = {"error": str(e)}
        
        return stats
    
    def _build_website_document(self, domain: str, site_profile: Dict, 
                               strategies: Dict, l3_results: List[Dict], 
                               success: bool) -> str:
        """构建网站文档"""
        
        doc_parts = [
            f"域名: {domain}",
            f"结果: {'成功' if success else '失败'}",
        ]
        
        # 添加网站特征
        for key, value in site_profile.items():
            if isinstance(value, list):
                doc_parts.append(f"{key}: {', '.join(map(str, value))}")
            else:
                doc_parts.append(f"{key}: {value}")
        
        # 添加策略信息
        if strategies:
            doc_parts.append(f"使用策略: {json.dumps(strategies, ensure_ascii=False)}")
        
        # 添加L3结果
        if l3_results:
            l3_titles = [result.get('title', '') for result in l3_results[:5]]
            doc_parts.append(f"发现的L3子库: {', '.join(l3_titles)}")
        
        return "".join(doc_parts)
    
    def _build_success_case_document(self, domain: str, task_description: str,
                                   strategy_used: Dict, l3_results: List[Dict]) -> str:
        """构建成功案例文档"""
        
        doc_parts = [
            f"域名: {domain}",
            f"任务: {task_description}",
            f"策略: {json.dumps(strategy_used, ensure_ascii=False)}"
        ]
        
        if l3_results:
            l3_titles = [result.get('title', '') for result in l3_results[:5]]
            doc_parts.append(f"L3结果: {', '.join(l3_titles)}")
        
        return "".join(doc_parts)
    
    def _build_query_text(self, site_profile: Dict, task_description: str = "") -> str:
        """构建查询文本"""
        
        query_parts = []
        
        if task_description:
            query_parts.append(task_description)
        
        # 添加关键特征
        important_keys = ['domain_type', 'institutional_type', 'language_hints', 'estimated_scale']
        for key in important_keys:
            if key in site_profile:
                value = site_profile[key]
                if isinstance(value, list):
                    query_parts.append(f"{key}: {', '.join(map(str, value))}")
                else:
                    query_parts.append(f"{key}: {value}")
        
        return " ".join(query_parts)
    
    def _build_site_profile_description(self, site_profile: Dict) -> str:
        """构建网站概况描述"""
        
        parts = []
        
        for key, value in site_profile.items():
            if isinstance(value, list):
                parts.append(f"{key}: {', '.join(map(str, value))}")
            else:
                parts.append(f"{key}: {value}")
        
        return " ".join(parts)
    
    def _flatten_site_profile(self, site_profile: Dict) -> Dict[str, Any]:
        """展开网站概况为平坦的元数据"""
        
        flattened = {}
        
        for key, value in site_profile.items():
            if isinstance(value, (str, int, float, bool)):
                flattened[key] = value
            elif isinstance(value, list):
                # 列表转换为字符串
                flattened[key] = json.dumps(value) if value else ""
            else:
                # 其他类型转换为字符串
                flattened[key] = str(value)
        
        return flattened
    
    def _extract_site_profile_from_metadata(self, metadata: Dict) -> Dict[str, Any]:
        """从元数据中提取网站概况"""
        
        site_profile = {}
        
        # 排除系统字段
        system_fields = {'domain', 'success', 'l3_count', 'timestamp'}
        
        for key, value in metadata.items():
            if key not in system_fields:
                # 尝试解析JSON列表
                if isinstance(value, str) and value.startswith('[') and value.endswith(']'):
                    try:
                        site_profile[key] = json.loads(value)
                    except:
                        site_profile[key] = value
                else:
                    site_profile[key] = value
        
        return site_profile
    
    def clear_all(self):
        """清空所有数据（调试用）"""
        
        if not self.client:
            logger.warning("Chroma 未初始化，无法清空数据")
            return
        
        try:
            # 删除所有集合
            collections_to_delete = ["website_knowledge", "extraction_patterns", "success_cases"]
            
            for collection_name in collections_to_delete:
                try:
                    self.client.delete_collection(collection_name)
                    logger.debug(f"已删除集合: {collection_name}")
                except:
                    pass  # 集合可能不存在
            
            # 重新创建集合
            self.website_collection = self._get_or_create_collection(
                "website_knowledge", "存储网站知识和提取策略"
            )
            self.pattern_collection = self._get_or_create_collection(
                "extraction_patterns", "存储成功的提取模式"
            )
            self.success_collection = self._get_or_create_collection(
                "success_cases", "存储成功案例"
            )
            
            logger.info("所有向量记忆数据已清空并重新初始化")
            
        except Exception as e:
            logger.error(f"清空向量数据失败: {e}")


# 全局实例
_chroma_memory = None

def get_chroma_memory() -> ChromaMemoryManager:
    """获取全局 Chroma 记忆管理器"""
    global _chroma_memory
    if _chroma_memory is None:
        _chroma_memory = ChromaMemoryManager()
    return _chroma_memory


# 便捷函数
def store_website_to_vector_memory(domain: str, site_profile: Dict, 
                                  strategies: Dict, l3_results: List[Dict], 
                                  success: bool):
    """存储网站到向量记忆"""
    return get_chroma_memory().store_website_knowledge(
        domain, site_profile, strategies, l3_results, success
    )

def find_similar_websites_from_memory(site_profile: Dict, task_description: str = "", 
                                     limit: int = 3) -> List[Dict]:
    """从记忆中查找相似网站"""
    return get_chroma_memory().find_similar_websites(site_profile, task_description, limit)

def get_vector_memory_stats() -> Dict[str, Any]:
    """获取向量记忆统计"""
    return get_chroma_memory().get_stats()
