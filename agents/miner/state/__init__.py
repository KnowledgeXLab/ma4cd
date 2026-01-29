# agents/miner/state/__init__.py
"""
状态模块的入口文件
方便从外部 import MinerState
"""

from .miner_state import MinerState

__all__ = [
    "MinerState",
]