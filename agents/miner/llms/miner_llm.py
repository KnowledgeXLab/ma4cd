# agents/miner/llms/miner_llm.py
"""
Miner Agent 专用的 LLM 客户端
基于 Scout 的 base.py，但针对 Miner 任务优化
"""

import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional, Generator, List
from loguru import logger

# 添加 utils 目录到路径（如果有全局工具）
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
utils_dir = os.path.join(project_root, "utils")
if utils_dir not in sys.path:
    sys.path.append(utils_dir)

try:
    from retry_helper import with_retry, LLM_RETRY_CONFIG
except ImportError:
    # 备用的装饰器实现
    def with_retry(config=None):
        def decorator(func):
            return func
        return decorator
    
    LLM_RETRY_CONFIG = {
        "max_retries": 5,          # Miner 任务允许更多重试
        "delay": 2.0,
        "backoff": 2.0,
        "exceptions": (Exception,)
    }

try:
    from openai import OpenAI, OpenAIError, APIConnectionError, RateLimitError, Timeout
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("OpenAI 库未安装，请运行 `pip install openai`")


class MinerLLMClient:
    """
    Miner Agent 专用 LLM 客户端
    优化点：
    - 默认模型 gpt-4o-mini（更强、更稳定）
    - 温度默认 0.3（结构化输出更可靠）
    - 重试次数更多（挖掘任务允许稍长等待）
    - 内置 JSON Schema 支持
    """
    
    def __init__(
        self,
        api_key: str = None,
        model_name: str = "gpt-4o-mini",  # Miner 推荐更强模型
        base_url: Optional[str] = None,
        timeout: float = 60.0,           # 挖掘任务允许更长超时
        max_retries: int = 5
    ):
        if api_key is None:
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
        if not api_key:
            raise ValueError("LLM API key is required.")
        
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        
        if not HAS_OPENAI:
            raise ImportError("OpenAI 库未安装，请运行 `pip install openai`")
        
        client_kwargs = {
            "api_key": api_key,
            "max_retries": 0,  # 重试由装饰器处理
        }
        if base_url:
            client_kwargs["base_url"] = base_url
        
        try:
            self.client = OpenAI(**client_kwargs)
            logger.info(f"MinerLLMClient 初始化成功: {model_name} @ {base_url or 'OpenAI'}")
        except Exception as e:
            logger.error(f"MinerLLMClient 初始化失败: {e}")
            raise
    
    def _build_messages(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        include_time: bool = False  # Miner 任务通常不需要时间前缀
    ) -> List[Dict[str, str]]:
        messages = []
        
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt.strip()})
        
        if include_time:
            current_time = datetime.now().strftime("%Y年%m月%d日 %H时%M分")
            user_content = f"当前时间是 {current_time}。\n{user_prompt}"
        else:
            user_content = user_prompt
        
        if user_content.strip():
            messages.append({"role": "user", "content": user_content.strip()})
        
        return messages
    
    @with_retry(LLM_RETRY_CONFIG)
    def invoke(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: float = 0.3,  # 默认低温度，结构化输出更稳定
        max_tokens: Optional[int] = 4000,
        include_time: bool = False,
        **kwargs
    ) -> str:
        try:
            messages = self._build_messages(system_prompt, user_prompt, include_time)
            
            request_params = {
                "model": self.model_name,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            
            allowed_keys = {"top_p", "presence_penalty", "frequency_penalty", "stream"}
            for key, value in kwargs.items():
                if key in allowed_keys and value is not None:
                    request_params[key] = value
            
            response = self.client.chat.completions.create(
                **request_params,
                timeout=self.timeout
            )
            
            if response.choices and response.choices[0].message.content:
                content = response.choices[0].message.content.strip()
                logger.debug(f"Miner LLM 响应长度: {len(content)} 字符")
                return content
            else:
                logger.warning("Miner LLM 返回空响应")
                return ""
                
        except Exception as e:
            logger.error(f"Miner LLM 调用失败: {e}")
            raise
    
    def invoke_json(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: float = 0.2,  # 更低温度，确保 JSON 稳定
        max_tokens: int = 4000,
        include_time: bool = False,
        schema: Optional[Dict] = None,  # 可选：JSON Schema
        **kwargs
    ) -> Dict[str, Any]:
        """
        强制返回 JSON 格式
        """
        try:
            # 强制 JSON 输出
            json_system = (
                f"{system_prompt}\n\n"
                "重要：必须以有效的 JSON 格式输出，不要包含任何解释性文本或多余字符。"
                "输出必须严格符合以下结构（如果有 schema，请遵守）："
            )
            if schema:
                json_system += f"\n{schema}"
            
            response = self.invoke(
                system_prompt=json_system,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                include_time=include_time,
                **kwargs
            )
            
            # 提取 JSON
            json_str = self._extract_json_from_response(response)
            
            import json
            return json.loads(json_str)
            
        except Exception as e:
            logger.error(f"Miner JSON 调用失败: {e}")
            return {"error": str(e), "raw_response": response}
    
    def _extract_json_from_response(self, response: str) -> str:
        import json
        import re
        
        # 尝试直接解析
        try:
            json.loads(response)
            return response
        except:
            pass
        
        # 提取 ```json ... ``` 块
        match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # 提取 { ... } 块
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            return json_match.group(0)
        
        # 兜底
        return json.dumps({"content": response}, ensure_ascii=False)

# 快速创建函数
def create_miner_llm(
    api_key: Optional[str] = None,
    model_name: str = "gpt-4o-mini",
    base_url: Optional[str] = None
) -> MinerLLMClient:
    if api_key is None:
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    return MinerLLMClient(api_key=api_key, model_name=model_name, base_url=base_url)