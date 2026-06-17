import sys
import os
import asyncio
import json
import time
import re
from urllib.parse import urlparse
from collections import defaultdict
from typing import Any, List, Dict
from loguru import logger

from utils.miner_heuristics import get_junk_ext_re, get_link_noise_re
from utils.miner_signals import negative_kw_re

class ExtractNode:
    def __init__(self):
        from agents.miner.llms.miner_llm import MinerLLMClient
        self.llm = MinerLLMClient()
        from agents.miner.tools.browse_page import BrowsePageTool
        self.browse_tool = BrowsePageTool()

    def _collect_noise_keywords(self, dna: Dict) -> set:
        """
        统一读取进化噪音关键词，兼容新旧字段：
        - 旧字段: blacklist_keywords
        - 新字段: prompt_overrides.structure_node.add_ignore_patterns
        """
        if not isinstance(dna, dict):
            return set()

        keywords = set()

        # 兼容旧字段
        legacy = dna.get("blacklist_keywords", [])
        if isinstance(legacy, list):
            keywords.update(str(k).strip().lower() for k in legacy if str(k).strip())

        # 对齐新字段（EvolutionEngine 当前写入路径）
        overrides = dna.get("prompt_overrides", {}).get("structure_node", {})
        ignore_patterns = overrides.get("add_ignore_patterns", []) if isinstance(overrides, dict) else []
        if isinstance(ignore_patterns, list):
            keywords.update(str(k).strip().lower() for k in ignore_patterns if str(k).strip())

        return keywords

    def _dynamic_heuristic_filter(self, links: List[Dict], dna: Dict, working_memory: Any = None) -> List[Dict]:
        """
        基于进化 DNA 和 轨迹记忆 的动态过滤。
        """
        junk_ext = get_junk_ext_re()
        hard_noise = get_link_noise_re()
        noise_keywords = self._collect_noise_keywords(dna)
        skill_neg = negative_kw_re()

        filtered = []
        seen_urls = set()

        for link in links:
            url = link.get('url', '').strip().split('#')[0].rstrip('/')
            raw_text = link.get('text', '').strip()
            text = re.sub(r'\s+', ' ', raw_text)[:60] 
            
            if not url or url in seen_urls: 
                continue
            if junk_ext.search(url) or hard_noise.search(url): 
                continue
            if skill_neg.search(url.lower()):
                continue
            
            # 🌟 [核心新增]: O(1) 短期记忆轨迹拦截
            if working_memory:
                past_status = working_memory.check_url_status(url)
                # 如果近期刚被判定为无效、死胡同或错误，直接跳过！
                if past_status in ["INVALID", "DROP", "DROP_IRRELEVANT", "ERROR", "BLOCKED"]:
                    logger.debug(f"🛑 轨迹拦截: 跳过已判死刑的链接 {url}")
                    continue
            
            url_lower = url.lower()
            is_noise = False
            for k in noise_keywords:
                pattern = rf'/{re.escape(k)}(/|\.[a-zA-Z0-9]+$|$)'
                if re.search(pattern, url_lower):
                    is_noise = True
                    break
                    
            if is_noise: 
                continue
            
            filtered.append({"url": url, "text": text})
            seen_urls.add(url)
            
        return filtered

    def _aggregate_links(self, links: List[Dict], threshold: int = 4) -> List[Dict]:
        """
        🌟 核心黑科技：URL 模式折叠 (Pattern Aggregation)
        """
        pattern_groups = defaultdict(list)
        
        for link in links:
            url = link.get('url', '')
            try:
                parsed = urlparse(url)
                path_parts = parsed.path.strip('/').split('/')
                if len(path_parts) > 1:
                    pattern_path = '/' + '/'.join(path_parts[:-1]) + '/*'
                else:
                    pattern_path = parsed.path or '/'
                    
                pattern = f"{parsed.scheme}://{parsed.netloc}{pattern_path}"
                pattern_groups[pattern].append(link)
            except Exception:
                pattern_groups[url].append(link)
                
        aggregated = []
        for pattern, group in pattern_groups.items():
            if len(group) < threshold:
                aggregated.extend(group)
            else:
                sample_texts = [l.get('text') for l in group[:3] if l.get('text')]
                aggregated.append({
                    "url_pattern": pattern,
                    "is_aggregated": True,
                    "total_links_hidden": len(group),
                    "example_url": group[0].get('url'),
                    "text_samples": sample_texts
                })
                
        return aggregated

    async def execute(self, state: Any) -> Any:
        start_time = time.time()
        current_clue = getattr(state, "current_clue", {})
        url = current_clue.get("url")
        evolution_dna = getattr(state, "evolution_dna", {}) 
        
        # 🌟 获取工作记忆
        working_memory = getattr(state, "working_memory", None)
        
        if not url:
            logger.error("ExtractNode: No URL found.")
            state.is_valid = False
            return state
            
        # 🌟 轨迹注入 Extract Planning
        recent_traj = working_memory.get_recent_trajectory_context(steps=3) if working_memory else "无近期轨迹"

        planning_prompt = (
            f"Current URL: {url}\n"
            f"Recent Trajectory: {recent_traj}\n"
            "Task: Identify links pointing to Private/Physical archives (L4) or Sub-databases (L3). "
            "Focus on navigation menus, 'Access Data' sections, and 'Registry' links. "
            "Avoid link patterns that failed in the Recent Trajectory. "
            "Output JSON: {{\"instruction\": \"...\"}}"
        )
        from utils.miner_prompts import get_miner_prompt_append
        skill_block = get_miner_prompt_append("extract_planning_append")
        if skill_block:
            planning_prompt = planning_prompt.rstrip() + "\n\n" + skill_block + "\n"
        
        try:
            plan_resp = await self.llm.ask(planning_prompt, response_format="json")
            browse_instruction = plan_resp.get("instruction", "Focus on data catalogs and specimen registries.")
        except Exception as e:
            logger.warning(f"ExtractNode Planning Failed: {e}. Using default instruction.")

        browse_result = await self.browse_tool.browse_resilient(url=url, use_js=True)

        from agents.miner.tools.browse_url_resolve import merge_access_denied_signal

        is_access_denied = merge_access_denied_signal(browse_result)
            
        state.is_access_denied = is_access_denied

        if browse_result and (browse_result.get("success") or is_access_denied):
            all_links = browse_result.get("all_links", [])
            # 🌟 将 working_memory 传入过滤器进行拦截
            cleaned_links = self._dynamic_heuristic_filter(all_links, evolution_dna, working_memory)
            final_links = self._aggregate_links(cleaned_links, threshold=4)
            
            state.raw_links = final_links 
            state.extracted_content = browse_result.get("html", "")[:6000]
            state.is_valid = True
            
            if is_access_denied:
                logger.warning(f"🛡️ 探测到访问限制 (可能为 L4 资产): {url}")
            else:
                logger.info(f"✅ DFS 分支提取完成: {len(all_links)} 原始链接 -> 过滤后压缩为 {len(final_links)} 个高优节点")
        else:
            logger.warning(f"❌ Browse Page Failed for URL: {url} | Denied: {is_access_denied}")
            state.is_valid = False
            # 🌟 如果页面崩溃，记录错误轨迹
            if working_memory:
                working_memory.record_step(url, "ERROR", getattr(state, "current_depth", 0), "Page failed to load or browser error")

        state.extract_duration = time.time() - start_time
        return state
