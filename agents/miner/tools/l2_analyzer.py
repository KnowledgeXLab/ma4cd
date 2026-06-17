# miner/tools/l2_analyzer.py
"""
L2站点分析器 - 截图分析主页并挖掘L3数据集
"""

import aiohttp
import asyncio
import base64
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
from loguru import logger
from urllib.parse import urljoin, urlparse
import re
import json

class L2SiteAnalyzer:
    """L2站点分析器"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.playwright = None
        self.browser = None
        
        # 数据库可能性指标
        self.database_indicators = [
            'database', 'repository', 'archive', 'collection', 'catalog',
            'search', 'browse', 'query', 'explore', 'data', 'records',
            'entries', 'samples', 'datasets', 'download', 'export'
        ]
        
        # 领域信号（通用底座 + skill miner_signals.domain_keywords 注入）
        self.domain_indicators = [
            "database", "repository", "archive", "dataset", "catalog",
            "metadata", "registry", "collection", "records",
        ]
        try:
            from utils.miner_signals import domain_keywords
            extra = [k for k in domain_keywords() if k and k not in self.domain_indicators]
            if extra:
                self.domain_indicators.extend(extra[:30])
        except Exception:
            pass
        # Backward-compatible alias
        self.biomedical_indicators = self.domain_indicators
        
        # 导航菜单关键词
        self.navigation_keywords = [
            'browse', 'search', 'download', 'data', 'datasets', 'tools',
            'api', 'help', 'documentation', 'submit', 'upload'
        ]
    
    async def analyze_and_mine_l3(self, l2_url: str) -> Dict:
        """分析L2站点并挖掘L3数据集"""
        
        logger.info(f"🔍 开始分析L2站点: {l2_url}")
        
        try:
            # 1. 截图并分析主页
            screenshot_analysis = await self._analyze_homepage_screenshot(l2_url)
            
            # 2. 分析页面内容
            content_analysis = await self._analyze_page_content(l2_url)
            
            # 3. 判断是否可能有数据库
            has_potential = self._evaluate_database_potential(screenshot_analysis, content_analysis)
            
            if not has_potential:
                return {
                    "url": l2_url,
                    "has_potential_databases": False,
                    "confidence": 0.0,
                    "l3_candidates": [],
                    "reason": "no_database_indicators_found"
                }
            
            # 4. 生成检索词
            keywords = await self._generate_search_keywords(l2_url, screenshot_analysis, content_analysis)
            
            # 5. 执行全网检索
            l3_candidates = await self._search_for_l3_datasets(l2_url, keywords)
            
            # 6. 验证L3候选
            verified_l3 = await self._verify_l3_candidates(l3_candidates)
            
            return {
                "url": l2_url,
                "has_potential_databases": True,
                "confidence": has_potential.get("confidence", 0.0),
                "analysis": {
                    "screenshot_analysis": screenshot_analysis,
                    "content_analysis": content_analysis,
                    "database_potential": has_potential
                },
                "search_keywords": keywords,
                "l3_candidates": verified_l3,
                "total_found": len(verified_l3)
            }
            
        except Exception as e:
            logger.error(f"L2分析失败 {l2_url}: {e}")
            return {
                "url": l2_url,
                "has_potential_databases": False,
                "error": str(e),
                "l3_candidates": []
            }
    
    async def _analyze_homepage_screenshot(self, url: str) -> Dict:
        """截图分析主页"""
        
        try:
            if not self.playwright:
                self.playwright = await async_playwright().start()
                self.browser = await self.playwright.chromium.launch(headless=True)
            
            page = await self.browser.new_page()
            
            # 设置视口和用户代理
            await page.set_viewport_size({"width": 1920, "height": 1080})
            await page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            
            # 访问页面
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # 等待页面加载
            await page.wait_for_timeout(3000)
            
            # 截图
            screenshot = await page.screenshot(full_page=True)
            
            # 提取页面文本内容
            page_text = await page.inner_text('body')
            
            # 提取导航菜单
            navigation = await self._extract_navigation_from_page(page)
            
            # 提取表单信息
            forms = await self._extract_forms_from_page(page)
            
            await page.close()
            
            # AI分析截图（这里简化为文本分析）
            visual_analysis = await self._analyze_visual_elements(page_text, navigation, forms)
            
            return {
                "screenshot_taken": True,
                "page_text_length": len(page_text),
                "navigation_items": navigation,
                "forms_found": forms,
                "visual_analysis": visual_analysis,
                "screenshot_base64": base64.b64encode(screenshot).decode('utf-8')[:100] + "..."  # 截断显示
            }
            
        except Exception as e:
            logger.error(f"截图分析失败: {e}")
            return {
                "screenshot_taken": False,
                "error": str(e),
                "visual_analysis": {"database_indicators": 0}
            }
    
    async def _extract_navigation_from_page(self, page) -> List[Dict]:
        """从页面提取导航信息"""
        
        navigation = []
        
        try:
            # 提取导航链接
            nav_links = await page.query_selector_all('nav a, .nav a, .menu a, header a')
            
            for link in nav_links:
                text = await link.inner_text()
                href = await link.get_attribute('href')
                
                if text and href:
                    navigation.append({
                        "text": text.strip(),
                        "href": href,
                        "is_database_related": any(keyword in text.lower() 
                                                 for keyword in self.navigation_keywords)
                    })
        except Exception as e:
            logger.debug(f"导航提取失败: {e}")
        
        return navigation
    
    async def _extract_forms_from_page(self, page) -> List[Dict]:
        """从页面提取表单信息"""
        
        forms = []
        
        try:
            form_elements = await page.query_selector_all('form')
            
            for form in form_elements:
                # 提取表单输入字段
                inputs = await form.query_selector_all('input, select, textarea')
                
                form_info = {
                    "action": await form.get_attribute('action') or '',
                    "method": await form.get_attribute('method') or 'get',
                    "inputs": []
                }
                
                for input_elem in inputs:
                    input_type = await input_elem.get_attribute('type') or 'text'
                    input_name = await input_elem.get_attribute('name') or ''
                    input_placeholder = await input_elem.get_attribute('placeholder') or ''
                    
                    form_info["inputs"].append({
                        "type": input_type,
                        "name": input_name,
                        "placeholder": input_placeholder
                    })
                
                # 判断是否为搜索表单
                form_text = await form.inner_text()
                form_info["is_search_form"] = any(keyword in form_text.lower() 
                                                for keyword in ['search', 'query', 'find'])
                
                forms.append(form_info)
                
        except Exception as e:
            logger.debug(f"表单提取失败: {e}")
        
        return forms
    
    async def _analyze_visual_elements(self, page_text: str, navigation: List, forms: List) -> Dict:
        """分析视觉元素"""
        
        page_text_lower = page_text.lower()
        
        # 计算数据库指标得分
        database_score = sum(1 for indicator in self.database_indicators 
                           if indicator in page_text_lower)
        
        # 计算生物医学指标得分
        biomedical_score = sum(1 for indicator in self.biomedical_indicators 
                             if indicator in page_text_lower)
        
        # 分析导航菜单
        nav_database_items = sum(1 for item in navigation 
                               if item.get("is_database_related", False))
        
        # 分析搜索表单
        search_forms = sum(1 for form in forms 
                         if form.get("is_search_form", False))
        
        return {
            "database_indicators": database_score,
            "biomedical_indicators": biomedical_score,
            "navigation_database_items": nav_database_items,
            "search_forms": search_forms,
            "total_navigation_items": len(navigation),
            "total_forms": len(forms),
            "page_complexity": len(page_text) // 1000  # 页面复杂度（KB）
        }
    
    async def _analyze_page_content(self, url: str) -> Dict:
        """分析页面内容"""
        
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        try:
            async with self.session.get(url, timeout=15) as response:
                if response.status >= 400:
                    return {"error": f"HTTP {response.status}"}
                
                content = await response.text()
                soup = BeautifulSoup(content, 'html.parser')
                
                return {
                    "title": soup.find('title').get_text() if soup.find('title') else '',
                    "meta_description": self._extract_meta_description(soup),
                    "headings": self._extract_headings(soup),
                    "links_analysis": self._analyze_links(soup, url),
                    "content_keywords": self._extract_content_keywords(content),
                    "structured_data": self._extract_structured_data(soup)
                }
                
        except Exception as e:
            return {"error": str(e)}
    
    def _extract_meta_description(self, soup: BeautifulSoup) -> str:
        """提取meta描述"""
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        return meta_desc.get('content', '') if meta_desc else ''
    
    def _extract_headings(self, soup: BeautifulSoup) -> List[str]:
        """提取标题"""
        headings = []
        for tag in ['h1', 'h2', 'h3']:
            for heading in soup.find_all(tag):
                text = heading.get_text().strip()
                if text:
                    headings.append(text)
        return headings
    
    def _analyze_links(self, soup: BeautifulSoup, base_url: str) -> Dict:
        """分析链接"""
        
        links = soup.find_all('a', href=True)
        
        internal_links = []
        external_links = []
        download_links = []
        
        for link in links:
            href = link.get('href')
            text = link.get_text().strip()
            
            # 转换为绝对URL
            absolute_url = urljoin(base_url, href)
            
            # 分类链接
            if urlparse(absolute_url).netloc == urlparse(base_url).netloc:
                internal_links.append({"url": absolute_url, "text": text})
            else:
                external_links.append({"url": absolute_url, "text": text})
            
            # 检查下载链接
            if any(keyword in text.lower() for keyword in ['download', 'export', 'save']):
                download_links.append({"url": absolute_url, "text": text})
        
        return {
            "total_links": len(links),
            "internal_links": len(internal_links),
            "external_links": len(external_links),
            "download_links": download_links,
            "sample_internal": internal_links[:10],  # 样本
            "sample_external": external_links[:5]
        }
    
    def _extract_content_keywords(self, content: str) -> Dict:
        """提取内容关键词"""
        
        content_lower = content.lower()
        
        # 统计关键词频率
        database_keywords = {}
        for keyword in self.database_indicators:
            count = content_lower.count(keyword)
            if count > 0:
                database_keywords[keyword] = count
        
        biomedical_keywords = {}
        for keyword in self.biomedical_indicators:
            count = content_lower.count(keyword)
            if count > 0:
                biomedical_keywords[keyword] = count
        
        return {
            "database_keywords": database_keywords,
            "biomedical_keywords": biomedical_keywords,
            "total_database_mentions": sum(database_keywords.values()),
            "total_biomedical_mentions": sum(biomedical_keywords.values())
        }
    
    def _extract_structured_data(self, soup: BeautifulSoup) -> Dict:
        """提取结构化数据"""
        
        structured_data = {
            "json_ld": [],
            "microdata": [],
            "rdfa": []
        }
        
        # JSON-LD
        json_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_scripts:
            try:
                data = json.loads(script.string)
                structured_data["json_ld"].append(data)
            except:
                pass
        
        # 简化的微数据检测
        microdata_elements = soup.find_all(attrs={"itemtype": True})
        for elem in microdata_elements:
            structured_data["microdata"].append({
                "itemtype": elem.get("itemtype"),
                "text": elem.get_text()[:100]
            })
        
        return structured_data
    
    def _evaluate_database_potential(self, screenshot_analysis: Dict, content_analysis: Dict) -> Dict:
        """评估数据库潜力"""
        
        score = 0
        evidence = []
        
        # 截图分析得分
        if "visual_analysis" in screenshot_analysis:
            visual = screenshot_analysis["visual_analysis"]
            
            # 数据库指标
            db_indicators = visual.get("database_indicators", 0)
            score += min(db_indicators * 0.5, 3)
            if db_indicators > 0:
                evidence.append(f"database_indicators_{db_indicators}")
            
            # 生物医学指标
            bio_indicators = visual.get("biomedical_indicators", 0)
            score += min(bio_indicators * 0.3, 2)
            if bio_indicators > 0:
                evidence.append(f"biomedical_indicators_{bio_indicators}")
            
            # 导航菜单
            nav_items = visual.get("navigation_database_items", 0)
            score += min(nav_items * 0.5, 2)
            if nav_items > 0:
                evidence.append(f"navigation_database_items_{nav_items}")
            
            # 搜索表单
            search_forms = visual.get("search_forms", 0)
            score += min(search_forms * 1, 2)
            if search_forms > 0:
                evidence.append(f"search_forms_{search_forms}")
        
        # 内容分析得分
        if "error" not in content_analysis:
            # 标题分析
            title = content_analysis.get("title", "").lower()
            if any(keyword in title for keyword in self.database_indicators):
                score += 1
                evidence.append("title_contains_database_keywords")
            
            # 链接分析
            links_analysis = content_analysis.get("links_analysis", {})
            download_links = len(links_analysis.get("download_links", []))
            if download_links > 0:
                score += min(download_links * 0.5, 2)
                evidence.append(f"download_links_{download_links}")
            
            # 关键词分析
            keywords = content_analysis.get("content_keywords", {})
            db_mentions = keywords.get("total_database_mentions", 0)
            bio_mentions = keywords.get("total_biomedical_mentions", 0)
            
            if db_mentions > 5:
                score += 1
                evidence.append(f"database_mentions_{db_mentions}")
            
            if bio_mentions > 3:
                score += 0.5
                evidence.append(f"biomedical_mentions_{bio_mentions}")
        
        # 计算置信度
        max_possible_score = 12  # 调整最大可能得分
        confidence = min(score / max_possible_score, 1.0)
        
        return {
            "has_potential": confidence >= 0.3,  # 阈值
            "confidence": round(confidence, 3),
            "score": score,
            "max_score": max_possible_score,
            "evidence": evidence
        }
    
    async def _generate_search_keywords(self, url: str, screenshot_analysis: Dict, content_analysis: Dict) -> List[str]:
        """生成搜索关键词"""
        
        keywords = set()
        
        # 从域名提取关键词
        domain = urlparse(url).netloc
        domain_parts = domain.replace('.', ' ').replace('-', ' ').split()
        keywords.update(part for part in domain_parts if len(part) > 2)
        
        # 从标题提取关键词
        if "error" not in content_analysis:
            title = content_analysis.get("title", "")
            title_words = re.findall(r'\b\w{3,}\b', title.lower())
            keywords.update(title_words[:5])  # 取前5个词
        
        # 从内容关键词提取
        if "error" not in content_analysis:
            content_keywords = content_analysis.get("content_keywords", {})
            
            # 高频数据库关键词
            db_keywords = content_keywords.get("database_keywords", {})
            top_db_keywords = sorted(db_keywords.items(), key=lambda x: x[1], reverse=True)[:3]
            keywords.update(kw for kw, _ in top_db_keywords)
            
            # 高频生物医学关键词
            bio_keywords = content_keywords.get("biomedical_keywords", {})
            top_bio_keywords = sorted(bio_keywords.items(), key=lambda x: x[1], reverse=True)[:3]
            keywords.update(kw for kw, _ in top_bio_keywords)
        
        # 添加通用数据集关键词
        generic_keywords = ['dataset', 'data', 'download', 'export', 'database']
        keywords.update(generic_keywords)
        
        return list(keywords)[:10]  # 限制关键词数量
    
    async def _search_for_l3_datasets(self, l2_url: str, keywords: List[str]) -> List[Dict]:
        """搜索L3数据集（skill: search_discovery 查询模板）"""
        from .search_engine import SearchEngine

        search_engine = SearchEngine()
        try:
            return await search_engine.search_for_l3_datasets(l2_url, keywords)
        except Exception as e:
            logger.error(f"搜索L3数据集失败: {e}")
            return []
        finally:
            await search_engine.close()
    
    async def _verify_l3_candidates(self, candidates: List[Dict]) -> List[Dict]:
        """验证L3候选"""
        
        # 这里需要集成L3检测器
        from .l3_detector import L3DatasetDetector
        
        detector = L3DatasetDetector()
        verified = []
        
        try:
            for candidate in candidates:
                url = candidate.get('url', '')
                if not url:
                    continue
                
                # 检测是否为L3数据集
                detection_result = await detector.detect_l3_dataset(url)
                
                if detection_result.get('is_l3', False):
                    verified.append({
                        **candidate,
                        "l3_detection": detection_result,
                        "confidence": detection_result.get('confidence', 0.0),
                        "evidence": detection_result.get('evidence', [])
                    })
            
            # 按置信度排序
            verified.sort(key=lambda x: x.get('confidence', 0), reverse=True)
            
            return verified[:20]  # 返回前20个最佳候选
            
        except Exception as e:
            logger.error(f"验证L3候选失败: {e}")
            return []
        finally:
            await detector.close()
    
    async def close(self):
        """关闭资源"""
        if self.session:
            await self.session.close()
        
        if self.browser:
            await self.browser.close()
        
        if self.playwright:
            await self.playwright.stop()