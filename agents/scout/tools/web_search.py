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

"""
广域侦察兵搜索工具 - 官方 API 版（Google, GitHub, ArXiv + DDG fallback）
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
from loguru import logger

# 项目根路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.append(project_root)

# 搜索引擎客户端
# 1. DuckDuckGo (fallback)
try:
    from ddgs import DDGS
    HAS_DDG = True
except ImportError:
    HAS_DDG = False
    logger.warning("ddgs 未安装，DuckDuckGo fallback 不可用")

# 2. Google Custom Search JSON API
try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False
    logger.warning("google-api-python-client 未安装，Google Search API 不可用")

# 3. GitHub API
try:
    from github import Github, GithubException
    HAS_GITHUB = True
except ImportError:
    HAS_GITHUB = False
    logger.warning("PyGithub 未安装，GitHub API 不可用")

# 4. arXiv API
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
            "snippet": self.snippet[:300],
            "source": self.source,
            "relevance_score": self.relevance_score,
            "tier": self.tier,
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
    广域侦察兵搜索工具 - 支持 Google, GitHub, ArXiv API + DDG fallback
    """
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        
        # API 配置（环境变量优先）
        self.google_api_key = os.getenv("GOOGLE_API_KEY") or self.config.get("google_api_key")
        self.google_cx = os.getenv("GOOGLE_CX") or self.config.get("google_cx")
        self.github_token = os.getenv("GITHUB_TOKEN") or self.config.get("github_token")
        
        self.max_results = self.config.get("max_results", 10)
        self.enable_cache = self.config.get("enable_cache", True)
        self.enable_ddg_fallback = self.config.get("enable_ddg_fallback", True)

        # 初始化客户端
        self.clients = {}

        # Google Custom Search
        if HAS_GOOGLE and self.google_api_key and self.google_cx:
            try:
                self.clients['google'] = build("customsearch", "v1", developerKey=self.google_api_key)
                logger.info("Google Custom Search API 已初始化")
            except Exception as e:
                logger.error(f"Google API 初始化失败: {str(e)}")

        # GitHub
        if HAS_GITHUB:
            try:
                if self.github_token:
                    self.clients['github'] = Github(self.github_token)
                    logger.info("GitHub API 已使用 token 初始化")
                else:
                    self.clients['github'] = Github()  # 匿名模式（限速）
                    logger.info("GitHub API 已匿名初始化（限速）")
            except Exception as e:
                logger.error(f"GitHub API 初始化失败: {str(e)}")

        # arXiv
        if HAS_ARXIV:
            self.clients['arxiv'] = arxiv.Client()
            logger.info("arXiv API 已初始化")

        # DDG fallback
        if HAS_DDG and self.enable_ddg_fallback:
            self.clients['ddg'] = DDGS()
            logger.info("DuckDuckGo fallback 已启用")

        # 缓存
        self.cache = {}

        # Tier 分类（不变）
        self.tier_classification = {
            'tier1': ['us', 'de', 'jp', 'uk', 'fr', 'ca', 'au', 'kr', 'sg', 'tw'],
            'tier2': ['vn', 'sa', 'ru', 'cn', 'in', 'br', 'mx', 'id', 'th', 'my'],
            'tier3': ['la', 'kh', 'mm', 'ke', 'ng', 'gh', 'et', 'tz', 'ug', 'zm', 'fj', 'vu', 'ws', 'to', 'sb']
        }

        logger.info(f"广域侦察兵搜索工具初始化完成，优先引擎: {list(self.clients.keys())}")

    def __call__(self, query: str, num_results: int = 10, **kwargs) -> List[Dict[str, Any]]:
        start_time = time.time()
        country_code = kwargs.get('country_code', 'us').lower()
        task_type = kwargs.get('task_type', 'general')
        tier = self._get_tier_by_country(country_code)

        logger.info(f"执行搜索: {query} | 国家: {country_code} | Tier: {tier} | 任务: {task_type}")

        optimized_query = self._apply_tier_strategy(query, tier, task_type)

        results = []

        # 优先级顺序：Google > GitHub > ArXiv > DDG fallback
        # 1. Google Custom Search API
        if 'google' in self.clients:
            google_results = self._search_google(query, num_results, tier)
            results.extend(google_results)

        # 2. GitHub API（技术/代码相关查询）
        if 'github' in self.clients and self._is_technical_query(query):
            github_results = self._search_github(query, num_results // 3)
            results.extend(github_results)

        # 3. ArXiv API（学术/论文相关查询）
        if 'arxiv' in self.clients and self._is_research_query(query, task_type):
            arxiv_results = self._search_arxiv(query, num_results // 3)
            results.extend(arxiv_results)

        # 4. DDG fallback（如果结果不足）
        if len(results) < num_results and 'ddg' in self.clients:
            ddg_results = self._search_ddg(query, num_results - len(results), tier, task_type)
            results.extend(ddg_results)

        # 去重和排序
        final_results = self._deduplicate_and_sort(results)[:num_results]

        # 转换为 Clue 格式
        clues = [r.to_clue_format() for r in final_results]

        elapsed = time.time() - start_time
        logger.info(f"搜索完成，用时 {elapsed:.2f}s，找到 {len(clues)} 个线索")

        return clues

    # Google Custom Search
    def _search_google(self, query: str, num_results: int, tier: str) -> List[SearchResult]:
        results = []
        try:
            request = self.clients['google'].cse().list(
                q=query,
                cx=self.google_cx,
                num=min(num_results, 10)
            )
            response = request.execute()
            items = response.get("items", [])
            for idx, item in enumerate(items, 1):
                result = SearchResult(
                    url=item.get("link", ""),
                    title=item.get("title", "无标题"),
                    snippet=item.get("snippet", ""),
                    source="google_search",
                    relevance_score=8.0 + (10 - idx) * 0.5,  # 排名越高分数越高
                    tier=tier,
                    metadata={
                        'engine': 'google',
                        'position': idx,
                        'display_link': item.get("displayLink", "")
                    }
                )
                results.append(result)
        except HttpError as e:
            logger.error(f"Google Search API 错误: {str(e)}")
        return results

    # GitHub API
    def _search_github(self, query: str, num_results: int) -> List[SearchResult]:
        results = []
        try:
            repos = self.clients['github'].search_repositories(query=query, sort="stars", order="desc")
            for repo in repos[:num_results]:
                result = SearchResult(
                    url=repo.html_url,
                    title=repo.full_name,
                    snippet=repo.description or "无描述",
                    source="github",
                    relevance_score=min(10.0, 5.0 + repo.stargazers_count / 1000),
                    tier="tier1",  # GitHub 资源通常高质量
                    metadata={
                        'engine': 'github',
                        'stars': repo.stargazers_count,
                        'forks': repo.forks_count,
                        'language': repo.language,
                        'updated_at': str(repo.updated_at)
                    }
                )
                results.append(result)
        except GithubException as e:
            logger.error(f"GitHub API 错误: {str(e)}")
        return results

    # ArXiv API
    def _search_arxiv(self, query: str, num_results: int) -> List[SearchResult]:
        results = []
        try:
            search = arxiv.Search(
                query=query,
                max_results=num_results,
                sort_by=arxiv.SortCriterion.Relevance
            )
            for paper in self.clients['arxiv'].results(search):
                result = SearchResult(
                    url=paper.entry_id,
                    title=paper.title,
                    snippet=paper.summary[:200],
                    source="arxiv",
                    relevance_score=9.0,
                    tier="tier1",
                    metadata={
                        'engine': 'arxiv',
                        'authors': [str(author) for author in paper.authors],
                        'published': str(paper.published),
                        'pdf_url': paper.pdf_url,
                        'categories': paper.categories
                    }
                )
                results.append(result)
        except Exception as e:
            logger.error(f"arXiv API 错误: {str(e)}")
        return results

    # DDG fallback
    def _search_ddg(self, query: str, num_results: int, tier: str, task_type: str) -> List[SearchResult]:
        results = []
        try:
            cache_key = f"ddg:{query}:{num_results}:{tier}"
            if self.enable_cache and cache_key in self.cache:
                return self.cache[cache_key]

            search_results = list(self.clients['ddg'].text(
                query,
                max_results=min(num_results * 2, 20),
                safesearch='moderate'
            ))

            for item in search_results:
                if not item.get('href') or not item.get('title'):
                    continue
                result = SearchResult(
                    url=item.get('href', ''),
                    title=item.get('title', '无标题'),
                    snippet=item.get('body', '')[:150],
                    source='duckduckgo',
                    relevance_score=self._calculate_relevance(query, item),
                    tier=tier,
                    metadata={
                        'engine': 'duckduckgo',
                        'domain': self._extract_domain(item.get('href', '')),
                        'raw_content_length': len(item.get('body', ''))
                    }
                )
                if self._passes_tier_filter(result, tier, task_type):
                    results.append(result)
                if len(results) >= num_results:
                    break

            if self.enable_cache:
                self.cache[cache_key] = results
        except Exception as e:
            logger.error(f"DDG fallback 失败: {str(e)}")
        return results

    # 其他方法保持不变
    def _get_tier_by_country(self, country_code: str) -> str:
        for tier, countries in self.tier_classification.items():
            if country_code in countries:
                return tier
        return 'tier1'

    def _apply_tier_strategy(self, query: str, tier: str, task_type: str) -> str:
        original_query = query
        if tier == 'tier1':
            if task_type in ['data', 'api', 'documentation']:
                if 'filetype:' not in query.lower():
                    query = f"{query} (filetype:json OR filetype:csv OR filetype:xml)"
                query = f"{query} site:data.gov OR site:api.gov OR site:github.io"
        elif tier == 'tier2':
            # 多语言支持（可扩展）
            pass
        elif tier == 'tier3':
            if 'site:' not in query.lower() and task_type in ['data', 'economic', 'development']:
                query = f"{query} site:worldbank.org OR site:adb.org OR site:undp.org OR site:un.org"
        if query != original_query:
            logger.debug(f"查询优化: {original_query} → {query}")
        return query

    def _calculate_relevance(self, query: str, item: Dict) -> float:
        score = 5.0
        title = item.get('title', '').lower()
        body = item.get('body', item.get('snippet', '')).lower()
        query_lower = query.lower()
        for term in query_lower.split():
            if term in title:
                score += 3.0
            if term in body:
                score += 1.0
        domain = self._extract_domain(item.get('href', item.get('link', '')))
        if any(ext in domain for ext in ['.edu', '.gov', '.org', '.ac.']):
            score += 2.0
        return min(score, 10.0)

    def _extract_domain(self, url: str) -> str:
        try:
            parsed = urllib.parse.urlparse(url)
            return parsed.netloc.lower()
        except:
            return ""

    def _is_research_query(self, query: str, task_type: str) -> bool:
        research_keywords = ['research', 'paper', 'study', 'academic', 'scholar', 'thesis', 'arxiv']
        query_lower = query.lower()
        return task_type in ['research', 'academic'] or any(kw in query_lower for kw in research_keywords)

    def _is_technical_query(self, query: str) -> bool:
        tech_keywords = ['github', 'git', 'code', 'api', 'sdk', 'library', 'framework', 'python', 'java']
        query_lower = query.lower()
        return any(kw in query_lower for kw in tech_keywords)

    def _passes_tier_filter(self, result: SearchResult, tier: str, task_type: str) -> bool:
        domain = result.metadata.get('domain', '') if result.metadata else ''
        spam_domains = ['ad.', 'click', 'banner', 'popup', 'ads.', 'track']
        if any(spam in domain for spam in spam_domains):
            return False
        return True

    def _deduplicate_and_sort(self, results: List[SearchResult]) -> List[SearchResult]:
        seen_urls = set()
        unique_results = []
        for result in results:
            if result.url and result.url not in seen_urls:
                seen_urls.add(result.url)
                unique_results.append(result)
        unique_results.sort(key=lambda x: x.relevance_score, reverse=True)
        return unique_results

    def clear_cache(self):
        self.cache.clear()
        logger.debug("搜索缓存已清除")

# 兼容接口
def create_search_tool(engine: str = "ddg", api_key: str = None, **kwargs) -> ScoutWebSearchTool:
    config = {
        'engine': engine,
        'api_key': api_key,
        **kwargs
    }
    return ScoutWebSearchTool(config)

WebSearchTool = ScoutWebSearchTool