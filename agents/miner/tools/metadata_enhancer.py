"""
元数据增强器 - 增强挖掘结果的元数据
"""
import requests
import time
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse
import re
import json
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.ERROR)

class MetadataEnhancer:
    """元数据增强器"""
   
    def __init__(self):
        self.session = None
       
        # 元数据提取规则
        self.meta_selectors = {
            'title': ['title', 'h1', '.title', '#title'],
            'description': ['meta[name="description"]', '.description', '.summary'],
            'keywords': ['meta[name="keywords"]', '.keywords', '.tags'],
            'author': ['meta[name="author"]', '.author', '.creator'],
            'date': ['meta[name="date"]', '.date', '.published', 'time'],
            'language': ['meta[name="language"]', 'html[lang]']
        }
       
        # 生物医学特定元数据
        self.biomedical_selectors = {
            'organism': ['.organism', '.species', '[data-organism]'],
            'tissue': ['.tissue', '.sample-type', '[data-tissue]'],
            'disease': ['.disease', '.condition', '[data-disease]'],
            'study_type': ['.study-type', '.experiment-type', '[data-study]'],
            'platform': ['.platform', '.technology', '[data-platform]'],
            'sample_size': ['.sample-size', '.n-samples', '[data-samples]']
        }
   
    def enhance_metadata(self, url: str, existing_title: str = None) -> Dict:
        """增强单个URL的元数据"""
       
        try:
            start_time = time.time()
           
            # 获取页面内容
            response = requests.get(url, timeout=15)
            if response.status_code >= 400:
                return {
                    "url": url,
                    "enhancement_success": False,
                    "error": f"HTTP {response.status_code}"
                }
               
            content = response.text
            soup = BeautifulSoup(content, 'html.parser')
           
            # 提取基础元数据
            basic_metadata = self._extract_basic_metadata(soup, existing_title)
           
            # 提取生物医学元数据
            biomedical_metadata = self._extract_biomedical_metadata(soup)
           
            # 提取结构化数据
            structured_data = self._extract_structured_data(soup)
           
            # 分析页面特征
            page_features = self._analyze_page_features(soup, content)
           
            # 提取下载信息
            download_info = self._extract_download_info(soup, url)
           
            # 计算增强质量分数
            quality_score = self._calculate_enhancement_quality(
                basic_metadata, biomedical_metadata, structured_data, page_features
            )
           
            processing_time = time.time() - start_time
           
            return {
                "url": url,
                "enhancement_success": True,
                "processing_time": round(processing_time, 2),
                "quality_score": quality_score,
                "basic_metadata": basic_metadata,
                "biomedical_metadata": biomedical_metadata,
                "structured_data": structured_data,
                "page_features": page_features,
                "download_info": download_info,
                "enhanced_at": time.time()
            }
           
        except Exception as e:
            logger.error(f"元数据增强失败 {url}: {e}")
            return {
                "url": url,
                "enhancement_success": False,
                "error": str(e)
            }
   
    def _extract_basic_metadata(self, soup: BeautifulSoup, existing_title: str = None) -> Dict:
        """提取基础元数据"""
       
        metadata = {}
       
        # 标题
        title = existing_title
        if not title:
            for selector in self.meta_selectors['title']:
                element = soup.select_one(selector)
                if element:
                    title = element.get_text().strip()
                    break
        metadata['title'] = title or ''
       
        # 描述
        for selector in self.meta_selectors['description']:
            element = soup.select_one(selector)
            if element:
                if element.name == 'meta':
                    metadata['description'] = element.get('content', '')
                else:
                    metadata['description'] = element.get_text().strip()[:500] # 限制长度
                break
        else:
            metadata['description'] = ''
       
        # 关键词
        keywords = []
        for selector in self.meta_selectors['keywords']:
            element = soup.select_one(selector)
            if element:
                if element.name == 'meta':
                    keywords_text = element.get('content', '')
                    keywords = [kw.strip() for kw in keywords_text.split(',')]
                else:
                    keywords_text = element.get_text()
                    keywords = [kw.strip() for kw in keywords_text.split(',')]
                break
        metadata['keywords'] = keywords
       
        # 作者
        for selector in self.meta_selectors['author']:
            element = soup.select_one(selector)
            if element:
                if element.name == 'meta':
                    metadata['author'] = element.get('content', '')
                else:
                    metadata['author'] = element.get_text().strip()
                break
        else:
            metadata['author'] = ''
       
        # 日期
        for selector in self.meta_selectors['date']:
            element = soup.select_one(selector)
            if element:
                if element.name == 'meta':
                    metadata['date'] = element.get('content', '')
                elif element.name == 'time':
                    metadata['date'] = element.get('datetime', element.get_text().strip())
                else:
                    metadata['date'] = element.get_text().strip()
                break
        else:
            metadata['date'] = ''
       
        # 语言
        for selector in self.meta_selectors['language']:
            element = soup.select_one(selector)
            if element:
                if element.name == 'meta':
                    metadata['language'] = element.get('content', '')
                else:
                    metadata['language'] = element.get('lang', '')
                break
        else:
            metadata['language'] = ''
       
        return metadata
   
    def _extract_biomedical_metadata(self, soup: BeautifulSoup) -> Dict:
        """提取生物医学特定元数据"""
       
        biomedical = {}
       
        for field, selectors in self.biomedical_selectors.items():
            for selector in selectors:
                elements = soup.select(selector)
                if elements:
                    if selector.startswith('[data-'):
                        # 数据属性
                        attr_name = selector[1:-1].split('=')[0]
                        values = [elem.get(attr_name) for elem in elements]
                    else:
                        # 文本内容
                        values = [elem.get_text().strip() for elem in elements]
                   
                    # 过滤空值
                    values = [v for v in values if v]
                    if values:
                        biomedical[field] = values[0] if len(values) == 1 else values
                        break
       
        # 使用正则表达式从文本中提取生物医学信息
        page_text = soup.get_text().lower()
       
        # 物种识别
        if 'organism' not in biomedical:
            species_patterns = [
                r'homo sapiens?', r'human', r'mouse', r'mus musculus',
                r'drosophila', r'c\.?\s*elegans', r'arabidopsis',
                r'saccharomyces cerevisiae', r'e\.?\s*coli'
            ]
            for pattern in species_patterns:
                if re.search(pattern, page_text):
                    biomedical['organism'] = re.sub(r'\.?\s*', ' ', pattern)
                    break
       
        # 疾病识别
        if 'disease' not in biomedical:
            disease_patterns = [
                r'cancer', r'diabetes', r'alzheimer', r'parkinson',
                r'cardiovascular', r'rare disease', r'genetic disorder'
            ]
            found_diseases = []
            for pattern in disease_patterns:
                if re.search(pattern, page_text):
                    found_diseases.append(pattern)
            if found_diseases:
                biomedical['disease'] = found_diseases
       
        return biomedical
   
    def _extract_structured_data(self, soup: BeautifulSoup) -> Dict:
        """提取结构化数据"""
       
        structured = {
            'json_ld': [],
            'microdata': {},
            'open_graph': {},
            'twitter_card': {}
        }
       
        # JSON-LD
        json_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_scripts:
            try:
                data = json.loads(script.string)
                structured['json_ld'].append(data)
            except:
                pass
       
        # Open Graph
        og_tags = soup.find_all('meta', property=lambda x: x and x.startswith('og:'))
        for tag in og_tags:
            prop = tag.get('property', '').replace('og:', '')
            structured['open_graph'][prop] = tag.get('content')
       
        # Twitter Card
        twitter_tags = soup.find_all('meta', name=lambda x: x and x.startswith('twitter:'))
        for tag in twitter_tags:
            name = tag.get('name', '').replace('twitter:', '')
            structured['twitter_card'][name] = tag.get('value') or tag.get('content')
       
        # Microdata (简单提取)
        microdata_items = soup.find_all(attrs={'itemscope': True})
        for item in microdata_items:
            itemtype = item.get('itemtype', 'unknown')
            if itemtype not in structured['microdata']:
                structured['microdata'][itemtype] = []
            props = {}
            prop_tags = item.find_all(attrs={'itemprop': True})
            for prop in prop_tags:
                prop_name = prop.get('itemprop')
                value = prop.get_text().strip() or prop.get('content') or prop.get('src') or prop.get('href')
                props[prop_name] = value
            structured['microdata'][itemtype].append(props)
       
        return structured
   
    def _analyze_page_features(self, soup: BeautifulSoup, content: str) -> Dict:
        """分析页面特征"""
       
        features = {
            'has_tables': len(soup.find_all('table')) > 0,
            'has_charts': bool(re.search(r'chart|graph|plot|visualization', content, re.I)),
            'has_download_links': len(soup.find_all('a', href=re.compile(r'\.(csv|xls|xlsx|pdf|zip|tar|gz|data|json)$', re.I))) > 0,
            'has_api_mentions': 'api' in content.lower() or 'endpoint' in content.lower(),
            'has_database_mentions': 'database' in content.lower() or 'dataset' in content.lower(),
            'page_type': 'unknown',
            'content_length': len(content),
            'link_count': len(soup.find_all('a'))
        }
       
        # 确定页面类型
        if features['has_tables']:
            features['page_type'] = 'data_table'
        elif features['has_charts']:
            features['page_type'] = 'visualization'
        elif features['has_download_links']:
            features['page_type'] = 'download_page'
        elif 'search' in content.lower() or len(soup.find_all('input', type='search')) > 0:
            features['page_type'] = 'search_portal'
       
        return features
   
    def _extract_download_info(self, soup: BeautifulSoup, url: str) -> List[Dict]:
        """提取下载信息"""
       
        downloads = []
       
        # 查找下载链接
        download_links = soup.find_all('a', href=re.compile(r'\.(csv|xls|xlsx|pdf|zip|tar|gz|data|json)$', re.I))
       
        for link in download_links:
            download_url = urljoin(url, link.get('href'))
            file_name = urlparse(download_url).path.split('/')[-1]
            text = link.get_text().strip()
            downloads.append({
                'url': download_url,
                'file_name': file_name,
                'text': text if text else file_name,
                'format': file_name.split('.')[-1].upper()
            })
       
        # 查找按钮或表单下载
        button_downloads = soup.find_all(['button', 'input'], attrs={'value': re.compile(r'download|下载', re.I)})
        for button in button_downloads:
            form = button.find_parent('form')
            if form:
                action = urljoin(url, form.get('action', ''))
                downloads.append({
                    'url': action,
                    'file_name': 'form_download',
                    'text': button.get('value') or button.get_text().strip(),
                    'format': 'UNKNOWN'
                })
       
        return downloads
   
    def _calculate_enhancement_quality(self, basic: Dict, biomedical: Dict, structured: Dict, features: Dict) -> float:
        """计算增强质量分数 (0-1)"""
       
        score = 0.0
        weights = {
            'basic': 0.4,
            'biomedical': 0.3,
            'structured': 0.2,
            'features': 0.1
        }
       
        # 基础元数据分数
        basic_filled = sum(1 for v in basic.values() if v) / len(basic)
        score += basic_filled * weights['basic']
       
        # 生物医学分数
        biomed_filled = sum(1 for v in biomedical.values() if v) / len(self.biomedical_selectors)
        score += biomed_filled * weights['biomedical']
       
        # 结构化数据分数
        structured_count = len(structured['json_ld']) + len(structured['microdata']) + len(structured['open_graph']) + len(structured['twitter_card'])
        structured_score = min(structured_count / 4, 1.0)
        score += structured_score * weights['structured']
       
        # 页面特征分数
        features_score = sum(1 for k, v in features.items() if k.startswith('has_') and v) / 5
        score += features_score * weights['features']
       
        return round(score, 2)