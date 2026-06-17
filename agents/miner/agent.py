import sys
import os
import asyncio
import uuid
import time
import traceback
import hashlib
import re
from typing import Dict, Any, List, Optional, Tuple, Callable, Awaitable, Union
from urllib.parse import urlparse, urlunparse
from loguru import logger

# =============================================================================
# 1. 环境路径修复
# =============================================================================
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# =============================================================================
# 2. 依赖导入
# =============================================================================
try:
    from agents.miner.state.miner_state import MinerState
    from agents.miner.nodes.extract_node import ExtractNode
    from agents.miner.nodes.structure_node import StructureNode
    from agents.miner.nodes.reflection_node import ReflectionNode
    from agents.miner.nodes.report_node import MinerReportNode
    from agents.miner.memory.managers.memory_manager import UnifiedMemoryManager, get_unified_memory
    from agents.miner.evolution.miner_evolution_engine import MemoryBasedEvolutionEngine
    from data_memory_center.manager import DataMemoryCenter

    # 🌟 [核心注入]: 引入我们刚刚升级的轨迹工作记忆
    from agents.miner.memory.storage.working_memory import WorkingMemory 
    from utils.miner_heuristics import (
        get_evolve_gates,
        get_invalid_path_suffixes,
        resolve_evolve_float,
        resolve_evolve_int,
    )
except ImportError as e:
    logger.error(f"❌ 依赖导入失败: {e}")
    # 兜底：如果路径不对，尝试从 agents 内部路径导入
    try:
        from agents.miner.memory.storage.working_memory import WorkingMemory
    except ImportError:
        logger.warning("⚠️ 未能精准定位 WorkingMemory 路径，请确保工作记忆文件位置正确。")
        WorkingMemory = None

class UniversalMinerAgent:
    """
    UniversalMinerAgent [Pure DFS Recall + Trajectory Tracker]
    专注高召回拓扑挖掘：只产出可深挖候选链接，语义分级交由 Inspector 负责。
    """

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.extract_node = ExtractNode()
        self.structure_node = StructureNode()
        self.reflection_node = ReflectionNode()
        self.report_node = MinerReportNode()  
        
        # 与 main_workflow 共享同一个记忆管理单例，避免 active_session_id 错位
        self.memory_manager = get_unified_memory()
        self.evolution_engine = MemoryBasedEvolutionEngine(self.memory_manager)
        self.data_center = DataMemoryCenter()
        self._active_batch_session_id: Optional[str] = None
        self._owns_session_lifecycle: bool = False
        
        # 🌟 实例化会话级工作记忆 (轨迹追踪器，支持 Redis 后端)
        if self.memory_manager and hasattr(self.memory_manager, "create_working_memory"):
            self.working_memory = self.memory_manager.create_working_memory()
        else:
            self.working_memory = WorkingMemory() if WorkingMemory else None
        
        self.runtime_instruction = None
        self.task_hash = "GLOBAL"
        self.batch_stats = {}

        # 状态控制池 (跨并发协程共享)
        self.shared_visited_urls = set()
        self.shared_processing_urls = set()
        self.shared_domain_fail_counts = {}
        self.shared_url_retry_counts = {}
        skill_gates = get_evolve_gates()
        # 正向进化触发参数：高质量产出样本也会促发学习（带冷却，防止过频）
        self._positive_evolve_min_assets = resolve_evolve_int(
            "MA4CD_POSITIVE_EVOLVE_MIN_ASSETS",
            config_value=self.config.get("positive_evolve_min_assets"),
            gate_key="positive_evolve_min_assets",
            default=20,
        )
        self._positive_evolve_min_topology = resolve_evolve_float(
            "MA4CD_POSITIVE_EVOLVE_MIN_TOPOLOGY",
            config_value=self.config.get("positive_evolve_min_topology"),
            gate_key="positive_evolve_min_topology",
            default=0.75,
        )
        self._positive_evolve_cooldown_sec = resolve_evolve_int(
            "MA4CD_POSITIVE_EVOLVE_COOLDOWN_SEC",
            config_value=self.config.get("positive_evolve_cooldown_sec"),
            gate_key="positive_evolve_cooldown_sec",
            default=600,
        )
        self._positive_evolve_last_ts: Dict[str, float] = {}
        # 进化节流与闸门：防止短时爆炸进化（如 3 分钟 20+ 代）
        self._evolve_min_interval_sec = resolve_evolve_int(
            "MA4CD_EVOLVE_MIN_INTERVAL_SEC",
            config_value=self.config.get("evolve_min_interval_sec"),
            gate_key="evolve_min_interval_sec",
            default=8,
        )
        self._evolve_domain_cooldown_sec = resolve_evolve_int(
            "MA4CD_EVOLVE_DOMAIN_COOLDOWN_SEC",
            config_value=self.config.get("evolve_domain_cooldown_sec"),
            gate_key="evolve_domain_cooldown_sec",
            default=90,
        )
        self._evolve_max_per_batch = resolve_evolve_int(
            "MA4CD_EVOLVE_MAX_PER_BATCH",
            config_value=self.config.get("evolve_max_per_batch"),
            gate_key="evolve_max_per_batch",
            default=10,
        )
        self._evolve_max_per_domain_per_batch = resolve_evolve_int(
            "MA4CD_EVOLVE_MAX_PER_DOMAIN_PER_BATCH",
            config_value=self.config.get("evolve_max_per_domain_per_batch"),
            gate_key="evolve_max_per_domain_per_batch",
            default=3,
        )
        self._min_recall_for_stability = resolve_evolve_float(
            "MA4CD_MIN_RECALL_FOR_STABILITY",
            config_value=self.config.get("min_recall_for_stability"),
            gate_key="min_recall_for_stability",
            default=float(skill_gates.get("min_recall_for_stability", 0.35)),
        )
        self._evolve_last_ts_global = 0.0
        self._evolve_last_ts_by_domain: Dict[str, float] = {}
        self._evolve_count_batch = 0
        self._evolve_count_by_domain: Dict[str, int] = {}
        # 噪声域/可信域：噪声域默认不参与进化固化，避免“学坏”
        skill_trusted, skill_noise = self._skill_evolve_domain_defaults()
        self._trusted_domain_patterns = self._load_domain_pattern_set(
            "MA4CD_EVOLVE_TRUSTED_DOMAIN_PATTERNS",
            skill_trusted or [
                r"(^|\.)nasa\.gov$",
                r"(^|\.)jpl\.nasa\.gov$",
                r"(^|\.)esa\.int$",
                r"(^|\.)jannaf\.org$",
                r"(^|\.)dtic\.mil$",
                r"(^|\.)ntrs\.nasa\.gov$",
                r"(^|\.)grc\.nasa\.gov$",
                r"(^|\.)pds-imaging\.jpl\.nasa\.gov$",
            ],
        )
        self._noise_domain_patterns = self._load_domain_pattern_set(
            "MA4CD_EVOLVE_NOISE_DOMAIN_PATTERNS",
            skill_noise or [
                r"(^|\.)instructables\.com$",
                r"(^|\.)rocketpropulsion\.systems$",
                r"(^|\.)spacenews\.com$",
                r"(^|\.)reddit\.com$",
                r"(^|\.)facebook\.com$",
                r"(^|\.)x\.com$",
                r"(^|\.)twitter\.com$",
                r"(^|\.)youtube\.com$",
                r"(^|\.)tiktok\.com$",
                r"(^|\.)medium\.com$",
                r"(^|\.)pinterest\.com$",
            ],
        )

        logger.info("🤖 UniversalMinerAgent 初始化完成 | 模式: 纯DFS高召回 + 反思防循环 + 轨迹追踪")

    def _bind_batch_session(self, incoming_session_id: Optional[str]) -> Optional[str]:
        """
        将当前批次绑定到统一会话：
        - 如果上游传入 session_id，复用该会话（不由 Miner 关闭）
        - 如果未传入，Miner 自建会话（由 Miner 负责关闭）
        """
        if not self.memory_manager or not hasattr(self.memory_manager, "start_session"):
            self._active_batch_session_id = incoming_session_id
            self._owns_session_lifecycle = False
            return self._active_batch_session_id

        task_info = {
            "task_intent": str(self.runtime_instruction or "Miner batch run"),
            "start_time": time.time(),
        }
        bound_id = self.memory_manager.start_session(task_info, session_id=incoming_session_id)
        self._active_batch_session_id = bound_id
        self._owns_session_lifecycle = incoming_session_id is None
        logger.info(
            f"🧷 [Miner Session] 会话已绑定: {bound_id} | source={'external' if incoming_session_id else 'miner'}"
        )
        return bound_id

    def apply_amendment(self, amendments: Dict[str, Any]):
        feedback_text = amendments.get("system_prompt_append", "")
        if not feedback_text: return

        logger.info(f"🧬 Miner 正在吸收人类指导: {feedback_text}")
        engine = self.evolution_engine
        if hasattr(engine, 'evolve'): engine.evolve(human_feedback=feedback_text)
        elif hasattr(engine, 'update_guidance'): engine.update_guidance(human_feedback=feedback_text)
            
        if self.runtime_instruction: self.runtime_instruction += f"\n[User Feedback]: {feedback_text}"
        else: self.runtime_instruction = feedback_text
        logger.success("✅ Miner 进化指令已实时挂载。")

    def _clean_and_check_vdir(self, url: str) -> Tuple[str, bool, str]:
        parsed = urlparse(url)
        path = parsed.path.lower()
        invalid_suffixes = get_invalid_path_suffixes()
        
        modified = True
        while modified:
            modified = False
            if path.endswith('/') and path != '/':
                path = path[:-1]
                modified = True
            for suffix in invalid_suffixes:
                if path.endswith(suffix):
                    path = path[:-len(suffix)]
                    modified = True
        
        cleaned_url = urlunparse((parsed.scheme, parsed.netloc, path or '/', parsed.params, parsed.query, parsed.fragment))
        has_vdir = bool(path.strip('/')) or bool(parsed.query)
        root_url = urlunparse((parsed.scheme, parsed.netloc, '', '', '', ''))
        return cleaned_url, has_vdir, root_url

    def _add_to_blacklist(self, url: str, reason: str):
        try:
            self.data_center.add_blacklist(url, reason, source="miner")
        except: pass

    def _get_structure_patterns_from_dna(self, dna: Dict[str, Any]) -> Tuple[List[str], List[str]]:
        if not isinstance(dna, dict):
            return [], []
        st = dna.get("prompt_overrides", {}).get("structure_node", {})
        if not isinstance(st, dict):
            return [], []
        ignore_patterns = [str(x).strip().lower() for x in (st.get("add_ignore_patterns", []) or []) if str(x).strip()]
        focus_patterns = [str(x).strip().lower() for x in (st.get("add_focus_patterns", []) or []) if str(x).strip()]
        return ignore_patterns, focus_patterns

    def _matches_any_pattern(self, text: str, patterns: List[str]) -> bool:
        if not text:
            return False
        t = text.lower()
        for p in patterns:
            try:
                if re.search(p, t):
                    return True
            except re.error:
                if p in t:
                    return True
        return False

    def _skill_evolve_domain_defaults(self) -> Tuple[Optional[List[str]], Optional[List[str]]]:
        try:
            from utils.skill_loader import get_miner_evolve_domain_patterns
            return get_miner_evolve_domain_patterns()
        except Exception:
            return None, None

    def _load_domain_pattern_set(self, env_name: str, default_patterns: List[str]) -> List[str]:
        raw = os.getenv(env_name, "").strip()
        if not raw:
            return list(default_patterns)
        items = [x.strip() for x in re.split(r"[,\n;]", raw) if x.strip()]
        return items if items else list(default_patterns)

    def _is_domain_match(self, domain: str, patterns: List[str]) -> bool:
        d = (domain or "").lower().strip()
        if not d:
            return False
        for p in patterns:
            try:
                if re.search(p, d):
                    return True
            except re.error:
                if p.lower() in d:
                    return True
        return False

    def _is_noise_domain_for_evolution(self, domain: str) -> bool:
        # 可信域优先放行，避免规则误伤
        if self._is_domain_match(domain, self._trusted_domain_patterns):
            return False
        return self._is_domain_match(domain, self._noise_domain_patterns)

    def _evolution_gate(
        self,
        domain: str,
        reflection_reason: str,
        topology_score: float,
        final_assets_count: int
    ) -> Tuple[bool, str]:
        now = time.time()

        # 批次总上限
        if self._evolve_count_batch >= self._evolve_max_per_batch:
            return False, "batch_cap"
        # 单域名批次上限
        if self._evolve_count_by_domain.get(domain, 0) >= self._evolve_max_per_domain_per_batch:
            return False, "domain_batch_cap"
        # 全局最小间隔
        if now - self._evolve_last_ts_global < self._evolve_min_interval_sec:
            return False, "global_cooldown"
        # 单域最小间隔
        if now - self._evolve_last_ts_by_domain.get(domain, 0.0) < self._evolve_domain_cooldown_sec:
            return False, "domain_cooldown"
        # 噪声域不固化：Miner 仅优化召回，不吸收明显噪声域策略
        if self._is_noise_domain_for_evolution(domain):
            return False, "noise_domain"
        # 低产出 + 高拓扑分通常是“页面看起来健康但价值低”，不做密集进化
        if reflection_reason == "low_yield" and topology_score >= 0.7 and final_assets_count == 0:
            return False, "low_yield_high_topology_skip"

        return True, "ok"

    def _register_evolution_attempt(self, domain: str):
        now = time.time()
        self._evolve_last_ts_global = now
        self._evolve_last_ts_by_domain[domain] = now
        self._evolve_count_batch += 1
        self._evolve_count_by_domain[domain] = self._evolve_count_by_domain.get(domain, 0) + 1

    def _lookup_path_efficiency(self, url: str, path_hints: List[Dict[str, Any]]) -> float:
        """读取路径效率先验：优先精确匹配，其次前缀匹配。"""
        if not url or not path_hints:
            return 0.0
        best = 0.0
        for hint in path_hints:
            path_url = str(hint.get("path_url", "") or "")
            if not path_url:
                continue
            eff = float(hint.get("efficiency", 0.0) or 0.0)
            if url == path_url:
                return eff
            if url.startswith(path_url):
                best = max(best, eff * 0.9)
        return best

    def _rank_candidates_for_output(
        self,
        candidates: List[Dict[str, Any]],
        domain: str,
        dna: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        运行时硬策略排序：
        - 融合路径效率（Memory 2）
        - 融合 focus/ignore 模式（Evolution DNA）
        - 对 ignore 且非 focus 的候选执行硬降权/剔除
        """
        ignore_patterns, focus_patterns = self._get_structure_patterns_from_dna(dna)
        path_hints = []
        if self.memory_manager and hasattr(self.memory_manager, "get_top_path_efficiency"):
            path_hints = self.memory_manager.get_top_path_efficiency(domain, limit=200)

        type_weight = {
            "asset_hint": 1.00,
            "legacy_l4_clue": 1.00,
            "legacy_l3_candidate": 0.90,
            "exploration_target": 0.80,
            "entry": 0.50,
            "unknown": 0.30
        }

        ranked = []
        for item in candidates:
            url = str(item.get("url", "") or "")
            title = str(item.get("title", "") or "")
            ctype = str(item.get("candidate_type", "unknown") or "unknown")
            if not url:
                continue

            text = f"{url} {title}".lower()
            ignore_hit = self._matches_any_pattern(text, ignore_patterns)
            focus_hit = self._matches_any_pattern(text, focus_patterns)

            # ignore 且非 focus：硬剔除，避免学到的噪音词只停留在 prompt 层
            if ignore_hit and not focus_hit:
                continue

            eff = self._lookup_path_efficiency(url, path_hints)
            score = type_weight.get(ctype, 0.3) + (0.8 * eff) + (0.5 if focus_hit else 0.0)
            ranked.append((score, item))

        ranked.sort(key=lambda x: x[0], reverse=True)
        return [it for _, it in ranked]

    def _compute_recall_metrics(
        self,
        domain: str,
        candidates: List[Dict[str, Any]],
        final_assets: List[Dict[str, Any]],
        topology_score: float,
        exploration_targets_count: int
    ) -> Dict[str, float]:
        """
        Miner 召回目标指标（严格与 Inspector 准确率解耦）：
        - coverage_rate: 候选覆盖率
        - domain_diversity: 域名多样性
        - novelty_rate: 候选新颖度（基于工作记忆）
        - miss_rate: 漏检率代理（1 - coverage）
        - recall_score: 用于 Miner 进化的总分
        """
        candidate_cnt = max(1, int(len(candidates)))
        output_cnt = int(len(final_assets))

        coverage_rate = min(1.0, output_cnt / candidate_cnt)
        miss_rate = max(0.0, 1.0 - coverage_rate)

        output_domains = set()
        novel_cnt = 0
        for item in final_assets:
            u = str(item.get("url", "") or "")
            if u:
                d = (urlparse(u).netloc or domain).lower()
                if d:
                    output_domains.add(d)
            if self.working_memory:
                st = self.working_memory.check_url_status(u) if u else None
                if not st:
                    novel_cnt += 1
            else:
                novel_cnt += 1

        domain_diversity = min(1.0, len(output_domains) / max(1, output_cnt))
        novelty_rate = min(1.0, novel_cnt / max(1, output_cnt)) if output_cnt > 0 else 0.0
        continuity_score = 1.0 if exploration_targets_count > 0 else (0.6 if output_cnt > 0 else 0.2)

        recall_score = (
            0.40 * coverage_rate +
            0.20 * domain_diversity +
            0.25 * novelty_rate +
            0.15 * continuity_score
        )
        recall_score = max(0.0, min(1.0, recall_score))

        return {
            "coverage_rate": round(coverage_rate, 4),
            "domain_diversity": round(domain_diversity, 4),
            "novelty_rate": round(novelty_rate, 4),
            "continuity_score": round(continuity_score, 4),
            "miss_rate": round(miss_rate, 4),
            "topology_score": round(float(topology_score), 4),
            "recall_score": round(recall_score, 4)
        }

    def ingest_inspector_supervision(
        self,
        miner_items: List[Dict[str, Any]],
        audited_items: List[Dict[str, Any]],
        inspector_supervision: Optional[List[Dict[str, Any]]] = None
    ):
        """
        共享监督通道（只接收 domain + reason_code + pass_rate，不共享策略状态）。
        """
        if not self.memory_manager:
            return

        # 严格模式：仅允许 Inspector 标准化 supervision payload，拒绝旧兼容分支。
        if not inspector_supervision or not isinstance(inspector_supervision, list):
            logger.warning("⚠️ [监督通道] 缺少标准 supervision payload，已跳过写入（不再支持旧兼容分支）。")
            return

        for row in inspector_supervision:
            if not isinstance(row, dict):
                continue
            d = str(row.get("domain", "") or "").strip().lower()
            if not d:
                continue
            reviewed = int(row.get("reviewed_count", row.get("miner_items", 0)) or 0)
            pass_cnt = int(row.get("pass_count", row.get("passed_items", 0)) or 0)
            reject_cnt = int(row.get("reject_count", row.get("rejected_items", 0)) or 0)
            if reviewed <= 0:
                reviewed = max(0, pass_cnt + reject_cnt)
            reason_breakdown = row.get("reason_breakdown", {}) or {}
            if hasattr(self.memory_manager, "record_domain_supervision"):
                self.memory_manager.record_domain_supervision(
                    domain=d,
                    miner_items=reviewed,
                    passed_items=pass_cnt,
                    rejected_items=reject_cnt,
                    reason_breakdown=reason_breakdown
                )

    async def _run_single_url_pipeline(self, url: str) -> List[Dict[str, Any]]:
            from agents.miner.tools.browse_url_resolve import normalize_browse_url

            original_seed_url = url
            url, host_remapped = normalize_browse_url(url)
            if host_remapped:
                logger.info(f"🔗 Miner 入口域名映射: {original_seed_url} -> {url}")

            run_id = str(uuid.uuid4())[:8]
            parsed = urlparse(url)
            domain = parsed.netloc or "unknown"
            
            # 🌟 [核心拦截 1]: O(1) 轨迹记忆秒杀
            if self.working_memory:
                past_status = self.working_memory.check_url_status(url)
                if past_status in ["INVALID", "DROP", "DROP_IRRELEVANT", "ERROR", "BLOCKED"]:
                    logger.debug(f"🛑 [轨迹秒杀] 该路径已被记忆判定为无效，放弃下钻: {url}")
                    return []
            
            state = MinerState(
                current_clue={"url": url, "domain": domain, "tier": "UNKNOWN"}, 
                task=f"Mining {domain}", 
                mined_items=[],
                visited_urls=self.shared_visited_urls,
                processing_urls=self.shared_processing_urls,
                domain_fail_counts=self.shared_domain_fail_counts,
                url_retry_counts=self.shared_url_retry_counts,
                coordination=(
                    self.memory_manager.coordination
                    if self.memory_manager and getattr(self.memory_manager, "coordination", None)
                    else None
                ),
                session_id=self._active_batch_session_id or "",
            )
            # 统一会话ID优先，避免每个 URL 用随机 run_id 造成会话碎片化
            state.task_id = self._active_batch_session_id or run_id
            state.run_id = run_id
            state.user_query = self.runtime_instruction 
            
            # 🌟 [核心注入]: 将工作记忆挂载到 state 上，传给下游 Node
            state.working_memory = self.working_memory

            if state.is_domain_banned(domain):
                logger.debug(f"🛑 [域名熔断] 该域名已被拉黑，跳过: {domain}")
                return []
            if not state.acquire_processing_lock(url): return []

            pipeline_success = False
            start_time = time.time()  # 🔥 记录提取开始时间，用于统计性能
            
            try:
                url_lower = url.lower()
                binary_exts = ('.pdf', '.zip', '.gz', '.tar', '.csv', '.xlsx', '.xls', '.nc', '.hdf5', '.json', '.txt')
                download_keywords = ('/download', 'download=', 'dl=1', '/servlets/purl/', 'export=')
                if url_lower.split('?')[0].endswith(binary_exts) or any(k in url_lower for k in download_keywords):
                    logger.info(f"📂 [文件嗅探] 判定为直接数据资产，跳过浏览器渲染: {url}")
                    # 刻录成功轨迹
                    if self.working_memory: self.working_memory.record_step(url, "L4_DIRECT_FILE", depth=1)
                    return [{"title": url.split('/')[-1] or "Data Asset", "url": url, "level": "L4", "reason": "Direct Download/Binary Link"}] 

                # 基因遗传：按域名加载运行时最优策略（优先 active domain strategy）
                if not hasattr(state, "evolution_dna"):
                    setattr(state, "evolution_dna", {})
                
                runtime_cfg = None
                if hasattr(self.evolution_engine, 'get_runtime_config_for_domain'):
                    runtime_cfg = self.evolution_engine.get_runtime_config_for_domain(domain)
                elif hasattr(self.evolution_engine, 'current_config'):
                    runtime_cfg = self.evolution_engine.current_config
                if isinstance(runtime_cfg, dict):
                    state.evolution_dna.update(runtime_cfg)
                state.evolution_dna["instruction_override"] = self.runtime_instruction

                logger.info(f"⛏️ [挖掘先行] 正在暴力扫描页面潜在链接: {url}")
                # 🚀 ExtractNode 内部已经能使用 working_memory 过滤烂链接了
                state = await self.extract_node.execute(state)
                if not state.is_valid:
                    state.record_domain_failure(domain)
                    return []
                if not state.extracted_content: return []
                
                # 🚀 执行重构后的 StructureNode (内部会自动把判定结果写回 working_memory)
                state = await self.structure_node.execute(state)

                current_site_name = state.structured_data.get("current_site_name", domain)
                if not current_site_name: current_site_name = domain

                # 纯高召回模式：只按拓扑结构聚合候选链接，语义筛选和分级交由 Inspector。
                candidates = [{"url": url, "is_entry": True, "title": current_site_name, "candidate_type": "entry"}]
                for c in state.structured_data.get("candidate_assets", []):
                    if c.get("url"):
                        candidates.append({
                            "url": c.get("url"),
                            "title": c.get("text") or c.get("reason") or "Asset Hint",
                            "candidate_type": "asset_hint"
                        })
                for c in state.structured_data.get("exploration_targets", [])[:120]:
                    if c.get("url"):
                        candidates.append({
                            "url": c.get("url"),
                            "title": c.get("reason") or c.get("text") or "Exploration Target",
                            "candidate_type": "exploration_target"
                        })
                # 向下兼容老字段（如果上游还在生产 l3_candidates/l4_clues，也一并吸纳为候选）
                for c in state.structured_data.get("l3_candidates", []):
                    if c.get("url"):
                        candidates.append({
                            "url": c.get("url"),
                            "title": c.get("title") or "Legacy Candidate",
                            "candidate_type": "legacy_l3_candidate"
                        })
                for c in state.structured_data.get("l4_clues", []):
                    if c.get("url"):
                        candidates.append({
                            "url": c.get("url"),
                            "title": c.get("title") or "Legacy Clue",
                            "candidate_type": "legacy_l4_clue"
                        })

                final_assets = []
                seen_output_urls = set()
                topology_score = float(state.structured_data.get("topology_score", 0.5))
                logger.info(f"🧭 [高召回DFS] 聚合候选 {len(candidates)} 条，按拓扑去重后输出给 Inspector...")

                ranked_candidates = self._rank_candidates_for_output(candidates, domain, getattr(state, "evolution_dna", {}))
                max_output = int(getattr(state, "evolution_dna", {}).get("max_links_limit", 120))
                max_output = max(1, max_output)

                # 确保 entry URL 一定进入候选输出，由 Inspector 判定 L2/L3
                entry_clean_url, _, _ = self._clean_and_check_vdir(url)
                selected_candidates = []
                selected_clean_urls = set()

                # 先尝试注入 entry 候选（若存在）
                for item in ranked_candidates:
                    cand_url = item.get("url")
                    if not cand_url:
                        continue
                    clean_url, _, _ = self._clean_and_check_vdir(cand_url)
                    is_entry_candidate = str(item.get("candidate_type", "") or "").strip().lower() == "entry" or clean_url == entry_clean_url
                    if is_entry_candidate:
                        selected_candidates.append(item)
                        selected_clean_urls.add(clean_url)
                        break

                # 再按排序补齐其余候选，直到上限
                for item in ranked_candidates:
                    if len(selected_candidates) >= max_output:
                        break
                    cand_url = item.get("url")
                    if not cand_url:
                        continue
                    clean_url, _, _ = self._clean_and_check_vdir(cand_url)
                    if clean_url in selected_clean_urls:
                        continue
                    selected_candidates.append(item)
                    selected_clean_urls.add(clean_url)

                for item in selected_candidates:
                    cand_url = item.get("url")
                    if not cand_url:
                        continue
                    clean_url, _, _ = self._clean_and_check_vdir(cand_url)
                    if not clean_url or clean_url in seen_output_urls:
                        continue

                    cand_domain = urlparse(clean_url).netloc
                    if state.is_domain_banned(cand_domain):
                        continue

                    is_entry_candidate = str(item.get("candidate_type", "") or "").strip().lower() == "entry" or clean_url == entry_clean_url
                    candidate_lock_acquired = False
                    # 只做工程级并发保护，不做语义去留裁决。
                    # entry URL 与当前 pipeline 根 URL 相同，避免被同轮根锁误拦截。
                    if not is_entry_candidate:
                        if not state.acquire_processing_lock(clean_url):
                            continue
                        candidate_lock_acquired = True

                    try:
                        if self.working_memory and not is_entry_candidate:
                            past_status = self.working_memory.check_url_status(clean_url)
                            if past_status in ["DROP", "DROP_IRRELEVANT", "ERROR", "BLOCKED"]:
                                continue

                        asset_data = {
                            "title": item.get("title") or clean_url,
                            "url": clean_url,
                            "level": "CANDIDATE",
                            "candidate_type": item.get("candidate_type", "unknown"),
                            "topology_score": topology_score,
                            "description": state.structured_data.get("site_analysis", "")
                        }
                        final_assets.append(asset_data)
                        seen_output_urls.add(clean_url)

                        if self.working_memory:
                            self.working_memory.record_step(
                                clean_url,
                                "TOPOLOGY_CANDIDATE",
                                depth=2,
                                reason=asset_data["candidate_type"]
                            )
                    finally:
                        if candidate_lock_acquired:
                            state.release_processing_lock(clean_url, success=True)

                # 召回指标（Miner 目标函数）
                exploration_targets = state.structured_data.get("exploration_targets", []) or []
                recall_metrics = self._compute_recall_metrics(
                    domain=domain,
                    candidates=candidates,
                    final_assets=final_assets,
                    topology_score=topology_score,
                    exploration_targets_count=len(exploration_targets)
                )
                setattr(state, "recall_metrics", recall_metrics)

                # 共享监督通道仅用于观测（不参与 Miner 奖励）
                supervision = {}
                if self.memory_manager and hasattr(self.memory_manager, "get_domain_supervision"):
                    supervision = self.memory_manager.get_domain_supervision(domain) or {}
                shared_pass_rate = supervision.get("pass_rate")
                shared_reviewed = int(supervision.get("reviewed_count", 0) or 0)
                shared_reasons = supervision.get("reason_breakdown", {}) or {}

                # 拓扑无产出/轨迹打转/低召回/高质量成功样本时，触发反思与进化。
                should_reflect = (len(final_assets) == 0)
                reflection_reason = "low_yield"
                if self.working_memory and self.working_memory.is_looping(drop_threshold=3):
                    should_reflect = True
                    reflection_reason = "looping"

                min_recall_for_stability = float(
                    getattr(state, "evolution_dna", {}).get(
                        "min_recall_for_stability", self._min_recall_for_stability,
                    )
                )
                if recall_metrics.get("recall_score", 0.0) < min_recall_for_stability and len(candidates) >= 10:
                    should_reflect = True
                    reflection_reason = "low_recall"

                # 新增：正向样本学习触发（高召回成功时也蒸馏可复用拓扑策略）
                positive_trigger = (
                    len(final_assets) >= self._positive_evolve_min_assets
                    and topology_score >= self._positive_evolve_min_topology
                )
                if positive_trigger:
                    now_ts = time.time()
                    last_ts = self._positive_evolve_last_ts.get(domain, 0.0)
                    if now_ts - last_ts >= self._positive_evolve_cooldown_sec:
                        should_reflect = True
                        reflection_reason = "positive_success"
                        self._positive_evolve_last_ts[domain] = now_ts

                if should_reflect:
                    if reflection_reason == "positive_success":
                        state.error_message = (
                            f"高质量成功样本触发正向进化。当前URL: {url}，"
                            f"候选数量: {len(candidates)}，输出数量: {len(final_assets)}，"
                            f"拓扑评分: {topology_score:.2f}。请提炼可复用拓扑模式。"
                        )
                    elif reflection_reason == "low_recall":
                        state.error_message = (
                            f"召回信号触发进化。域名: {domain}，"
                            f"coverage={recall_metrics.get('coverage_rate', 0):.2f}，"
                            f"novelty={recall_metrics.get('novelty_rate', 0):.2f}，"
                            f"diversity={recall_metrics.get('domain_diversity', 0):.2f}。"
                            f"请优先优化“找全、找广、不断档”的拓扑策略。"
                        )
                    else:
                        state.error_message = (
                            f"拓扑挖掘产出不足。当前URL: {url}，候选数量: {len(candidates)}，"
                            f"拓扑评分: {topology_score:.2f}。请做 DFS 路径反思。"
                        )
                    state = await self.reflection_node.execute(state)
                    if hasattr(state, "reflection_result") and state.reflection_result:
                        allow_evolve, gate_reason = self._evolution_gate(
                            domain=domain,
                            reflection_reason=reflection_reason,
                            topology_score=topology_score,
                            final_assets_count=len(final_assets),
                        )
                        if allow_evolve:
                            logger.info(f"🧬 [基因传递] 触发反思进化，原因: {reflection_reason}")
                            evolve_res = await self.evolution_engine.evolve_with_memory_guidance(
                                current_reflection=state.reflection_result,
                                state_info=state
                            )
                            self._register_evolution_attempt(domain)
                            if evolve_res.get("success"):
                                state.evolution_dna = evolve_res.get("config", {})
                        else:
                            logger.info(f"⏸️ [进化节流] 本次跳过进化 | domain={domain} | reason={gate_reason}")

                        topology_state = str(state.reflection_result.get("topology_state", "")).lower()
                        if reflection_reason != "positive_success" and ("infiniteloop" in topology_state or state.quality_score < 0.2):
                            self._add_to_blacklist(domain, "DFS reflection: loop trap / severe low quality")

                self.batch_stats[domain] = {
                    "count": len(final_assets),
                    "score": topology_score,
                    "recall_score": recall_metrics.get("recall_score", 0.0),
                    "coverage_rate": recall_metrics.get("coverage_rate", 0.0),
                    "novelty_rate": recall_metrics.get("novelty_rate", 0.0),
                    "domain_diversity": recall_metrics.get("domain_diversity", 0.0),
                    "shared_pass_rate": shared_pass_rate,
                    "shared_reviewed": shared_reviewed,
                    "shared_reason_codes": list(shared_reasons.keys())[:8]
                }
                pipeline_success = True
                
                # =========================================================================
                # 🌟🌟🌟 新增核心逻辑：向记忆管家汇报战果，激活底层 SQLite 记忆库！ 🌟🌟🌟
                # =========================================================================
                try:
                    structured_data = getattr(state, "structured_data", {})
                    
                    # 1. 组装网站画像 (Site Profile)
                    site_profile = {
                        "site_name": structured_data.get("current_site_name", domain),
                        "description": structured_data.get("current_site_description", ""),
                        "level_guess": structured_data.get("current_level_guess", "UNKNOWN")
                    }
                    
                    exec_time = time.time() - start_time
                    
                    # 2. 汇报网站知识 -> 存入 website_knowledge 表
                    # Miner 成功判定只使用召回目标，不使用 Inspector 准确率目标。
                    recall_success_threshold = float(getattr(state, "evolution_dna", {}).get("recall_success_threshold", 0.45))
                    success_flag = (
                        recall_metrics.get("recall_score", 0.0) >= recall_success_threshold
                        or len(final_assets) > 0
                    )

                    if self.memory_manager and hasattr(self.memory_manager, 'record_extraction'):
                        self.memory_manager.record_extraction(
                            session_id=state.task_id,
                            domain=domain,
                            url=url,
                            site_profile=site_profile,
                            strategy_used=getattr(state, "evolution_dna", {}),
                            success=success_flag,
                            l3_candidates=final_assets,  # 传入实际产出的资产
                            execution_time=exec_time,
                            error_message=None
                        )
                    
                    # 3. 汇报路径智能 -> 存入 path_intelligence 表
                    if self.memory_manager and hasattr(self.memory_manager, 'update_path_efficiency'):
                        self.memory_manager.update_path_efficiency(
                            domain=domain,
                            path_url=url,
                            found_count=len(final_assets)
                        )
                except Exception as mem_e:
                    logger.error(f"⚠️ 记忆归档落盘失败，但不影响主提取流程: {mem_e}")
                # =========================================================================

                return final_assets

            except Exception as e:
                logger.error(f"❌ Pipeline 致命异常 ({url}): {e}")
                logger.error(traceback.format_exc())
                state.record_domain_failure(domain)
                # 记录崩溃轨迹
                if self.working_memory: self.working_memory.record_step(url, "ERROR", 0, str(e))
                return []
            finally:
                state.release_processing_lock(url, success=pipeline_success)

    async def mine_urls(
        self,
        urls: List[str],
        user_query: Optional[str] = None,
        session_id: str = None,
        *,
        resume_batch: bool = False,
        on_url_complete: Optional[Callable[[str, List[Dict[str, Any]]], Union[None, Awaitable[None]]]] = None,
    ) -> List[Dict[str, Any]]:
        if not urls:
            return []

        # 接收全局查询指令
        if user_query:
            self.runtime_instruction = user_query
            self.task_hash = hashlib.md5(user_query.encode('utf-8')).hexdigest()[:6]

        # 绑定本批次会话（外部会话复用 / 内部会话自建）
        self._bind_batch_session(session_id)

        coordination = (
            self.memory_manager.coordination
            if self.memory_manager and getattr(self.memory_manager, "coordination", None)
            else None
        )
        batch_sid = self._active_batch_session_id or ""

        pending_urls = list(urls)
        if resume_batch and coordination and batch_sid:
            pending_urls = [
                u for u in urls
                if u and not coordination.is_visited(batch_sid, u)
            ]
            if len(pending_urls) < len(urls):
                logger.info(
                    f"⏩ Miner 续挖：跳过 {len(urls) - len(pending_urls)} 个已完成 URL"
                )
        elif resume_batch and self.shared_visited_urls:
            pending_urls = [u for u in urls if u not in self.shared_visited_urls]
            if len(pending_urls) < len(urls):
                logger.info(
                    f"⏩ Miner 续挖（内存）：跳过 {len(urls) - len(pending_urls)} 个已完成 URL"
                )

        if not pending_urls:
            logger.info("⏩ Miner 本批次无待挖 URL")
            return []

        if not resume_batch:
            if coordination and batch_sid:
                coordination.reset_batch(batch_sid)
            else:
                self.shared_visited_urls.clear()
                self.shared_processing_urls.clear()
                self.shared_domain_fail_counts.clear()
                self.shared_url_retry_counts.clear()

            if self.working_memory:
                if batch_sid:
                    self.working_memory.bind_session(batch_sid)
                self.working_memory.reset_session()

            self.batch_stats = {}
            self._evolve_last_ts_global = 0.0
            self._evolve_last_ts_by_domain.clear()
            self._evolve_count_batch = 0
            self._evolve_count_by_domain.clear()
        elif self.working_memory and batch_sid:
            self.working_memory.bind_session(batch_sid)

        mode = "续挖" if resume_batch else "新批次"
        logger.info(
            f"🚀 Miner {mode} | 待挖: {len(pending_urls)}/{len(urls)} | "
            f"模式: DFS + Deep Research 轨迹防撞墙"
        )

        try:
            miner_concurrency = int(os.getenv("MA4CD_MINER_CONCURRENCY", str(self.config.get("miner_concurrency", 3))))
            semaphore = asyncio.Semaphore(max(1, miner_concurrency))
            url_timeout = float(os.getenv("MA4CD_MINER_URL_TIMEOUT", "600"))

            async def _notify(url: str, assets: List[Dict[str, Any]]) -> None:
                if not on_url_complete:
                    return
                result = on_url_complete(url, assets or [])
                if asyncio.iscoroutine(result):
                    await result

            async def limited_run(url):
                async with semaphore:
                    try:
                        assets = await asyncio.wait_for(
                            self._run_single_url_pipeline(url),
                            timeout=url_timeout,
                        )
                    except asyncio.TimeoutError:
                        logger.error(
                            f"⏱️ Miner 单 URL 超时 ({url_timeout}s)，跳过: {url}"
                        )
                        if self.working_memory:
                            self.working_memory.record_step(
                                url, "ERROR", 0, f"url_timeout_{url_timeout}s"
                            )
                        assets = []
                    await _notify(url, assets if isinstance(assets, list) else [])
                    return assets if isinstance(assets, list) else []

            results_list = await asyncio.gather(
                *[limited_run(u) for u in pending_urls],
                return_exceptions=True,
            )
            for i, res in enumerate(results_list):
                if isinstance(res, BaseException):
                    logger.error(f"❌ Miner gather 异常 ({pending_urls[i]}): {res}")
                    results_list[i] = []

            all_assets = []
            for res in results_list:
                if res:
                    all_assets.extend(res)

            if all_assets or self.batch_stats:
                logger.info(f"📝 Miner 批处理挖掘完毕，正在生成阶段报告...")
                try:
                    dna = {}
                    if hasattr(self.evolution_engine, 'current_config'):
                        dna = self.evolution_engine.current_config

                    dna['user_guidance_prompt'] = self.runtime_instruction or "默认挖掘任务"

                    report_path = self.report_node.generate(
                        domain_stats=self.batch_stats,
                        evolution_dna=dna,
                        all_results=all_assets
                    )
                    logger.info(f"📄 Miner Markdown 报告已生成: {report_path}")
                except Exception as e:
                    logger.error(f"❌ 报告生成失败: {e}")

            return all_assets
        finally:
            # 仅关闭 Miner 自建会话，外部传入会话由上层工作流统一关闭
            if self._owns_session_lifecycle and self._active_batch_session_id:
                try:
                    if hasattr(self.memory_manager, "end_session"):
                        self.memory_manager.end_session(self._active_batch_session_id)
                        logger.info(f"🔒 [Miner Session] 已关闭自建会话: {self._active_batch_session_id}")
                except Exception as e:
                    logger.warning(f"关闭 Miner 自建会话失败: {e}")
            self._active_batch_session_id = None
            self._owns_session_lifecycle = False

    async def close(self):
        return
