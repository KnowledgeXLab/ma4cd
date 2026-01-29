import os
import json
import time
import uuid
import hashlib
import random
import asyncio
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from loguru import logger

try:
    from memory.managers.memory_manager import get_unified_memory
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
    def __init__(self, memory_manager=None):
        self.memory_manager = memory_manager
        # 这里的 self.storage 必须指向持久化实例
        self.storage = getattr(memory_manager, 'storage', None)
        
        # 1. 尝试从数据库恢复代数，若数据库刚被 rm -rf，则 latest 为 None，代数归零
        self.generation = 0
        if self.storage:
            try:
                latest = self.storage.get_latest_evolution_config()
                if latest and isinstance(latest, dict):
                    self.generation = latest.get('generation', 0)
            except Exception:
                self.generation = 0
        
        # 2. 初始化配置（调用下方补全的方法）
        self.current_config = self._get_default_config()
        logger.info(f"🧬 EvolutionEngine 觉醒 | 当前代数: {self.generation}")


    def _get_default_config(self) -> dict:
            """
            🚀 补全方法：定义 Agent 的初始通用基因
            基于通用场景，不针对特定网站，确保冷启动时的探测能力。
            """
            return {
                'quality_threshold': 0.2,       # 初始质量阈值
                'request_delay': 2.0,           # 默认请求间隔（秒）
                'concurrent_limit': 1,          # 并行挖掘限制
                'generation': self.generation,  # 绑定当前代数
                'prompt_overrides': {
                    "structure_node": {
                        # 通用正向特征：引导 Agent 初次运行时关注数据属性强的词汇
                        "add_focus_patterns": [
                            "database", "repository", "archive", 
                            "dataset", "download", "query"
                        ],
                        # 通用负向特征：引导 Agent 避开明显的非数据干扰项
                        "add_ignore_patterns": [
                            "terms-of-service", "privacy-policy", 
                            "news-release", "career"
                        ],
                        "scoring_bias": {}
                    }
                }
            }

    def _safe_copy_state(self, state_info):
        """安全复制状态信息"""
        if isinstance(state_info, dict):
            return state_info.copy()
        elif hasattr(state_info, '__dict__'):
            # 如果是对象，转换为字典
            return {
                'url': self._safe_get_url(state_info),
                'task': getattr(state_info, 'task', 'mining'),
                'timestamp': time.time(),
                'type': type(state_info).__name__
            }
        else:
            return {'url': 'unknown', 'task': 'mining', 'timestamp': time.time()}

    def force_evolve_multiple_times(self, mining_results: Dict, miner_state, max_attempts: int = 5) -> Dict:
        """强制进行多次进化尝试"""
        results = {
            'attempts': 0,
            'successful_evolutions': 0,
            'improvements': [],
            'evolution_history': []
        }
        
        try:
            for attempt in range(max_attempts):
                logger.info(f"🔄 进化尝试 {attempt + 1}/{max_attempts}")
                results['attempts'] += 1
                
                # 安全创建当前状态的副本
                current_state = self._safe_copy_state(miner_state)
                
                # 尝试不同的进化策略
                evolution_strategies = [
                    'quality_threshold_adjustment',
                    'timing_optimization', 
                    'weight_rebalancing',
                    'l3_criteria_relaxation',
                    'metadata_enhancement'
                ]
                
                strategy = evolution_strategies[attempt % len(evolution_strategies)]
                
                # 执行进化
                success = self._apply_evolution_strategy(strategy, current_state)
                
                if success:
                    results['successful_evolutions'] += 1
                    results['improvements'].append(f"策略: {strategy}")
                    results['evolution_history'].append({
                        'attempt': attempt + 1,
                        'strategy': strategy,
                        'timestamp': time.time(),
                        'success': True
                    })
                    
                    # 更新配置
                    self.generation += 1
                    logger.debug(f"进化成功，当前代数: {self.generation}")
                
            logger.success(f"🧬 完成 {max_attempts} 次进化尝试，成功 {results['successful_evolutions']} 次")
            return results
            
        except Exception as e:
            logger.error(f"强制进化过程失败: {e}")
            return results

    def _apply_evolution_strategy(self, strategy: str, current_state: Dict) -> bool:
        """应用进化策略"""
        try:
            if strategy == 'quality_threshold_adjustment':
                return self._adjust_quality_threshold()
            elif strategy == 'timing_optimization':
                return self._adjust_request_timing()
            elif strategy == 'weight_rebalancing':
                return self._adjust_classification_weights()
            elif strategy == 'l3_criteria_relaxation':
                return self._adjust_l3_criteria()
            elif strategy == 'metadata_enhancement':
                return self._adjust_metadata_enhancement()
            else:
                logger.warning(f"未知的进化策略: {strategy}")
                return False
        except Exception as e:
            logger.error(f"应用进化策略 {strategy} 失败: {e}")
            return False

    def _adjust_quality_threshold(self) -> bool:
        """调整质量阈值"""
        try:
            old_threshold = self.current_config.get('quality_threshold', 0.2)
            new_threshold = max(0.1, old_threshold - 0.03)
            self.current_config['quality_threshold'] = new_threshold
            logger.info(f"🧬 进化策略-质量: 阈值 {old_threshold:.3f} -> {new_threshold:.3f}")
            return True
        except Exception as e:
            logger.error(f"调整质量阈值失败: {e}")
            return False

    def _adjust_request_timing(self) -> bool:
        """调整请求时间"""
        try:
            old_delay = self.current_config.get('request_delay', 3.0)
            new_delay = max(1.0, old_delay - 0.3)
            self.current_config['request_delay'] = new_delay
            logger.info(f"🧬 进化策略-时间: 延迟 {old_delay}s -> {new_delay}s")
            return True
        except Exception as e:
            logger.error(f"调整请求时间失败: {e}")
            return False

    def _adjust_classification_weights(self) -> bool:
        """调整分类权重"""
        try:
            weight_keys = list(self.classification_weights.keys())
            if weight_keys:
                key = random.choice(weight_keys)
                old_value = self.classification_weights[key]
                new_value = min(1.0, old_value + 0.04)
                self.classification_weights[key] = new_value
                logger.info(f"🧬 进化策略-权重: {key} {old_value:.3f} -> {new_value:.3f}")
                return True
            return False
        except Exception as e:
            logger.error(f"调整分类权重失败: {e}")
            return False

    def _adjust_l3_criteria(self) -> bool:
        """调整L3标准"""
        try:
            current_level = self.current_config.get('l3_relaxation_level', 0)
            new_level = min(3, current_level + 1)
            self.current_config['l3_relaxation_level'] = new_level
            logger.info(f"🧬 进化策略-L3: 放宽级别 -> {new_level}")
            return True
        except Exception as e:
            logger.error(f"调整L3标准失败: {e}")
            return False

    def _adjust_metadata_enhancement(self) -> bool:
        """调整元数据增强"""
        try:
            current_level = self.current_config.get('metadata_enhancement_level', 1)
            new_level = min(5, current_level + 1)
            self.current_config['metadata_enhancement_level'] = new_level
            logger.info(f"🧬 进化策略-元数据: 增强级别 -> {new_level}")
            return True
        except Exception as e:
            logger.error(f"调整元数据增强失败: {e}")
            return False

    async def evolve_with_memory_guidance(self, current_reflection: Dict, state_info) -> Dict:
            """
            基于记忆指导的深度进化 (Gen 4 架构版)
            功能：将自然语言反思转化为 StructureNode 可理解的 Pattern 补丁
            """
            try:
                url = self._safe_get_url(state_info)
                domain = url.split('/')[2] if '/' in url else "unknown"
                quality_score = current_reflection.get('quality_score', 1.0)
                
                logger.info(f"🧬 启动 Gen {self.generation} 进化流程 | 目标: {domain}")

                # 1. 结构化进化：提取 Pattern (这是关键！)
                # 我们不再只是存一句话，而是提取出可以放入 StructureNode 的模式
                issues = current_reflection.get('issues', [])
                strategy = current_reflection.get('strategy_adjustments', {})
                
                # 初始化补丁包
                prompt_overrides = {
                    "structure_node": {
                        "add_focus_patterns": [],
                        "add_ignore_patterns": [],
                        "scoring_bias": {}
                    }
                }

                # 2. 负向进化：从失败中学习 (General Avoidance)
                # 如果反思提到抓到了太多“文档”或“指南”
                if any("指南" in issue or "文档" in issue or "反爬" in issue for issue in issues):
                    # 提取通用干扰模式
                    prompt_overrides["structure_node"]["add_ignore_patterns"].extend(["guide", "help", "handbook", "tutorial"])
                    # 调整偏置：降低这类页面的评分
                    prompt_overrides["structure_node"]["scoring_bias"]["documentation_penalty"] = "high"

                # 3. 正向进化：从成功中学习 (General Focus)
                struct_focus = strategy.get('structure', {}).get('focus', "")
                if "完整性" in struct_focus or "数据集" in struct_focus:
                    # 强化通用数据特征
                    prompt_overrides["structure_node"]["add_focus_patterns"].extend(["dataset", "download", "archive"])

                # 4. 数值进化：动态调整执行参数
                if quality_score < 0.7:
                    self._adjust_quality_threshold()
                    # 如果分低，通常意味着判定太严，放宽 L3 标准
                    self._adjust_l3_criteria() 

                # 5. 更新配置与状态
                self.generation += 1
                self.current_config.update({
                    'generation': self.generation,
                    'prompt_overrides': prompt_overrides, # 注入结构化补丁
                    'last_score': quality_score,
                    'updated_at': time.time()
                })

                # 6. 存储进化结果 (SQL + JSON)
                if self.storage:
                    self.storage.store_strategy_evolution(
                        domain=domain,
                        strategy_config=self.current_config,
                        performance_score=quality_score
                    )
                
                self._store_reflection_memory_safe(current_reflection, state_info)

                logger.success(f"✅ 第 {self.generation} 代进化完成 | 注入模式: {len(prompt_overrides['structure_node']['add_ignore_patterns'])} 负向 / {len(prompt_overrides['structure_node']['add_focus_patterns'])} 正向")
                
                return {
                    'success': True,
                    'new_generation': self.generation,
                    'prompt_overrides': prompt_overrides # 返回给 Agent 进行下一轮循环
                }

            except Exception as e:
                logger.error(f"❌ 进化流程崩溃: {e}")
                return {'success': False, 'error': str(e)}

    # [新增] 补全缺失的方法
    async def _retrieve_similar_reflections_safe(self, state_info) -> List[Dict]:
        """
        检索相似反思记录的占位符/安全方法
        """
        try:
            if not self.memory_manager:
                return []
            
            # 如果 memory_manager 支持检索，这里调用
            # 暂时返回空列表，避免 Crash
            return []
        except Exception:
            return []

    # [新增] 补全缺失的方法
    def _adjust_weights_based_on_history(self, similar_reflections: List[Dict]) -> int:
        """
        基于历史反思调整权重的简单实现
        """
        adjustments = 0
        if not similar_reflections:
            return 0
            
        # 简单逻辑：如果历史平均分很高，稍微提高阈值；如果很低，尝试调整参数
        try:
            avg_score = sum(r.get('quality_score', 0) for r in similar_reflections) / len(similar_reflections)
            
            if avg_score < 0.3:
                # 历史表现不好，尝试放宽 L3 标准
                if self._adjust_l3_criteria():
                    adjustments += 1
            elif avg_score > 0.8:
                # 历史表现很好，保持现状或微调
                pass
                
        except Exception as e:
            logger.warning(f"调整历史权重时出错: {e}")
            
        return adjustments

    def get_global_best_config(self, domain: str) -> Dict:
            """从数据库获取最优配置"""
            if not self.storage:
                return self.current_config
                
            # 尝试获取该域名特定的进化策略
            latest = self.storage.get_latest_strategy(domain)
            if latest:
                logger.info(f"✨ 发现域名 {domain} 的历史最优基因 (v{latest['version']})")
                config = latest['config']
                config['generation'] = latest['version'] # 用版本号映射代数
                return config
                
            return self.current_config
    
    def _store_reflection_memory_safe(self, reflection_data: Dict, context: Dict = None) -> bool:
        """
        安全存储反思记忆
        :param reflection_data: 反思结果 (JSON)
        :param context: 上下文信息 (如 url, task)，用于生成更有意义的文件名或索引
        """
        try:
            # 1. 准备目录
            root_path = getattr(self.storage, "root_path", "./memory_data")
            reflection_dir = os.path.join(root_path, "reflections")
            os.makedirs(reflection_dir, exist_ok=True)

            # 2. 生成文件名
            
            # 使用 URL 的 hash (如果有) 或者是随机 UUID
            if context and "url" in context:
                url_str = str(context["url"])
                url_hash = hashlib.md5(url_str.encode()).hexdigest()[:8]
                # 加上时间戳避免覆盖
                timestamp_str = str(int(time.time()))
                filename = f"reflection_{url_hash}_{timestamp_str}.json"
            else:
                timestamp = int(time.time())
                filename = f"reflection_{timestamp}.json"
                
            filepath = os.path.join(reflection_dir, filename)

            # 3. 写入文件
            save_data = {
                "meta": self._safe_copy_state(context) if context else {},
                "reflection": reflection_data,
                "timestamp": time.time()
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)

            logger.info(f"反思记忆已保存: {filename}")
            return True

        except Exception as e:
            logger.error(f"存储反思记忆失败: {e}")
            return False

    def _safe_get_url(self, state_info):
        try:
            if isinstance(state_info, dict):
                return state_info.get('url', 'unknown')
            return getattr(state_info, 'url', 'unknown')
        except Exception:
            return 'unknown'