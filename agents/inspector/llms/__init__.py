import os
import logging
from .inspector_llm import InspectorLLM
from utils.env import get_llm_api_key

# 设置模块级的日志记录器
logging.getLogger(__name__).addHandler(logging.NullHandler())

# 定义对外暴露的接口
__all__ = ["InspectorLLM"]

# 模块元数据
__version__ = "1.0.0"
__author__ = "Zhuyao"

# 可选：模块初始化时的环境检查
def _check_environment():
    """
    检查运行环境是否具备基础配置
    """
    if not get_llm_api_key():
        import warnings
        warnings.warn(
            "Neither OPENAI_API_KEY nor MA4CD_LLM_API_KEY is set. "
            "InspectorLLM will require an explicit api_key during initialization.",
            UserWarning
        )

_check_environment()
