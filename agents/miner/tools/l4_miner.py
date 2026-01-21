# miner/tools/l4_miner.py
"""
L4记录挖掘器 - 从L3数据集挖掘具体记录
"""

import aiohttp
import asyncio
import re
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
from loguru import logger
from urllib.parse import urljoin, urlparse, parse_qs
import json
import csv
import io

class L4RecordMiner:
    """L4记录挖掘器"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        
        # L4记录特征模式
        self.record_patterns = [
            r'\b[A-Z]{2,}\d{6,}\b',  # 通用登录号模式 (如 GSM123456)
            r'\b[A-Z]+\d{4,}\b',     # 简化登录号 (如 SRR1234)
            r'\bENS[A-Z]*\d+\b',     # Ensembl ID
            r'\brs\d+\b',            # SNP ID
            r'\b[A-Z]{1,2}_\d+\b',   # RefSeq ID
            r'\bGO:\d+\b',           # Gene Ontology
            r'\bHP:\d+\b',           # Human Phenotype Ontology
        ]
        
        # 数据库类型识别
        self.database_types = {
            'ncbi': {
                'patterns': [r'ncbi\.nlm\.nih\.gov', r'pubmed', r'genbank'],
                'record_patterns': [r'[A-Z]{1,2}\d{6,}', r'rs\d+', r'[A-Z]{2,}\d{6,}']
            },
            'ebi': {
                'patterns': [r'ebi\.ac\.uk', r'ensembl', r'uniprot'],
                'record_patterns': [r'ENS[A-Z]*\d+', r'[A-Z]\d[A-Z0-9]{3}\d', r'[A-Z]{1,2}_\d+']
            },
            'omim': {
                'patterns': [r'omim\.org'],
                'record_patterns': [r'#\d{6}', r'\*\d{6}', r'%\d{6}']
            },
            'clinvar': {
                'patterns': [r'clinvar'],
                'record_patterns': [r'VCV\d+', r'RCV\d+', r'SCV\d+']
            }
        }
        
        # 页面结构类型
        self.structure_indicators = {
            'database_portal': ['search', 'browse', 'query', 'database'],
            'file_listing': ['directory', 'files', 'download', 'ftp'],
            'api_endpoint': ['api', 'rest', 'json', 'xml', 'endpoint'],
            'download_page': ['download', 'export', 'save', 'bulk']
        }
    
    async def mine_l4_records(self, l3_url: str, l3_metadata: Dict = None) -> Dict:
        """从L3数据集挖掘L4记录"""
        
        logger.info(f"🔍 开始挖掘L4记录: {l3_url}")
        
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        try:
            # 1. 分析L3页面结构
            page_structure = await self._analyze_l3_structure(l3_url)
            
            # 2. 根据结构类型选择挖掘策略
            structure_type = page_structure.get('type', 'unknown')
            
            if structure_type == 'database_portal':
                records = await self._mine_from_database_portal(l3_url, page_structure)
            elif structure_type == 'file_listing':
                records = await self._mine_from_file_listing(l3_url, page_structure)
            elif structure_type == 'api_endpoint':
                records = await self._mine_from_api(l3_url, page_structure)
            elif structure_type == 'download_page':
                records = await self._mine_from_download_page(l3_url, page_structure)
            else:
                records = await self._mine_generic_records(l3_url, page_structure)
            
            # 3. 验证和丰富L4记录
            verified_records = []
            for record in records:
                if await self._verify_l4_record(record):
                    enriched = await self._enrich_l4_metadata(record, l3_metadata)
                    verified_records.append(enriched)
            
            return {
                "l3_url": l3_url,
                "structure_type": structure_type,
                "page_analysis": page_structure,
                "total_records_found": len(records),
                "verified_records": len(verified_records),
                "l4_records": verified_records,
                "mining_strategy": structure_type
            }
            
        except Exception as e:
            logger.error(f"L4挖掘失败 {l3_url}: {e}")
            return {
                "l3_url": l3_url,
                "error": str(e),
                "l4_records": []
            }
    
    async def _analyze_l3_structure(self, url: str) -> Dict:
        """分析L3页面结构"""
        
        try:
            async with self.session.get(url, timeout=15) as response:
                if response.status >= 400:
                    return {"type": "unknown", "error": f"HTTP {response.status}"}
                
                content = await response.text()
                soup = BeautifulSoup(content, 'html.parser')
                
                # 分析页面特征
                page_features = {
                    "title": soup.find('title').get_text() if soup.find('title') else '',
                    "forms": len(soup.find_all('form')),
                    "tables": len(soup.find_all('table')),
                    "links": len(soup.find_all('a')),
                    "scripts": len(soup.find_all('script')),
                    "content_length": len(content)
                }
                
                # 检测数据库类型
                database_type = self._detect_database_type(url, content)
                
                # 判断结构类型
                structure_type = self._classify_page_structure(content, soup, page_features)
                
                # 提取关键元素
                key_elements = await self._extract_key_elements(soup, structure_type)
                
                return {
                    "type": structure_type,
                    "database_type": database_type,
                    "page_features": page_features,
                    "key_elements": key_elements,
                    "analysis_success": True
                }
                
        except Exception as e:
            return {"type": "unknown", "error": str(e)}
    
    def _detect_database_type(self, url: str, content: str) -> str:
        """检测数据库类型"""
        
        url_lower = url.lower()
        content_lower = content.lower()
        
        for db_type, config in self.database_types.items():
            # 检查URL模式
            if any(re.search(pattern, url_lower) for pattern in config['patterns']):
                return db_type
            
            # 检查内容模式
            if any(pattern in content_lower for pattern in config['patterns']):
                return db_type
        
        return 'generic'
    
    def _classify_page_structure(self, content: str, soup: BeautifulSoup, features: Dict) -> str:
        """分类页面结构"""
        
        content_lower = content.lower()
        
        # 计算各种结构类型的得分
        scores = {}
        
        for structure_type, indicators in self.structure_indicators.items():
            score = sum(1 for indicator in indicators if indicator in content_lower)
            
            # 根据页面特征调整得分
            if structure_type == 'database_portal':
                score += features['forms'] * 0.5 + features['tables'] * 0.3
            elif structure_type == 'file_listing':
                # 检查文件链接
                file_links = len([a for a in soup.find_all('a', href=True) 
                                if any(ext in a.get('href', '').lower() 
                                     for ext in ['.csv', '.xlsx', '.json', '.xml', '.zip'])])
                score += file_links * 0.5
            elif structure_type == 'api_endpoint':
                score += features['scripts'] * 0.2
                # 检查JSON/XML内容
                if 'application/json' in content_lower or '<xml' in content_lower:
                    score += 2
            
            scores[structure_type] = score
        
        # 返回得分最高的结构类型
        if not scores or max(scores.values()) == 0:
            return 'unknown'
        
        return max(scores.keys(), key=lambda k: scores[k])
    
    async def _extract_key_elements(self, soup: BeautifulSoup, structure_type: str) -> Dict:
        """提取关键元素"""
        
        elements = {}
        
        if structure_type == 'database_portal':
            # 提取搜索表单
            elements['search_forms'] = []
            for form in soup.find_all('form'):
                form_info = {
                    'action': form.get('action', ''),
                    'method': form.get('method', 'get'),
                    'inputs': [{'name': inp.get('name', ''), 'type': inp.get('type', 'text')} 
                             for inp in form.find_all('input')]
                }
                elements['search_forms'].append(form_info)
            
            # 提取浏览链接
            elements['browse_links'] = []
            for link in soup.find_all('a', href=True):
                text = link.get_text().lower()
                if any(keyword in text for keyword in ['browse', 'view', 'show', 'list']):
                    elements['browse_links'].append({
                        'href': link.get('href'),
                        'text': link.get_text().strip()
                    })
        
        elif structure_type == 'file_listing':
            # 提取文件链接
            elements['file_links'] = []
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                if any(ext in href.lower() for ext in ['.csv', '.xlsx', '.json', '.xml', '.txt']):
                    elements['file_links'].append({
                        'href': href,
                        'text': link.get_text().strip(),
                        'file_type': self._get_file_type(href)
                    })
        
        elif structure_type == 'api_endpoint':
            # 提取API信息
            elements['api_info'] = {
                'endpoints': self._extract_api_endpoints(soup),
                'documentation_links': [link.get('href') for link in soup.find_all('a', href=True)
                                      if 'doc' in link.get_text().lower() or 'api' in link.get_text().lower()]
            }
        
        return elements
    
    def _get_file_type(self, filename: str) -> str:
        """获取文件类型"""
        if '.csv' in filename.lower():
            return 'csv'
        elif '.xlsx' in filename.lower() or '.xls' in filename.lower():
            return 'excel'
        elif '.json' in filename.lower():
            return 'json'
        elif '.xml' in filename.lower():
            return 'xml'
        else:
            return 'unknown'
    
    def _extract_api_endpoints(self, soup: BeautifulSoup) -> List[str]:
        """提取API端点"""
        endpoints = []
        
        # 从代码块中提取
        for code in soup.find_all(['code', 'pre']):
            text = code.get_text()
            # 查找URL模式
            urls = re.findall(r'https?://[^\s<>"]+', text)
            endpoints.extend(urls)
        
        return list(set(endpoints))  # 去重
    
    async def _mine_from_database_portal(self, url: str, structure: Dict) -> List[Dict]:
        """从数据库门户挖掘记录"""
        
        records = []
        
        try:
            # 获取页面内容
            async with self.session.get(url, timeout=15) as response:
                content = await response.text()
                soup = BeautifulSoup(content, 'html.parser')
            
            # 1. 从页面文本中提取记录ID
            text_records = self._extract_records_from_text(content, structure.get('database_type', 'generic'))
            records.extend(text_records)
            
            # 2. 从表格中提取记录
            table_records = await self._extract_records_from_tables(soup, url)
            records.extend(table_records)
            
            # 3. 从链接中提取记录
            link_records = await self._extract_records_from_links(soup, url)
            records.extend(link_records)
            
            # 4. 尝试通过搜索表单获取更多记录
            if structure.get('key_elements', {}).get('search_forms'):
                search_records = await self._mine_through_search(url, structure['key_elements']['search_forms'])
                records.extend(search_records)
            
        except Exception as e:
            logger.error(f"数据库门户挖掘失败: {e}")
        
        return records
    
    async def _mine_from_file_listing(self, url: str, structure: Dict) -> List[Dict]:
        """从文件列表挖掘记录"""
        
        records = []
        
        try:
            file_links = structure.get('key_elements', {}).get('file_links', [])
            
            for file_link in file_links[:5]:  # 限制处理文件数量
                file_url = urljoin(url, file_link['href'])
                file_type = file_link.get('file_type', 'unknown')
                
                if file_type == 'csv':
                    file_records = await self._extract_records_from_csv(file_url)
                elif file_type == 'json':
                    file_records = await self._extract_records_from_json(file_url)
                elif file_type == 'xml':
                    file_records = await self._extract_records_from_xml(file_url)
                else:
                    continue
                
                records.extend(file_records)
                
        except Exception as e:
            logger.error(f"文件列表挖掘失败: {e}")
        
        return records
    
    async def _mine_from_api(self, url: str, structure: Dict) -> List[Dict]:
        """从API端点挖掘记录"""
        
        records = []
        
        try:
            api_info = structure.get('key_elements', {}).get('api_info', {})
            endpoints = api_info.get('endpoints', [])
            
            for endpoint in endpoints[:3]:  # 限制API调用数量
                try:
                    async with self.session.get(endpoint, timeout=10) as response:
                        if response.status == 200:
                            content_type = response.headers.get('Content-Type', '').lower()
                            
                            if 'json' in content_type:
                                data = await response.json()
                                api_records = self._extract_records_from_json_data(data)
                                records.extend(api_records)
                            elif 'xml' in content_type:
                                text = await response.text()
                                api_records = self._extract_records_from_xml_text(text)
                                records.extend(api_records)
                                
                except Exception as e:
                    logger.debug(f"API调用失败 {endpoint}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"API挖掘失败: {e}")
        
        return records
    
    async def _mine_from_download_page(self, url: str, structure: Dict) -> List[Dict]:
        """从下载页面挖掘记录"""
        
        records = []
        
        try:
            # 获取页面内容
            async with self.session.get(url, timeout=15) as response:
                content = await response.text()
                soup = BeautifulSoup(content, 'html.parser')
            
            # 查找下载链接
            download_links = []
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                text = link.get_text().lower()
                
                if ('download' in text or 'export' in text or 
                    any(ext in href.lower() for ext in ['.csv', '.xlsx', '.json', '.xml'])):
                    download_links.append(urljoin(url, href))
            
            # 处理下载文件
            for download_url in download_links[:3]:  # 限制下载数量
                try:
                    if '.csv' in download_url.lower():
                        file_records = await self._extract_records_from_csv(download_url)
                    elif '.json' in download_url.lower():
                        file_records = await self._extract_records_from_json(download_url)
                    else:
                        continue
                    
                    records.extend(file_records)
                    
                except Exception as e:
                    logger.debug(f"下载文件处理失败 {download_url}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"下载页面挖掘失败: {e}")
        
        return records
    
    async def _mine_generic_records(self, url: str, structure: Dict) -> List[Dict]:
        """通用记录挖掘"""
        
        records = []
        
        try:
            async with self.session.get(url, timeout=15) as response:
                content = await response.text()
                soup = BeautifulSoup(content, 'html.parser')
            
            # 从文本中提取记录
            text_records = self._extract_records_from_text(content, 'generic')
            records.extend(text_records)
            
            # 从表格中提取记录
            table_records = await self._extract_records_from_tables(soup, url)
            records.extend(table_records)
            
        except Exception as e:
            logger.error(f"通用挖掘失败: {e}")
        
        return records
    
    def _extract_records_from_text(self, content: str, database_type: str) -> List[Dict]:
        """从文本中提取记录"""
        
        records = []
        
        # 根据数据库类型选择模式
        if database_type in self.database_types:
            patterns = self.database_types[database_type]['record_patterns']
        else:
            patterns = self.record_patterns
        
        for pattern in patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                records.append({
                    "record_id": match,
                    "source": "text_extraction",
                    "pattern": pattern,
                    "database_type": database_type
                })
        
        return records
    
    async def _extract_records_from_tables(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """从表格中提取记录"""
        
        records = []
        
        tables = soup.find_all('table')
        for table in tables[:3]:  # 限制处理表格数量
            rows = table.find_all('tr')
            
            for row in rows:
                cells = row.find_all(['td', 'th'])
                for cell in cells:
                    cell_text = cell.get_text().strip()
                    
                    # 检查是否包含记录ID
                    for pattern in self.record_patterns:
                        matches = re.findall(pattern, cell_text)
                        for match in matches:
                            # 检查是否有链接
                            link = cell.find('a', href=True)
                            record_url = urljoin(base_url, link.get('href')) if link else None
                            
                            records.append({
                                "record_id": match,
                                "source": "table_extraction",
                                "record_url": record_url,
                                "context": cell_text[:100]
                            })
        
        return records
    
    async def _extract_records_from_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """从链接中提取记录"""
        
        records = []
        
        links = soup.find_all('a', href=True)
        for link in links:
            href = link.get('href')
            text = link.get_text().strip()
            
            # 检查链接文本和URL中的记录ID
            for pattern in self.record_patterns:
                # 检查链接文本
                text_matches = re.findall(pattern, text)
                for match in text_matches:
                    records.append({
                        "record_id": match,
                        "source": "link_text",
                        "record_url": urljoin(base_url, href),
                        "link_text": text
                    })
                
                # 检查URL
                url_matches = re.findall(pattern, href)
                for match in url_matches:
                    records.append({
                        "record_id": match,
                        "source": "link_url",
                        "record_url": urljoin(base_url, href),
                        "link_text": text
                    })
        
        return records
    
    async def _extract_records_from_csv(self, csv_url: str) -> List[Dict]:
        """从CSV文件提取记录"""
        
        records = []
        
        try:
            async with self.session.get(csv_url, timeout=30) as response:
                if response.status == 200:
                    content = await response.text()
                    
                    # 解析CSV
                    csv_reader = csv.DictReader(io.StringIO(content))
                    
                    for i, row in enumerate(csv_reader):
                        if i >= 100:  # 限制处理行数
                            break
                        
                        # 查找可能的记录ID列
                        for key, value in row.items():
                            if value and any(re.search(pattern, str(value)) for pattern in self.record_patterns):
                                records.append({
                                    "record_id": str(value),
                                    "source": "csv_file",
                                    "file_url": csv_url,
                                    "column": key,
                                    "row_data": dict(row)
                                })
                                break
                        
        except Exception as e:
            logger.debug(f"CSV处理失败 {csv_url}: {e}")
        
        return records
    
    async def _extract_records_from_json(self, json_url: str) -> List[Dict]:
        """从JSON文件提取记录"""
        
        records = []
        
        try:
            async with self.session.get(json_url, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    records = self._extract_records_from_json_data(data)
                    
                    # 添加源信息
                    for record in records:
                        record["file_url"] = json_url
                        
        except Exception as e:
            logger.debug(f"JSON处理失败 {json_url}: {e}")
        
        return records
    
    def _extract_records_from_json_data(self, data) -> List[Dict]:
        """从JSON数据提取记录"""
        
        records = []
        
        def extract_from_obj(obj, path=""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    new_path = f"{path}.{key}" if path else key
                    
                    if isinstance(value, str) and any(re.search(pattern, value) for pattern in self.record_patterns):
                        records.append({
                            "record_id": value,
                            "source": "json_data",
                            "json_path": new_path,
                            "context": obj
                        })
                    else:
                        extract_from_obj(value, new_path)
                        
            elif isinstance(obj, list):
                for i, item in enumerate(obj[:50]):  # 限制处理数量
                    extract_from_obj(item, f"{path}[{i}]")
        
        extract_from_obj(data)
        return records
    
    async def _verify_l4_record(self, record: Dict) -> bool:
        """验证L4记录"""
        
        record_id = record.get('record_id', '')
        
        # 基础验证
        if not record_id or len(record_id) < 3:
            return False
        
        # 模式验证
        if not any(re.search(pattern, record_id) for pattern in self.record_patterns):
            return False
        
        # 如果有记录URL，尝试验证
        record_url = record.get('record_url')
        if record_url:
            try:
                async with self.session.head(record_url, timeout=5) as response:
                    return response.status < 400
            except:
                pass  # URL验证失败不影响记录有效性
        
        return True
    
    async def _enrich_l4_metadata(self, record: Dict, l3_metadata: Dict = None) -> Dict:
        """丰富L4记录元数据"""
        
        enriched = record.copy()
        
        # 添加L3来源信息
        if l3_metadata:
            enriched["l3_source"] = l3_metadata
        
        # 分析记录ID类型
        record_id = record.get('record_id', '')
        enriched["id_type"] = self._classify_record_id(record_id)
        
        # 添加时间戳
        import time
        enriched["extracted_at"] = time.time()
        
        # 如果有记录URL，尝试获取更多信息
        record_url = record.get('record_url')
        if record_url:
            try:
                async with self.session.get(record_url, timeout=10) as response:
                    if response.status == 200:
                        content = await response.text()
                        soup = BeautifulSoup(content, 'html.parser')
                        
                        # 提取标题
                        title = soup.find('title')
                        if title:
                            enriched["record_title"] = title.get_text().strip()
                        
                        # 提取描述
                        meta_desc = soup.find('meta', attrs={'name': 'description'})
                        if meta_desc:
                            enriched["record_description"] = meta_desc.get('content', '')
                        
            except Exception as e:
                logger.debug(f"记录元数据丰富失败 {record_url}: {e}")
        
        return enriched
    
    def _classify_record_id(self, record_id: str) -> str:
        """分类记录ID类型"""
        
        id_types = {
            'ncbi_accession': r'^[A-Z]{1,2}\d{6,}$',
            'ensembl_id': r'^ENS[A-Z]*\d+$',
            'uniprot_id': r'^[A-Z]\d[A-Z0-9]{3}\d$',
            'refseq_id': r'^[A-Z]{1,2}_\d+$',
            'snp_id': r'^rs\d+$',
            'go_id': r'^GO:\d+$',
            'omim_id': r'^[#*%]\d{6}$',
            'clinvar_id': r'^[A-Z]{3}\d+$'
        }
        
        for id_type, pattern in id_types.items():
            if re.match(pattern, record_id):
                return id_type
        
        return 'unknown'
    
    async def close(self):
        """关闭会话"""
        if self.session:
            await self.session.close()
