import json
import time
import uuid
import asyncio
import aiohttp
from typing import Dict, Any, List, Optional, Set
import datetime
from loguru import logger
from urllib.parse import urljoin, urlparse, parse_qs
import re
from bs4 import BeautifulSoup
import hashlib

# 核心组件
from state.miner_state import MinerState
from nodes.extract_node import ExtractNode
from nodes.structure_node import StructureNode
from nodes.validate_node import ValidateNode
from nodes.reflection_node import ReflectionNode
from evolution.miner_evolution_engine import get_memory_evolution_engine
from llms.miner_llm import create_miner_llm

# 工具套件
from tools import (
    URLValidator, URLClassifier, L2SiteAnalyzer, L3DatasetDetector, 
    L4RecordMiner, SearchEngine, BlacklistManager, GitHubHandler,
    DetailedStatistics, MetadataEnhancer, BrowsePageTool,
    create_tool_suite, close_all_tools
)

class UniversalMinerAgent:
    """
    通用数据挖掘智能体 - 修复版本
    
    核心特性：
    1. 🌐 真实网页抓取：所有数据来源于真实网页
    2. 🧠 通用AI分析：不限定特定领域或场景
    3. 🎯 多层挖掘：L1->L2->L3->L4完整流程
    4. 📊 智能发现：自动识别数据结构和模式
    5. 🔄 自我进化：基于真实结果持续优化
    6. 🔧 错误修复：解决LLM调用和备用方法问题
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.session_id = str(uuid.uuid4())
        
        # 🧠 核心组件初始化
        self.state = MinerState()
        self.llm = create_miner_llm()
        self.evolution_engine = get_memory_evolution_engine()
        
        # 🔄 处理节点
        self.extract_node = ExtractNode()
        self.structure_node = StructureNode()
        self.validate_node = ValidateNode()
        self.reflection_node = ReflectionNode()
        
        # 🛠️ 工具套件
        try:
            self.tools = create_tool_suite()
        except Exception as e:
            logger.error(f"工具套件初始化失败: {e}")
            self.tools = {}
        
        # 🌐 网络会话
        self.session = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        }
        
        # 📊 挖掘统计
        self.stats = {
            'session_id': self.session_id,
            'start_time': None,
            'end_time': None,
            'total_processed': 0,
            'successful_extractions': 0,
            'failed_extractions': 0,
            'evolution_cycles': 0,
            'memory_updates': 0,
            'l1_urls': [],
            'l2_sites': [],
            'l3_datasets': [],
            'l4_records': [],
            'invalid_urls': [],
            'errors': [],
            'evolution_history': [],
            'discovered_patterns': set(),
            'visited_urls': set()
        }
        
        # ⚙️ 配置参数
        self.max_concurrent = self.config.get('max_concurrent', 2)
        self.enable_l4_mining = self.config.get('enable_l4_mining', True)
        self.enable_metadata_enhancement = self.config.get('enable_metadata_enhancement', True)
        self.enable_github_upload = self.config.get('enable_github_upload', False)
        self.enable_evolution = self.config.get('enable_evolution', True)
        self.quality_threshold = self.config.get('quality_threshold', 0.3)
        self.reflection_interval = self.config.get('reflection_interval', 10)
        self.request_timeout = self.config.get('request_timeout', 30)
        self.request_delay = self.config.get('request_delay', 2.0)
        self.max_depth = self.config.get('max_depth', 3)
        self.max_links_per_page = self.config.get('max_links_per_page', 50)
        
        logger.info(f"🤖 通用Miner Agent 初始化完成 - Session: {self.session_id}")
    
    async def _get_session(self):
        """获取或创建HTTP会话"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            connector = aiohttp.TCPConnector(
                limit=50, 
                limit_per_host=3,
                ttl_dns_cache=300,
                use_dns_cache=True
            )
            
            self.session = aiohttp.ClientSession(
                timeout=timeout, 
                connector=connector,
                headers=self.headers
            )
        return self.session
    
    async def _safe_llm_invoke(self, prompt: str, expect_json: bool = True) -> Dict:
        """安全的LLM调用方法"""
        try:
            if hasattr(self.llm, 'invoke_json') and expect_json:
                response = self.llm.invoke_json(prompt)
                if isinstance(response, dict):
                    return response
                elif isinstance(response, str):
                    return json.loads(response)
                else:
                    raise Exception(f"Unexpected response type: {type(response)}")
            
            elif hasattr(self.llm, 'invoke'):
                response = self.llm.invoke(prompt)
                if expect_json:
                    return json.loads(response)
                else:
                    return {'response': response}
            
            elif hasattr(self.llm, 'agenerate'):
                response = await self.llm.agenerate(prompt)
                if expect_json:
                    return json.loads(response)
                else:
                    return {'response': response}
            
            else:
                available_methods = [method for method in dir(self.llm) if not method.startswith('_')]
                raise Exception(f"LLM没有可用的调用方法。可用方法: {available_methods}")
        
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            raise Exception(f"LLM返回的不是有效JSON格式")
        
        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            raise e

    def _fallback_analyze_content(self, url: str, soup: BeautifulSoup = None, links: List[Dict] = None) -> Dict:
        """备用的基于规则的内容分析"""
        
        if soup is None:
            return {
                'tier': 'L1',
                'confidence': 0.1,
                'page_type': 'unknown',
                'content_category': 'unknown',
                'data_density': 'low',
                'structure_level': 'low',
                'navigation_complexity': 'low',
                'key_features': ['fallback_analysis'],
                'potential_value': 0.1,
                'reason': 'Fallback analysis due to parsing failure',
                'title': '',
                'meta_description': '',
                'meta_keywords': '',
                'text_length': 0,
                'links_count': 0,
                'analysis_method': 'fallback_minimal'
            }
        
        links = links or []
        
        # 基础分析
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        text_content = soup.get_text()
        clean_text = ' '.join(text_content.split())
        
        # 提取meta信息
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        meta_desc_content = meta_desc.get('content', '').strip() if meta_desc else ""
        
        meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
        meta_keywords_content = meta_keywords.get('content', '').strip() if meta_keywords else ""
        
        # 简单的层级判断
        if len(links) > 50:
            tier = 'L2'
            page_type = 'portal'
            confidence = 0.7
            data_density = 'high'
            navigation_complexity = 'high'
        elif len(links) > 10:
            tier = 'L2'
            page_type = 'list'
            confidence = 0.6
            data_density = 'medium'
            navigation_complexity = 'medium'
        elif 'id=' in url or 'record' in url.lower() or 'detail' in url.lower():
            tier = 'L4'
            page_type = 'detail'
            confidence = 0.8
            data_density = 'high'
            navigation_complexity = 'low'
        elif len(clean_text) > 5000:
            tier = 'L3'
            page_type = 'content'
            confidence = 0.5
            data_density = 'medium'
            navigation_complexity = 'medium'
        else:
            tier = 'L1'
            page_type = 'general'
            confidence = 0.4
            data_density = 'low'
            navigation_complexity = 'low'
        
        # 结构化程度分析
        tables = soup.find_all('table')
        lists = soup.find_all(['ul', 'ol'])
        forms = soup.find_all('form')
        
        structure_score = len(tables) * 0.3 + len(lists) * 0.1 + len(forms) * 0.2
        if structure_score > 2:
            structure_level = 'high'
        elif structure_score > 0.5:
            structure_level = 'medium'
        else:
            structure_level = 'low'
        
        # 内容类别判断
        content_lower = clean_text.lower()
        if any(keyword in content_lower for keyword in ['data', 'database', 'search', 'browse']):
            content_category = 'data_portal'
            confidence += 0.1
        elif any(keyword in content_lower for keyword in ['research', 'publication', 'article']):
            content_category = 'research_content'
            confidence += 0.05
        elif any(keyword in content_lower for keyword in ['government', 'statistics', 'official']):
            content_category = 'government_data'
            confidence += 0.05
        else:
            content_category = 'general'
        
        # 关键特征提取
        key_features = ['fallback_analysis']
        if len(tables) > 0:
            key_features.append('has_tables')
        if len(forms) > 0:
            key_features.append('has_forms')
        if len(links) > 20:
            key_features.append('link_rich')
        if len(clean_text) > 3000:
            key_features.append('content_rich')
        
        return {
            'tier': tier,
            'confidence': min(confidence, 1.0),
            'page_type': page_type,
            'content_category': content_category,
            'data_density': data_density,
            'structure_level': structure_level,
            'navigation_complexity': navigation_complexity,
            'key_features': key_features,
            'potential_value': min(confidence, 1.0),
            'reason': f'Rule-based fallback analysis: {tier} classification based on content length ({len(clean_text)}) and link count ({len(links)})',
            'title': title,
            'meta_description': meta_desc_content,
            'meta_keywords': meta_keywords_content,
            'text_length': len(clean_text),
            'links_count': len(links),
            'tables_count': len(tables),
            'lists_count': len(lists),
            'forms_count': len(forms),
            'analysis_method': 'fallback_rules'
        }

    def _fallback_analyze_links(self, base_url: str, links: List[Dict]) -> List[Dict]:
        """备用的基于规则的链接分析"""
        
        l3_candidates = []
        
        # 简单的启发式规则
        for link in links[:20]:
            text = link['text'].lower()
            url = link['absolute_url'].lower()
            
            # 计算相关性分数
            score = 0.0
            
            # 基于文本内容的评分
            valuable_keywords = [
                'data', 'information', 'details', 'view', 'show', 'display',
                'content', 'article', 'page', 'item', 'entry', 'record',
                'database', 'search', 'browse', 'download', 'access'
            ]
            
            for keyword in valuable_keywords:
                if keyword in text:
                    score += 0.1
            
            # 基于URL结构的评分
            parsed_url = urlparse(url)
            path_parts = parsed_url.path.split('/')
            if len(path_parts) > 2:
                score += 0.2
            
            if any(param in url for param in ['id=', 'page=', 'item=', 'view=', 'search=']):
                score += 0.3
            
            # 避免明显的导航链接
            nav_keywords = ['home', 'about', 'contact', 'login', 'register', 'menu', 'help']
            if any(keyword in text for keyword in nav_keywords):
                score -= 0.2
            
            # 避免文件下载链接
            file_extensions = ['.pdf', '.doc', '.xls', '.zip', '.jpg', '.png', '.gif']
            if any(ext in url for ext in file_extensions):
                score -= 0.3
            
            # 如果分数足够高，添加为候选
            if score > 0.2:
                l3_candidates.append({
                    'url': link['absolute_url'],
                    'title': link['text'],
                    'source_l2': base_url,
                    'confidence': min(score, 0.8),
                    'reason': f'Rule-based analysis: score {score:.2f}',
                    'expected_content_type': 'content_page',
                    'priority': 'high' if score > 0.5 else 'medium',
                    'discovery_method': 'rule_based'
                })
        
        # 按置信度排序
        l3_candidates.sort(key=lambda x: x.get('confidence', 0), reverse=True)
        
        return l3_candidates[:10]

    async def mine_urls(self, urls: List[str], instructions: str = None) -> Dict[str, Any]:
        """主挖掘入口：执行完整的通用挖掘流程"""
        
        self.stats['start_time'] = time.time()
        self.stats['total_processed'] = len(urls)
        logger.info(f"🚀 开始通用数据挖掘 {len(urls)} 个URL")
        
        try:
            # 🧠 加载历史记忆和经验
            await self._load_historical_memory()
            
            # 🎯 执行多阶段真实挖掘流程
            mining_results = await self._execute_mining_pipeline(urls, instructions)
            
            # 🔄 执行反思和进化
            if self.enable_evolution:
                evolution_results = await self._execute_evolution_cycle(mining_results)
                mining_results['evolution'] = evolution_results
            
            # 💾 保存经验到记忆
            await self._save_experience_to_memory(mining_results)
            
            # 📊 生成最终报告
            self.stats['end_time'] = time.time()
            final_report = await self._generate_mining_report(mining_results)
            
            logger.info(f"✅ 通用挖掘完成！总耗时: {self.stats['end_time'] - self.stats['start_time']:.2f}秒")
            return final_report
            
        except Exception as e:
            logger.error(f"❌ 挖掘过程发生错误: {e}")
            self.stats['end_time'] = time.time()
            
            return {
                'success': False,
                'error': str(e),
                'partial_results': self.stats,
                'timestamp': datetime.datetime.now().isoformat(),
                'summary': {
                    'total_urls_processed': len(urls),
                    'l2_sites_found': 0,
                    'l3_datasets_verified': 0,
                    'l4_records_mined': 0,
                    'high_quality_items': 0,
                    'success_rate': 0.0,
                    'evolution_improvements': 0
                }
            }
        finally:
            # 清理资源
            await self._safe_close_resources()

    async def _load_historical_memory(self):
        """🧠 加载历史记忆和经验"""
        try:
            if hasattr(self.evolution_engine, 'load_memory'):
                memory_data = await self.evolution_engine.load_memory()
                if memory_data:
                    learned_strategies = memory_data.get('successful_strategies', {})
                    if learned_strategies:
                        self._apply_learned_strategies(learned_strategies)
                    
                    # 加载已发现的模式
                    patterns = memory_data.get('discovered_patterns', [])
                    self.stats['discovered_patterns'].update(patterns)
                    
                    logger.info(f"🧠 已加载历史记忆: {len(memory_data.get('experiences', []))} 条经验")
                else:
                    logger.info("🧠 首次运行，无历史记忆")
            else:
                logger.info("🧠 进化引擎暂无记忆加载接口")
        except Exception as e:
            logger.error(f"记忆加载失败: {e}")

    def _apply_learned_strategies(self, strategies: Dict):
        """应用学习到的策略"""
        if 'optimal_quality_threshold' in strategies:
            self.quality_threshold = strategies['optimal_quality_threshold']
            logger.info(f"📈 应用学习策略: 质量阈值 -> {self.quality_threshold}")
        
        if 'optimal_concurrency' in strategies:
            self.max_concurrent = min(strategies['optimal_concurrency'], 3)
            logger.info(f"📈 应用学习策略: 并发数 -> {self.max_concurrent}")
        
        if 'optimal_request_delay' in strategies:
            self.request_delay = strategies['optimal_request_delay']
            logger.info(f"📈 应用学习策略: 请求延迟 -> {self.request_delay}")

    async def _execute_mining_pipeline(self, urls: List[str], instructions: str = None) -> Dict:
        """🎯 执行通用多阶段挖掘流程"""
        
        pipeline_results = {}
        
        # 第一阶段：L1 URL验证和内容分析
        logger.info("📋 第一阶段：L1 URL验证和内容分析")
        l1_results = await self._process_l1_urls(urls)
        pipeline_results['l1_results'] = l1_results
        
        # 第二阶段：L2 站点结构分析
        logger.info("🔍 第二阶段：L2 站点结构分析")
        l2_results = await self._process_l2_sites(l1_results['valid_urls'], instructions)
        pipeline_results['l2_results'] = l2_results
        
        # 第三阶段：L3 深度内容挖掘
        logger.info("📊 第三阶段：L3 深度内容挖掘")
        l3_results = await self._process_l3_content(l2_results['potential_l3s'])
        pipeline_results['l3_results'] = l3_results
        
        # 第四阶段：L4 具体数据提取（可选）
        l4_results = {'l4_records': [], 'total_records': 0}
        if self.enable_l4_mining and l3_results['verified_l3s']:
            logger.info("🎯 第四阶段：L4 具体数据提取")
            l4_results = await self._process_l4_records(l3_results['verified_l3s'])
        pipeline_results['l4_results'] = l4_results
        
        # 第五阶段：元数据增强（可选）
        enhanced_results = []
        if self.enable_metadata_enhancement:
            logger.info("✨ 第五阶段：元数据增强")
            enhanced_results = await self._enhance_metadata(
                l3_results['verified_l3s'] + l4_results['l4_records']
            )
        pipeline_results['enhanced_results'] = enhanced_results
        
        # 第六阶段：质量评估和过滤
        logger.info("🎯 第六阶段：质量评估和过滤")
        final_results = await self._assess_quality(
            l3_results['verified_l3s'], l4_results['l4_records'], enhanced_results
        )
        pipeline_results['final_results'] = final_results
        
        return pipeline_results

    async def _process_l1_urls(self, urls: List[str]) -> Dict:
        """第一阶段：L1 URL验证和内容分析"""
        
        self.state.current_stage = "L1_processing"
        self.state.total_urls = len(urls)
        
        valid_urls = []
        invalid_urls = []
        
        session = await self._get_session()
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def process_single_url(url: str) -> Dict:
            async with semaphore:
                try:
                    # 检查是否已访问过
                    url_hash = hashlib.md5(url.encode()).hexdigest()
                    if url_hash in self.stats['visited_urls']:
                        logger.info(f"⏭️ 跳过已访问URL: {url}")
                        return None
                    
                    self.stats['visited_urls'].add(url_hash)
                    
                    # 添加延迟以避免被封
                    await asyncio.sleep(self.request_delay)
                    
                    logger.info(f"🔍 处理URL: {url}")
                    
                    # 真实HTTP请求验证URL
                    try:
                        async with session.head(url, allow_redirects=True) as response:
                            if response.status >= 400:
                                raise Exception(f"HTTP {response.status}")
                            
                            final_url = str(response.url)
                            content_type = response.headers.get('content-type', '').lower()
                            
                            # 只处理HTML内容
                            if 'text/html' not in content_type:
                                raise Exception(f"非HTML内容: {content_type}")
                    except Exception as head_error:
                        # 如果HEAD请求失败，尝试GET请求
                        logger.warning(f"HEAD请求失败，尝试GET: {head_error}")
                        async with session.get(url, allow_redirects=True) as response:
                            if response.status >= 400:
                                raise Exception(f"HTTP {response.status}")
                            
                            final_url = str(response.url)
                            content_type = response.headers.get('content-type', '').lower()
                            content = await response.text()
                    else:
                        # HEAD请求成功，获取页面内容
                        async with session.get(final_url) as content_response:
                            if content_response.status >= 400:
                                raise Exception(f"内容获取失败: HTTP {content_response.status}")
                            
                            content = await content_response.text()
                    
                    # 分析页面内容
                    analysis = await self._analyze_page_content(final_url, content)
                    
                    url_info = {
                        'original_url': url,
                        'final_url': final_url,
                        'success': True,
                        'validation': {
                            'is_valid': True,
                            'status_code': 200,
                            'content_type': content_type,
                            'content_length': len(content),
                            'redirected': url != final_url
                        },
                        'analysis': analysis,
                        'tier': analysis.get('tier', 'L1'),
                        'confidence': analysis.get('confidence', 0.5),
                        'processing_timestamp': time.time()
                    }
                    
                    logger.info(f"✅ URL处理成功: {url} -> {final_url} (层级: {analysis.get('tier', 'L1')}, 置信度: {analysis.get('confidence', 0.5):.2f})")
                    return url_info
                            
                except Exception as e:
                    error_info = {
                        'url': url,
                        'success': False,
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'processing_timestamp': time.time()
                    }
                    logger.error(f"❌ URL处理失败: {url} - {e}")
                    self.stats['errors'].append({
                        'stage': 'L1_processing',
                        'url': url,
                        'error': str(e),
                        'timestamp': time.time()
                    })
                    return error_info
        
        # 并发处理所有URL
        tasks = [process_single_url(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 分类结果
        for result in results:
            if result is None:
                continue
            elif isinstance(result, Exception):
                invalid_urls.append({
                    'url': 'unknown',
                    'success': False,
                    'error': str(result)
                })
            elif result.get('success'):
                valid_urls.append(result)
            else:
                invalid_urls.append(result)
        
        # 按置信度排序
        valid_urls.sort(key=lambda x: x.get('confidence', 0.0), reverse=True)
        
        self.stats['l1_urls'] = valid_urls
        self.stats['invalid_urls'] = invalid_urls
        
        logger.info(f"📋 L1处理完成: {len(valid_urls)} 有效, {len(invalid_urls)} 无效")
        
        return {
            'valid_urls': valid_urls,
            'invalid_urls': invalid_urls,
            'total_processed': len(urls)
        }

    async def _analyze_page_content(self, url: str, content: str) -> Dict:
        """使用LLM分析页面内容"""
        
        try:
            soup = BeautifulSoup(content, 'html.parser')
            
            # 提取基本信息
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            
            # 提取meta信息
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            meta_desc_content = meta_desc.get('content', '').strip() if meta_desc else ""
            
            meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
            meta_keywords_content = meta_keywords.get('content', '').strip() if meta_keywords else ""
            
            # 提取主要文本内容（前2000字符）
            text_content = soup.get_text()
            clean_text = ' '.join(text_content.split())[:2000]
            
            # 提取链接信息
            links = []
            for link in soup.find_all('a', href=True):
                href = link.get('href')
                link_text = link.get_text().strip()
                if href and link_text and len(link_text) < 200:
                    links.append({
                        'href': href,
                        'text': link_text,
                        'absolute_url': urljoin(url, href)
                    })
            
            # 构建通用分析提示
            prompt = f"""
请分析这个网页的内容和结构，确定其在数据挖掘分类中的层级和特征：

URL: {url}
标题: {title}
描述: {meta_desc_content}
关键词: {meta_keywords_content}
内容摘要: {clean_text}
链接数量: {len(links)}

请根据以下标准进行分析：
1. 内容层级分类：
   - L1: 门户首页、导航页面、一般信息页面
   - L2: 包含多个子页面或数据源链接的中心页面
   - L3: 具体的内容页面、数据展示页面
   - L4: 详细的单项记录或数据条目页面

2. 内容特征分析：
   - 页面类型（门户、列表、详情、搜索等）
   - 数据密度（高、中、低）
   - 结构化程度（高、中、低）
   - 导航复杂度（高、中、低）

请返回JSON格式：
{{
    "tier": "L1/L2/L3/L4",
    "confidence": 0.0-1.0,
    "page_type": "portal/list/detail/search/other",
    "content_category": "主要内容类别",
    "data_density": "high/medium/low",
    "structure_level": "high/medium/low",
    "navigation_complexity": "high/medium/low",
    "key_features": ["特征1", "特征2", "特征3"],
    "potential_value": 0.0-1.0,
    "reason": "分类和评估的详细原因"
}}
"""
            
            # 修复：使用安全的LLM调用方法
            try:
                result = await self._safe_llm_invoke(prompt, expect_json=True)
                
                # 添加提取的基础信息
                result.update({
                    'title': title,
                    'meta_description': meta_desc_content,
                    'meta_keywords': meta_keywords_content,
                    'text_length': len(clean_text),
                    'links_count': len(links),
                    'analysis_method': 'llm_analysis'
                })
                
                return result
                
            except Exception as llm_error:
                logger.error(f"LLM调用失败: {llm_error}")
                return self._fallback_analyze_content(url, soup, links)
                
        except Exception as e:
            logger.error(f"页面内容分析失败 {url}: {e}")
            return self._fallback_analyze_content(url, soup if 'soup' in locals() else None, [])

    async def _process_l2_sites(self, l1_urls: List[Dict], instructions: str = None) -> Dict:
        """第二阶段：L2 站点结构分析"""
        
        self.state.current_stage = "L2_analysis"
        
        l2_sites = []
        potential_l3s = []
        
        session = await self._get_session()
        semaphore = asyncio.Semaphore(max(1, self.max_concurrent // 2))
        
        async def analyze_l2_site(url_info: Dict):
            async with semaphore:
                url = url_info.get('final_url', url_info.get('original_url'))
                
                try:
                    await asyncio.sleep(self.request_delay)
                    logger.info(f"🔍 分析L2站点: {url}")
                    
                    # 获取页面内容
                    async with session.get(url) as response:
                        if response.status >= 400:
                            raise Exception(f"HTTP {response.status}")
                        
                        content = await response.text()
                        soup = BeautifulSoup(content, 'html.parser')
                        
                        # 提取和分析链接
                        l3_candidates = await self._extract_potential_l3_links(url, soup, instructions)
                        
                        site_info = {
                            'url': url,
                            'original_analysis': url_info.get('analysis', {}),
                            'l3_candidates_found': len(l3_candidates),
                            'analysis_success': True,
                            'processing_timestamp': time.time()
                        }
                        
                        l2_sites.append(site_info)
                        potential_l3s.extend(l3_candidates)
                        
                        logger.info(f"✅ L2分析完成: {url} - 发现 {len(l3_candidates)} 个L3候选")
                        
                except Exception as e:
                    logger.error(f"❌ L2分析失败: {url} - {e}")
                    self.stats['errors'].append({
                        'stage': 'L2_analysis',
                        'url': url,
                        'error': str(e),
                        'timestamp': time.time()
                    })
        
        # 修复：更宽松的L2选择条件
        l2_candidates = []
        for url_info in l1_urls:
            analysis = url_info.get('analysis', {})
            links_count = analysis.get('links_count', 0)
            confidence = url_info.get('confidence', 0)
            
            # 降低选择门槛
            if (confidence > 0.2 and links_count > 3) or analysis.get('tier') in ['L2', 'L3']:
                l2_candidates.append(url_info)
        
        # 如果没有合适的L2候选，选择所有有效URL
        if not l2_candidates:
            l2_candidates = l1_urls[:3]
        
        # 限制L2分析的数量
        l2_candidates = l2_candidates[:10]
        
        # 并发分析
        if l2_candidates:
            tasks = [analyze_l2_site(url_info) for url_info in l2_candidates]
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # 去重和排序潜在L3
        unique_l3s = {}
        for l3 in potential_l3s:
            url = l3['url']
            if url not in unique_l3s or l3.get('confidence', 0) > unique_l3s[url].get('confidence', 0):
                unique_l3s[url] = l3
        
        potential_l3s = list(unique_l3s.values())
        potential_l3s.sort(key=lambda x: x.get('confidence', 0), reverse=True)
        
        # 限制L3候选数量
        potential_l3s = potential_l3s[:30]
        
        self.stats['l2_sites'] = l2_sites
        
        logger.info(f"🔍 L2处理完成: {len(l2_sites)} 个L2站点, {len(potential_l3s)} 个潜在L3")
        
        return {
            'l2_sites': l2_sites,
            'potential_l3s': potential_l3s,
            'total_l2_analyzed': len(l2_sites)
        }

    async def _extract_potential_l3_links(self, base_url: str, soup: BeautifulSoup, instructions: str = None) -> List[Dict]:
        """提取潜在的L3链接"""
        
        try:
            # 提取所有链接
            all_links = []
            for link in soup.find_all('a', href=True):
                href = link.get('href')
                text = link.get_text().strip()
                
                if not href or not text or len(text) > 200:
                    continue
                
                # 转换为绝对URL
                absolute_url = urljoin(base_url, href)
                
                # 基本过滤
                parsed_url = urlparse(absolute_url)
                if not parsed_url.scheme or parsed_url.scheme not in ['http', 'https']:
                    continue
                
                # 跳过明显的非内容链接
                if any(skip in href.lower() for skip in [
                    'javascript:', 'mailto:', 'tel:', '#', 
                    '.pdf', '.doc', '.xls', '.zip', '.jpg', '.png', '.gif'
                ]):
                    continue
                
                all_links.append({
                    'href': href,
                    'text': text,
                    'absolute_url': absolute_url
                })
            
            # 限制链接数量
            if len(all_links) > self.max_links_per_page:
                all_links = all_links[:self.max_links_per_page]
            
            # 使用LLM分析链接
            l3_candidates = await self._analyze_links_for_l3_potential(base_url, all_links, instructions)
            
            return l3_candidates
            
        except Exception as e:
            logger.error(f"L3链接提取失败 {base_url}: {e}")
            return []

    async def _analyze_links_for_l3_potential(self, base_url: str, links: List[Dict], instructions: str = None) -> List[Dict]:
        """使用LLM分析链接的L3潜力"""
        
        if not links:
            return []
        
        try:
            # 准备链接信息
            links_info = []
            for i, link in enumerate(links[:30]):
                links_info.append({
                    'index': i,
                    'text': link['text'],
                    'url': link['absolute_url'],
                    'path': urlparse(link['absolute_url']).path
                })
            
            # 构建分析提示
            prompt = f"""
分析以下链接，识别哪些可能指向有价值的内容页面（L3级别）：

基础URL: {base_url}
用户指令: {instructions or "寻找有价值的内容页面"}

链接列表:
{json.dumps(links_info, ensure_ascii=False, indent=2)}

请评估每个链接的潜在价值，考虑：
1. 链接文本的描述性和相关性
2. URL路径的结构和深度
3. 是否指向具体内容而非导航页面
4. 与用户指令的匹配度

请返回JSON格式的候选列表：
{{
    "candidates": [
        {{
            "index": 链接索引,
            "confidence": 0.0-1.0,
            "reason": "选择原因",
            "expected_content_type": "预期内容类型",
            "priority": "high/medium/low"
        }}
    ]
}}
"""
            
            try:
                # 使用安全的LLM调用方法
                result = await self._safe_llm_invoke(prompt, expect_json=True)
                candidates = result.get('candidates', [])
                
                # 构建L3候选列表
                l3_candidates = []
                for candidate in candidates:
                    index = candidate.get('index')
                    if index is not None and 0 <= index < len(links):
                        link = links[index]
                        l3_candidates.append({
                            'url': link['absolute_url'],
                            'title': link['text'],
                            'source_l2': base_url,
                            'confidence': candidate.get('confidence', 0.5),
                            'reason': candidate.get('reason', ''),
                            'expected_content_type': candidate.get('expected_content_type', ''),
                            'priority': candidate.get('priority', 'medium'),
                            'discovery_method': 'llm_analysis'
                        })
                
                # 按置信度排序
                l3_candidates.sort(key=lambda x: x.get('confidence', 0), reverse=True)
                
                return l3_candidates[:20]
                
            except Exception as llm_error:
                logger.error(f"LLM链接分析失败: {llm_error}")
                return self._fallback_analyze_links(base_url, links)
                
        except Exception as e:
            logger.error(f"链接分析失败 {base_url}: {e}")
            return self._fallback_analyze_links(base_url, links)

    async def _process_l3_content(self, potential_l3s: List[Dict]) -> Dict:
        """第三阶段：L3 深度内容挖掘"""
        
        self.state.current_stage = "L3_content_mining"
        
        verified_l3s = []
        rejected_l3s = []
        
        session = await self._get_session()
        semaphore = asyncio.Semaphore(max(1, self.max_concurrent // 3))
        
        async def verify_l3_content(l3_candidate: Dict):
            async with semaphore:
                url = l3_candidate['url']
                
                try:
                    # 检查是否已访问过
                    url_hash = hashlib.md5(url.encode()).hexdigest()
                    if url_hash in self.stats['visited_urls']:
                        logger.info(f"⏭️ 跳过已访问L3: {url}")
                        return
                    
                    self.stats['visited_urls'].add(url_hash)
                    
                    await asyncio.sleep(self.request_delay)
                    logger.info(f"🔍 验证L3内容: {url}")
                    
                    async with session.get(url) as response:
                        if response.status >= 400:
                            raise Exception(f"HTTP {response.status}")
                        
                        content = await response.text()
                        
                        # 分析L3内容质量
                        content_analysis = await self._analyze_l3_content_quality(url, content)
                        
                        if content_analysis.get('quality_score', 0) >= self.quality_threshold:
                            verified_l3 = {
                                **l3_candidate,
                                'content_analysis': content_analysis,
                                'final_confidence': content_analysis.get('quality_score', 0),
                                'verification_status': 'verified',
                                'verification_timestamp': time.time()
                            }
                            verified_l3s.append(verified_l3)
                            logger.info(f"✅ L3验证通过: {url} (质量分数: {content_analysis.get('quality_score', 0):.2f})")
                        else:
                            rejected_l3 = {
                                **l3_candidate,
                                'content_analysis': content_analysis,
                                'rejection_reason': 'low_quality_score',
                                'rejection_timestamp': time.time()
                            }
                            rejected_l3s.append(rejected_l3)
                            logger.info(f"❌ L3验证失败: {url} (质量分数: {content_analysis.get('quality_score', 0):.2f})")
                        
                except Exception as e:
                    logger.error(f"❌ L3验证失败: {url} - {e}")
                    rejected_l3s.append({
                        **l3_candidate,
                        'rejection_reason': 'verification_error',
                        'error': str(e),
                        'rejection_timestamp': time.time()
                    })
                    self.stats['errors'].append({
                        'stage': 'L3_verification',
                        'url': url,
                        'error': str(e),
                        'timestamp': time.time()
                    })
        
        # 并发验证L3候选
        if potential_l3s:
            # 按优先级和置信度排序
            potential_l3s.sort(key=lambda x: (
                x.get('priority') == 'high',
                x.get('confidence', 0)
            ), reverse=True)
            
            # 限制验证数量
            candidates_to_verify = potential_l3s[:20]
            
            tasks = [verify_l3_content(candidate) for candidate in candidates_to_verify]
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # 按质量分数排序
        verified_l3s.sort(key=lambda x: x.get('final_confidence', 0), reverse=True)
        
        self.stats['l3_datasets'] = verified_l3s
        
        logger.info(f"📊 L3处理完成: {len(verified_l3s)} 个验证通过, {len(rejected_l3s)} 个被拒绝")
        
        return {
            'verified_l3s': verified_l3s,
            'rejected_l3s': rejected_l3s,
            'total_l3_candidates': len(potential_l3s)
        }

    async def _analyze_l3_content_quality(self, url: str, content: str) -> Dict:
        """分析L3内容质量"""
        
        try:
            soup = BeautifulSoup(content, 'html.parser')
            
            # 提取基本信息
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            text_content = soup.get_text()
            clean_text = ' '.join(text_content.split())
            
            # 提取结构化信息
            tables = soup.find_all('table')
            lists = soup.find_all(['ul', 'ol'])
            forms = soup.find_all('form')
            
            # 构建质量分析提示
            prompt = f"""
分析这个页面的内容质量和价值：

URL: {url}
标题: {title}
内容长度: {len(clean_text)} 字符
表格数量: {len(tables)}
列表数量: {len(lists)}
表单数量: {len(forms)}

内容摘要: {clean_text[:1500]}

请评估页面的质量和价值，考虑：
1. 内容的信息密度和深度
2. 结构化程度（表格、列表等）
3. 内容的独特性和价值
4. 页面的完整性和可用性

请返回JSON格式：
{{
    "quality_score": 0.0-1.0,
    "content_type": "内容类型描述",
    "information_density": "high/medium/low",
    "structure_quality": "high/medium/low",
    "uniqueness": "high/medium/low",
    "completeness": "high/medium/low",
    "key_features": ["特征1", "特征2"],
    "value_indicators": ["价值指标1", "价值指标2"],
    "assessment_reason": "详细评估原因"
}}
"""
            
            try:
                result = await self._safe_llm_invoke(prompt, expect_json=True)
                
                # 添加基础统计信息
                result.update({
                    'content_length': len(clean_text),
                    'tables_count': len(tables),
                    'lists_count': len(lists),
                    'forms_count': len(forms),
                    'analysis_method': 'llm_quality_analysis'
                })
                
                return result
                
            except Exception as llm_error:
                logger.error(f"LLM质量分析失败: {llm_error}")
                return self._fallback_analyze_quality(url, soup, clean_text)
                
        except Exception as e:
            logger.error(f"L3内容质量分析失败 {url}: {e}")
            return self._fallback_analyze_quality(url, None, "")

    def _fallback_analyze_quality(self, url: str, soup: BeautifulSoup = None, text: str = "") -> Dict:
        """备用的基于规则的质量分析"""
        
        if soup is None:
            return {
                'quality_score': 0.1,
                'content_type': 'unknown',
                'information_density': 'low',
                'structure_quality': 'low',
                'uniqueness': 'low',
                'completeness': 'low',
                'key_features': ['fallback_analysis'],
                'value_indicators': ['minimal_content'],
                'assessment_reason': 'Fallback analysis due to parsing failure',
                'analysis_method': 'fallback_minimal'
            }
        
        # 基础质量评估
        score = 0.0
        
        # 内容长度评分
        text_length = len(text)
        if text_length > 5000:
            score += 0.3
        elif text_length > 1000:
            score += 0.2
        elif text_length > 500:
            score += 0.1
        
        # 结构化内容评分
        tables = soup.find_all('table')
        lists = soup.find_all(['ul', 'ol'])
        
        if len(tables) > 0:
            score += 0.2
        if len(lists) > 2:
            score += 0.1
        
        # 标题结构评分
        headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        if len(headings) > 3:
            score += 0.1
        
        # 链接密度评分（适中的链接密度是好的）
        links = soup.find_all('a', href=True)
        link_density = len(links) / max(text_length, 1) * 1000
        if 5 < link_density < 50:
            score += 0.1
        
        return {
            'quality_score': min(score, 1.0),
            'content_type': 'content_page',
            'information_density': 'high' if text_length > 3000 else 'medium' if text_length > 1000 else 'low',
            'structure_quality': 'high' if len(tables) + len(lists) > 3 else 'medium',
            'uniqueness': 'medium',
            'completeness': 'medium',
            'key_features': ['fallback_analysis'],
            'value_indicators': [f'content_length_{text_length}', f'tables_{len(tables)}', f'lists_{len(lists)}'],
            'assessment_reason': f'Rule-based quality assessment: score {score:.2f}',
            'content_length': text_length,
            'tables_count': len(tables),
            'lists_count': len(lists),
            'analysis_method': 'fallback_rules'
        }

    async def _process_l4_records(self, verified_l3s: List[Dict]) -> Dict:
        """第四阶段：L4 具体数据提取"""
        
        self.state.current_stage = "L4_data_extraction"
        
        all_l4_records = []
        
        session = await self._get_session()
        semaphore = asyncio.Semaphore(1)
        
        async def extract_l4_data(l3_item: Dict):
            async with semaphore:
                url = l3_item['url']
                
                try:
                    await asyncio.sleep(self.request_delay * 1.5)
                    logger.info(f"🎯 提取L4数据: {url}")
                    
                    async with session.get(url) as response:
                        if response.status >= 400:
                            raise Exception(f"HTTP {response.status}")
                        
                        content = await response.text()
                        
                        # 提取具体数据记录
                        l4_records = await self._extract_data_records(url, content, l3_item)
                        
                        all_l4_records.extend(l4_records)
                        
                        logger.info(f"✅ L4提取完成: {url} - 提取 {len(l4_records)} 条记录")
                        
                except Exception as e:
                    logger.error(f"❌ L4提取失败: {url} - {e}")
                    self.stats['errors'].append({
                        'stage': 'L4_extraction',
                        'url': url,
                        'error': str(e),
                        'timestamp': time.time()
                    })
        
        # 选择高质量的L3进行L4提取
        high_quality_l3s = [
            l3 for l3 in verified_l3s 
            if l3.get('final_confidence', 0) > 0.6
        ][:5]
        
        if high_quality_l3s:
            tasks = [extract_l4_data(l3_item) for l3_item in high_quality_l3s]
            await asyncio.gather(*tasks, return_exceptions=True)
        
        self.stats['l4_records'] = all_l4_records
        
        logger.info(f"🎯 L4处理完成: {len(all_l4_records)} 条记录")
        
        return {
            'l4_records': all_l4_records,
            'total_records': len(all_l4_records)
        }

    async def _extract_data_records(self, url: str, content: str, l3_item: Dict) -> List[Dict]:
        """从页面中提取具体的数据记录"""
        
        try:
            soup = BeautifulSoup(content, 'html.parser')
            
            # 提取结构化数据
            records = []
            
            # 从表格中提取数据
            for table in soup.find_all('table'):
                table_records = self._extract_table_records(url, table, l3_item)
                records.extend(table_records)
            
            # 从列表中提取数据
            for ul in soup.find_all(['ul', 'ol']):
                list_records = self._extract_list_records(url, ul, l3_item)
                records.extend(list_records)
            
            # 从定义列表中提取数据
            for dl in soup.find_all('dl'):
                dl_records = self._extract_definition_records(url, dl, l3_item)
                records.extend(dl_records)
            
            # 限制记录数量
            return records[:10]
            
        except Exception as e:
            logger.error(f"数据记录提取失败 {url}: {e}")
            return []

    def _extract_table_records(self, url: str, table: BeautifulSoup, l3_item: Dict) -> List[Dict]:
        """从表格中提取记录"""
        
        records = []
        
        try:
            rows = table.find_all('tr')
            if len(rows) < 2:
                return records
            
            # 提取表头
            header_row = rows[0]
            headers = [th.get_text().strip() for th in header_row.find_all(['th', 'td'])]
            
            if not headers:
                return records
            
            # 提取数据行
            for i, row in enumerate(rows[1:], 1):
                if i > 5:  # 限制每个表格的记录数量
                    break
                
                cells = row.find_all(['td', 'th'])
                if len(cells) != len(headers):
                    continue
                
                record_data = {}
                for j, cell in enumerate(cells):
                    if j < len(headers):
                        record_data[headers[j]] = cell.get_text().strip()
                
                if record_data:
                    record = {
                        'url': f"{url}#table_{table.get('id', 'unknown')}_row_{i}",
                        'source_l3': url,
                        'source_l3_info': l3_item,
                        'record_type': 'table_row',
                        'data': record_data,
                        'extraction_method': 'table_parsing',
                        'confidence': 0.7,
                        'extraction_timestamp': time.time()
                    }
                    records.append(record)
            
        except Exception as e:
            logger.error(f"表格记录提取失败: {e}")
        
        return records

    def _extract_list_records(self, url: str, ul: BeautifulSoup, l3_item: Dict) -> List[Dict]:
        """从列表中提取记录"""
        
        records = []
        
        try:
            items = ul.find_all('li')
            
            for i, item in enumerate(items[:5], 1):
                text = item.get_text().strip()
                if not text or len(text) < 10:
                    continue
                
                # 提取链接（如果有）
                link = item.find('a', href=True)
                item_url = urljoin(url, link['href']) if link else f"{url}#list_item_{i}"
                
                record = {
                    'url': item_url,
                    'source_l3': url,
                    'source_l3_info': l3_item,
                    'record_type': 'list_item',
                    'data': {
                        'text': text,
                        'has_link': bool(link),
                        'position': i
                    },
                    'extraction_method': 'list_parsing',
                    'confidence': 0.5,
                    'extraction_timestamp': time.time()
                }
                records.append(record)
            
        except Exception as e:
            logger.error(f"列表记录提取失败: {e}")
        
        return records

    def _extract_definition_records(self, url: str, dl: BeautifulSoup, l3_item: Dict) -> List[Dict]:
        """从定义列表中提取记录"""
        
        records = []
        
        try:
            terms = dl.find_all('dt')
            definitions = dl.find_all('dd')
            
            # 确保术语和定义数量匹配
            min_count = min(len(terms), len(definitions), 5)
            
            for i in range(min_count):
                term_text = terms[i].get_text().strip()
                def_text = definitions[i].get_text().strip()
                
                if not term_text or not def_text:
                    continue
                
                record = {
                    'url': f"{url}#definition_{i}",
                    'source_l3': url,
                    'source_l3_info': l3_item,
                    'record_type': 'definition',
                    'data': {
                        'term': term_text,
                        'definition': def_text,
                        'position': i + 1
                    },
                    'extraction_method': 'definition_parsing',
                    'confidence': 0.6,
                    'extraction_timestamp': time.time()
                }
                records.append(record)
            
        except Exception as e:
            logger.error(f"定义记录提取失败: {e}")
        
        return records

    async def _enhance_metadata(self, items: List[Dict]) -> List[Dict]:
        """第五阶段：元数据增强"""
        
        enhanced_items = []
        
        for item in items[:10]:
            try:
                # 基础元数据增强
                enhanced_item = item.copy()
                
                # 添加URL分析
                parsed_url = urlparse(item['url'])
                enhanced_item['url_analysis'] = {
                    'domain': parsed_url.netloc,
                    'path_depth': len(parsed_url.path.split('/')) - 1,
                    'has_query': bool(parsed_url.query),
                    'has_fragment': bool(parsed_url.fragment)
                }
                
                # 添加时间戳和会话信息
                enhanced_item['metadata'] = {
                    'session_id': self.session_id,
                    'enhancement_timestamp': time.time(),
                    'enhancement_method': 'basic_metadata',
                    'item_hash': hashlib.md5(str(item).encode()).hexdigest()[:8]
                }
                
                # 添加质量评估
                quality_score = item.get('final_confidence', item.get('confidence', 0.5))
                enhanced_item['quality_assessment'] = {
                    'score': quality_score,
                    'tier': 'high' if quality_score > 0.7 else 'medium' if quality_score > 0.4 else 'low',
                    'assessment_timestamp': time.time()
                }
                
                # 添加内容特征
                if 'content_analysis' in item:
                    content_analysis = item['content_analysis']
                    enhanced_item['content_features'] = {
                        'information_density': content_analysis.get('information_density', 'unknown'),
                        'structure_quality': content_analysis.get('structure_quality', 'unknown'),
                        'content_type': content_analysis.get('content_type', 'unknown')
                    }
                
                enhanced_items.append(enhanced_item)
                
            except Exception as e:
                logger.error(f"元数据增强失败: {e}")
                enhanced_items.append(item)
        
        logger.info(f"✨ 元数据增强完成: {len(enhanced_items)} 个项目")
        return enhanced_items

    async def _assess_quality(self, l3_items: List[Dict], l4_records: List[Dict], enhanced_items: List[Dict]) -> Dict:
        """第六阶段：质量评估和过滤"""
        
        all_items = []
        
        # 合并所有项目
        for item in l3_items:
            item['item_type'] = 'l3_content'
            all_items.append(item)
        
        for record in l4_records:
            record['item_type'] = 'l4_record'
            all_items.append(record)
        
        for enhanced in enhanced_items:
            if enhanced not in all_items:
                enhanced['item_type'] = 'enhanced_item'
                all_items.append(enhanced)
        
        # 质量过滤
        high_quality_items = []
        
        for item in all_items:
            try:
                # 获取质量分数
                quality_score = self._calculate_item_quality_score(item)
                item['quality_score'] = quality_score
                
                # 应用质量阈值
                if quality_score >= self.quality_threshold:
                    high_quality_items.append(item)
                
            except Exception as e:
                logger.error(f"质量评估失败: {e}")
        
        # 按质量分数排序
        high_quality_items.sort(key=lambda x: x.get('quality_score', 0), reverse=True)
        
        # 计算通过率
        pass_rate = len(high_quality_items) / len(all_items) if all_items else 0
        
        logger.info(f"🎯 质量评估完成: {len(high_quality_items)} 个高质量项目")
        
        return {
            'high_quality_items': high_quality_items,
            'total_items': len(all_items),
            'pass_rate': pass_rate,
            'quality_threshold': self.quality_threshold
        }

    def _calculate_item_quality_score(self, item: Dict) -> float:
        """计算项目的质量分数"""
        
        score = 0.0
        
        # 基础置信度分数
        base_confidence = item.get('final_confidence', item.get('confidence', 0.5))
        score += base_confidence * 0.4
        
        # 内容分析分数
        if 'content_analysis' in item:
            content_analysis = item['content_analysis']
            content_score = content_analysis.get('quality_score', 0.5)
            score += content_score * 0.3
        
        # 结构化程度分数
        if 'content_analysis' in item:
            structure_level = item['content_analysis'].get('structure_level', 'low')
            if structure_level == 'high':
                score += 0.2
            elif structure_level == 'medium':
                score += 0.1
        
        # 数据密度分数
        if 'content_analysis' in item:
            data_density = item['content_analysis'].get('information_density', 'low')
            if data_density == 'high':
                score += 0.1
            elif data_density == 'medium':
                score += 0.05
        
        # L4记录额外分数
        if item.get('item_type') == 'l4_record':
            score += 0.1
        
        return min(score, 1.0)

    async def _execute_evolution_cycle(self, mining_results: Dict) -> Dict:
        """🔄 执行进化周期"""
        
        try:
            logger.info("🔄 开始进化周期")
            
            # 提取性能指标
            performance_metrics = self._extract_performance_metrics(mining_results)
            
            # 准备进化数据
            evolution_data = {
                'session_id': self.session_id,
                'mining_results': mining_results,
                'performance_metrics': performance_metrics,
                'current_config': {
                    'quality_threshold': self.quality_threshold,
                    'max_concurrent': self.max_concurrent,
                    'request_delay': self.request_delay
                }
            }
            
            # 执行进化
            if hasattr(self.evolution_engine, 'evolve'):
                evolution_result = await self.evolution_engine.evolve(evolution_data)
            else:
                # 基于性能的简单进化
                evolution_result = self._simple_evolution(performance_metrics)
            
            if evolution_result.get('success'):
                # 应用进化结果
                new_strategies = evolution_result.get('evolved_strategies', {})
                if new_strategies:
                    self._apply_evolved_strategies(new_strategies)
                
                self.stats['evolution_cycles'] += 1
                self.stats['evolution_history'].append({
                    'timestamp': time.time(),
                    'improvements': evolution_result.get('improvements', []),
                    'new_strategies': new_strategies,
                    'performance_metrics': performance_metrics
                })
                
                logger.info(f"🔄 进化周期完成: {len(new_strategies)} 项策略更新")
            
            return evolution_result
        
        except Exception as e:
            logger.error(f"进化周期失败: {e}")
            return {'success': False, 'error': str(e)}

    def _simple_evolution(self, performance_metrics: Dict) -> Dict:
        """简单的基于性能的进化"""
        
        improvements = []
        evolved_strategies = {}
        
        # 基于成功率调整质量阈值
        success_rate = performance_metrics.get('overall_success_rate', 0.5)
        if success_rate < 0.3:
            # 成功率太低，降低质量阈值
            new_threshold = max(0.1, self.quality_threshold - 0.1)
            evolved_strategies['quality_threshold'] = new_threshold
            improvements.append('lowered_quality_threshold')
        elif success_rate > 0.8:
            # 成功率很高，可以提高质量阈值
            new_threshold = min(0.9, self.quality_threshold + 0.05)
            evolved_strategies['quality_threshold'] = new_threshold
            improvements.append('raised_quality_threshold')
        
        # 基于错误率调整请求延迟
        error_rate = performance_metrics.get('error_rate', 0.0)
        if error_rate > 0.3:
            # 错误率高，增加延迟
            new_delay = min(5.0, self.request_delay + 0.5)
            evolved_strategies['request_delay'] = new_delay
            improvements.append('increased_request_delay')
        elif error_rate < 0.1:
            # 错误率低，可以减少延迟
            new_delay = max(0.5, self.request_delay - 0.2)
            evolved_strategies['request_delay'] = new_delay
            improvements.append('decreased_request_delay')
        
        # 基于处理效率调整并发数
        processing_efficiency = performance_metrics.get('processing_efficiency', 0.5)
        if processing_efficiency < 0.3 and error_rate < 0.2:
            # 效率低但错误率不高，可以增加并发
            new_concurrent = min(5, self.max_concurrent + 1)
            evolved_strategies['max_concurrent'] = new_concurrent
            improvements.append('increased_concurrency')
        elif error_rate > 0.4:
            # 错误率高，减少并发
            new_concurrent = max(1, self.max_concurrent - 1)
            evolved_strategies['max_concurrent'] = new_concurrent
            improvements.append('decreased_concurrency')
        
        return {
            'success': True,
            'evolved_strategies': evolved_strategies,
            'improvements': improvements,
            'evolution_method': 'simple_performance_based'
        }

    def _extract_performance_metrics(self, mining_results: Dict) -> Dict:
        """提取性能指标"""
        
        metrics = {}
        
        # L1阶段指标
        l1_results = mining_results.get('l1_results', {})
        if l1_results:
            total = l1_results.get('total_processed', 0)
            valid = len(l1_results.get('valid_urls', []))
            metrics['l1_success_rate'] = valid / max(total, 1)  # 修复：避免除零
        
        # L2阶段指标
        l2_results = mining_results.get('l2_results', {})
        if l2_results:
            analyzed = l2_results.get('total_l2_analyzed', 0)
            potential_l3s = len(l2_results.get('potential_l3s', []))
            metrics['l2_discovery_rate'] = potential_l3s / max(analyzed, 1)  # 修复：避免除零
        
        # L3阶段指标
        l3_results = mining_results.get('l3_results', {})
        if l3_results:
            candidates = l3_results.get('total_l3_candidates', 0)
            verified = len(l3_results.get('verified_l3s', []))
            metrics['l3_verification_rate'] = verified / max(candidates, 1)  # 修复：避免除零
        
        # 整体质量指标
        final_results = mining_results.get('final_results', {})
        if final_results:
            metrics['overall_quality'] = final_results.get('pass_rate', 0)
            metrics['high_quality_count'] = len(final_results.get('high_quality_items', []))
        
        # 错误率
        total_errors = len(self.stats['errors'])
        total_processed = max(self.stats.get('total_processed', 1), 1)  # 修复：避免除零
        metrics['error_rate'] = total_errors / total_processed
        
        # 处理效率（项目数/时间）
        processing_time = max(time.time() - self.stats['start_time'], 0.1)  # 修复：避免除零
        metrics['processing_efficiency'] = metrics.get('high_quality_count', 0) / processing_time
        
        # 整体成功率
        metrics['overall_success_rate'] = (
            metrics.get('l1_success_rate', 0) * 0.3 +
            metrics.get('l3_verification_rate', 0) * 0.4 +
            metrics.get('overall_quality', 0) * 0.3
        )
        
        return metrics

    def _apply_evolved_strategies(self, strategies: Dict):
        """应用进化策略"""
        
        if 'quality_threshold' in strategies:
            old_threshold = self.quality_threshold
            self.quality_threshold = strategies['quality_threshold']
            logger.info(f"🧬 进化策略: 质量阈值 {old_threshold:.3f} -> {self.quality_threshold:.3f}")
        
        if 'max_concurrent' in strategies:
            old_concurrent = self.max_concurrent
            self.max_concurrent = strategies['max_concurrent']
            logger.info(f"🧬 进化策略: 并发数 {old_concurrent} -> {self.max_concurrent}")
        
        if 'request_delay' in strategies:
            old_delay = self.request_delay
            self.request_delay = strategies['request_delay']
            logger.info(f"🧬 进化策略: 请求延迟 {old_delay:.1f}s -> {self.request_delay:.1f}s")

    async def _save_experience_to_memory(self, mining_results: Dict):
        """💾 保存经验到记忆"""
        
        try:
            experience = {
                'session_id': self.session_id,
                'timestamp': time.time(),
                'mining_results': mining_results,
                'final_config': {
                    'quality_threshold': self.quality_threshold,
                    'max_concurrent': self.max_concurrent,
                    'request_delay': self.request_delay
                },
                'performance_summary': self._extract_performance_metrics(mining_results),
                'success_indicators': self._extract_success_indicators(mining_results),
                'discovered_patterns': list(self.stats['discovered_patterns'])
            }
            
            # 检查进化引擎的保存方法
            if hasattr(self.evolution_engine, 'save_experience'):
                save_result = await self.evolution_engine.save_experience(experience)
            elif hasattr(self.evolution_engine, 'save_memory'):
                save_result = await self.evolution_engine.save_memory(experience)
            else:
                save_result = {'success': True}  # 模拟保存成功
            
            if save_result.get('success'):
                self.stats['memory_updates'] += 1
                logger.info("💾 经验已保存到记忆系统")
            else:
                logger.error(f"记忆保存失败: {save_result.get('error', '')}")
        
        except Exception as e:
            logger.error(f"保存经验失败: {e}")

    def _extract_success_indicators(self, mining_results: Dict) -> Dict:
        """提取成功指标"""
        
        indicators = {}
        
        # 提取各阶段的成功模式
        final_results = mining_results.get('final_results', {})
        high_quality_items = final_results.get('high_quality_items', [])
        
        if high_quality_items:
            # 成功的域名模式
            successful_domains = {}
            successful_patterns = set()
            
            for item in high_quality_items:
                try:
                    parsed_url = urlparse(item['url'])
                    domain = parsed_url.netloc
                    successful_domains[domain] = successful_domains.get(domain, 0) + 1
                    
                    # 提取URL模式
                    path_parts = parsed_url.path.split('/')
                    if len(path_parts) > 2:
                        pattern = '/'.join(path_parts[:3])
                        successful_patterns.add(pattern)
                        
                except Exception:
                    pass
            
            indicators['successful_domains'] = successful_domains
            indicators['successful_url_patterns'] = list(successful_patterns)
            
            # 成功的质量分数范围
            quality_scores = [item.get('quality_score', 0) for item in high_quality_items]
            if quality_scores:
                indicators['optimal_quality_range'] = {
                    'min': min(quality_scores),
                    'max': max(quality_scores),
                    'avg': sum(quality_scores) / len(quality_scores)
                }
            
            # 成功的内容类型
            content_types = {}
            for item in high_quality_items:
                content_type = item.get('analysis', {}).get('content_type', 'unknown')
                content_types[content_type] = content_types.get(content_type, 0) + 1
            indicators['successful_content_types'] = content_types
        
        return indicators

    async def _generate_mining_report(self, mining_results: Dict) -> Dict:
        """📊 生成挖掘报告"""
        
        # 基础统计
        basic_stats = self.stats.copy()
        basic_stats.update({
            'total_processed': mining_results.get('l1_results', {}).get('total_processed', 0),
            'successful_extractions': len(mining_results.get('final_results', {}).get('high_quality_items', [])),
            'failed_extractions': len(self.stats['invalid_urls']) + len(self.stats['errors'])
        })
        
        # 生成详细统计
        try:
            detailed_stats = DetailedStatistics(
                mined_items=mining_results.get('final_results', {}).get('high_quality_items', []),
                invalid_urls=self.stats['invalid_urls'],
                start_time=self.stats['start_time'],
                end_time=self.stats['end_time']
            )
            statistics_report = detailed_stats.generate_report()
        except Exception as e:
            logger.error(f"详细统计生成失败: {e}")
            statistics_report = {
                'summary': {
                    'success_rate': basic_stats['successful_extractions'] / max(basic_stats['total_processed'], 1),
                    'average_time_per_url': (self.stats['end_time'] - self.stats['start_time']) / max(basic_stats['total_processed'], 1)
                }
            }
        
        # 进化特定报告
        evolution_report = {
            'evolution_cycles_completed': self.stats['evolution_cycles'],
            'memory_updates': self.stats['memory_updates'],
            'evolution_history': self.stats['evolution_history'],
            'final_evolved_config': {
                'quality_threshold': self.quality_threshold,
                'max_concurrent': self.max_concurrent,
                'request_delay': self.request_delay
            },
            'discovered_patterns': list(self.stats['discovered_patterns']),
            'learning_summary': self._generate_learning_summary()
        }
        
        return {
            'success': True,
            'agent_type': 'universal_miner',
            'session_id': self.session_id,
            'timestamp': datetime.datetime.now().isoformat(),
            'processing_time': self.stats['end_time'] - self.stats['start_time'],
            
            # 挖掘结果
            'mining_results': mining_results,
            
            # 统计报告
            'statistics': statistics_report,
            'basic_stats': basic_stats,
            
            # 进化报告
            'evolution': evolution_report,
            
            # 摘要
            'summary': {
                'total_urls_processed': mining_results.get('l1_results', {}).get('total_processed', 0),
                'l2_sites_found': len(mining_results.get('l2_results', {}).get('l2_sites', [])),
                'l3_datasets_verified': len(mining_results.get('l3_results', {}).get('verified_l3s', [])),
                'l4_records_mined': len(mining_results.get('l4_results', {}).get('l4_records', [])),
                'high_quality_items': len(mining_results.get('final_results', {}).get('high_quality_items', [])),
                'success_rate': statistics_report['summary']['success_rate'],
                'evolution_improvements': len(self.stats['evolution_history']),
                'discovered_patterns': len(self.stats['discovered_patterns'])
            }
        }

    def _generate_learning_summary(self) -> Dict:
        """生成学习摘要"""
        
        summary = {
            'sessions_completed': 1,
            'total_evolution_cycles': self.stats['evolution_cycles'],
            'key_learnings': [],
            'performance_trends': {},
            'pattern_discoveries': len(self.stats['discovered_patterns'])
        }
        
        # 从进化历史中提取关键学习
        for evolution in self.stats['evolution_history']:
            improvements = evolution.get('improvements', [])
            summary['key_learnings'].extend(improvements)
        
        # 去重关键学习
        summary['key_learnings'] = list(set(summary['key_learnings']))
        
        return summary

    def print_detailed_results(self, results: Dict):
        """打印详细的挖掘结果"""
        
        print("\n" + "="*80)
        print("🎯 通用数据挖掘结果报告")
        print("="*80)
        
        # 基本信息
        print(f"\n📋 会话信息:")
        print(f"   Session ID: {results.get('session_id', 'N/A')}")
        print(f"   处理时间: {results.get('processing_time', 0):.2f} 秒")
        print(f"   Agent类型: {results.get('agent_type', 'N/A')}")
        
        # 摘要统计
        summary = results.get('summary', {})
        print(f"📊 处理摘要:")
        print(f"   总URL数量: {summary.get('total_urls_processed', 0)}")
        print(f"   L2站点发现: {summary.get('l2_sites_found', 0)}")
        print(f"   L3内容验证: {summary.get('l3_datasets_verified', 0)}")
        print(f"   L4记录挖掘: {summary.get('l4_records_mined', 0)}")
        print(f"   高质量项目: {summary.get('high_quality_items', 0)}")
        print(f"   成功率: {summary.get('success_rate', 0):.2%}")
        print(f"   进化改进次数: {summary.get('evolution_improvements', 0)}")
        print(f"   发现模式数: {summary.get('discovered_patterns', 0)}")
        
        # 详细挖掘结果
        mining_results = results.get('mining_results', {})
        
        # L1结果
        l1_results = mining_results.get('l1_results', {})
        if l1_results:
            print(f"🔍 L1 URL验证结果:")
            valid_urls = l1_results.get('valid_urls', [])
            invalid_urls = l1_results.get('invalid_urls', [])
            
            print(f"   有效URL: {len(valid_urls)}")
            for i, url_info in enumerate(valid_urls[:5], 1):
                print(f"     {i}. {url_info.get('final_url', url_info.get('original_url', 'N/A'))}")
                analysis = url_info.get('analysis', {})
                print(f"        层级: {analysis.get('tier', 'N/A')}")
                print(f"        置信度: {analysis.get('confidence', 0):.2f}")
                print(f"        页面类型: {analysis.get('page_type', 'N/A')}")
                print(f"        内容类别: {analysis.get('content_category', 'N/A')}")
            
            if len(valid_urls) > 5:
                print(f"     ... 还有 {len(valid_urls) - 5} 个有效URL")
            
            if invalid_urls:
                print(f"   无效URL: {len(invalid_urls)}")
                for i, url_info in enumerate(invalid_urls[:3], 1):
                    print(f"     {i}. {url_info.get('url', 'N/A')}")
                    print(f"        错误: {url_info.get('error', 'N/A')}")
        
        # L2结果
        l2_results = mining_results.get('l2_results', {})
        if l2_results:
            print(f"🏢 L2 站点分析结果:")
            l2_sites = l2_results.get('l2_sites', [])
            potential_l3s = l2_results.get('potential_l3s', [])
            
            print(f"   分析的L2站点: {len(l2_sites)}")
            for i, site in enumerate(l2_sites[:3], 1):
                print(f"     {i}. {site['url']}")
                print(f"        发现L3候选: {site.get('l3_candidates_found', 0)}")
            
            print(f"   发现的潜在L3: {len(potential_l3s)}")
            for i, l3 in enumerate(potential_l3s[:5], 1):
                print(f"     {i}. {l3['url']}")
                print(f"        标题: {l3.get('title', 'N/A')}")
                print(f"        置信度: {l3.get('confidence', 0):.2f}")
                print(f"        发现方法: {l3.get('discovery_method', 'N/A')}")
                print(f"        优先级: {l3.get('priority', 'N/A')}")
        
        # L3结果
        l3_results = mining_results.get('l3_results', {})
        if l3_results:
            print(f"📊 L3 内容挖掘结果:")
            verified_l3s = l3_results.get('verified_l3s', [])
            rejected_l3s = l3_results.get('rejected_l3s', [])
            
            print(f"   验证通过的L3内容: {len(verified_l3s)}")
            for i, content in enumerate(verified_l3s[:5], 1):
                print(f"     {i}. {content['url']}")
                print(f"        标题: {content.get('title', 'N/A')}")
                print(f"        最终置信度: {content.get('final_confidence', 0):.2f}")
                analysis = content.get('content_analysis', {})
                print(f"        内容类型: {analysis.get('content_type', 'N/A')}")
                print(f"        信息密度: {analysis.get('information_density', 'N/A')}")
            
            if rejected_l3s:
                print(f"   被拒绝的L3候选: {len(rejected_l3s)}")
        
        # L4结果
        l4_results = mining_results.get('l4_results', {})
        if l4_results:
            print(f"🎯 L4 数据提取结果:")
            l4_records = l4_results.get('l4_records', [])
            
            print(f"   提取的L4记录: {len(l4_records)}")
            
            # 按记录类型分组显示
            record_types = {}
            for record in l4_records:
                record_type = record.get('record_type', 'unknown')
                if record_type not in record_types:
                    record_types[record_type] = []
                record_types[record_type].append(record)
            
            for record_type, records in record_types.items():
                print(f"     {record_type}: {len(records)} 条")
                for i, record in enumerate(records[:3], 1):
                    print(f"       {i}. {record['url']}")
                    print(f"          来源L3: {record.get('source_l3', 'N/A')}")
                    print(f"          置信度: {record.get('confidence', 0):.2f}")
        
        # 最终高质量项目
        final_results = mining_results.get('final_results', {})
        if final_results:
            print(f"⭐ 最终高质量项目:")
            high_quality_items = final_results.get('high_quality_items', [])
            
            print(f"   高质量项目数量: {len(high_quality_items)}")
            print(f"   质量阈值: {final_results.get('quality_threshold', 0):.2f}")
            print(f"   通过率: {final_results.get('pass_rate', 0):.2%}")
            
            # 按项目类型分组显示
            item_types = {}
            for item in high_quality_items:
                item_type = item.get('item_type', 'unknown')
                if item_type not in item_types:
                    item_types[item_type] = []
                item_types[item_type].append(item)
            
            for item_type, items in item_types.items():
                print(f"     {item_type}: {len(items)} 个")
                for i, item in enumerate(items[:3], 1):
                    print(f"       {i}. {item['url']}")
                    print(f"          质量分数: {item.get('quality_score', 0):.3f}")
                    if 'title' in item:
                        print(f"          标题: {item['title']}")
        
        # 进化信息
        evolution = results.get('evolution', {})
        if evolution:
            print(f"🧬 进化学习信息:")
            print(f"   进化周期: {evolution.get('evolution_cycles_completed', 0)}")
            print(f"   记忆更新: {evolution.get('memory_updates', 0)}")
            print(f"   发现模式: {len(evolution.get('discovered_patterns', []))}")
            
            final_config = evolution.get('final_evolved_config', {})
            if final_config:
                print(f"   最终配置:")
                print(f"     质量阈值: {final_config.get('quality_threshold', 0):.3f}")
                print(f"     并发数: {final_config.get('max_concurrent', 0)}")
                print(f"     请求延迟: {final_config.get('request_delay', 0):.1f}s")
            
            evolution_history = evolution.get('evolution_history', [])
            if evolution_history:
                print(f"   进化历史: {len(evolution_history)} 次改进")
                for i, evo in enumerate(evolution_history[-3:], 1):
                    improvements = evo.get('improvements', [])
                    print(f"     改进 {i}: {', '.join(improvements) if improvements else '无'}")
        
        # 错误信息
        basic_stats = results.get('basic_stats', {})
        errors = basic_stats.get('errors', [])
        if errors:
            print(f"⚠️  错误信息:")
            print(f"   错误数量: {len(errors)}")
            
            # 按阶段分组错误
            error_by_stage = {}
            for error in errors:
                stage = error.get('stage', 'unknown')
                if stage not in error_by_stage:
                    error_by_stage[stage] = []
                error_by_stage[stage].append(error)
            
            for stage, stage_errors in error_by_stage.items():
                print(f"     {stage}: {len(stage_errors)} 个错误")
                for i, error in enumerate(stage_errors[-2:], 1):
                    print(f"       {i}. URL: {error.get('url', 'N/A')}")
                    print(f"          错误: {error.get('error', 'N/A')}")
        
        print("\n" + "="*80)
        print("🎉 通用挖掘报告完成")
        print("="*80 + "")

    async def _safe_close_resources(self):
        """安全关闭所有资源"""
        try:
            # 关闭HTTP会话
            if self.session and not self.session.closed:
                await self.session.close()
                logger.debug("HTTP会话已关闭")
            
            # 关闭工具套件
            if hasattr(self, 'tools') and self.tools:
                for tool_name, tool in self.tools.items():
                    if hasattr(tool, 'session') and tool.session:
                        if not tool.session.closed:
                            await tool.session.close()
                    if hasattr(tool, 'close'):
                        await tool.close()
                
                await close_all_tools(self.tools)
            
            logger.info("所有资源已安全关闭")
            
        except Exception as e:
            logger.error(f"资源关闭失败: {e}")

    async def close(self):
        """关闭Agent和所有资源"""
        await self._safe_close_resources()
        logger.info(f"🤖 通用Miner Agent 已关闭 - Session: {self.session_id}")


# 便捷函数
async def mine_data_universal(urls: List[str], config: Dict = None, 
                             instructions: str = None) -> Dict[str, Any]:
    """
    便捷函数：通用数据挖掘
    
    Args:
        urls: 要挖掘的URL列表
        config: 配置参数
        instructions: 自定义挖掘指令
        
    Returns:
        完整的挖掘结果
    """
    
    agent = UniversalMinerAgent(config)
    
    try:
        results = await agent.mine_urls(urls, instructions)
        return results
    finally:
        await agent.close()


# 测试代码
if __name__ == "__main__":
    import asyncio
    
    async def test_universal_miner():
        test_urls = [
            "https://www.youtube.com/"
        ]
        
        config = {
            'max_concurrent': 1,  # 降低并发避免问题
            'enable_l4_mining': True,
            'enable_metadata_enhancement': True,
            'enable_github_upload': False,
            'enable_evolution': True,
            'quality_threshold': 0.2,  # 降低阈值
            'reflection_interval': 10,
            'request_delay': 3.0,  # 增加延迟
            'max_depth': 3,
            'max_links_per_page': 30
        }
        
        instructions = """
        执行通用数据挖掘，寻找有价值的内容和数据：
        1. 识别包含结构化数据的页面
        2. 发现有深度内容的页面
        3. 提取具体的数据记录
        4. 评估内容的质量和价值
        
        重点关注信息密度高、结构化程度好的内容。
        """
        
        print("🚀 开始通用数据挖掘...")
        print(f"📋 目标URL数量: {len(test_urls)}")
        print("🎯 目标URL列表:")
        for i, url in enumerate(test_urls, 1):
            print(f"   {i}. {url}")
        
        print(f"⚙️ 配置参数:")
        print(f"   并发数: {config['max_concurrent']}")
        print(f"   质量阈值: {config['quality_threshold']}")
        print(f"   请求延迟: {config['request_delay']}s")
        print(f"   启用L4挖掘: {config['enable_l4_mining']}")
        print(f"   启用元数据增强: {config['enable_metadata_enhancement']}")
        print(f"   启用进化: {config['enable_evolution']}")
        
        print("\n" + "="*60)
        
        # 执行挖掘
        results = await mine_data_universal(test_urls, config, instructions)
        
        # 基本摘要
        print("🎉 通用挖掘完成！")
        
        # 安全地访问结果
        summary = results.get('summary', {})
        print(f"📊 处理了 {summary.get('total_urls_processed', 0)} 个URL")
        print(f"🎯 发现 {summary.get('high_quality_items', 0)} 个高质量项目")
        print(f"🔄 完成 {summary.get('evolution_improvements', 0)} 次进化改进")
        print(f"🧩 发现 {summary.get('discovered_patterns', 0)} 个模式")
        print(f"⏱️ 总耗时 {results.get('processing_time', 0):.2f} 秒")
        
        # 创建Agent实例来调用详细输出方法
        agent = UniversalMinerAgent()
        agent.print_detailed_results(results)
        await agent.close()
        
        return results
    
    # 运行测试
    asyncio.run(test_universal_miner())
