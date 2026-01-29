import json
import re
from typing import Dict, Any, List
from loguru import logger
from state.miner_state import MinerState
from llms.miner_llm import MinerLLMClient

BASE_STRUCTURE_PROMPT = """
你是一个通用的【数据资源意图分析专家】。请分析页面链接的语义，将其归类。

### 🚨 归类准则 (Strict General Logic)
- 【L3 - 独立数据库/数据入口】：
    - 意图：提供数据检索、查询或直接下载。
    - 特征：通常是网站的垂直功能子系统，具有独立名称。不仅仅是文章，而是具备交互属性的“工具”。
- 【L2 - 目录/索引页】：
    - 意图：作为资源的集合点。包含分类列表、A-Z 索引或多个数据库的入口汇编。
- 【忽略 (Ignored)】：
    - 纯阅读性材料：帮助手册、用户指南、新闻公告、法律条款、关于页面。

### 🛡️ 通用过滤启发式
- 负向：若 URL 包含 /guide/, /help/, /handbook/ 且不含 "Search" 或 "Query"，应优先忽略。
- 正向：指向外部数据源（如 FTP, Github 仓库）或具有独立域名/子路径的功能模块应优先判定为 L3。
"""

class StructureNode:
    def __init__(self):
        self.llm = MinerLLMClient()
        logger.info("🧩 StructureNode 初始化完成（通用进化模式）")

    def _build_prompt(self, state: MinerState) -> str:
        prompt_parts = [BASE_STRUCTURE_PROMPT]
        overrides = getattr(state, "prompt_overrides", None) or {}
        struct_override = overrides.get("structure_node", {})
        
        # 注入进化基因
        if struct_override.get("add_focus_patterns"):
            prompt_parts.append("\n【历史成功模式增强】: " + ", ".join(struct_override["add_focus_patterns"]))
        if struct_override.get("add_ignore_patterns"):
            prompt_parts.append("\n【历史失败模式避障】: " + ", ".join(struct_override["add_ignore_patterns"]))

        prompt_parts.append("""
        请严格输出 JSON 格式：
        {
            "l3_candidates": [{"url": "...", "title": "...", "confidence": 0.9, "reason": "..."}],
            "exploration_targets": [{"url": "...", "title": "...", "score": 0.8, "reason": "..."}],
            "ignored": [{"url": "...", "reason": "..."}]
        }
        """)
        return "\n".join(prompt_parts)

    async def execute(self, state: MinerState) -> MinerState:
        if not state or not getattr(state, "raw_links", None): return state
        
        valid_links = [l for l in state.raw_links if l.get("url") and len(str(l.get("text", ""))) > 2][:100]
        links_payload = [{"url": l["url"], "title": l.get("title") or l.get("text", "Unknown")} for l in valid_links]

        try:
            response = self.llm.invoke(
                system_prompt=self._build_prompt(state),
                user_prompt=json.dumps({"links": links_payload}, ensure_ascii=False),
                temperature=0.2
            )
            parsed = self._safe_parse_json(response)
            real_urls = {l["url"] for l in valid_links}
            
            state.structured_data = {
                "l3_candidates": [c for c in parsed.get("l3_candidates", []) if c["url"] in real_urls],
                "exploration_targets": [t for t in parsed.get("exploration_targets", []) if t["url"] in real_urls]
            }
            state.candidate_subportals = state.structured_data["l3_candidates"]
            logger.info(f"🧠 StructureNode 决策完成 | L3: {len(state.candidate_subportals)}")
        except Exception as e:
            logger.error(f"StructureNode 异常: {e}")
        return state

    def _safe_parse_json(self, text: str):
        try:
            match = re.search(r"(\{.*\})", text, re.DOTALL)
            return json.loads(match.group(1)) if match else {}
        except: return {}