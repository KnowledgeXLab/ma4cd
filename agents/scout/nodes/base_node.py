"""
节点基类 - 基于 QueryEngine 设计模式
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from loguru import logger
from ..llms.base import LLMClient
from ..state.state import ScoutState


class BaseNode(ABC):
    """节点基类"""
    
    def __init__(self, llm_client: LLMClient, node_name: str = ""):
        self.llm_client = llm_client
        self.node_name = node_name or self.__class__.__name__
        logger.debug(f"初始化节点: {self.node_name}")
    
    @abstractmethod
    def run(self, input_data: Any, state: Optional[ScoutState] = None, **kwargs) -> Any:
        """执行节点处理逻辑"""
        pass
    
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据"""
        return True
    
    def process_output(self, output: Any) -> Any:
        """处理输出数据"""
        return output
    
    def log_info(self, message: str):
        logger.info(f"[{self.node_name}] {message}")
    
    def log_warning(self, message: str):
        logger.warning(f"[{self.node_name}] 警告: {message}")
    
    def log_error(self, message: str):
        logger.error(f"[{self.node_name}] 错误: {message}")
    
    def log_debug(self, message: str):
        logger.debug(f"[{self.node_name}] {message}")


class StateMutationNode(BaseNode):
    """带状态修改功能的节点基类"""
    
    @abstractmethod
    def mutate_state(self, input_data: Any, state: ScoutState, **kwargs) -> ScoutState:
        """修改状态"""
        pass