# evolution/memory_based_evolution.py (完全重写为简化版)
"""
简化的基于记忆的进化引擎 - 适配现有记忆系统
"""

import json
import time
import uuid
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from loguru import logger
import numpy as np

try:
    from memory import get_unified_memory
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    logger.warning("记忆系统不可用，使用本地存储")

@dataclass
class EvolutionStats:
    """进化统计"""
    generation: int
    total_evolutions: int
    current_quality: float
    quality_trend: str
    last_evolution_time: float
    
    def get(self, key: str, default=None):
        """提供 get 方法以兼容字典访问"""
        return getattr(self, key, default)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)

class MemoryBasedEvolutionEngine:
    """
    简化的基于记忆的进化引擎
    """
    
    def __init__(self):
        # 尝试连接记忆系统
        self.memory = None
        if MEMORY_AVAILABLE:
            try:
                self.memory = get_unified_memory()
                logger.info("成功连接记忆系统")
            except Exception as e:
                logger.warning(f"连接记忆系统失败: {e}")
        
        self.generation = 0
        self.evolution_history = []
        
        # 分类权重
        self.classification_weights = {
            'download_indicators': 0.4,
            'file_format_hints': 0.3,
            'api_endpoints': 0.2,
            'metadata_quality': 0.1
        }
        
        logger.info(f"MemoryBasedEvolutionEngine 初始化完成，当前代数: {self.generation}")
    
    async def evolve_with_memory_guidance(self, current_reflection: Dict, 
                                        state_info: Dict) -> Dict:
        """基于记忆指导的进化"""
        
        try:
            logger.info("开始基于记忆的进化...")
            
            # 1. 尝试存储反思记忆
            reflection_id = await self._store_reflection_memory_safe(current_reflection, state_info)
            
            # 2. 尝试检索相似经验
            similar_reflections = await self._retrieve_similar_reflections_safe(state_info)
            
            # 3. 分析模式并调整权重
            adjustments_made = 0
            if similar_reflections:
                adjustments_made = self._adjust_weights_based_on_history(similar_reflections)
            
            # 4. 更新代数
            self.generation += 1
            
            # 5. 记录进化历史
            evolution_record = {
                'generation': self.generation,
                'timestamp': time.time(),
                'reflection_id': reflection_id,
                'similar_experiences': len(similar_reflections),
                'quality_score': current_reflection.get('quality_score', 0.5),
                'adjustments_made': adjustments_made
            }
            self.evolution_history.append(evolution_record)
            
            evolution_result = {
                'success': True,
                'generation': self.generation,
                'reflection_id': reflection_id,
                'similar_experiences': len(similar_reflections),
                'adjustments_made': adjustments_made
            }
            
            logger.success(f"基于记忆的进化完成: 第{self.generation}代")
            return evolution_result
            
        except Exception as e:
            logger.error(f"基于记忆的进化失败: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _store_reflection_memory_safe(self, reflection_data: Dict, state_info: Dict) -> str:
        """安全地存储反思记忆"""
        
        try:
            reflection_id = f"reflection_{uuid.uuid4().hex[:8]}"
            
            # 构建存储文本
            reflection_text = self._build_reflection_text(reflection_data, state_info)
            
            # 尝试存储到记忆系统
            if self.memory and hasattr(self.memory, 'chroma_memory') and self.memory.chroma_memory:
                try:
                    # 尝试不同的存储方法
                    if hasattr(self.memory.chroma_memory, 'store_website_knowledge'):
                        success = self.memory.chroma_memory.store_website_knowledge(
                            domain=self._extract_domain(state_info.get('url', '')),
                            content=reflection_text,
                            metadata={
                                'type': 'reflection_memory',
                                'reflection_id': reflection_id,
                                'quality_score': reflection_data.get('quality_score', 0.5),
                                'generation': self.generation,
                                'timestamp': time.time()
                            }
                        )
                    elif hasattr(self.memory.chroma_memory, 'add_documents'):
                        # 使用原生 ChromaDB 接口
                        self.memory.chroma_memory.add_documents(
                            documents=[reflection_text],
                            metadatas=[{
                                'type': 'reflection_memory',
                                'reflection_id': reflection_id,
                                'quality_score': reflection_data.get('quality_score', 0.5),
                                'generation': self.generation,
                                'timestamp': time.time()
                            }],
                            ids=[reflection_id]
                        )
                        success = True
                    else:
                        logger.warning("记忆系统不支持存储操作")
                        success = False
                    
                    if success:
                        logger.info(f"反思记忆已存储: {reflection_id}")
                        return reflection_id
                        
                except Exception as e:
                    logger.error(f"存储到记忆系统失败: {e}")
            
            # 本地存储作为备份
            self._store_locally(reflection_id, reflection_data, state_info)
            return reflection_id
            
        except Exception as e:
            logger.error(f"存储反思记忆异常: {e}")
            return "storage_error"
    
    def _store_locally(self, reflection_id: str, reflection_data: Dict, state_info: Dict):
        """本地存储反思记忆"""
        try:
            import os
            import json
            
            # 创建本地存储目录
            storage_dir = "./memory_data/reflections"
            os.makedirs(storage_dir, exist_ok=True)
            
            # 存储数据
            storage_data = {
                'reflection_id': reflection_id,
                'reflection_data': reflection_data,
                'state_info': state_info,
                'timestamp': time.time(),
                'generation': self.generation
            }
            
            file_path = os.path.join(storage_dir, f"{reflection_id}.json")
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(storage_data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"反思记忆已本地存储: {file_path}")
            
        except Exception as e:
            logger.error(f"本地存储失败: {e}")
    
    async def _retrieve_similar_reflections_safe(self, context: Dict) -> List[Dict]:
        """安全地检索相似反思"""
        
        try:
            # 先尝试从记忆系统检索
            if self.memory and hasattr(self.memory, 'chroma_memory') and self.memory.chroma_memory:
                query_text = self._build_query_text(context)
                
                try:
                    if hasattr(self.memory.chroma_memory, 'query'):
                        results = self.memory.chroma_memory.query(
                            query_texts=[query_text],
                            n_results=5,
                            where={'type': 'reflection_memory'}
                        )
                        
                        # 处理查询结果
                        reflection_results = []
                        if results and 'documents' in results:
                            for i, doc in enumerate(results['documents'][0]):
                                metadata = results.get('metadatas', [[]])[0]
                                if i < len(metadata):
                                    reflection_results.append({
                                        'document': doc,
                                        'metadata': metadata[i] if metadata else {}
                                    })
                        
                        logger.info(f"从记忆系统检索到 {len(reflection_results)} 个相似反思")
                        return reflection_results
                        
                except Exception as e:
                    logger.error(f"从记忆系统检索失败: {e}")
            
            # 尝试从本地存储检索
            return self._retrieve_locally(context)
            
        except Exception as e:
            logger.error(f"检索相似反思失败: {e}")
            return []
    
    def _retrieve_locally(self, context: Dict) -> List[Dict]:
        """从本地存储检索"""
        try:
            import os
            import json
            
            storage_dir = "./memory_data/reflections"
            if not os.path.exists(storage_dir):
                return []
            
            results = []
            for filename in os.listdir(storage_dir):
                if filename.endswith('.json'):
                    file_path = os.path.join(storage_dir, filename)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            results.append({
                                'reflection_data': data.get('reflection_data', {}),
                                'metadata': {
                                    'reflection_id': data.get('reflection_id'),
                                    'quality_score': data.get('reflection_data', {}).get('quality_score', 0.5),
                                    'timestamp': data.get('timestamp', 0)
                                }
                            })
                    except Exception as e:
                        logger.debug(f"读取本地文件失败: {filename} - {e}")
            
            # 按时间排序，返回最近的5个
            results.sort(key=lambda x: x['metadata'].get('timestamp', 0), reverse=True)
            return results[:5]
            
        except Exception as e:
            logger.error(f"本地检索失败: {e}")
            return []
    
    def _build_reflection_text(self, reflection_data: Dict, state_info: Dict) -> str:
        """构建反思文本"""
        
        parts = [
            f"任务: {state_info.get('task', 'unknown')}",
            f"URL: {state_info.get('url', 'unknown')}",
            f"质量分数: {reflection_data.get('quality_score', 0.5)}",
        ]
        
        issues = reflection_data.get('issues_found', [])
        if issues:
            parts.append(f"问题: {', '.join(issues)}")
        
        recommendations = reflection_data.get('recommendations', [])
        if recommendations:
            parts.append(f"建议: {', '.join(recommendations)}")
        
        return " | ".join(parts)
    
    def _build_query_text(self, context: Dict) -> str:
        """构建查询文本"""
        
        query_parts = []
        
        if context.get('task'):
            query_parts.append(f"任务: {context['task']}")
        
        if context.get('url'):
            query_parts.append(f"URL: {context['url']}")
        
        return " ".join(query_parts)
    
    def _adjust_weights_based_on_history(self, similar_reflections: List[Dict]) -> int:
        """基于历史调整权重"""
        
        if not similar_reflections:
            return 0
        
        adjustments_made = 0
        
        # 计算历史平均质量
        quality_scores = []
        for reflection in similar_reflections:
            quality = reflection.get('metadata', {}).get('quality_score', 0.5)
            quality_scores.append(quality)
        
        if not quality_scores:
            return 0
        
        avg_quality = np.mean(quality_scores)
        
        # 如果历史质量较低，调整权重
        if avg_quality < 0.6:
            old_download = self.classification_weights['download_indicators']
            old_metadata = self.classification_weights['metadata_quality']
            
            self.classification_weights['download_indicators'] += 0.05
            self.classification_weights['metadata_quality'] += 0.03
            adjustments_made += 2
            
            # 归一化
            total = sum(self.classification_weights.values())
            for key in self.classification_weights:
                self.classification_weights[key] = self.classification_weights[key] / total
            
            logger.debug(f"基于历史质量 {avg_quality:.2f} 调整了权重: "
                        f"download_indicators {old_download:.3f} -> {self.classification_weights['download_indicators']:.3f}, "
                        f"metadata_quality {old_metadata:.3f} -> {self.classification_weights['metadata_quality']:.3f}")
        
        return adjustments_made
    
    def _extract_domain(self, url: str) -> str:
        """提取域名"""
        try:
            from urllib.parse import urlparse
            return urlparse(url).netloc or 'unknown'
        except:
            return 'unknown'
    
    async def get_domain_insights(self, domain: str) -> Dict:
        """获取域名洞察"""
        
        try:
            # 基于历史记录计算洞察
            domain_records = [
                h for h in self.evolution_history 
                if self._extract_domain(h.get('url', '')) == domain
            ]
            
            insights = {
                'domain': domain,
                'total_experiences': len(domain_records),
                'avg_quality': 0.5,
                'success_rate': 0.5,
                'confidence_level': 'medium'
            }
            
            # 如果有该域名的历史记录
            if domain_records:
                quality_scores = [r.get('quality_score', 0.5) for r in domain_records]
                insights['avg_quality'] = np.mean(quality_scores)
                insights['success_rate'] = sum(1 for q in quality_scores if q > 0.6) / len(quality_scores)
                
                if insights['success_rate'] > 0.7:
                    insights['confidence_level'] = 'high'
                elif insights['success_rate'] < 0.4:
                    insights['confidence_level'] = 'low'
            else:
                # 使用全局历史记录
                if self.evolution_history:
                    all_quality_scores = [h.get('quality_score', 0.5) for h in self.evolution_history]
                    insights['avg_quality'] = np.mean(all_quality_scores)
                    insights['total_experiences'] = len(self.evolution_history)
            
            return insights
            
        except Exception as e:
            logger.error(f"获取域名洞察失败: {e}")
            return {'domain': domain, 'error': str(e)}
    
    async def retrieve_similar_reflections(self, context: Dict, top_k: int = 5) -> List[Dict]:
        """检索相似反思（公共接口）"""
        return await self._retrieve_similar_reflections_safe(context)
    
    def get_evolution_stats(self):
        """获取进化统计 - 添加这个缺少的方法"""
        
        # 创建一个简单的统计类
        class EvolutionStats:
            def __init__(self, generation, total_evolutions, current_quality, quality_trend, last_evolution_time):
                self.generation = generation
                self.total_evolutions = total_evolutions
                self.current_quality = current_quality
                self.quality_trend = quality_trend
                self.last_evolution_time = last_evolution_time
            
            def to_dict(self):
                """转换为字典"""
                return {
                    'generation': self.generation,
                    'total_evolutions': self.total_evolutions,
                    'current_quality': self.current_quality,
                    'quality_trend': self.quality_trend,
                    'last_evolution_time': self.last_evolution_time
                }
            
            def get(self, key, default=None):
                """提供 get 方法以兼容字典访问"""
                return getattr(self, key, default)
        
        # 计算当前质量和趋势
        current_quality = 0.5
        quality_trend = 'stable'
        
        if hasattr(self, 'evolution_history') and self.evolution_history:
            recent_quality = self.evolution_history[-1].get('quality_score', 0.5)
            current_quality = recent_quality
            
            if len(self.evolution_history) >= 2:
                prev_quality = self.evolution_history[-2].get('quality_score', 0.5)
                if recent_quality > prev_quality + 0.05:
                    quality_trend = 'improving'
                elif recent_quality < prev_quality - 0.05:
                    quality_trend = 'declining'
        
        return EvolutionStats(
            generation=getattr(self, 'generation', 0),
            total_evolutions=len(getattr(self, 'evolution_history', [])),
            current_quality=current_quality,
            quality_trend=quality_trend,
            last_evolution_time=self.evolution_history[-1]['timestamp'] if hasattr(self, 'evolution_history') and self.evolution_history else 0
        )

# 全局实例
_memory_evolution_engine = None

def get_memory_evolution_engine():
    """获取基于记忆的进化引擎"""
    global _memory_evolution_engine
    if _memory_evolution_engine is None:
        _memory_evolution_engine = MemoryBasedEvolutionEngine()
    return _memory_evolution_engine
