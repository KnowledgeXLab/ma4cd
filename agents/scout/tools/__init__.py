"""
Scout Tools Package
导出侦察兵所需的搜索工具
"""

# 从 web_search.py 导入新类名 ScoutWebSearchTool
from .web_search import ScoutWebSearchTool

# 为了兼容性，也可以保留一个旧名字的别名（可选，但推荐）
WebSearchTool = ScoutWebSearchTool

__all__ = [
    "ScoutWebSearchTool",
    "WebSearchTool"
]