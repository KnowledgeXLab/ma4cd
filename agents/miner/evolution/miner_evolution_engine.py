import sys
import os
import json
import asyncio
import time
import random
import hashlib
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from loguru import logger

# =============================================================================
# 🛠️ 路径暴力修正 (确保能找到 agents 包)
# =============================================================================
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# =============================================================================
# 📦 绝对路径导入
# =============================================================================
try:
    from agents.miner.llms.miner_llm import MinerLLMClient
    from agents.miner.memory.managers.memory_manager import UnifiedMemoryManager as MemoryManager
except ImportError as e:
    logger.error(f"❌ EvolutionEngine 导入失败 (请检查路径): {e}")
    pass

@dataclass
class EvolutionStats:
    """进化统计数据结构"""
    generation: int
    total_evolutions: int
    current_quality: float
    quality_trend: str
    last_evolution_time: float
    
    def get(self, key: str, default=None):
        return getattr(self, key, default)
    
    def to_dict(self) -> Dict:
        return asdict(self)

class MemoryBasedEvolutionEngine:
    def __init__(self, memory_manager=None):
        self.memory_manager = memory_manager
        self.storage = getattr(memory_manager, 'storage', None)
        
        self.generation = 0
        if self.storage:
            try:
                self.generation = self._restore_generation_from_storage()
            except Exception as restore_err:
                logger.warning(f"恢复进化代数失败，使用默认代数 0: {restore_err}")
                self.generation = 0
        
        self.current_config = self._get_default_config()
        restored_cfg = self._restore_latest_config_from_storage()
        if restored_cfg:
            self.current_config = self._merge_with_default_config(restored_cfg)

        self.classification_weights = {"default": 1.0}
        # 运行时临时指导
        self.guidance = {}
        
        logger.info(f"🧬 EvolutionEngine 觉醒 | 初始代数: {self.generation}")

    def _restore_generation_from_storage(self) -> int:
        """
        从持久化存储恢复全局进化代数，避免每次重启都从 0 开始。
        优先使用 strategy_evolution 的总记录数，失败时回退读取最新配置中的 generation。
        """
        if not self.storage:
            return 0

        # 1) 直接从 SQLite 统计总进化次数（最稳妥）
        if hasattr(self.storage, "_get_conn"):
            try:
                with self.storage._get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM strategy_evolution")
                    row = cursor.fetchone()
                    if row and row[0] is not None:
                        return int(row[0])
            except Exception as db_err:
                logger.debug(f"通过 strategy_evolution 计数恢复代数失败: {db_err}")

        # 2) 回退：读取最新 evolution config 的 generation 字段
        if hasattr(self.storage, "get_latest_evolution_config"):
            try:
                latest_cfg = self.storage.get_latest_evolution_config() or {}
                gen = int(latest_cfg.get("generation", 0))
                if gen >= 0:
                    return gen
            except Exception as cfg_err:
                logger.debug(f"通过 latest_evolution_config 恢复代数失败: {cfg_err}")

        return 0

    def _get_default_config(self) -> dict:
        """定义 Agent 的初始通用基因 (Base Strategy)"""
        from utils.miner_heuristics import get_evolve_gates, resolve_evolve_float

        gates = get_evolve_gates()
        return {
            'generation': self.generation,
            'max_depth': 2,           
            'timeout': 60,            
            'max_links_limit': 100,   
            'quality_threshold': 0.2, 
            'user_guidance_prompt': "", 
            'prompt_overrides': {
                "structure_node": {
                    "add_focus_patterns": [],
                    "add_ignore_patterns": [],
                    "scoring_bias": {}
                }
            },
            # Miner 双目标中的“召回目标”配置（与 Inspector 准确率目标解耦）
            "recall_weights": {
                "coverage": 0.40,
                "novelty": 0.25,
                "diversity": 0.20,
                "continuity": 0.15
            },
            "rollback_margin": float(os.getenv("MA4CD_EVOLVE_ROLLBACK_MARGIN", "0.05")),
            # 低分保护：召回分/拓扑分过低时，仅存 shadow，不激活
            "min_recall_score_to_activate": resolve_evolve_float(
                "MA4CD_EVOLVE_MIN_RECALL_SCORE",
                gate_key="min_recall_score_to_activate",
                default=float(gates.get("min_recall_score_to_activate", 0.45)),
            ),
            "min_topology_score_to_activate": resolve_evolve_float(
                "MA4CD_EVOLVE_MIN_TOPOLOGY_SCORE",
                gate_key="min_topology_score_to_activate",
                default=float(gates.get("min_topology_score_to_activate", 0.35)),
            ),
            "min_recall_for_stability": resolve_evolve_float(
                "MA4CD_MIN_RECALL_FOR_STABILITY",
                gate_key="min_recall_for_stability",
                default=float(gates.get("min_recall_for_stability", 0.35)),
            ),
            "effective_score": 0.5,
            "recall_score": 0.5,
            "topology_score": 0.5,
            "strategy_mode": "active"
        }

    @staticmethod
    def _strip_shared_supervision_fields(cfg: Dict[str, Any]) -> Dict[str, Any]:
        """共享监督信号只保留在监督表，不写入 Miner 策略配置。"""
        if not isinstance(cfg, dict):
            return cfg
        cfg.pop("shared_pass_rate", None)
        cfg.pop("shared_reviewed", None)
        cfg.pop("shared_reason_breakdown", None)
        return cfg

    def _merge_with_default_config(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """浅层配置 + 关键嵌套段合并，避免历史字段缺失导致运行异常。"""
        base = self._get_default_config()
        if not isinstance(cfg, dict):
            return base
        merged = base.copy()
        merged.update(cfg)

        base_po = base.get("prompt_overrides", {}).get("structure_node", {})
        cfg_po = cfg.get("prompt_overrides", {}).get("structure_node", {}) if isinstance(cfg.get("prompt_overrides", {}), dict) else {}
        po = base_po.copy()
        if isinstance(cfg_po, dict):
            po.update(cfg_po)
        merged["prompt_overrides"] = {"structure_node": po}
        return self._strip_shared_supervision_fields(merged)

    def _restore_latest_config_from_storage(self) -> Optional[Dict[str, Any]]:
        """重启恢复：优先取最近激活策略，再回退到最新配置。"""
        if not self.storage:
            return None
        try:
            if hasattr(self.storage, "get_latest_active_strategy"):
                active = self.storage.get_latest_active_strategy("GLOBAL")
                if active and isinstance(active, dict) and active.get("config"):
                    logger.info("♻️ 已恢复全局激活策略到 current_config")
                    return active.get("config")
        except Exception as e:
            logger.debug(f"恢复全局激活策略失败: {e}")

        try:
            if hasattr(self.storage, "get_latest_evolution_config"):
                latest = self.storage.get_latest_evolution_config() or {}
                if isinstance(latest, dict) and latest:
                    logger.info("♻️ 已恢复最新进化配置到 current_config")
                    return latest
        except Exception as e:
            logger.debug(f"恢复最新进化配置失败: {e}")
        return None

    def get_runtime_config_for_domain(self, domain: str) -> Dict[str, Any]:
        """
        运行时策略加载：优先域名激活策略 -> 域名最佳策略 -> current_config。
        """
        runtime = self._merge_with_default_config(self.current_config)
        if not domain or not self.storage:
            return runtime

        candidate = None
        try:
            if hasattr(self.storage, "get_latest_active_strategy"):
                candidate = self.storage.get_latest_active_strategy(domain)
            if not candidate and hasattr(self.storage, "get_best_strategy"):
                candidate = self.storage.get_best_strategy(domain)
            if candidate and isinstance(candidate, dict) and candidate.get("config"):
                runtime = self._merge_with_default_config(candidate["config"])
        except Exception as e:
            logger.debug(f"读取域名运行时策略失败 ({domain}): {e}")
        return runtime

    @staticmethod
    def _safe_float(v: Any, default: float = 0.0) -> float:
        try:
            return float(v)
        except Exception:
            return float(default)

    def _extract_recall_metrics(self, state_info: Any) -> Dict[str, float]:
        raw = getattr(state_info, "recall_metrics", None)
        if not isinstance(raw, dict) and isinstance(state_info, dict):
            raw = state_info.get("recall_metrics", {})
        if not isinstance(raw, dict):
            raw = {}
        coverage = self._safe_float(raw.get("coverage_rate", 0.0), 0.0)
        novelty = self._safe_float(raw.get("novelty_rate", 0.0), 0.0)
        diversity = self._safe_float(raw.get("domain_diversity", 0.0), 0.0)
        continuity = self._safe_float(raw.get("continuity_score", 0.0), 0.0)
        if continuity <= 0.0:
            continuity = 0.6 if coverage > 0 else 0.2
        miss_rate = self._safe_float(raw.get("miss_rate", max(0.0, 1.0 - coverage)), max(0.0, 1.0 - coverage))
        return {
            "coverage_rate": max(0.0, min(1.0, coverage)),
            "novelty_rate": max(0.0, min(1.0, novelty)),
            "domain_diversity": max(0.0, min(1.0, diversity)),
            "continuity_score": max(0.0, min(1.0, continuity)),
            "miss_rate": max(0.0, min(1.0, miss_rate))
        }

    def _compose_recall_score(self, topology_quality: float, recall_metrics: Dict[str, float], cfg: Dict[str, Any]) -> float:
        weights = cfg.get("recall_weights", {}) if isinstance(cfg.get("recall_weights", {}), dict) else {}
        w_cov = self._safe_float(weights.get("coverage", 0.40), 0.40)
        w_nov = self._safe_float(weights.get("novelty", 0.25), 0.25)
        w_div = self._safe_float(weights.get("diversity", 0.20), 0.20)
        w_con = self._safe_float(weights.get("continuity", 0.15), 0.15)

        # 归一化，防止权重被配置污染
        total_w = w_cov + w_nov + w_div + w_con
        if total_w <= 1e-8:
            w_cov, w_nov, w_div, w_con = 0.40, 0.25, 0.20, 0.15
            total_w = 1.0
        w_cov, w_nov, w_div, w_con = w_cov / total_w, w_nov / total_w, w_div / total_w, w_con / total_w

        coverage = recall_metrics.get("coverage_rate", 0.0)
        novelty = recall_metrics.get("novelty_rate", 0.0)
        diversity = recall_metrics.get("domain_diversity", 0.0)
        continuity = recall_metrics.get("continuity_score", 0.0)
        miss_rate = recall_metrics.get("miss_rate", max(0.0, 1.0 - coverage))

        recall_base = (
            w_cov * coverage +
            w_nov * novelty +
            w_div * diversity +
            w_con * continuity
        )
        # 轻惩罚高漏检率 + 微弱引导拓扑健康
        score = recall_base - (0.10 * miss_rate) + (0.05 * max(0.0, min(1.0, topology_quality)))
        return max(0.0, min(1.0, score))

    # 🌟 兼容 Agent 调用接口
    def update_guidance(self, human_feedback: str):
        self.guidance['user_guidance_prompt'] = human_feedback
        
    def evolve(self, human_feedback: str):
        self.update_guidance(human_feedback)

    async def evolve_with_memory_guidance(self, current_reflection: Dict, state_info: Any) -> Dict:
        """
        🔥 [核心方法] 纯大模型驱动进化：直接吸收 ReflectionNode 提炼的 DNA
        """
        try:
            url = self._safe_get_url(state_info)
            domain = url.split('/')[2] if '/' in url else "unknown"
            
            quality_score = float(current_reflection.get('quality_score', 0.0))
            
            # 🌟 核心：直接提取 LLM 在 ReflectionNode 中蒸馏出的 DNA
            distilled_dna = current_reflection.get('distilled_dna', {})
            new_blacklists = distilled_dna.get('new_blacklist_keywords', [])
            new_focuses = distilled_dna.get('new_high_value_patterns', [])
            logic_correction = distilled_dna.get('logic_correction', "")
            
            logger.info(f"🧬 [进化] 正在吸收 {domain} 的智能反思 DNA (得分: {quality_score})")

            # =========================================================
            # A. 继承历史基座
            # =========================================================
            next_config = self._get_default_config().copy()
            best_history = self.get_global_best_config(domain)
            if best_history:
                if 'user_guidance_prompt' in best_history:
                    del best_history['user_guidance_prompt']
                next_config.update(best_history)
                next_config = self._strip_shared_supervision_fields(next_config)
                logger.info(f"📚 [记忆] 已加载历史最佳配置 (Gen {next_config.get('generation', '?')})")

            # =========================================================
            # B. 注入智能 DNA (大模型决策层)
            # =========================================================
            prompt_overrides = next_config.get('prompt_overrides', {}).get("structure_node", {})
            current_ignores = set(prompt_overrides.get("add_ignore_patterns", []))
            current_focus = set(prompt_overrides.get("add_focus_patterns", []))

            if new_blacklists:
                logger.warning(f"🛡️ [进化免疫] 吸收新黑名单特征: {new_blacklists}")
                current_ignores.update(new_blacklists)
                
            if new_focuses:
                logger.info(f"🎯 [进化聚焦] 吸收新高优特征: {new_focuses}")
                current_focus.update(new_focuses)

            prompt_overrides["add_ignore_patterns"] = list(current_ignores)
            prompt_overrides["add_focus_patterns"] = list(current_focus)
            
            if "structure_node" not in next_config.setdefault("prompt_overrides", {}):
                next_config["prompt_overrides"]["structure_node"] = prompt_overrides
            else:
                next_config["prompt_overrides"]["structure_node"] = prompt_overrides

            # =========================================================
            # C. 用户指令叠加 (Human in the Loop)
            # =========================================================
            next_config['user_guidance_prompt'] = "" 
            active_guidance = []
            
            # 1. 尝试从引擎自身暂存的 runtime_instruction 读取 (兼容 apply_amendment)
            if self.guidance.get('user_guidance_prompt'):
                active_guidance.append(self.guidance['user_guidance_prompt'])
                
            # 2. 尝试从数据库读取针对该域名的持久化指令
            if self.memory_manager and hasattr(self.memory_manager, 'get_active_instructions'):
                try:
                    db_instructions = self.memory_manager.get_active_instructions(domain, agent_name="Miner")
                    if db_instructions:
                        active_guidance.extend(db_instructions)
                except Exception:
                    pass
            
            # 3. 如果大模型给出了纠偏逻辑，也作为系统指令压入
            if logic_correction:
                active_guidance.append(f"[自我反思纠偏]: {logic_correction}")

            if active_guidance:
                combined_guidance = "\n".join([f"- {inst}" for inst in active_guidance])
                next_config['user_guidance_prompt'] = f"\n【⚠️ 最高指令与纠偏策略】\n{combined_guidance}"
                logger.success(f"🗣️ [指导] 已成功打包进化指令层")

            # =========================================================
            # D. 代数推进与固化
            # =========================================================
            recall_metrics = self._extract_recall_metrics(state_info)
            recall_score = self._compose_recall_score(quality_score, recall_metrics, next_config)
            effective_score = recall_score
            prev_effective = float(self.current_config.get("effective_score", self.current_config.get("last_score", 0.5)))
            rollback_margin = float(next_config.get("rollback_margin", 0.05))
            min_recall_score_to_activate = float(next_config.get("min_recall_score_to_activate", 0.45))
            min_topology_score_to_activate = float(next_config.get("min_topology_score_to_activate", 0.35))

            # 绝对低分保护：不管是否有足够 reviewed，低分策略一律不激活
            if effective_score < min_recall_score_to_activate or quality_score < min_topology_score_to_activate:
                logger.warning(
                    f"⛔ [低分守门] {domain} 本次策略不激活 "
                    f"(recall={effective_score:.3f}, topology={quality_score:.3f}, "
                    f"min_recall={min_recall_score_to_activate:.3f}, min_topology={min_topology_score_to_activate:.3f})"
                )
                shadow_cfg = next_config.copy()
                shadow_cfg.update({
                    "updated_at": time.time(),
                    "last_score": quality_score,
                    "effective_score": effective_score,
                    "recall_score": recall_score,
                    "topology_score": quality_score,
                    "strategy_mode": "shadow",
                    "rejection_reason": "low_score_guard"
                })
                shadow_cfg = self._strip_shared_supervision_fields(shadow_cfg)
                if self.storage and hasattr(self.storage, 'store_strategy_evolution'):
                    try:
                        self.storage.store_strategy_evolution(
                            domain=domain,
                            strategy_config=shadow_cfg,
                            performance_score=effective_score,
                            is_active=False
                        )
                    except Exception as e:
                        logger.error(f"存储低分影子策略失败: {e}")
                self._store_reflection_memory_safe(current_reflection, state_info)
                return {
                    'success': False,
                    'rolled_back': True,
                    'rejected_by_guard': 'low_score_guard',
                    'new_generation': self.generation,
                    'config': self.current_config
                }

            # 灰度守门：召回分显著退化时，不激活新策略（自动回滚到当前策略）
            if effective_score < (prev_effective - rollback_margin):
                logger.warning(
                    f"⛔ [回滚守门] {domain} 新策略召回效果退化 "
                    f"(new={effective_score:.3f} < prev={prev_effective:.3f}-{rollback_margin:.3f})，"
                    f"转为 SHADOW，不覆盖 current_config。"
                )
                shadow_cfg = next_config.copy()
                shadow_cfg.update({
                    "updated_at": time.time(),
                    "last_score": quality_score,
                    "effective_score": effective_score,
                    "recall_score": recall_score,
                    "topology_score": quality_score,
                    "strategy_mode": "shadow"
                })
                shadow_cfg = self._strip_shared_supervision_fields(shadow_cfg)
                if self.storage and hasattr(self.storage, 'store_strategy_evolution'):
                    try:
                        self.storage.store_strategy_evolution(
                            domain=domain,
                            strategy_config=shadow_cfg,
                            performance_score=effective_score,
                            is_active=False
                        )
                    except Exception as e:
                        logger.error(f"存储影子策略失败: {e}")
                self._store_reflection_memory_safe(current_reflection, state_info)
                return {
                    'success': False,
                    'rolled_back': True,
                    'new_generation': self.generation,
                    'config': self.current_config
                }

            self.generation += 1
            next_config['generation'] = self.generation
            next_config['updated_at'] = time.time()
            next_config['last_score'] = quality_score
            next_config['effective_score'] = effective_score
            next_config['recall_score'] = recall_score
            next_config['topology_score'] = quality_score
            next_config['recall_metrics'] = recall_metrics
            next_config['strategy_mode'] = "active"
            next_config = self._strip_shared_supervision_fields(next_config)
            self.current_dna = next_config # 保存当前 DNA 供 Report 读取
            
            self.current_config = next_config

            if self.storage and hasattr(self.storage, 'store_strategy_evolution'):
                try:
                    self.storage.store_strategy_evolution(
                        domain=domain,
                        strategy_config=next_config,
                        performance_score=effective_score,
                        is_active=True
                    )
                except Exception as e:
                    logger.error(f"存储进化策略失败: {e}")
                
            self._store_reflection_memory_safe(current_reflection, state_info)

            logger.success(f"✅ Gen {self.generation} 智能进化完成 (完全由大模型驱动)")
            
            return {
                'success': True,
                'new_generation': self.generation,
                'config': next_config,
                'prompt_overrides': next_config['prompt_overrides']
            }

        except Exception as e:
            logger.error(f"❌ 进化流程崩溃: {e}")
            return {'success': False, 'config': self.current_config}

    def get_global_best_config(self, domain: str) -> Dict:
        if not self.storage: return None 
        try:
            if hasattr(self.storage, 'get_latest_active_strategy'):
                active = self.storage.get_latest_active_strategy(domain)
                if active and 'config' in active:
                    return active['config'] if isinstance(active['config'], dict) else json.loads(active['config'])
            if hasattr(self.storage, 'get_best_strategy'):
                best = self.storage.get_best_strategy(domain)
                if best and 'config' in best:
                    return best['config'] if isinstance(best['config'], dict) else json.loads(best['config'])
            elif hasattr(self.storage, 'get_latest_strategy'):
                latest = self.storage.get_latest_strategy(domain)
                if latest and 'config' in latest:
                    return latest['config'] if isinstance(latest['config'], dict) else json.loads(latest['config'])
        except Exception as e:
            logger.warning(f"读取历史配置失败: {e}")
        return None

    def _safe_get_url(self, state_info):
            try:
                if isinstance(state_info, dict): 
                    return state_info.get('current_url', state_info.get('url', 'unknown'))
                # 优先获取 current_url，如果没有再尝试 url
                return getattr(state_info, 'current_url', getattr(state_info, 'url', 'unknown'))
            except Exception:
                return 'unknown'

    def _safe_copy_state(self, state_info):
        if isinstance(state_info, dict): return state_info.copy()
        elif hasattr(state_info, '__dict__'): return {'url': self._safe_get_url(state_info), 'timestamp': time.time()}
        return {'url': 'unknown', 'timestamp': time.time()}

    def _store_reflection_memory_safe(self, reflection_data: Dict, context: Dict = None) -> bool:
        try:
            root_path = "./memory_data"
            if self.storage and hasattr(self.storage, "root_path"): root_path = self.storage.root_path
            reflection_dir = os.path.join(root_path, "reflections")
            os.makedirs(reflection_dir, exist_ok=True)
            timestamp = int(time.time())
            filename = f"reflection_{timestamp}.json"
            if context:
                 url = self._safe_get_url(context)
                 if url != 'unknown':
                     url_hash = hashlib.md5(str(url).encode()).hexdigest()[:8]
                     filename = f"reflection_{url_hash}_{timestamp}.json"
            filepath = os.path.join(reflection_dir, filename)
            save_data = {"meta": self._safe_copy_state(context), "reflection": reflection_data, "timestamp": time.time()}
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.warning(f"存储反思日志失败: {e}")
            return False

    def force_evolve_multiple_times(self, mining_results: Dict, miner_state, max_attempts: int = 5) -> Dict:
        logger.warning("⚠️ force_evolve_multiple_times 已废弃，采用大模型驱动单次精准进化。")
        return {'attempts': 0, 'successful_evolutions': 0}
