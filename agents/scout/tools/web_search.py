'''
"""
广域侦察兵搜索工具 - 轻量级公网数据挖掘
专为 MA4CD Scout 设计的策略化搜索工具 - 最终版
"""

import os
import sys
import time
import json
import hashlib
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import urllib.parse
from dataclasses import asdict
from loguru import logger

# 添加项目根目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.append(project_root)

# 简化的搜索引擎客户端
try:
    from ddgs import DDGS
    HAS_DDG = True
except ImportError:
    HAS_DDG = False
    logger.warning("ddgs 未安装，DuckDuckGo 搜索不可用")

try:
    import arxiv
    HAS_ARXIV = True
except ImportError:
    HAS_ARXIV = False
    logger.info("arxiv 未安装，学术搜索不可用")


@dataclass
class SearchResult:
    """搜索结果 - 适配 Scout 的 Clue 格式"""
    url: str
    title: str
    snippet: str
    source: str = "unknown"
    relevance_score: float = 5.0
    tier: str = "tier1"  # tier1/tier2/tier3
    metadata: Dict[str, Any] = None
    
    def to_clue_format(self) -> Dict[str, Any]:
        """转换为 SearchNode 期望的 Clue 格式"""
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "source": self.source,
            "relevance_score": self.relevance_score,
            "metadata": {
                "tier": self.tier,
                "search_time": datetime.now().isoformat(),
                **(self.metadata or {})
            }
        }
    
    def to_dict(self):
        return asdict(self)


class ScoutWebSearchTool:
    """
    广域侦察兵搜索工具
    轻量级、策略化的公网数据挖掘
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化搜索工具
        
        Args:
            config: 配置参数
        """
        self.config = config or {}
        
        # 初始化客户端
        self.clients = {}
        if HAS_DDG:
            self.clients['ddg'] = DDGS()
            logger.info("DuckDuckGo 客户端已初始化")
        
        if HAS_ARXIV:
            self.clients['arxiv'] = arxiv.Client()
            logger.info("arXiv 客户端已初始化")
        
        # 缓存
        self.cache = {}
        
        # 国家/地区分类
        self.tier_classification = {
            # Tier 1: 美国、德国、日本等
            'tier1': ['us', 'de', 'jp', 'uk', 'fr', 'ca', 'au', 'kr', 'sg', 'tw'],
            # Tier 2: 越南、沙特、俄罗斯等
            'tier2': ['vn', 'sa', 'ru', 'cn', 'in', 'br', 'mx', 'id', 'th', 'my'],
            # Tier 3: 老挝、非洲国家、岛国等
            'tier3': ['la', 'kh', 'mm', 'ke', 'ng', 'gh', 'et', 'tz', 'ug', 'zm',
                     'fj', 'vu', 'ws', 'to', 'sb']  # 使用标准国家代码
        }
        
        logger.info("广域侦察兵搜索工具初始化完成")
    
    def __call__(self, query: str, num_results: int = 10, **kwargs) -> List[Dict[str, Any]]:
        """
        执行搜索 - 适配 SearchNode 调用
        
        Args:
            query: 搜索查询
            num_results: 结果数量
            **kwargs: 额外参数，包括:
                - country_code: 国家代码，用于确定 Tier 策略
                - task_type: 任务类型
                - enable_proxy: 是否启用代理
                
        Returns:
            搜索结果列表
        """
        start_time = time.time()
        
        # 获取国家代码和策略
        country_code = kwargs.get('country_code', 'us').lower()
        task_type = kwargs.get('task_type', 'general')
        tier = self._get_tier_by_country(country_code)
        
        logger.info(f"执行搜索: {query} | 国家: {country_code} | Tier: {tier} | 任务: {task_type}")
        
        # 应用 Tier 策略优化查询
        optimized_query = self._apply_tier_strategy(query, tier, task_type)
        
        # 多源搜索
        results = []
        
        # 1. 网页搜索 (DuckDuckGo) - 主要数据源
        if 'ddg' in self.clients:
            web_results = self._search_web(optimized_query, num_results, tier, task_type)
            results.extend(web_results)
        
        # 2. 学术搜索 (arXiv) - 如果是研究类任务
        if 'arxiv' in self.clients and self._is_research_query(query, task_type):
            academic_results = self._search_academic(query, max(3, num_results // 3))
            results.extend(academic_results)
        
        # 3. 代码搜索 (如果查询包含技术关键词)
        if self._is_technical_query(query) and 'ddg' in self.clients:
            code_results = self._search_code(query, max(2, num_results // 4))
            results.extend(code_results)
        
        # 去重和排序
        final_results = self._deduplicate_and_sort(results)[:num_results]
        
        # 转换为 Clue 格式
        clues = [result.to_clue_format() for result in final_results]
        
        elapsed = time.time() - start_time
        logger.info(f"搜索完成，用时 {elapsed:.2f}s，找到 {len(clues)} 个线索")
        
        return clues
    
    def _get_tier_by_country(self, country_code: str) -> str:
        """根据国家代码确定 Tier"""
        for tier, countries in self.tier_classification.items():
            if country_code in countries:
                return tier
        return 'tier1'  # 默认 Tier 1
    
    def _apply_tier_strategy(self, query: str, tier: str, task_type: str) -> str:
        """
        应用 Tier 策略优化查询
        """
        original_query = query
        
        if tier == 'tier1':
            # 美/德/日: 增加文件类型和政府网站搜索
            if task_type in ['data', 'api', 'documentation']:
                # 对数据/API任务添加文件类型搜索
                if 'filetype:' not in query.lower():
                    query = f"{query} (filetype:json OR filetype:csv OR filetype:xml)"
                # 添加政府/技术网站
                query = f"{query} site:data.gov OR site:api.gov OR site:github.io"
        
        elif tier == 'tier2':
            # 越/沙/俄: 添加本地化支持
            # 简化的多语言处理 - 添加本地化关键词
            if 'site:' not in query.lower():
                # 根据常见国家添加本地化网站
                localized_sites = {
                    'cn': 'site:.cn',
                    'ru': 'site:.ru',
                    'sa': 'site:.sa',
                    'vn': 'site:.vn'
                }
                # 这里可以扩展更多本地化逻辑
        
        elif tier == 'tier3':
            # 老/非/岛国: 强制国际组织网站
            if 'site:' not in query.lower() and task_type in ['data', 'economic', 'development']:
                query = f"{query} site:worldbank.org OR site:adb.org OR site:undp.org OR site:un.org"
        
        if query != original_query:
            logger.debug(f"查询优化: {original_query} -> {query}")
        
        return query
    
    def _search_web(self, query: str, num_results: int, tier: str, task_type: str) -> List[SearchResult]:
        """使用 DuckDuckGo 搜索网页"""
        results = []
        
        try:
            # 生成缓存键
            cache_key = f"ddg:{query}:{num_results}:{tier}"
            
            # 检查缓存
            if cache_key in self.cache:
                logger.debug(f"使用缓存: {query}")
                return self.cache[cache_key]
            
            # 执行搜索
            search_results = list(self.clients['ddg'].text(
                query,
                max_results=min(num_results * 2, 20),  # 限制最大数量
                safesearch='moderate'
            ))
            
            for item in search_results:
                # 基础筛选
                if not item.get('href') or not item.get('title'):
                    continue
                
                # 创建结果
                result = SearchResult(
                    url=item.get('href', ''),
                    title=item.get('title', '无标题'),
                    snippet=item.get('body', '')[:150],
                    source='duckduckgo',
                    relevance_score=self._calculate_relevance(query, item),
                    tier=tier,
                    metadata={
                        'domain': self._extract_domain(item.get('href', '')),
                        'search_engine': 'ddg',
                        'raw_content_length': len(item.get('body', '')),
                        'task_type': task_type
                    }
                )
                
                # 应用 Tier 过滤
                if self._passes_tier_filter(result, tier, task_type):
                    results.append(result)
                    if len(results) >= num_results:
                        break
            
            # 缓存结果
            self.cache[cache_key] = results
            
            logger.debug(f"网页搜索完成: {len(results)} 结果")
            
        except Exception as e:
            logger.error(f"网页搜索失败: {str(e)}")
        
        return results
    
    def _search_academic(self, query: str, num_results: int) -> List[SearchResult]:
        """搜索学术论文"""
        results = []
        
        try:
            search = arxiv.Search(
                query=query,
                max_results=num_results,
                sort_by=arxiv.SortCriterion.Relevance
            )
            
            for paper in self.clients['arxiv'].results(search):
                # 修复：确保创建 SearchResult 对象
                result = SearchResult(
                    url=paper.entry_id,
                    title=paper.title,
                    snippet=paper.summary[:200],
                    source='arxiv',
                    relevance_score=9.0,
                    tier='tier1',  # 学术资源默认 Tier 1
                    metadata={
                        'authors': [str(author) for author in paper.authors],
                        'published': str(paper.published),
                        'categories': paper.categories,
                        'pdf_url': paper.pdf_url,
                        'data_type': 'research_paper',
                        'search_engine': 'arxiv'
                    }
                )
                results.append(result)
                
            logger.debug(f"arXiv 搜索完成: {len(results)} 论文")
            
        except Exception as e:
            logger.error(f"学术搜索失败: {str(e)}")
        
        return results
    
    def _search_code(self, query: str, num_results: int) -> List[SearchResult]:
        """搜索代码相关资源"""
        results = []
        
        # 使用 DuckDuckGo 搜索代码相关网站
        code_query = f"{query} site:github.com OR site:gitlab.com OR site:stackoverflow.com"
        
        try:
            search_results = list(self.clients['ddg'].text(
                code_query,
                max_results=num_results,
                safesearch='moderate'
            ))
            
            for item in search_results:
                result = SearchResult(
                    url=item.get('href', ''),
                    title=item.get('title', ''),
                    snippet=item.get('body', '')[:150],
                    source='code_search',
                    relevance_score=self._calculate_relevance(query, item),
                    tier='tier1',  # 代码资源默认 Tier 1
                    metadata={
                        'domain': self._extract_domain(item.get('href', '')),
                        'search_engine': 'ddg',
                        'data_type': 'code_repository'
                    }
                )
                results.append(result)
                
            logger.debug(f"代码搜索完成: {len(results)} 结果")
            
        except Exception as e:
            logger.error(f"代码搜索失败: {str(e)}")
        
        return results
    
    def _calculate_relevance(self, query: str, item: Dict) -> float:
        """计算相关性分数"""
        score = 5.0  # 基础分
        
        title = item.get('title', '').lower()
        body = item.get('body', '').lower()
        query_lower = query.lower()
        
        # 标题匹配
        if any(term in title for term in query_lower.split()):
            score += 3.0
        
        # 内容匹配
        if any(term in body for term in query_lower.split()):
            score += 1.0
        
        # 域名可信度加分
        domain = self._extract_domain(item.get('href', ''))
        if any(ext in domain for ext in ['.edu', '.gov', '.ac.', '.org']):
            score += 2.0
        
        return min(score, 10.0)
    
    def _extract_domain(self, url: str) -> str:
        """提取域名"""
        try:
            parsed = urllib.parse.urlparse(url)
            return parsed.netloc.lower()
        except:
            return ""
    
    def _is_research_query(self, query: str, task_type: str) -> bool:
        """判断是否为研究类查询"""
        research_keywords = ['research', 'paper', 'study', 'academic', 'scholar', 'thesis']
        query_lower = query.lower()
        
        return (task_type in ['research', 'academic'] or
                any(keyword in query_lower for keyword in research_keywords))
    
    def _is_technical_query(self, query: str) -> bool:
        """判断是否为技术相关查询"""
        tech_keywords = [
            'github', 'git', 'code', 'api', 'sdk', 'library', 'framework',
            'python', 'java', 'javascript', 'cpp', 'rust', 'go',
            'docker', 'kubernetes', 'aws', 'azure', 'gcp'
        ]
        
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in tech_keywords)
    
    def _passes_tier_filter(self, result: SearchResult, tier: str, task_type: str) -> bool:
        """Tier 特定过滤"""
        domain = result.metadata.get('domain', '') if result.metadata else ''
        
        # 对所有 Tier 都不过滤太严格，先确保有结果
        # 未来可以根据需求添加更严格的过滤
        
        # 基础垃圾过滤
        spam_domains = ['ad.', 'click', 'banner', 'popup', 'ads.', 'track']
        if any(spam in domain for spam in spam_domains):
            return False
        
        return True
    
    def _deduplicate_and_sort(self, results: List[SearchResult]) -> List[SearchResult]:
        """去重和排序"""
        # URL 去重
        seen_urls = set()
        unique_results = []
        
        for result in results:
            if result.url and result.url not in seen_urls:
                seen_urls.add(result.url)
                unique_results.append(result)
        
        # 按相关性排序
        unique_results.sort(key=lambda x: x.relevance_score, reverse=True)
        
        return unique_results
    
    def clear_cache(self):
        """清除缓存"""
        self.cache.clear()
        logger.debug("搜索缓存已清除")
    
    def test_all_tiers(self) -> Dict[str, List[Dict[str, Any]]]:
        """测试所有 Tier 策略"""
        test_cases = [
            ("机器学习数据集", "us", "tier1", "data"),
            ("人工智能研究", "cn", "tier2", "research"),
            ("经济发展数据", "la", "tier3", "economic"),
            ("Python API", "jp", "tier1", "api"),
        ]
        
        results = {}
        
        for query, country, expected_tier, task_type in test_cases:
            print(f"\n🔍 测试: {query} [国家: {country}, Tier: {expected_tier}]")
            
            try:
                clues = self(query, num_results=2, 
                           country_code=country, 
                           task_type=task_type)
                
                results[f"{query}_{country}"] = clues
                
                if clues:
                    print(f"  找到 {len(clues)} 个结果:")
                    for i, clue in enumerate(clues, 1):
                        print(f"    {i}. [{clue.get('source')}] {clue.get('title', '')[:40]}...")
                else:
                    print("  没有找到结果")
                    
            except Exception as e:
                print(f"  搜索失败: {str(e)}")
        
        return results


# 兼容接口的工厂函数
def create_search_tool(
    engine: str = "ddg",
    api_key: str = None,
    max_results: int = 10,
    **kwargs
) -> ScoutWebSearchTool:
    """创建搜索工具实例"""
    config = {
        'engine': engine,
        'api_key': api_key,
        'max_results': max_results,
        **kwargs
    }
    return ScoutWebSearchTool(config)


# 全局实例
_global_search_tool = None

def get_global_search_tool(config: Dict[str, Any] = None) -> ScoutWebSearchTool:
    """获取全局搜索工具实例"""
    global _global_search_tool
    
    if _global_search_tool is None:
        config = config or {}
        _global_search_tool = create_search_tool(**config)
    
    return _global_search_tool


# WebSearchTool 别名保持兼容
WebSearchTool = ScoutWebSearchTool
'''

import os
import sys
import time
import requests
from typing import Dict, List, Any
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse
from loguru import logger

try:
    from agents.miner.memory.backends.redis_aux import _MISS, get_scout_search_cache
except ImportError:
    _MISS = object()
    get_scout_search_cache = lambda: None  # type: ignore

# 项目根路径处理
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.append(project_root)

# -----------------------------------------------------------------------------
# 依赖库动态加载
# -----------------------------------------------------------------------------
try:
    from tavily import TavilyClient
    HAS_TAVILY = True
except ImportError:
    HAS_TAVILY = False

try:
    from duckduckgo_search import DDGS
    HAS_DDG = True
except ImportError:
    HAS_DDG = False

try:
    import chromadb
    HAS_CHROMA = True
except ImportError:
    HAS_CHROMA = False

@dataclass
class SearchResult:
    """搜索结果标准对象"""
    url: str
    title: str = ""
    snippet: str = ""
    source: str = "unknown"
    relevance_score: float = 5.0
    tier: str = "tier1"
    metadata: Dict[str, Any] = None

    def to_clue_format(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet[:500],
            "source": self.source,
            "relevance_score": self.relevance_score,
            "tier": self.tier,
            "metadata": {
                "tier": self.tier,
                "search_time": datetime.now().isoformat(),
                **(self.metadata or {})
            }
        }

class ScoutWebSearchTool:
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.tavily_key = os.getenv("TAVILY_API_KEY") or "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"
        self.scrapingdog_key = os.getenv("SCRAPINGDOG_API_KEY") or "6940b6ae850c994adefd4780"
        
        self.clients = {}
        if HAS_TAVILY and self.tavily_key:
            try:
                self.clients['tavily'] = TavilyClient(api_key=self.tavily_key)
                logger.success("✅ Tavily Search API 已激活 (主引擎)")
            except Exception as e:
                logger.error(f"❌ Tavily 初始化失败: {e}")

    def __call__(self, query: str, num_results: int = 10, **kwargs) -> List[Dict[str, Any]]:
        """执行搜索。默认仅 Tavily API 真实返回，不混用 ScrapingDog/DDG 等。"""
        start_time = time.time()
        tavily_only = kwargs.get("tavily_only", True)
        if isinstance(tavily_only, str):
            tavily_only = tavily_only.lower() not in ("0", "false", "no")
        session_id = kwargs.get("session_id")

        scout_cache = get_scout_search_cache()
        if scout_cache and tavily_only:
            cached = scout_cache.get_search(query, num_results, tavily_only=tavily_only)
            if cached is not _MISS:
                logger.info(f"♻️ [Scout] Tavily 缓存命中: '{query}' ({len(cached)} 条)")
                for item in cached:
                    if isinstance(item, dict) and item.get("url") and session_id:
                        scout_cache.add_session_url(session_id, item["url"])
                return cached

        logger.info(f"🔎 [Scout] Tavily 搜索: '{query}'")

        if "tavily" not in self.clients:
            logger.error("❌ Tavily 未配置或初始化失败，Scout 不返回非 Tavily 结果")
            return []

        t_res = self._search_tavily(query, max_results=num_results)
        # 仅保留 Tavily 源
        t_res = [r for r in t_res if r.source == "tavily" and r.url]

        if tavily_only:
            final_clues = [r.to_clue_format() for r in t_res[:num_results]]
            if scout_cache:
                scout_cache.set_search(query, num_results, final_clues, tavily_only=tavily_only)
                if session_id:
                    for item in final_clues:
                        if item.get("url"):
                            scout_cache.add_session_url(session_id, item["url"])
            elapsed = time.time() - start_time
            logger.success(
                f"✅ Scout Tavily: 用时 {elapsed:.2f}s | 捕获线索: {len(final_clues)}"
            )
            return final_clues

        # 非 strict 模式（保留旧行为，需显式 tavily_only=False）
        results = list(t_res)
        if len(results) < num_results and self.scrapingdog_key:
            results.extend(self._search_scrapingdog(query, num_results=10))
        final_results = self._deduplicate_and_filter(results)
        final_clues = [r.to_clue_format() for r in final_results[:num_results]]
        elapsed = time.time() - start_time
        logger.success(f"✅ Scout 完成: 用时 {elapsed:.2f}s | 捕获线索: {len(final_clues)}")
        return final_clues

    def _identify_level_heuristic(self, url: str) -> str:
        """根据 URL 结构特征识别线索层级"""
        u = url.lower().rstrip('/')
        path = urlparse(u).path
        
        # L1/L2: 根域名或极短路径 (无虚拟目录)
        if not path or path in ["", "/"]:
            return "L1_L2"
        # L4: 物理资产 (直接指向文件)
        if any(u.endswith(ext) for ext in ['.pdf', '.csv', '.xlsx', '.json', '.zip']):
            return "L4"
        # L3: 含有专属数据库名称的路径
        db_keywords = ['dataset', 'database', 'record', 'genbank', 'archive', 'repository', 'projects']
        if any(kw in path for kw in db_keywords):
            return "L3"
        return "OTHER"

    def _deduplicate_and_filter(self, results: List[SearchResult]) -> List[SearchResult]:
        """按层级分桶采样，确保 L3/L4 发现率"""
        seen_urls = set()
        buckets = {"L3": [], "L4": [], "L1_L2": [], "OTHER": []}
        
        # 学术论文大户排除项 (噪声排除)
        junk_domains = [
            "nature.com", "sciencedirect.com", "arxiv.org", "ieeexplore.ieee.org",
            "researchgate.net", "frontiersin.org", "zhihu.com", "baidu.com"
        ]

        for r in results:
            if not r.url or r.url in seen_urls: continue
            if any(junk in r.url for junk in junk_domains): continue
            
            # 物理去重与层级入桶
            level = self._identify_level_heuristic(r.url)
            buckets[level].append(r)
            seen_urls.add(r.url)

        # 多样性轮询采样：按 L3 -> L4 -> L1_L2 顺序抓取
        final_list = []
        for key in buckets:
            buckets[key].sort(key=lambda x: x.relevance_score, reverse=True)
        
        idx = 0
        while len(final_list) < len(seen_urls):
            added = False
            for b_key in ["L3", "L4", "L1_L2", "OTHER"]:
                if idx < len(buckets[b_key]):
                    final_list.append(buckets[b_key][idx])
                    added = True
            if not added: break
            idx += 1
        
        logger.info(f"📊 发现层级分布: L3({len(buckets['L3'])}), L4({len(buckets['L4'])}), L1/L2({len(buckets['L1_L2'])})")
        return final_list

    def _search_tavily(self, query: str, max_results: int) -> List[SearchResult]:
        results = []
        try:
            response = self.clients['tavily'].search(
                query=query, search_depth="advanced", max_results=max_results,
                exclude_domains=["zhidao.baidu.com", "zhihu.com", "nature.com"]
            )
            for item in response.get('results', []):
                results.append(SearchResult(
                    url=item.get('url'), title=item.get('title'),
                    snippet=item.get('content'), source="tavily", relevance_score=9.8
                ))
        except Exception as e:
            logger.error(f"❌ Tavily 搜索异常: {e}")
        return results

    def _search_scrapingdog(self, query: str, num_results: int) -> List[SearchResult]:
        results = []
        endpoint = "https://api.scrapingdog.com/google_search"
        params = {"api_key": self.scrapingdog_key, "query": query, "results": num_results}
        try:
            resp = requests.get(endpoint, params=params, timeout=30)
            if resp.status_code == 200:
                for item in resp.json().get('organic_results', []):
                    results.append(SearchResult(
                        url=item.get('link'), title=item.get('title'),
                        snippet=item.get('snippet', ''), source="scrapingdog", relevance_score=9.0
                    ))
        except Exception as e:
            logger.error(f"❌ ScrapingDog 搜索异常: {e}")
        return results

# 兼容导出
ScoutWebSearchTool = ScoutWebSearchTool