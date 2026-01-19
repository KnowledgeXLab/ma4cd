"""
Miner 的核心工具：智能网页访问与结构提取
- 基础层: 访问 URL + 获取 HTML
- 增强层: JS 渲染 + 基本元数据提取
- 核心层: 提取所有 <a href> 链接（用 Playwright eval） + 关键词匹配 + Negative Logic
- 智能层: 指令式 LLM 分析 (识别 L3 子库、过滤噪音)
"""

import sys
import os

# 计算项目根目录（ma4cd）
# 当前文件在 agents/miner/tools/ → 向上 3 层就是根
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))

# 加到 sys.path
if project_root not in sys.path:
    sys.path.insert(0, project_root)
import asyncio
import json
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse

from loguru import logger
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from seaf.interface.base_tool import BaseTool
from agents.miner.llms.miner_llm import create_miner_llm  # Miner 专属 LLM 客户端

class BrowsePageTool(BaseTool):
    """
    访问网页，支持 JS 渲染，提取所有链接、元数据，支持指令式智能分析。
    输出结构化 JSON，供 Miner 判断是否分裂 L3 子库。
    
    参数:
    - url: 要访问的 URL
    - instructions: 自定义指令 (e.g. "提取所有数据相关链接，并判断是否是 L3 子库")
    - use_js: 是否启用 JS 渲染 (默认 True)
    - timeout: 超时秒数 (默认 90)
    """

    name = "browse_page"
    description = """
    访问任意网页，返回结构化内容。
    支持 JS 渲染、全链接提取、智能指令分析。
    主要用于 Miner 识别 L2 门户的子入口（Data/Statistics/Archives 等）。
    """

    def __init__(self):
        super().__init__(name=self.name, description=self.description)
        # 初始化 Miner 专用 LLM
        self.llm = create_miner_llm()
        self.playwright = None
        self.browser = None

    async def _init_browser(self):
        if self.playwright is None:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True, args=['--no-sandbox'])

    async def _close_browser(self):
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None

    async def __call__(
        self,
        url: str,
        instructions: Optional[str] = None,
        use_js: bool = True,
        timeout: int = 90,
    ) -> Dict[str, Any]:
        """
        主调用入口：访问网页，提取链接、元数据、LLM 分析
        """
        await self._init_browser()

        try:
            # 创建上下文和页面
            context = await self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                ignore_https_errors=True,
                java_script_enabled=use_js,
                locale="zh-CN",  # 支持中文站点
                timezone_id="Asia/Shanghai"
            )
            page = await context.new_page()

            # 访问页面 - 使用 networkidle 等待所有网络请求完成
            response = await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            if response is None or response.status >= 400:
                raise ValueError(f"HTTP {response.status} 错误: {url}")

            # 额外等待，确保动态内容加载
            await page.wait_for_timeout(5000)  # 5秒缓冲

            # 获取完整 HTML
            html = await page.content()

            # 增强层：提取标题和描述
            title = await page.title()
            description = await page.evaluate('''() => {
                const meta = document.querySelector('meta[name="description"]');
                return meta ? meta.getAttribute('content') : '';
            }''') or ""

            # 核心层：用 Playwright 提取所有 <a href> 链接
            raw_links = await page.eval_on_selector_all(
                'a[href]',
                '''elements => elements.map(el => ({
                    url: el.href,
                    text: el.innerText.trim(),
                    class: el.className,
                    id: el.id || null
                }))'''
            )

            # 过滤无效链接 + 绝对化 URL + 去重
            seen_urls = set()
            all_links = []
            for link in raw_links:
                full_url = urljoin(url, link['url'])
                if full_url in seen_urls or not full_url.startswith(('http://', 'https://')):
                    continue
                seen_urls.add(full_url)

                text_lower = link['text'].lower()

                # 正向关键词匹配
                positive_keywords = [
                    "data", "dataset", "statistics", "statistik", "thống kê", "dữ liệu", "archive", 
                    "resources", "publications", "database", "cơ sở dữ liệu", "portal", "repository", 
                    "library", "catalog", "series", "collection", "industrial", "population", "economic",
                    "数据", "统计", "年鉴", "数据库", "指标", "查询", "档案", "资源"
                ]
                matched_keywords = [kw for kw in positive_keywords if kw.lower() in text_lower]

                # Negative Logic
                negative_keywords = [
                    "about", "contact", "news", "blog", "home", "login", "search", "press",
                    "media", "career", "job", "team", "partner", "sitemap", "关于", "联系", "新闻", "博客"
                ]
                is_noise = any(nk.lower() in text_lower for nk in negative_keywords)

                confidence = len(matched_keywords) * 0.3
                if is_noise:
                    confidence -= 0.5

                all_links.append({
                    "url": full_url,
                    "text": link['text'],
                    "class": link['class'],
                    "id": link['id'],
                    "matched_keywords": matched_keywords,
                    "is_noise": is_noise,
                    "confidence": max(0.0, min(1.0, confidence))
                })

            # 排序（confidence 降序）
            all_links.sort(key=lambda x: x["confidence"], reverse=True)

            # 智能层：LLM 分析（如果有指令）
            analysis = {"potential_subportals": [], "noise_links": [], "reason_summary": "无指令"}
            if instructions:
                analysis = await self._llm_analysis(url, html, all_links, instructions)

            result = {
                "url": url,
                "success": True,
                "title": title,
                "description": description,
                "all_links": all_links[:50],  # 限制输出数量，避免过大
                "analysis": analysis,
                "html_length": len(html)
            }

            await context.close()
            return result

        except PlaywrightTimeoutError:
            logger.warning(f"页面加载超时: {url}")
            return {"url": url, "success": False, "error": "页面加载超时"}
        except Exception as e:
            logger.error(f"browse_page 失败: {url} - {str(e)}")
            return {"url": url, "success": False, "error": str(e)}
        finally:
            await self._close_browser()

    async def _llm_analysis(self, url: str, html: str, links: List[Dict], instructions: str) -> Dict[str, Any]:
        """智能层：LLM 深度分析（判断 L3 子库、过滤噪音）"""
        # 简化 links 为 JSON（避免 token 超）
        links_json = json.dumps(links[:20], ensure_ascii=False)  # 只取前 20 个

        prompt = f"""
Role: 深度挖掘工 - 子库识别专家
Task: 分析门户网站 {url} 的结构，找出可能的 L3 子库入口。

链接列表 (前 20 个):
{links_json}

指令:
{instructions}

Rules:
1. L3 特征（满足任意 2 条视为 L3）:
   - 有独立名称/Logo（如 "工业统计门户"）
   - 有专用搜索框或数据筛选器
   - 路径不同（非首页子路径）
   - 包含数据表格、API 接口、下载入口
2. Negative Logic: 忽略 "About Us", "Contact", "News", "Blog", "Home", "Login" 等
3. 输出严格 JSON，不要多余文字:

{{
  "potential_subportals": [
    {{
      "url": "https://...",
      "title": "...",
      "reason": "...",
      "confidence": 0.0-1.0
    }}
  ],
  "noise_links": ["url1", "url2"],
  "confidence": 0.0-1.0,
  "reason_summary": "str"
}}
"""

        try:
            response = self.llm.invoke_json(prompt, temperature=0.3)
            return response
        except Exception as e:
            logger.error(f"LLM 分析失败: {str(e)}")
            return {"potential_subportals": [], "noise_links": [], "reason_summary": f"分析错误: {str(e)}", "confidence": 0.0}

# 测试代码
if __name__ == "__main__":
    import asyncio
    import json

    tool = BrowsePageTool()

    async def test():
        result = await tool(
            url="https://www.stats.gov.hk/",
            instructions="提取所有与数据、统计、年鉴、指标查询相关的链接，并判断哪些可能是独立的 L3 子库（有独立名称、搜索框、数据界面）。忽略新闻、首页等。",
            use_js=True,
            timeout=90
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    asyncio.run(test())