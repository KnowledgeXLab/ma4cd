import sys
import os
import asyncio
import uuid
import time
from datetime import datetime
import json
from typing import Dict, Any, List
from urllib.parse import urlparse
from loguru import logger

# 确保项目根目录在路径中
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from state.miner_state import MinerState
from nodes.extract_node import ExtractNode
from nodes.structure_node import StructureNode
from nodes.reflection_node import ReflectionNode
from tools.l4_miner import L4RecordMiner

from memory.managers.memory_manager import UnifiedMemoryManager
from evolution.miner_evolution_engine import MemoryBasedEvolutionEngine

class UniversalMinerAgent:
    """
    进化版 UniversalMinerAgent
    修复了字段对齐问题，打通了从 L4 挖掘到记忆进化的全链路。
    """

    def __init__(self, config: Dict = None):
        self.config = config or {}
        # Nodes
        self.extract_node = ExtractNode()
        self.structure_node = StructureNode()
        self.reflection_node = ReflectionNode()
        
        # Memory & Evolution
        self.memory_manager = UnifiedMemoryManager()
        self.evolution_engine = MemoryBasedEvolutionEngine(self.memory_manager)

        logger.info("🤖 UniversalMinerAgent 初始化完成 | 进化引擎已就绪")

    async def mine_urls(self, urls: List[str]):
        """批量处理入口"""
        for url in urls:
            await self._run_single_url_pipeline(url)

    async def _run_single_url_pipeline(self, url: str):
            run_id = str(uuid.uuid4())[:8]
            start_time = time.time()
            domain = urlparse(url).netloc
            
            # 结果保存路径
            output_dir = "agents/miner/output"
            os.makedirs(output_dir, exist_ok=True)

            logger.info(f"▶️ Pipeline Start | RunID: {run_id} | Domain: {domain}")

            # 1️⃣ 初始化 State
            state = MinerState()
            state.url = url
            state.domain = domain
            state.is_valid = True
            state.current_clue = {"url": url, "domain": domain, "tier": "L1", "context": "Seed URL"}

            # 2️⃣ 加载进化基因
            evolved_config = self.evolution_engine.get_global_best_config(domain)
            state.prompt_overrides = evolved_config.get("prompt_overrides", {})
            state.evolution_config = evolved_config
            logger.info(f"🧬 已注入进化参数 (代数: {evolved_config.get('generation', 'New')})")

            final_items: List[Dict[str, Any]] = []
            quality_score = 0.0

            try:
                # 3️⃣ 网页提取 (Extract)
                state = await self.extract_node.execute(state)

                # 4️⃣ 结构分析 (Structure)
                state = await self.structure_node.execute(state)

                # 5️⃣ 执行 L4 深度挖掘
                max_depth = evolved_config.get("max_depth", 2)
                l4_miner = L4RecordMiner(max_depth=max_depth)

                candidates = []
                if hasattr(state, "structured_data") and isinstance(state.structured_data, dict):
                    candidates.extend(state.structured_data.get("l3_candidates", []))
                    candidates.extend(state.structured_data.get("exploration_targets", []))

                if candidates:
                    logger.info(f"🔎 发现 {len(candidates)} 个潜在数据入口，开始并行挖掘...")
                    async def deep_scan(c):
                        target_url = c.get("url")
                        if not target_url: return []
                        res = await l4_miner.mine_l4_records(target_url)
                        return res.get("l4_records", []) if isinstance(res, dict) else []

                    results = await asyncio.gather(*(deep_scan(c) for c in candidates))
                    for r in results: final_items.extend(r)

                # 去重
                seen_urls = set()
                state.final_items = [
                    item for item in final_items
                    if item.get("url") and not (item["url"] in seen_urls or seen_urls.add(item["url"]))
                ]

                # 6️⃣ 结果反思 (Reflection)
                state.total_duration = round(time.time() - start_time, 2)
                state = await self.reflection_node.execute(state)
                reflection = getattr(state, "reflection_result", {}) or {}
                quality_score = reflection.get("quality_score", 0.0 if not state.final_items else 0.5)

                # 7️⃣ 进化闭环 (Evolution)
                evolution_result = await self.evolution_engine.evolve_with_memory_guidance(
                    current_reflection={
                        "quality_score": quality_score,
                        "issues": reflection.get("issues", ["无显著问题"]),
                        "strategy_adjustments": reflection.get("strategy_adjustments", {}),
                    },
                    state_info={
                        "url": url,
                        "domain": domain,
                        "run_id": run_id,
                        "items_count": len(state.final_items)
                    }
                )
                if evolution_result.get("success"):
                    logger.success(f"🧬 进化完成 | 新代数: {evolution_result.get('new_generation')}")

            except Exception as e:
                logger.error(f"❌ Pipeline 崩溃: {e}")
                import traceback
                logger.debug(traceback.format_exc())
            
            finally:
                # =====================================================
                # 8️⃣ 运行记忆持久化与可视化报告 (核心补全)
                # =====================================================
                duration = time.time() - start_time
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                # A. 保存全量结果 JSON (运行记忆的真实镜像)
                result_data = {
                    "metadata": {
                        "run_id": run_id,
                        "url": url,
                        "duration": f"{duration:.2f}s",
                        "quality_score": quality_score,
                        "generation": self.evolution_engine.generation
                    },
                    "evolution_applied": state.prompt_overrides,
                    "l3_discovery": state.structured_data.get("l3_candidates", []),
                    "final_records": state.final_items
                }
                json_file = os.path.join(output_dir, f"miner_result_{run_id}_{timestamp}.json")
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(result_data, f, ensure_ascii=False, indent=2)

                # B. 生成 Markdown 可视化报告 (给人类看)
                md_file = os.path.join(output_dir, f"report_{domain}_{timestamp}.md")
                with open(md_file, 'w', encoding='utf-8') as f:
                    f.write(f"# 🛡️ Miner 挖掘报告: {domain}\n\n")
                    f.write(f"- **Run ID**: `{run_id}`\n- **质量评分**: `{quality_score:.2f}`\n")
                    f.write(f"- **耗时**: {duration:.2f}s | **产出**: {len(state.final_items)} 条真实线索\n\n")
                    f.write("## 💎 识别到的 L3 数据库入口\n")
                    f.write("| 名称 | URL | 置信度 |\n| :--- | :--- | :--- |\n")
                    for c in state.structured_data.get("l3_candidates", []):
                        f.write(f"| {c['title']} | {c['url']} | {c.get('confidence', 'N/A')} |\n")
                    f.write(f"\n> 详细数据已持久化至: `{json_file}`\n")

                # C. 存入持久化数据库快照 (SQL Session)
                if hasattr(self.memory_manager, "storage") and self.memory_manager.storage:
                    self.memory_manager.storage.save_session_snapshot(
                        session_id=run_id,
                        domain=domain,
                        data=result_data
                    )

                logger.info(
                    f"🏁 Pipeline 任务结束\n"
                    f"   [域名]: {domain}\n"
                    f"   [结果]: {len(state.final_items)} items\n"
                    f"   [质量]: {quality_score:.2f}\n"
                    f"   [报告]: {md_file}"
                )

if __name__ == "__main__":
    async def main():
        agent = UniversalMinerAgent()
        # 测试目标
        test_urls = ["https://unidata.pro/datasets/"]
        await agent.mine_urls(test_urls)

    asyncio.run(main())