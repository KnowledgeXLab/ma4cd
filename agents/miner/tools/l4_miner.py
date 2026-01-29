# agents/miner/tools/l4_miner.py

import asyncio
import re
import json
import hashlib
from typing import Dict, List, Optional, Any, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from loguru import logger
from playwright.async_api import async_playwright, Page

from llms.miner_llm import create_miner_llm

class L4RecordMiner:
    def __init__(self, max_depth: int = 2):
        self.llm = create_miner_llm()
        self.max_depth = max_depth
        self.visited_urls: Set[str] = set()
        # L3 特征词：用于识别专业数据库
        self.l3_keywords = r'home|database|system|bank|archive|repository|portal|resource|center'

    async def mine_l4_records(self, l3_url: str, l3_metadata: Dict = None) -> Dict:
        """挖掘主入口：现在具备识别 L3 子库和 L4 记录的双重能力"""
        logger.info(f"🚀 [L4Miner] 深度扫描资源: {l3_url}")
        self.visited_urls.clear()
        
        raw_results = []
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    viewport={'width': 1280, 'height': 1200},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
                )
                raw_results = await self._recursive_mine(context, l3_url, depth=0)
                await browser.close()

            # 执行分级去重
            return self._classify_and_deduplicate(raw_results)

        except Exception as e:
            logger.error(f"L4 挖掘严重错误: {e}")
            return {"l3_sub_databases": [], "l4_records": [], "error": str(e)}

    async def _recursive_mine(self, context, url: str, depth: int) -> List[Dict]:
        if depth > self.max_depth or url in self.visited_urls:
            return []
        
        self.visited_urls.add(url)
        logger.info(f"📍 层级 [{depth}] 扫描: {url}")
        
        found_items = []
        page = await context.new_page()
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(1) # 等待动态内容
            
            html_content = await page.content()
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 核心改进：提取并初步判断级别
            current_items = await self._extract_with_level_hint(soup, url)
            found_items.extend(current_items)
            
            # 自动深入挖掘（广度优先）
            if depth < self.max_depth:
                nav_targets = await self._get_nav_targets(page, url)
                for target in nav_targets:
                    if "ncbi.nlm.nih.gov" in target:
                        found_items.extend(await self._recursive_mine(context, target, depth + 1))
        except Exception as e:
            logger.warning(f"路径跳过 {url}: {e}")
        finally:
            await page.close()
        return found_items

    async def _extract_with_level_hint(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """改进的提取逻辑：增加 L3 vs L4 的特征探测"""
        items = []
        # 排除干扰区域
        for noise in soup(['nav', 'footer', 'header', 'script', 'style']):
            noise.decompose()

        for container in soup.find_all(['div', 'li', 'section']):
            link = container.find('a', href=True)
            if not link: continue
            
            title = link.get_text(strip=True)
            if len(title) < 2 or len(title) > 100: continue
            
            full_text = container.get_text(" ", strip=True)
            desc = full_text.replace(title, "", 1).strip()
            
            if 15 < len(desc) < 800:
                item_url = urljoin(base_url, link['href'])
                
                # --- 核心逻辑：特征识别 ---
                # 1. 物理特征判断
                is_l3_candidate = False
                if re.search(self.l3_keywords, title, re.I) or re.search(self.l3_keywords, item_url, re.I):
                    is_l3_candidate = True
                
                # 2. 结构特征判断 (短路径通常是库，长参数通常是数据记录)
                parsed_url = urlparse(item_url)
                if len(parsed_url.path.strip('/').split('/')) <= 1:
                    is_l3_candidate = True

                items.append({
                    "title": title,
                    "url": item_url,
                    "description": desc[:300],
                    "is_l3_hint": is_l3_candidate,
                    "source_page": base_url
                })
        return items

    def _classify_and_deduplicate(self, raw_results: List[Dict]) -> Dict:
        """最终分类器：根据特征将结果分流到 L3 线索或 L4 记录"""
        l3_sub_databases = []
        l4_records = []
        seen_urls = set()

        for item in raw_results:
            url = item['url'].split('#')[0].rstrip('/')
            if url in seen_urls: continue
            seen_urls.add(url)

            # 生成唯一ID
            item['record_id'] = hashlib.md5(url.encode()).hexdigest()[:12]

            # 最终分类逻辑
            # 如果标题含有 GenBank, PubMed 等或满足 candidate 特征，判定为 L3
            if item.get('is_l3_hint') or any(kw in item['title'].lower() for kw in ['bank', 'database', 'system']):
                # 构造符合 L3 规范的线索结构
                l3_sub_databases.append({
                    "url": item['url'],
                    "title": item['title'],
                    "confidence": 0.95,
                    "reason": f"识别为专业子库 (独立名称: {item['title']})",
                    "description": item['description'],
                    "likely_level": "L3"
                })
            else:
                l4_records.append(item)

        return {
            "l3_sub_databases": l3_sub_databases,  # 发现的新子库入口
            "l4_records": l4_records[:100],        # 发现的具体数据条目
            "total_l3": len(l3_sub_databases),
            "total_l4": len(l4_records)
        }

    async def _get_nav_targets(self, page: Page, current_url: str) -> List[str]:
        """获取导航目标（保持原有逻辑）"""
        try:
            # 简单的规则筛选更有价值的导航链接
            links = await page.eval_on_selector_all("a[href]", "elements => elements.map(e => ({text: e.innerText, href: e.href}))")
            targets = []
            for l in links:
                if re.search(r'all|list|directory|guide|browse', l['text'], re.I):
                    targets.append(l['href'])
            return list(set(targets))[:3]
        except: return []

    async def close(self):
        logger.info("🧹 L4Miner 资源释放")