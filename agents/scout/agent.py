"""
Scout Agent (HITL & Evolution Enabled)
职责：广域搜索，获取种子 URL（仅 Tavily API 真实返回）。
"""
from typing import List, Dict, Any, Union
from loguru import logger

# 路径兼容处理
try:
    from .tools.web_search import ScoutWebSearchTool
    from .nodes.planning_node import PlanningNode
    from .nodes.search_node import SearchNode
    from agents.miner.llms.miner_llm import MinerLLMClient
except (ImportError, ValueError):
    from agents.scout.tools.web_search import ScoutWebSearchTool
    from agents.scout.nodes.planning_node import PlanningNode
    from agents.scout.nodes.search_node import SearchNode
    from agents.miner.llms.miner_llm import MinerLLMClient

from utils.prompt_contracts import (
    scout_max_seed_urls,
    scout_results_per_query,
    scout_plan_from_commander_queries,
)


class ScoutAgent:
    def __init__(self):
        logger.info("🛰️ Scout Agent (侦察兵) 正在初始化...")

        self.search_tool = ScoutWebSearchTool()

        try:
            self.llm = MinerLLMClient()
        except Exception as e:
            logger.warning(f"Scout LLM 初始化失败: {e}，规划阶段不可用")
            self.llm = None

        self.planning_node = PlanningNode(self.llm)
        self.search_node = SearchNode(self.llm, self.search_tool)

        self.dynamic_config = {}
        self.semantic_patch = ""

        try:
            import data_memory_center.manager as dmc_manager
            self.memory_center = dmc_manager.DataMemoryCenter()
            logger.info("✅ Scout 已连接 DataMemoryCenter (启用黑名单过滤)")
        except Exception as e:
            logger.warning(f"⚠️ Scout 无法连接数据中心: {e}")
            self.memory_center = None

        self.search_results = []
        logger.info("🛰️ Scout Agent 就绪 (仅 Tavily 真实结果)")

    def apply_amendment(self, amendment: Union[Dict, str]):
        """应用人类反馈修正"""
        if not amendment:
            return

        if isinstance(amendment, str):
            logger.warning("🛡️ 收到非结构化反馈，已强制转化为语义补丁")
            self.semantic_patch += f"\n[Priority Instruction]: {amendment}"
            return

        new_instruction = amendment.get("system_prompt_append")
        if new_instruction:
            logger.info(f"🛰️ Scout 注入新语义 DNA: {new_instruction}")
            self.semantic_patch += f"\n[User Directive]: {new_instruction}"

            if hasattr(self.planning_node, "update_instruction"):
                self.planning_node.update_instruction(self.semantic_patch)

        config_update = amendment.get("config_update")
        if config_update:
            logger.info(f"🛰️ Scout 更新配置参数: {config_update}")
            self.dynamic_config.update(config_update)

    def run(self, task: str, config: Dict[str, Any] = None, session_id: str = None) -> List[str]:
        """执行 OSINT 侦察：仅执行规划产出的 query，且 URL 必须来自 Tavily。"""
        effective_task = task
        if self.semantic_patch:
            effective_task = (
                f"### IMPORTANT INSTRUCTION ###\n{self.semantic_patch}\n\n"
                f"### ORIGINAL TASK ###\n{task}"
            )
            logger.info("🧠 [Semantic Injected] Scout 正在带着进化后的意志运行...")

        logger.info(f"🛰️ Scout 接收宏观指令: {task[:60]}...")

        final_config = config or {}
        final_config.update(self.dynamic_config)
        scout_runtime_config = (
            final_config.get("scout_config", final_config)
            if isinstance(final_config, dict)
            else {}
        )
        if not isinstance(scout_runtime_config, dict):
            scout_runtime_config = {}
        scout_runtime_config.setdefault(
            "results_per_query", scout_results_per_query(scout_runtime_config)
        )
        scout_runtime_config["tavily_only"] = True
        if session_id:
            scout_runtime_config["session_id"] = session_id

        # 1. 规划阶段；失败时回退 Commander search_queries
        logger.info("📋 [Scout] OSINT 查询扩展（规划失败则回退 Commander queries）...")
        plan: List[str] = []
        if self.llm is None:
            logger.warning("⚠️ Scout LLM 不可用，跳过 PlanningNode，直接使用 Commander queries")
            plan = scout_plan_from_commander_queries(final_config)
        else:
            try:
                planning_payload = {
                    "user_request": effective_task,
                    "commander_task_config": final_config,
                    "runtime_config": scout_runtime_config,
                }
                plan_dicts = self.planning_node.run(planning_payload)
                for p in plan_dicts:
                    if isinstance(p, dict) and p.get("query"):
                        plan.append(str(p["query"]).strip())
                    elif isinstance(p, str) and p.strip():
                        plan.append(p.strip())
            except Exception as e:
                logger.error(f"⚠️ PlanningNode 规划异常: {e}")

            if not plan:
                plan = scout_plan_from_commander_queries(final_config)
                if plan:
                    logger.warning(
                        f"⚠️ [Scout] PlanningNode 未产出有效 query，"
                        f"回退 Commander search_queries（{len(plan)} 条）"
                    )

        if not plan:
            logger.error("❌ Scout 无有效搜索计划，跳过搜索（PlanningNode 与 Commander 均无 query）")
            return []

        # 2. 执行 Tavily 搜索
        per_q = scout_results_per_query(scout_runtime_config)
        logger.info(f"🔎 [Scout] 执行 {len(plan)} 条 query（Tavily only，每条最多 {per_q} 条）")
        clues = self._execute_search_plan(plan, scout_runtime_config)
        unique_urls = self._collect_valid_urls(clues)
        max_urls = scout_max_seed_urls(scout_runtime_config)
        if len(unique_urls) > max_urls:
            before = len(unique_urls)
            unique_urls = self._cap_seed_urls(unique_urls, max_urls)
            logger.warning(
                f"✂️ [Scout] 种子 URL 已裁剪: {before} -> {len(unique_urls)} "
                f"(上限 max_seed_urls={max_urls})"
            )

        logger.success(
            f"✅ Scout 完成: Tavily 原始 {len(clues)} 条 -> "
            f"黑名单过滤后 {len(unique_urls)} 个 URL"
        )
        return unique_urls

    def _execute_search_plan(self, plan: List[str], scout_runtime_config: Dict[str, Any]) -> List[Dict]:
        if hasattr(self.search_node, "run_with_config"):
            return self.search_node.run_with_config(plan, config=scout_runtime_config)
        if hasattr(self.search_node, "execute"):
            try:
                return self.search_node.execute(plan, config=scout_runtime_config)
            except TypeError:
                return self.search_node.execute(plan)

        per_q = scout_results_per_query(scout_runtime_config)
        out: List[Dict] = []
        for query in plan:
            out.extend(
                self.search_tool(query, num_results=per_q, tavily_only=True, **scout_runtime_config)
            )
        return out

    @staticmethod
    def _is_tavily_clue(c: Any) -> bool:
        if isinstance(c, dict):
            return str(c.get("source", "")).lower() == "tavily"
        return str(getattr(c, "source", "")).lower() == "tavily"

    def _collect_valid_urls(self, clues: List[Any]) -> List[str]:
        seen_stored = {
            r.get("url")
            for r in self.search_results
            if isinstance(r, dict) and r.get("url")
        }
        valid_urls: List[str] = []
        for c in clues:
            if not self._is_tavily_clue(c):
                continue
            url = c.get("url") if isinstance(c, dict) else getattr(c, "url", None)
            if not url:
                continue
            if self.memory_center and self.memory_center.is_blacklisted(url):
                logger.info(f"🚫 [Blacklist] 免疫拦截已知噪音: {url}")
                continue
            valid_urls.append(url)
            if url not in seen_stored:
                self.search_results.append(c)
                seen_stored.add(url)
        return list(set(valid_urls))

    def _cap_seed_urls(self, urls: List[str], max_urls: int) -> List[str]:
        """按 Tavily relevance_score 保留前 N 条种子 URL。"""
        if len(urls) <= max_urls:
            return urls
        scores: Dict[str, float] = {}
        for r in self.search_results:
            if not isinstance(r, dict):
                continue
            u = r.get("url")
            if u in urls:
                scores[u] = max(scores.get(u, 0.0), float(r.get("relevance_score") or 0))
        ranked = sorted(urls, key=lambda u: scores.get(u, 0.0), reverse=True)
        kept = ranked[:max_urls]
        kept_set = set(kept)
        self.search_results = [
            r for r in self.search_results
            if isinstance(r, dict) and r.get("url") in kept_set
        ]
        return kept

    def get_search_results(self) -> List[str]:
        """获取所有累积的有效 URL（仅 Tavily）"""
        raw_urls = [
            r["url"]
            for r in self.search_results
            if isinstance(r, dict) and r.get("url") and self._is_tavily_clue(r)
        ]

        if not self.memory_center:
            return list(set(raw_urls))

        clean_urls = []
        for url in raw_urls:
            if not self.memory_center.is_blacklisted(url):
                clean_urls.append(url)

        return list(set(clean_urls))
