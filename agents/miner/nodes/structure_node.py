import sys
import os
import json
import re
from typing import Dict, Any, List
from urllib.parse import urlparse, urlunparse
from loguru import logger

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from agents.miner.state.miner_state import MinerState
    from agents.miner.llms.miner_llm import MinerLLMClient
    from agents.miner.prompts.prompt import SYSTEM_PROMPT_STRUCTURE
except ImportError as e:
    logger.error(f"导入失败，请检查路径: {e}")

class StructureNode:
    """
    StructureNode (纯物理拓扑驱动版 + DFS 轨迹感知防鬼打墙)
    设计理念：彻底剥离语义和 L1-L4 分级，只负责寻找高潜力的网页结构和资产终点。
    """
    def __init__(self):
        self.llm = MinerLLMClient()
        logger.info("🧩 StructureNode 初始化完成（已切换为纯拓扑驱动模式，语义验证交由 Inspector 处理）")

    def _normalize_url(self, url: str) -> str:
        """轻量 URL 归一化，避免同链路重复。"""
        if not url or not isinstance(url, str):
            return ""
        try:
            clean = url.strip().split("#")[0]
            parsed = urlparse(clean)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                return ""
            normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))
            return normalized.rstrip("/") if parsed.path not in ("", "/") else normalized
        except Exception:
            return ""

    def _sanitize_candidate_list(
        self,
        items: List[Dict[str, Any]],
        candidate_type: str
    ) -> List[Dict[str, Any]]:
        """
        对模型产出的候选链接进行去重、归一化和结构补全。
        candidate_type: "asset_hint" | "exploration_target"
        """
        if not isinstance(items, list):
            return []

        results: List[Dict[str, Any]] = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                continue

            normalized_url = self._normalize_url(str(item.get("url", "")))
            if not normalized_url or normalized_url in seen:
                continue

            reason = str(item.get("reason", "")).strip()
            text = str(item.get("text", "")).strip()
            results.append({
                "url": normalized_url,
                "text": text[:120],
                "reason": reason[:300],
                "candidate_type": candidate_type
            })
            seen.add(normalized_url)

        return results

    def _format_evolutionary_hint(self, state: MinerState) -> str:
        hints = []

        # 1) 长期进化 DNA（跨 URL/跨批次）
        evolution_dna = getattr(state, "evolution_dna", {})
        if isinstance(evolution_dna, dict):
            structure_overrides = evolution_dna.get("prompt_overrides", {}).get("structure_node", {})
            if isinstance(structure_overrides, dict):
                ignore_patterns = structure_overrides.get("add_ignore_patterns", []) or []
                focus_patterns = structure_overrides.get("add_focus_patterns", []) or []
                if ignore_patterns:
                    hints.append(f"长期结构噪音词: {ignore_patterns[:20]}")
                if focus_patterns:
                    hints.append(f"长期高潜结构模式: {focus_patterns[:20]}")

            guidance = str(evolution_dna.get("user_guidance_prompt", "")).strip()
            if guidance:
                hints.append(f"长期指导: {guidance[:300]}")

        # 2) 当前反思结果（短期热反馈）
        reflection = getattr(state, "reflection_result", {})
        if not isinstance(reflection, dict):
            reflection = {}
        distilled = reflection.get("distilled_dna", {})
        if isinstance(distilled, dict):
            if distilled.get("new_blacklist_keywords"):
                hints.append(f"短期结构噪音词: {distilled['new_blacklist_keywords']}")
            if distilled.get("new_high_value_patterns"):
                hints.append(f"短期高潜结构模式: {distilled['new_high_value_patterns']}")

        if not hints:
            return "暂无历史进化经验。"
        return "\n".join(hints)

    def _build_final_system_prompt(self, state: MinerState) -> str:
        evo_hint = self._format_evolutionary_hint(state)
        
        # 获取近期轨迹，用于防死循环
        working_memory = getattr(state, "working_memory", None)
        recent_trajectory = working_memory.get_recent_trajectory_context(steps=4) if working_memory else "暂无探索轨迹。"
        
        try:
            raw_links = getattr(state, "raw_links", [])
            valid_links = []
            seen_urls = set()
            
            for l in raw_links:
                if not isinstance(l, dict) or not l.get("url"): continue
                url_str = str(l["url"])
                if len(url_str) > 300 or url_str in seen_urls: continue
                
                text_str = str(l.get("text", "")).strip()
                if len(text_str) > 100: text_str = text_str[:97] + "..."
                    
                valid_links.append({"url": url_str, "text": text_str})
                seen_urls.add(url_str)
            
            md_links = []
            for i, vl in enumerate(valid_links[:150]):
                md_links.append(f"{i+1}. [{vl['text']}]({vl['url']})")
            links_payload = "\n".join(md_links)

            raw_content = getattr(state, "extracted_content", "")
            if raw_content:
                clean_text = re.sub(r'<(script|style).*?>.*?</\1>', '', raw_content, flags=re.IGNORECASE | re.DOTALL)
                clean_text = re.sub(r'<[^>]+>', ' ', clean_text)
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                page_text_snippet = clean_text[:5000]
            else:
                page_text_snippet = "No text content available."

            # 🚨 注意：这里彻底移除了 user_query 的注入，防止大模型偷偷做语义过滤
            from utils.miner_prompts import append_to_prompt
            base = SYSTEM_PROMPT_STRUCTURE.format(
                current_url=getattr(state, "current_url", "unknown"),
                page_title=getattr(state, "current_page_title", "Unknown Page"),
                page_text=page_text_snippet,
                links_json=links_payload, 
                recent_trajectory=recent_trajectory,
                evolutionary_hint=evo_hint
            )
            return append_to_prompt(base, "structure_append")
        except Exception as e:
            logger.error(f"Prompt 构建异常: {e}")
            return "执行拓扑评估。"

    async def execute(self, state: MinerState) -> MinerState:
        if not state: return state
        try:
            system_prompt = self._build_final_system_prompt(state)
            is_denied = getattr(state, "is_access_denied", False)
            working_memory = getattr(state, "working_memory", None)
            
            # 全新的 User Prompt：强调结构，禁止谈论主题
            user_prompt = (
                "请执行纯粹的【网页拓扑结构与下钻潜力】评估。\n"
                "⚠️ 【最高指令】：\n"
                "1. 🙈 [语义绝对屏蔽]：哪怕这个页面在讲毫不相关的游戏或娱乐，只要它具备良好的列表或目录结构，就必须提取！语义审查是下游 Inspector 的工作！\n"
                "2. 🕸️ [高召回拓扑]：重点提取两类链接：① 潜在资产终点 (candidate_assets)；② 高价值下钻目录/分页 (exploration_targets)。\n"
                "3. 🚫 [禁止分级越权]：严禁在本节点输出 L1/L2/L3/L4 定级结论。只能输出拓扑线索与下钻价值。\n"
            )

            if is_denied:
                user_prompt += (
                    "\n🚨 【特殊状态告警】：当前 URL 遭遇了强力的访问限制（如 403 / 验证码）！\n"
                    "在结构层面上，这极大概率是一个高价值的受保护资产终点 (Asset)。请务必提升其拓扑评分！"
                )

            response = await self.llm.ainvoke_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.2 
            )
            
            parsed = response if isinstance(response, dict) else self._safe_parse_json(response)
            if not parsed: parsed = {}

            # 提取大模型的结构判定
            trajectory_check = str(parsed.get("trajectory_check", "")).strip()
            page_type = str(parsed.get("page_type", "Unknown")).upper()
            if page_type not in {"DIRECTORY", "LIST", "ASSET", "DEADEND"}:
                page_type = "UNKNOWN"
            reasoning = str(parsed.get("reasoning_summary", "无理由"))
            
            if trajectory_check:
                logger.debug(f"🧠 模型轨迹反思: {trajectory_check}")

            # 统一将潜在资产和下钻目标提取出来
            candidate_assets = parsed.get("candidate_assets") or []
            explore_targets = parsed.get("exploration_targets") or []

            valid_assets = self._sanitize_candidate_list(candidate_assets, candidate_type="asset_hint")
            valid_explore = self._sanitize_candidate_list(explore_targets, candidate_type="exploration_target")

            topology_score = float(parsed.get("topology_score", 0.5))
            state.quality_score = topology_score  # 现在这个分只代表“结构好不好”
            
            # 🌟 核心拦截机制（仅基于结构和轨迹死循环，不再基于语义）
            if "DEADEND" in page_type or (topology_score < 0.3 and "loop" in trajectory_check.lower()):
                valid_assets = []
                valid_explore = []
                state.quality_score = 0.0
                logger.warning(f"🚫 [拓扑死胡同/轨迹规避] 模型判定为静态终点或陷入死循环，终止下钻: {state.current_url}")

            # 记录轨迹动作
            if working_memory:
                depth = getattr(state, "current_depth", 0)
                working_memory.record_step(
                    url=state.current_url,
                    action_state=page_type, 
                    depth=depth,
                    reason=reasoning
                )

            # 更新状态：废除旧的 L3/L4 字段，使用通用资产字段（注意要和你的状态类定义兼容，如果不兼容，可以在外层适配）
            state.structured_data = {
                "page_type": page_type,
                "topology_score": topology_score,
                "candidate_assets": valid_assets,
                "exploration_targets": valid_explore,
                "site_analysis": reasoning,
                # 为了向下兼容旧代码，将候选统一映射给下游 Inspector 做最终语义判定
                "l3_candidates": valid_assets + valid_explore,
                "l4_clues": []  # Miner 不再输出 L4，全放进 l3_candidates 作为一个筐
            }
            
            logger.success(f"🧠 StructureNode 判定: {page_type} | 拓扑分: {topology_score:.2f} | 潜在资产: {len(valid_assets)} | 下钻目录: {len(valid_explore)}")
            
        except Exception as e:
            logger.error(f"❌ StructureNode 异常: {e}")
            state.structured_data = {
                "page_type": "DEADEND",
                "topology_score": 0.0,
                "candidate_assets": [], 
                "exploration_targets": [],
                "l3_candidates": [],
                "l4_clues": []
            }
            state.quality_score = 0.0
            if getattr(state, "working_memory", None):
                state.working_memory.record_step(state.current_url, "ERROR", getattr(state, "current_depth", 0), f"Node Exception: {e}")

        return state

    def _safe_parse_json(self, text: str) -> Dict:
        if not text or not isinstance(text, str): return {}
        try: return json.loads(text)
        except json.JSONDecodeError: pass
        for pattern in [r"```(?:json)?\s*(\{.*?\})\s*```", r"(\{.*\})"]:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try: return json.loads(match.group(1))
                except: continue
        return {}
