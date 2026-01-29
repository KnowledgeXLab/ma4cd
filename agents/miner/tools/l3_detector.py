# miner/tools/l3_detector.py
"""
L3数据集检测器 - 使用启发式规则判断是否为L3数据集
"""

import aiohttp
import re
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
from loguru import logger
from urllib.parse import urljoin, urlparse

class L3DatasetDetector:
    """L3数据集检测器"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        
        # 下载指示器
        self.download_indicators = [
            "download", "export", "save as", "get data", "download dataset", 
            "export data", "bulk download", "download file", "download link",
            "download now", "free download", "download here"
        ]
        
        # 文件格式指示器
        self.file_indicators = [
            ".csv", ".xlsx", ".xls", ".tsv", ".json", ".xml", ".zip", 
            ".tar.gz", ".rar", ".7z", ".fasta", ".fastq", ".bam", 
            ".vcf", ".bed", ".gff", ".gtf", ".sam", ".cram"
        ]
        
        # UI元素指示器
        self.ui_indicators = [
            "download button", "export button", "data access", "file download",
            "bulk export", "api endpoint", "download icon", "save icon"
        ]
        
        # 数据库特征词
        self.database_keywords = [
            "database", "repository", "archive", "collection", "catalog",
            "registry", "portal", "platform", "resource", "service",
            "dataset", "data", "records", "entries", "samples"
        ]
        
        # 生物医学特征词
        self.biomedical_keywords = [
            "genome", "genomic", "genetic", "gene", "dna", "rna", "protein",
            "sequence", "mutation", "variant", "clinical", "patient", "disease",
            "rare disease", "disorder", "phenotype", "genotype"
        ]
    
    async def detect_l3_dataset(self, url: str) -> Dict:
        """检测是否为L3数据集"""
        
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        try:
            async with self.session.get(url, timeout=15) as response:
                if response.status >= 400:
                    return {
                        "url": url,
                        "is_l3": False,
                        "confidence": 0.0,
                        "error": f"HTTP {response.status}"
                    }
                
                content = await response.text()
                soup = BeautifulSoup(content, 'html.parser')
                
                return await self._analyze_content(url, content, soup)
                
        except Exception as e:
            logger.error(f"L3检测失败 {url}: {e}")
            return {
                "url": url,
                "is_l3": False,
                "confidence": 0.0,
                "error": str(e)
            }
    
    async def _analyze_content(self, url: str, content: str, soup: BeautifulSoup) -> Dict:
        """分析页面内容"""
        
        score = 0
        evidence = []
        details = {}
        
        # 1. 检查下载指示器 (权重: 3)
        download_score = self._check_download_indicators(content, soup)
        score += download_score * 3
        if download_score > 0:
            evidence.append("has_download_links")
            details["download_links"] = self._extract_download_links(soup)
        
        # 2. 检查文件格式指示器 (权重: 2)
        file_score = self._check_file_indicators(content, url)
        score += file_score * 2
        if file_score > 0:
            evidence.append("has_data_files")
            details["file_formats"] = self._extract_file_formats(content)
        
        # 3. 检查数据库特征 (权重: 2)
        db_score = self._check_database_features(content, soup)
        score += db_score * 2
        if db_score > 0:
            evidence.append("has_database_features")
        
        # 4. 检查生物医学相关性 (权重: 1)
        bio_score = self._check_biomedical_relevance(content)
        score += bio_score * 1
        if bio_score > 0:
            evidence.append("biomedical_relevant")
        
        # 5. 检查表格数据 (权重: 2)
        table_score = self._check_table_data(soup)
        score += table_score * 2
        if table_score > 0:
            evidence.append("has_tabular_data")
            details["table_count"] = len(soup.find_all('table'))
        
        # 6. 检查API端点 (权重: 1)
        api_score = self._check_api_endpoints(content, soup)
        score += api_score * 1
        if api_score > 0:
            evidence.append("has_api_access")
        
        # 计算最终置信度
        max_possible_score = 11  # 3+2+2+1+2+1
        confidence = min(score / max_possible_score, 1.0)
        
        # 判断阈值
        is_l3 = confidence >= 0.3  # 可调整阈值
        
        return {
            "url": url,
            "is_l3": is_l3,
            "confidence": round(confidence, 3),
            "evidence": evidence,
            "score_breakdown": {
                "download_indicators": download_score,
                "file_indicators": file_score,
                "database_features": db_score,
                "biomedical_relevance": bio_score,
                "table_data": table_score,
                "api_endpoints": api_score,
                "total_score": score,
                "max_score": max_possible_score
            },
            "details": details
        }
    
    def _check_download_indicators(self, content: str, soup: BeautifulSoup) -> float:
        """检查下载指示器"""
        content_lower = content.lower()
        score = 0
        
        # 检查文本中的下载词汇
        for indicator in self.download_indicators:
            if indicator in content_lower:
                score += 0.1
        
        # 检查下载链接
        download_links = soup.find_all('a', href=True)
        for link in download_links:
            href = link.get('href', '').lower()
            text = link.get_text().lower()
            
            if any(indicator in href or indicator in text for indicator in self.download_indicators):
                score += 0.2
        
        return min(score, 1.0)
    
    def _check_file_indicators(self, content: str, url: str) -> float:
        """检查文件格式指示器"""
        content_lower = content.lower()
        url_lower = url.lower()
        score = 0
        
        # 检查内容中的文件格式
        for indicator in self.file_indicators:
            if indicator in content_lower:
                score += 0.15
            if indicator in url_lower:
                score += 0.1
        
        return min(score, 1.0)
    
    def _check_database_features(self, content: str, soup: BeautifulSoup) -> float:
        """检查数据库特征"""
        content_lower = content.lower()
        score = 0
        
        # 检查数据库关键词
        for keyword in self.database_keywords:
            if keyword in content_lower:
                score += 0.1
        
        # 检查页面标题
        title = soup.find('title')
        if title:
            title_text = title.get_text().lower()
            for keyword in self.database_keywords:
                if keyword in title_text:
                    score += 0.2
        
        return min(score, 1.0)
    
    def _check_biomedical_relevance(self, content: str) -> float:
        """检查生物医学相关性"""
        content_lower = content.lower()
        score = 0
        
        for keyword in self.biomedical_keywords:
            if keyword in content_lower:
                score += 0.1
        
        return min(score, 1.0)
    
    def _check_table_data(self, soup: BeautifulSoup) -> float:
        """检查表格数据"""
        tables = soup.find_all('table')
        
        if not tables:
            return 0
        
        # 根据表格数量和复杂度评分
        score = min(len(tables) * 0.2, 0.8)
        
        # 检查表格是否包含数据特征
        for table in tables[:3]:  # 只检查前3个表格
            rows = table.find_all('tr')
            if len(rows) > 5:  # 有足够多的行
                score += 0.1
            
            # 检查是否有数字数据
            table_text = table.get_text()
            if re.search(r'\d+\.\d+|\d+%|\d+,\d+', table_text):
                score += 0.1
        
        return min(score, 1.0)
    
    def _check_api_endpoints(self, content: str, soup: BeautifulSoup) -> float:
        """检查API端点"""
        content_lower = content.lower()
        score = 0
        
        api_indicators = ['api', 'rest', 'endpoint', 'json', 'xml', 'web service']
        
        for indicator in api_indicators:
            if indicator in content_lower:
                score += 0.15
        
        # 检查代码块中的API示例
        code_blocks = soup.find_all(['code', 'pre'])
        for block in code_blocks:
            block_text = block.get_text().lower()
            if 'http' in block_text and ('api' in block_text or 'json' in block_text):
                score += 0.2
        
        return min(score, 1.0)
    
    def _extract_download_links(self, soup: BeautifulSoup) -> List[str]:
        """提取下载链接"""
        download_links = []
        
        links = soup.find_all('a', href=True)
        for link in links:
            href = link.get('href', '')
            text = link.get_text().lower()
            
            if any(indicator in text for indicator in self.download_indicators):
                download_links.append(href)
            elif any(ext in href.lower() for ext in self.file_indicators):
                download_links.append(href)
        
        return download_links[:10]  # 最多返回10个
    
    def _extract_file_formats(self, content: str) -> List[str]:
        """提取文件格式"""
        formats = []
        content_upper = content.upper()
        
        format_patterns = [
            'CSV', 'TSV', 'XLSX', 'XLS', 'JSON', 'XML', 'ZIP',
            'FASTA', 'FASTQ', 'BAM', 'VCF', 'BED', 'GFF', 'GTF'
        ]
        
        for fmt in format_patterns:
            if fmt in content_upper:
                formats.append(fmt)
        
        return list(set(formats))  # 去重
    
    async def close(self):
        """关闭会话"""
        if self.session:
            await self.session.close()
