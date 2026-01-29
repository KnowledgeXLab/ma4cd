# miner/tools/url_classifier.py
"""
URL分级器 - 将URL分类为L1/L2/L3/L4层级
"""

import aiohttp
import re
from bs4 import BeautifulSoup
from typing import Dict, Optional
from loguru import logger
from urllib.parse import urlparse, urljoin

class URLClassifier:
    """URL层级分类器"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        
        # L1 门户特征 - 顶级机构和组织
        self.l1_patterns = [
            # 国际组织
            r'who\.int', r'nih\.gov', r'ebi\.ac\.uk', r'ncbi\.nlm\.nih\.gov',
            r'ensembl\.org', r'uniprot\.org', r'embl\.de', r'rcsb\.org',
            # 大型研究机构
            r'broadinstitute\.org', r'wellcome\.ac\.uk', r'sanger\.ac\.uk',
            # 政府机构
            r'\.gov$', r'\.gov\.', r'europa\.eu', r'ec\.europa\.eu'
        ]
        
        # L2 数据库门户特征
        self.l2_indicators = [
            'database', 'repository', 'archive', 'portal', 'platform',
            'resource', 'service', 'registry', 'catalog', 'collection',
            'browse', 'search', 'query', 'explore'
        ]
        
        # L3 数据集特征
        self.l3_indicators = [
            'download', 'export', 'dataset', 'data', 'file', 'bulk',
            'csv', 'xlsx', 'json', 'xml', 'fasta', 'fastq', 'vcf'
        ]
        
        # L4 记录特征
        self.l4_indicators = [
            'record', 'entry', 'sample', 'specimen', 'patient', 'case',
            'individual', 'subject', 'accession', 'id:', 'identifier'
        ]
        
        # 生物医学领域特征
        self.biomedical_domains = [
            'ebi.ac.uk', 'ncbi.nlm.nih.gov', 'ensembl.org', 'uniprot.org',
            'omim.org', 'clinvar.nlm.nih.gov', 'pharmgkb.org', 'reactome.org',
            'string-db.org', 'disgenet.org', 'orphanet.org'
        ]
    
    async def classify_url(self, url: str) -> Dict:
        """分类单个URL"""
        
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        try:
            # 1. 基于URL结构的初步分类
            url_analysis = self._analyze_url_structure(url)
            
            # 2. 获取页面内容进行深度分析
            content_analysis = await self._analyze_page_content(url)
            
            # 3. 综合判断
            final_classification = self._make_final_classification(
                url, url_analysis, content_analysis
            )
            
            return final_classification
            
        except Exception as e:
            logger.error(f"URL分类失败 {url}: {e}")
            return {
                "url": url,
                "tier": "unknown",
                "confidence": 0.0,
                "error": str(e)
            }
    
    def _analyze_url_structure(self, url: str) -> Dict:
        """基于URL结构分析"""
        
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        path = parsed.path.lower()
        
        analysis = {
            "domain": domain,
            "path": path,
            "is_biomedical_domain": any(bd in domain for bd in self.biomedical_domains),
            "url_indicators": {}
        }
        
        # 检查L1特征
        l1_score = 0
        for pattern in self.l1_patterns:
            if re.search(pattern, domain):
                l1_score += 1
        analysis["url_indicators"]["l1_score"] = l1_score
        
        # 检查路径特征
        path_features = {
            "has_browse": 'browse' in path,
            "has_search": 'search' in path,
            "has_download": 'download' in path,
            "has_record_id": bool(re.search(r'/[A-Z0-9]{6,}', path)),
            "depth": len([p for p in path.split('/') if p])
        }
        analysis["path_features"] = path_features
        
        return analysis
    
    async def _analyze_page_content(self, url: str) -> Dict:
        """分析页面内容"""
        
        try:
            async with self.session.get(url, timeout=10) as response:
                if response.status >= 400:
                    return {"error": f"HTTP {response.status}"}
                
                content = await response.text()
                soup = BeautifulSoup(content, 'html.parser')
                
                return {
                    "title": self._extract_title(soup),
                    "content_indicators": self._analyze_content_indicators(content),
                    "navigation_structure": self._analyze_navigation(soup),
                    "data_access_methods": self._analyze_data_access(soup),
                    "page_complexity": self._analyze_page_complexity(soup)
                }
                
        except Exception as e:
            return {"error": str(e)}
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """提取页面标题"""
        title_tag = soup.find('title')
        return title_tag.get_text().strip() if title_tag else ""
    
    def _analyze_content_indicators(self, content: str) -> Dict:
        """分析内容指标"""
        content_lower = content.lower()
        
        return {
            "l1_indicators": sum(1 for ind in ['organization', 'institution', 'consortium', 'initiative'] 
                               if ind in content_lower),
            "l2_indicators": sum(1 for ind in self.l2_indicators if ind in content_lower),
            "l3_indicators": sum(1 for ind in self.l3_indicators if ind in content_lower),
            "l4_indicators": sum(1 for ind in self.l4_indicators if ind in content_lower),
            "biomedical_terms": sum(1 for term in ['genome', 'gene', 'protein', 'disease', 'clinical'] 
                                  if term in content_lower)
        }
    
    def _analyze_navigation(self, soup: BeautifulSoup) -> Dict:
        """分析导航结构"""
        
        # 查找导航元素
        nav_elements = soup.find_all(['nav', 'ul', 'ol'])
        menu_items = []
        
        for nav in nav_elements:
            links = nav.find_all('a')
            for link in links:
                text = link.get_text().strip().lower()
                if text:
                    menu_items.append(text)
        
        return {
            "has_browse_menu": any('browse' in item for item in menu_items),
            "has_search_menu": any('search' in item for item in menu_items),
            "has_download_menu": any('download' in item for item in menu_items),
            "has_help_menu": any('help' in item or 'documentation' in item for item in menu_items),
            "menu_complexity": len(set(menu_items))
        }
    
    def _analyze_data_access(self, soup: BeautifulSoup) -> Dict:
        """分析数据访问方式"""
        
        # 查找表单
        forms = soup.find_all('form')
        search_forms = len([f for f in forms if 'search' in str(f).lower()])
        
        # 查找下载链接
        download_links = len([a for a in soup.find_all('a', href=True) 
                            if 'download' in a.get('href', '').lower() or 
                               'download' in a.get_text().lower()])
        
        # 查找API文档
        api_mentions = len(re.findall(r'\bapi\b', soup.get_text().lower()))
        
        return {
            "search_forms": search_forms,
            "download_links": download_links,
            "api_mentions": api_mentions,
            "has_bulk_access": 'bulk' in soup.get_text().lower()
        }
    
    def _analyze_page_complexity(self, soup: BeautifulSoup) -> Dict:
        """分析页面复杂度"""
        
        return {
            "total_links": len(soup.find_all('a')),
            "total_forms": len(soup.find_all('form')),
            "total_tables": len(soup.find_all('table')),
            "content_length": len(soup.get_text()),
            "has_javascript": bool(soup.find_all('script'))
        }
    
    def _make_final_classification(self, url: str, url_analysis: Dict, content_analysis: Dict) -> Dict:
        """综合判断最终分类"""
        
        scores = {"L1": 0, "L2": 0, "L3": 0, "L4": 0}
        evidence = []
        
        # URL结构评分
        if url_analysis["url_indicators"]["l1_score"] > 0:
            scores["L1"] += 3
            evidence.append("l1_domain_pattern")
        
        if url_analysis["is_biomedical_domain"]:
            scores["L1"] += 1
            scores["L2"] += 1
            evidence.append("biomedical_domain")
        
        # 路径特征评分
        path_features = url_analysis.get("path_features", {})
        if path_features.get("has_browse"):
            scores["L2"] += 2
        if path_features.get("has_download"):
            scores["L3"] += 2
        if path_features.get("has_record_id"):
            scores["L4"] += 3
        
        # 内容指标评分
        if "error" not in content_analysis:
            content_indicators = content_analysis.get("content_indicators", {})
            
            scores["L1"] += content_indicators.get("l1_indicators", 0)
            scores["L2"] += content_indicators.get("l2_indicators", 0) * 0.5
            scores["L3"] += content_indicators.get("l3_indicators", 0) * 0.5
            scores["L4"] += content_indicators.get("l4_indicators", 0) * 0.5
            
            # 导航结构评分
            nav_structure = content_analysis.get("navigation_structure", {})
            if nav_structure.get("has_browse_menu"):
                scores["L2"] += 1
            if nav_structure.get("has_download_menu"):
                scores["L3"] += 1
            
            # 数据访问方式评分
            data_access = content_analysis.get("data_access_methods", {})
            if data_access.get("search_forms", 0) > 0:
                scores["L2"] += 1
            if data_access.get("download_links", 0) > 0:
                scores["L3"] += 1
            if data_access.get("api_mentions", 0) > 0:
                scores["L2"] += 0.5
        
        # 确定最终层级
        max_score = max(scores.values())
        if max_score == 0:
            tier = "unknown"
            confidence = 0.0
        else:
            tier = max(scores.keys(), key=lambda k: scores[k])
            confidence = min(max_score / 5.0, 1.0)  # 标准化到0-1
        
        return {
            "url": url,
            "tier": tier,
            "confidence": round(confidence, 3),
            "scores": scores,
            "evidence": evidence,
            "analysis": {
                "url_structure": url_analysis,
                "content_analysis": content_analysis
            }
        }
    
    async def close(self):
        """关闭会话"""
        if self.session:
            await self.session.close()
