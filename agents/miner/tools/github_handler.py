# miner/tools/github_handler.py
"""
GitHub特殊处理器 - 处理GitHub仓库的特殊逻辑
"""

import aiohttp
import re
from typing import Dict, Optional, List
from loguru import logger
from urllib.parse import urlparse, urljoin
import json

class GitHubHandler:
    """GitHub特殊处理器"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.github_api_base = "https://api.github.com"
        
        # GitHub个人数据仓库特征
        self.personal_data_indicators = [
            'data', 'dataset', 'research', 'analysis', 'study', 'experiment',
            'results', 'supplementary', 'raw-data', 'processed-data'
        ]
        
        # 有用数据集的特征
        self.useful_dataset_indicators = [
            'readme', 'documentation', 'license', 'citation', 'doi',
            'publication', 'paper', 'journal', 'conference'
        ]
        
        # 数据文件扩展名
        self.data_file_extensions = [
            '.csv', '.tsv', '.xlsx', '.json', '.xml', '.fasta', '.fastq',
            '.vcf', '.bed', '.gff', '.gtf', '.bam', '.sam', '.h5', '.hdf5'
        ]
    
    async def handle_github_url(self, url: str) -> Dict:
        """处理GitHub URL"""
        
        if not self._is_github_url(url):
            return {"error": "不是GitHub URL"}
        
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        try:
            # 解析GitHub URL
            repo_info = self._parse_github_url(url)
            if not repo_info:
                return {"error": "无法解析GitHub URL"}
            
            # 获取仓库信息
            repo_data = await self._get_repository_info(repo_info)
            
            # 判断是否为个人数据仓库
            is_personal_data = await self._is_personal_data_repo(repo_info, repo_data)
            
            if is_personal_data:
                return await self._handle_personal_data_repo(url, repo_info, repo_data)
            else:
                return await self._handle_standard_repo(url, repo_info, repo_data)
                
        except Exception as e:
            logger.error(f"GitHub处理失败 {url}: {e}")
            return {"error": str(e)}
    
    def _is_github_url(self, url: str) -> bool:
        """检查是否为GitHub URL"""
        return 'github.com' in url.lower()
    
    def _parse_github_url(self, url: str) -> Optional[Dict]:
        """解析GitHub URL"""
        
        # 匹配GitHub仓库URL模式
        patterns = [
            r'github\.com/([^/]+)/([^/]+)/?$',  # 基础仓库URL
            r'github\.com/([^/]+)/([^/]+)/tree/([^/]+)',  # 分支URL
            r'github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)',  # 文件URL
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                groups = match.groups()
                return {
                    'owner': groups[0],
                    'repo': groups[1].replace('.git', ''),
                    'branch': groups[2] if len(groups) > 2 else 'main',
                    'path': groups[3] if len(groups) > 3 else ''
                }
        
        return None
    
    async def _get_repository_info(self, repo_info: Dict) -> Dict:
        """获取仓库信息"""
        
        api_url = f"{self.github_api_base}/repos/{repo_info['owner']}/{repo_info['repo']}"
        
        try:
            async with self.session.get(api_url) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 404:
                    return {"error": "仓库不存在或私有"}
                else:
                    return {"error": f"API请求失败: {response.status}"}
        except Exception as e:
            return {"error": str(e)}
    
    async def _is_personal_data_repo(self, repo_info: Dict, repo_data: Dict) -> bool:
        """判断是否为个人数据仓库"""
        
        if "error" in repo_data:
            return False
        
        # 检查仓库名称
        repo_name = repo_data.get('name', '').lower()
        if any(indicator in repo_name for indicator in self.personal_data_indicators):
            return True
        
        # 检查描述
        description = repo_data.get('description', '').lower()
        if any(indicator in description for indicator in self.personal_data_indicators):
            return True
        
        # 检查主题标签
        topics = repo_data.get('topics', [])
        if any(indicator in topics for indicator in self.personal_data_indicators):
            return True
        
        # 检查仓库内容
        has_data_files = await self._check_data_files(repo_info)
        
        return has_data_files
    
    async def _check_data_files(self, repo_info: Dict) -> bool:
        """检查仓库是否包含数据文件"""
        
        contents_url = f"{self.github_api_base}/repos/{repo_info['owner']}/{repo_info['repo']}/contents"
        
        try:
            async with self.session.get(contents_url) as response:
                if response.status == 200:
                    contents = await response.json()
                    
                    for item in contents:
                        if item.get('type') == 'file':
                            filename = item.get('name', '').lower()
                            if any(ext in filename for ext in self.data_file_extensions):
                                return True
                    
                    return False
                else:
                    return False
        except Exception:
            return False
    
    async def _handle_personal_data_repo(self, url: str, repo_info: Dict, repo_data: Dict) -> Dict:
        """处理个人数据仓库"""
        
        # 检查主页是否存在
        main_page_exists = await self._check_main_page_exists(repo_info)
        
        # 评估数据集有用性
        dataset_useful = await self._evaluate_dataset_usefulness(repo_info, repo_data)
        
        result = {
            "url": url,
            "type": "github_personal_data",
            "repo_info": repo_info,
            "main_page_exists": main_page_exists,
            "dataset_useful": dataset_useful,
            "store_portal": False,
            "classification": "L3",  # 个人数据通常是L3
            "confidence": 0.7
        }
        
        # 特殊逻辑：如果数据集有用但主页不存在，仍然存储门户
        if dataset_useful and not main_page_exists:
            result.update({
                "store_portal": True,
                "reason": "useful_dataset_despite_missing_main_page",
                "recommendation": "store_as_l3_dataset"
            })
        elif dataset_useful and main_page_exists:
            result.update({
                "store_portal": True,
                "reason": "useful_dataset_with_main_page",
                "recommendation": "store_as_l3_dataset"
            })
        
        # 提取元数据
        result["metadata"] = await self._extract_repo_metadata(repo_info, repo_data)
        
        return result
    
    async def _handle_standard_repo(self, url: str, repo_info: Dict, repo_data: Dict) -> Dict:
        """处理标准仓库"""
        
        return {
            "url": url,
            "type": "github_standard",
            "repo_info": repo_info,
            "classification": "L2",  # 标准仓库通常是L2
            "confidence": 0.5,
            "metadata": await self._extract_repo_metadata(repo_info, repo_data)
        }
    
    async def _check_main_page_exists(self, repo_info: Dict) -> bool:
        """检查主页是否存在"""
        
        # 检查README文件
        readme_files = ['README.md', 'README.rst', 'README.txt', 'readme.md']
        
        for readme in readme_files:
            readme_url = f"{self.github_api_base}/repos/{repo_info['owner']}/{repo_info['repo']}/contents/{readme}"
            
            try:
                async with self.session.get(readme_url) as response:
                    if response.status == 200:
                        return True
            except Exception:
                continue
        
        return False
    
    async def _evaluate_dataset_usefulness(self, repo_info: Dict, repo_data: Dict) -> bool:
        """评估数据集有用性"""
        
        if "error" in repo_data:
            return False
        
        score = 0
        
        # 检查星标数
        stars = repo_data.get('stargazers_count', 0)
        if stars > 10:
            score += 1
        if stars > 50:
            score += 1
        
        # 检查fork数
        forks = repo_data.get('forks_count', 0)
        if forks > 5:
            score += 1
        
        # 检查是否有许可证
        if repo_data.get('license'):
            score += 1
        
        # 检查描述质量
        description = repo_data.get('description', '')
        if len(description) > 50:
            score += 1
        
        # 检查是否有有用的指标
        for indicator in self.useful_dataset_indicators:
            if indicator in description.lower():
                score += 1
        
        # 检查最近活动
        import datetime
        updated_at = repo_data.get('updated_at', '')
        if updated_at:
            try:
                updated_date = datetime.datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                days_since_update = (datetime.datetime.now(datetime.timezone.utc) - updated_date).days
                if days_since_update < 365:  # 一年内有更新
                    score += 1
            except:
                pass
        
        return score >= 3  # 阈值可调整
    
    async def _extract_repo_metadata(self, repo_info: Dict, repo_data: Dict) -> Dict:
        """提取仓库元数据"""
        
        if "error" in repo_data:
            return {"error": repo_data["error"]}
        
        metadata = {
            "owner": repo_info['owner'],
            "repository": repo_info['repo'],
            "full_name": repo_data.get('full_name', ''),
            "description": repo_data.get('description', ''),
            "language": repo_data.get('language', ''),
            "stars": repo_data.get('stargazers_count', 0),
            "forks": repo_data.get('forks_count', 0),
            "size": repo_data.get('size', 0),
            "created_at": repo_data.get('created_at', ''),
            "updated_at": repo_data.get('updated_at', ''),
            "license": repo_data.get('license', {}).get('name', '') if repo_data.get('license') else '',
            "topics": repo_data.get('topics', []),
            "default_branch": repo_data.get('default_branch', 'main')
        }
        
        # 获取文件列表
        metadata["data_files"] = await self._get_data_files_list(repo_info)
        
        return metadata
    
    async def _get_data_files_list(self, repo_info: Dict) -> List[str]:
        """获取数据文件列表"""
        
        contents_url = f"{self.github_api_base}/repos/{repo_info['owner']}/{repo_info['repo']}/contents"
        
        try:
            async with self.session.get(contents_url) as response:
                if response.status == 200:
                    contents = await response.json()
                    
                    data_files = []
                    for item in contents:
                        if item.get('type') == 'file':
                            filename = item.get('name', '')
                            if any(ext in filename.lower() for ext in self.data_file_extensions):
                                data_files.append(filename)
                    
                    return data_files
                else:
                    return []
        except Exception:
            return []
    
    async def close(self):
        """关闭会话"""
        if self.session:
            await self.session.close()