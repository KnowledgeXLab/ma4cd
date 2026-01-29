# miner/tools/__init__.py
"""
Miner工具模块 - 提供各种专业化工具
"""

from .url_validator import URLValidator
from .url_classifier import URLClassifier
from .l2_analyzer import L2SiteAnalyzer
from .l3_detector import L3DatasetDetector
from .l4_miner import L4RecordMiner
from .search_engine import SearchEngine
from .blacklist_manager import BlacklistManager
from .github_handler import GitHubHandler
from .statistics import DetailedStatistics
from .metadata_enhancer import MetadataEnhancer
from .browse_page import BrowsePageTool

__all__ = [
    'URLValidator',
    'URLClassifier', 
    'L2SiteAnalyzer',
    'L3DatasetDetector',
    'L4RecordMiner',
    'SearchEngine',
    'BlacklistManager',
    'GitHubHandler',
    'DetailedStatistics',
    'MetadataEnhancer',
    'BrowsePageTool'
]

# 工具版本信息
__version__ = "1.0.0"

# 工具配置
TOOL_CONFIG = {
    "url_validation": {
        "timeout": 10,
        "max_retries": 3,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    },
    "l3_detection": {
        "confidence_threshold": 0.3,
        "max_download_links": 10,
        "file_extensions": ['.csv', '.xlsx', '.json', '.xml', '.fasta', '.fastq']
    },
    "l4_mining": {
        "max_records_per_source": 100,
        "max_files_to_process": 5,
        "record_patterns": [
            r'\b[A-Z]{2,}\d{6,}\b',
            r'\b[A-Z]+\d{4,}\b',
            r'\bENS[A-Z]*\d+\b'
        ]
    },
    "search_engine": {
        "max_results_per_query": 10,
        "timeout": 15,
        "rate_limit": 1.0  # 秒
    },
    "blacklist": {
        "duration_hours": 24,
        "permanent_threshold": 5,
        "file_path": "data/blacklist.json"
    }
}

def get_tool_config(tool_name: str) -> dict:
    """获取工具配置"""
    return TOOL_CONFIG.get(tool_name, {})

def create_tool_suite():
    """创建完整的工具套件"""
    return {
        'url_validator': URLValidator(),
        'url_classifier': URLClassifier(),
        'l2_analyzer': L2SiteAnalyzer(),
        'l3_detector': L3DatasetDetector(),
        'l4_miner': L4RecordMiner(),
        'search_engine': SearchEngine(),
        'blacklist_manager': BlacklistManager(),
        'github_handler': GitHubHandler(),
        'browse_page': BrowsePageTool()
    }

async def close_all_tools(tool_suite: dict):
    """关闭所有工具的资源"""
    for tool_name, tool in tool_suite.items():
        if hasattr(tool, 'close'):
            try:
                await tool.close()
            except Exception as e:
                print(f"关闭工具 {tool_name} 失败: {e}")
