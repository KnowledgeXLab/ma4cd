# agents/scout/tools/__init__.py
from .web_search import (
    ScoutWebSearchTool,
    WebSearchTool,  # 如果你有这个别名
    SearchResult
)

__all__ = [
    'ScoutWebSearchTool',
    'WebSearchTool',
    'SearchResult'
]