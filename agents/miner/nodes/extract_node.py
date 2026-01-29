import sys
import os
import asyncio
import json
import time
import re
from typing import Any, List, Dict
from loguru import logger

class ExtractNode:
    def __init__(self):
        from llms.miner_llm import MinerLLMClient
        self.llm = MinerLLMClient()
        from tools.browse_page import BrowsePageTool
        self.browse_tool = BrowsePageTool()

    def _heuristic_filter(self, links: List[Dict]) -> List[Dict]:
        """
        地毯式扫描后的初步物理过滤，保留有价值的候选链
        """
        junk_ext = re.compile(r'\.(png|jpg|jpeg|gif|css|js|pdf|docx|zip|exe|mp4|avi|mp3|wav|woff|ttf)$', re.I)
        noise_keywords = {'login', 'signin', 'facebook', 'twitter', 'terms', 'privacy', 'help', 'faq'}
        
        filtered = []
        seen_urls = set()

        for link in links:
            url = link.get('url', '').strip().split('#')[0].rstrip('/')
            text = link.get('text', '').strip()
            
            if not url or url in seen_urls: continue
            if junk_ext.search(url): continue
            
            url_lower = url.lower()
            if any(k in url_lower for k in noise_keywords): continue
            if len(text) < 2 and not link.get('context'): continue # 过滤无文本且无上下文的链接
            
            filtered.append(link)
            seen_urls.add(url)
        return filtered

    async def execute(self, state: Any) -> Any:
        start_time = time.time()
        # 修复：确保从 current_clue 获取 URL
        current_clue = getattr(state, "current_clue", {})
        url = current_clue.get("url")
        if not url:
            logger.error("ExtractNode: No URL found in state.current_clue")
            state.is_valid = False
            return state

        logger.info(f"🚀 ExtractNode 广度扫描启动: {url}")

        # 1. 动态生成浏览指令
        plan_result = {"browse_instructions": "Scroll to bottom to load all content; capture all link texts and surrounding descriptions."}

        # 2. 调用 BrowseTool（带重试机制）
        browse_result = None
        for attempt in range(2):
            try:
                # 假设 browse_tool 已优化，支持抓取 context
                browse_result = await asyncio.wait_for(
                    self.browse_tool(url=url, use_js=True),
                    timeout=120
                )
                if browse_result and browse_result.get("success"):
                    break
            except Exception as e:
                logger.warning(f"⚠️ 访问尝试 {attempt+1} 失败: {e}")
                await asyncio.sleep(2)

        if browse_result and browse_result.get("success"):
            all_links = browse_result.get("all_links", [])
            # 物理过滤，但不改变顺序，保留 DOM 逻辑关系
            cleaned_links = self._heuristic_filter(all_links)
            
            # DFS 关键：限制单页分支宽度，防止搜索爆炸，优先保留疑似目录的链接
            state.raw_links = cleaned_links[:100] 
            state.extracted_content = browse_result.get("html", "")
            state.metadata = {
                "url": url,
                "link_stats": {"raw": len(all_links), "cleaned": len(cleaned_links)}
            }
            state.is_valid = True
            logger.info(f"✅ 广度提取完成: {len(state.raw_links)} 个候选链接进入决策")
        else:
            state.is_valid = False
            state.error = "BrowseTool Failed"

        state.extract_duration = time.time() - start_time
        return state