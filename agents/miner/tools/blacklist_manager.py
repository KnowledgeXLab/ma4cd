# miner/tools/blacklist_manager.py
"""
黑名单管理器 - 管理无效URL黑名单
"""

import json
import os
import time
from typing import Dict, List, Set
from loguru import logger
from datetime import datetime, timedelta
import hashlib

class BlacklistManager:
    """黑名单管理器"""
    
    def __init__(self, blacklist_file: str = "config/blacklist.json"):
        self.blacklist_file = blacklist_file
        self.blacklist: Dict[str, Dict] = {}
        self.temp_blacklist: Set[str] = set()  # 临时黑名单（会话级别）
        
        # 黑名单配置
        self.max_retries = 3
        self.blacklist_duration = 24 * 60 * 60  # 24小时
        self.permanent_blacklist_threshold = 5  # 失败5次后永久拉黑
        
        # 确保数据目录存在
        os.makedirs(os.path.dirname(self.blacklist_file), exist_ok=True)
        
        # 加载现有黑名单
        self._load_blacklist()
    
    def _load_blacklist(self):
        """加载黑名单文件"""
        try:
            if os.path.exists(self.blacklist_file):
                with open(self.blacklist_file, 'r', encoding='utf-8') as f:
                    self.blacklist = json.load(f)
                logger.info(f"加载黑名单: {len(self.blacklist)} 个URL")
            else:
                self.blacklist = {}
                logger.info("创建新的黑名单文件")
        except Exception as e:
            logger.error(f"加载黑名单失败: {e}")
            self.blacklist = {}
    
    def _save_blacklist(self):
        """保存黑名单到文件"""
        try:
            with open(self.blacklist_file, 'w', encoding='utf-8') as f:
                json.dump(self.blacklist, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存黑名单失败: {e}")
    
    def is_blacklisted(self, url: str) -> bool:
        """检查URL是否在黑名单中"""
        
        # 检查临时黑名单
        if url in self.temp_blacklist:
            return True
        
        # 检查持久黑名单
        url_hash = self._hash_url(url)
        
        if url_hash not in self.blacklist:
            return False
        
        entry = self.blacklist[url_hash]
        
        # 检查是否为永久黑名单
        if entry.get('permanent', False):
            return True
        
        # 检查是否过期
        blacklist_time = entry.get('blacklisted_at', 0)
        if time.time() - blacklist_time > self.blacklist_duration:
            # 过期，从黑名单移除
            del self.blacklist[url_hash]
            self._save_blacklist()
            return False
        
        return True
    
    def add_to_blacklist(self, url: str, error_type: str, error_message: str, temporary: bool = False): 
        """添加URL到黑名单"""
        
        if temporary:
            self.temp_blacklist.add(url)
            logger.info(f"添加到临时黑名单: {url}")
            return
        
        url_hash = self._hash_url(url)
        current_time = time.time()
        
        if url_hash in self.blacklist:
            # 更新现有条目
            entry = self.blacklist[url_hash]
            entry['failure_count'] = entry.get('failure_count', 0) + 1
            entry['last_failure'] = current_time
            entry['last_error_type'] = error_type
            entry['last_error_message'] = error_message
            
            # 检查是否需要永久拉黑
            if entry['failure_count'] >= self.permanent_blacklist_threshold:
                entry['permanent'] = True
                logger.warning(f"URL永久拉黑: {url} (失败{entry['failure_count']}次)")
            
        else:
            # 创建新条目
            self.blacklist[url_hash] = {
                'url': url,
                'blacklisted_at': current_time,
                'failure_count': 1,
                'first_failure': current_time,
                'last_failure': current_time,
                'error_type': error_type,
                'last_error_type': error_type,
                'error_message': error_message,
                'last_error_message': error_message,
                'permanent': False
            }
        
        self._save_blacklist()
        logger.info(f"添加到黑名单: {url} ({error_type})")
    
    def get_blacklist_stats(self) -> Dict:
        """获取黑名单统计信息"""
        
        total_blacklisted = len(self.blacklist)
        permanent_count = sum(1 for entry in self.blacklist.values() 
                            if entry.get('permanent', False))
        temporary_count = len(self.temp_blacklist)
        
        # 按错误类型统计
        error_types = {}
        for entry in self.blacklist.values():
            error_type = entry.get('last_error_type', 'UNKNOWN')
            error_types[error_type] = error_types.get(error_type, 0) + 1
        
        return {
            'total_blacklisted': total_blacklisted,
            'permanent_blacklisted': permanent_count,
            'temporary_blacklisted': temporary_count,
            'error_type_distribution': error_types,
            'blacklist_file': self.blacklist_file
        }
    
    def get_blacklisted_urls(self, include_temporary: bool = True) -> List[Dict]:
        """获取黑名单URL列表"""
        
        urls = []
        
        # 持久黑名单
        for entry in self.blacklist.values():
            urls.append({
                'url': entry['url'],
                'type': 'permanent' if entry.get('permanent', False) else 'temporary',
                'failure_count': entry.get('failure_count', 0),
                'last_error': entry.get('last_error_type', 'UNKNOWN'),
                'blacklisted_at': datetime.fromtimestamp(
                    entry.get('blacklisted_at', 0)
                ).isoformat()
            })
        
        # 临时黑名单
        if include_temporary:
            for url in self.temp_blacklist:
                urls.append({
                    'url': url,
                    'type': 'session_temporary',
                    'failure_count': 1,
                    'last_error': 'SESSION_FAILURE',
                    'blacklisted_at': datetime.now().isoformat()
                })
        
        return urls
    
    def remove_from_blacklist(self, url: str) -> bool:
        """从黑名单移除URL"""
        
        # 从临时黑名单移除
        if url in self.temp_blacklist:
            self.temp_blacklist.remove(url)
            logger.info(f"从临时黑名单移除: {url}")
            return True
        
        # 从持久黑名单移除
        url_hash = self._hash_url(url)
        if url_hash in self.blacklist:
            del self.blacklist[url_hash]
            self._save_blacklist()
            logger.info(f"从黑名单移除: {url}")
            return True
        
        return False
    
    def clear_expired_entries(self):
        """清理过期的黑名单条目"""
        
        current_time = time.time()
        expired_hashes = []
        
        for url_hash, entry in self.blacklist.items():
            # 跳过永久黑名单
            if entry.get('permanent', False):
                continue
            
            # 检查是否过期
            blacklist_time = entry.get('blacklisted_at', 0)
            if current_time - blacklist_time > self.blacklist_duration:
                expired_hashes.append(url_hash)
        
        # 移除过期条目
        for url_hash in expired_hashes:
            del self.blacklist[url_hash]
        
        if expired_hashes:
            self._save_blacklist()
            logger.info(f"清理过期黑名单条目: {len(expired_hashes)} 个")
    
    def _hash_url(self, url: str) -> str:
        """生成URL哈希"""
        return hashlib.md5(url.encode('utf-8')).hexdigest()
    
    def clear_temporary_blacklist(self):
        """清空临时黑名单"""
        self.temp_blacklist.clear()
        logger.info("清空临时黑名单")
    
    def export_blacklist(self, export_file: str):
        """导出黑名单"""
        try:
            export_data = {
                'exported_at': datetime.now().isoformat(),
                'total_entries': len(self.blacklist),
                'blacklist': self.blacklist
            }
            
            with open(export_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"黑名单已导出到: {export_file}")
            
        except Exception as e:
            logger.error(f"导出黑名单失败: {e}")
    
    def import_blacklist(self, import_file: str, merge: bool = True):
        """导入黑名单"""
        try:
            with open(import_file, 'r', encoding='utf-8') as f:
                import_data = json.load(f)
            
            imported_blacklist = import_data.get('blacklist', {})
            
            if merge:
                # 合并模式
                self.blacklist.update(imported_blacklist)
            else:
                # 替换模式
                self.blacklist = imported_blacklist
            
            self._save_blacklist()
            logger.info(f"黑名单已导入: {len(imported_blacklist)} 个条目")
            
        except Exception as e:
            logger.error(f"导入黑名单失败: {e}")
