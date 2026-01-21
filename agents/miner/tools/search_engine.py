# miner/tools/search_engine.py
"""
搜索引擎集成 - 支持多种搜索API
"""

import aiohttp
import asyncio
from typing import Dict, List, Optional
from loguru import logger
import json
import os
from urllib.parse import quote_plus

class SearchEngine:
    """搜索引擎集成器"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        
        # API配置 (从环境变量获取)
        self.google_api_key = os.getenv('GOOGLE_API_KEY')
        self.google_cx = os.getenv('GOOGLE_SEARCH_CX')
        self.bing_api_key = os.getenv('BING_API_KEY')
        
        # 搜索引擎端点
        self.endpoints = {
            'google': 'https://www.googleapis.com/customsearch/v1',
            'bing': 'https://api.bing.microsoft.com/v7.0/search',
            'duckduckgo': 'https://api.duckduckgo.com/'
        }
        
        # 生物医学专用搜索
        self.biomedical_sites = [
            'ncbi.nlm.nih.gov', 'ebi.ac.uk', 'ensembl.org', 'uniprot.org',
            'omim.org', 'clinvar.nlm.nih.gov', 'orphanet.org', 'disgenet.org'
        ]
    
    async def search(self, query: str, search_type: str = "general", 
                    max_results: int = 10, site_filter: str = None) -> List[Dict]:
        """执行搜索"""
        
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        results = []
        
        try:
            if search_type == "general":
                results = await self._search_general(query, max_results, site_filter)
            elif search_type == "biomedical":
                results = await self._search_biomedical(query, max_results)
            elif search_type == "dataset":
                results = await self._search_datasets(query, max_results)
            elif search_type == "academic":
                results = await self._search_academic(query, max_results)
            
            return self._deduplicate_results(results)
            
        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return []
    
    async def _search_general(self, query: str, max_results: int, site_filter: str = None) -> List[Dict]:
        """通用搜索"""
        results = []
        
        # 构建搜索查询
        search_query = query
        if site_filter:
            search_query += f" site:{site_filter}"
        
        # 尝试Google搜索
        if self.google_api_key and self.google_cx:
            google_results = await self._google_search(search_query, max_results)
            results.extend(google_results)
        
        # 如果Google结果不足，尝试Bing
        if len(results) < max_results and self.bing_api_key:
            remaining = max_results - len(results)
            bing_results = await self._bing_search(search_query, remaining)
            results.extend(bing_results)
        
        return results[:max_results]
    
    async def _search_biomedical(self, query: str, max_results: int) -> List[Dict]:
        """生物医学专用搜索"""
        results = []
        
        # 为每个生物医学站点搜索
        tasks = []
        for site in self.biomedical_sites[:5]:  # 限制并发数
            site_query = f"{query} site:{site}"
            tasks.append(self._search_general(site_query, 2))  # 每个站点2个结果
        
        site_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in site_results:
            if isinstance(result, list):
                results.extend(result)
        
        return results[:max_results]
    
    async def _search_datasets(self, query: str, max_results: int) -> List[Dict]:
        """数据集专用搜索"""
        
        # 增强查询词
        dataset_query = f"{query} (dataset OR database OR repository OR download OR export)"
        
        # 文件类型过滤
        filetype_queries = [
            f"{query} filetype:csv",
            f"{query} filetype:xlsx", 
            f"{query} filetype:json",
            f"{query} filetype:xml"
        ]
        
        results = []
        
        # 基础数据集搜索
        base_results = await self._search_general(dataset_query, max_results // 2)
        results.extend(base_results)
        
        # 文件类型搜索
        for ft_query in filetype_queries:
            if len(results) >= max_results:
                break
            ft_results = await self._search_general(ft_query, 2)
            results.extend(ft_results)
        
        return results[:max_results]
    
    async def _search_academic(self, query: str, max_results: int) -> List[Dict]:
        """学术搜索"""
        
        # 学术站点
        academic_sites = [
            'pubmed.ncbi.nlm.nih.gov',
            'scholar.google.com',
            'arxiv.org',
            'biorxiv.org',
            'medrxiv.org'
        ]
        
        results = []
        
        for site in academic_sites:
            if len(results) >= max_results:
                break
            
            site_query = f"{query} site:{site}"
            site_results = await self._search_general(site_query, 2)
            results.extend(site_results)
        
        return results[:max_results]
    
    async def _google_search(self, query: str, max_results: int) -> List[Dict]:
        """Google自定义搜索"""
        
        if not self.google_api_key or not self.google_cx:
            return []
        
        try:
            params = {
                'key': self.google_api_key,
                'cx': self.google_cx,
                'q': query,
                'num': min(max_results, 10)  # Google限制每次最多10个
            }
            
            async with self.session.get(self.endpoints['google'], params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_google_results(data)
                else:
                    logger.error(f"Google搜索失败: {response.status}")
                    return []
                    
        except Exception as e:
            logger.error(f"Google搜索异常: {e}")
            return []
    
    async def _bing_search(self, query: str, max_results: int) -> List[Dict]:
        """Bing搜索"""
        
        if not self.bing_api_key:
            return []
        
        try:
            headers = {'Ocp-Apim-Subscription-Key': self.bing_api_key}
            params = {
                'q': query,
                'count': min(max_results, 50),  # Bing限制
                'responseFilter': 'Webpages'
            }
            
            async with self.session.get(self.endpoints['bing'], 
                                      headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_bing_results(data)
                else:
                    logger.error(f"Bing搜索失败: {response.status}")
                    return []
                    
        except Exception as e:
            logger.error(f"Bing搜索异常: {e}")
            return []
    
    def _parse_google_results(self, data: Dict) -> List[Dict]:
        """解析Google搜索结果"""
        results = []
        
        for item in data.get('items', []):
            results.append({
                'title': item.get('title', ''),
                'url': item.get('link', ''),
                'snippet': item.get('snippet', ''),
                'source': 'google'
            })
        
        return results
    
    def _parse_bing_results(self, data: Dict) -> List[Dict]:
        """解析Bing搜索结果"""
        results = []
        
        webpages = data.get('webPages', {})
        for item in webpages.get('value', []):
            results.append({
                'title': item.get('name', ''),
                'url': item.get('url', ''),
                'snippet': item.get('snippet', ''),
                'source': 'bing'
            })
        
        return results
    
    def _deduplicate_results(self, results: List[Dict]) -> List[Dict]:
        """去重搜索结果"""
        seen_urls = set()
        unique_results = []
        
        for result in results:
            url = result.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(result)
        
        return unique_results
    
    async def search_for_l3_datasets(self, l2_url: str, keywords: List[str]) -> List[Dict]:
        """为L2站点搜索L3数据集"""
        
        from urllib.parse import urlparse
        domain = urlparse(l2_url).netloc
        
        results = []
        
        for keyword in keywords:
            # 构建针对性搜索查询
            queries = [
                f"{keyword} site:{domain} (download OR export OR dataset)",
                f"{keyword} site:{domain} filetype:csv",
                f"{keyword} site:{domain} filetype:xlsx",
                f"{keyword} site:{domain} (bulk OR api)"
            ]
            
            for query in queries:
                if len(results) >= 20:  # 限制结果数量
                    break
                
                search_results = await self.search(query, "general", 3)
                results.extend(search_results)
        
        return self._deduplicate_results(results)
    
    async def close(self):
        """关闭会话"""
        if self.session:
            await self.session.close()
