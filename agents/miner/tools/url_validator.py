# miner/tools/url_validator.py
"""
URL验证器 - 检查URL有效性
"""

import aiohttp
import asyncio
from typing import Dict, Optional
from loguru import logger
import time
from urllib.parse import urlparse

class URLValidator:
    """URL有效性验证器"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.timeout = aiohttp.ClientTimeout(total=10)
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def validate_url(self, url: str) -> Dict:
        """验证单个URL"""
        start_time = time.time()
        
        # 基础格式检查
        if not self._is_valid_url_format(url):
            return {
                "url": url,
                "is_valid": False,
                "error_type": "INVALID_FORMAT",
                "error_message": "URL格式无效",
                "response_time": 0,
                "status_code": None
            }
        
        # 网络检查
        if not self.session:
            self.session = aiohttp.ClientSession(timeout=self.timeout)
            
        try:
            async with self.session.head(url, allow_redirects=True) as response:
                response_time = (time.time() - start_time) * 1000
                
                return {
                    "url": url,
                    "is_valid": response.status < 400,
                    "status_code": response.status,
                    "error_type": None if response.status < 400 else f"HTTP_{response.status}",
                    "error_message": None if response.status < 400 else f"HTTP {response.status}",
                    "response_time": round(response_time, 2),
                    "final_url": str(response.url),  # 处理重定向
                    "content_type": response.headers.get('Content-Type', ''),
                    "server": response.headers.get('Server', '')
                }
                
        except asyncio.TimeoutError:
            return {
                "url": url,
                "is_valid": False,
                "error_type": "TIMEOUT",
                "error_message": "请求超时",
                "response_time": (time.time() - start_time) * 1000,
                "status_code": None
            }
            
        except aiohttp.ClientError as e:
            return {
                "url": url,
                "is_valid": False,
                "error_type": self._classify_client_error(e),
                "error_message": str(e),
                "response_time": (time.time() - start_time) * 1000,
                "status_code": None
            }
            
        except Exception as e:
            return {
                "url": url,
                "is_valid": False,
                "error_type": "UNKNOWN_ERROR",
                "error_message": str(e),
                "response_time": (time.time() - start_time) * 1000,
                "status_code": None
            }
    
    def _is_valid_url_format(self, url: str) -> bool:
        """检查URL格式是否有效"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False
    
    def _classify_client_error(self, error: aiohttp.ClientError) -> str:
        """分类客户端错误"""
        error_str = str(error).lower()
        
        if "name or service not known" in error_str or "nodename nor servname provided" in error_str:
            return "DNS_RESOLUTION_FAILED"
        elif "connection refused" in error_str:
            return "CONNECTION_REFUSED"
        elif "ssl" in error_str or "certificate" in error_str:
            return "SSL_ERROR"
        elif "too many redirects" in error_str:
            return "TOO_MANY_REDIRECTS"
        else:
            return "CLIENT_ERROR"
    
    async def batch_validate(self, urls: list) -> Dict:
        """批量验证URL"""
        results = []
        valid_count = 0
        
        async with self:
            tasks = [self.validate_url(url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理异常结果
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    processed_results.append({
                        "url": urls[i],
                        "is_valid": False,
                        "error_type": "VALIDATION_EXCEPTION",
                        "error_message": str(result),
                        "response_time": 0,
                        "status_code": None
                    })
                else:
                    processed_results.append(result)
                    if result.get("is_valid", False):
                        valid_count += 1
        
        return {
            "total_urls": len(urls),
            "valid_urls": valid_count,
            "invalid_urls": len(urls) - valid_count,
            "success_rate": valid_count / len(urls) if urls else 0,
            "results": processed_results
        }
