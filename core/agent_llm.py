# ma4cd/core/agent_llm.py
"""
Agent 专用的 LLM 业务封装层。
底层依赖 core.llm_client.LLMClient
自动处理时间前缀、默认参数、重试、JSON 模式、日志等
"""

import json
from datetime import datetime
from typing import Any, Dict, Optional, Generator, List

from loguru import logger

# 假设你已经有 core/llm_client.py 了
from core.llm_client import LLMClient


class AgentLLM:
    """
    Agent 专用 LLM 封装：
    - 自动加时间前缀
    - 默认 temperature / max_tokens
    - 支持 JSON 强制输出
    - 日志记录
    - 重试已由底层 LLMClient 处理
    - 提供 generate() 方法，完美兼容 seaf 的 Reflector
    """

    def __init__(
        self,
        api_key: str,
        model_name: str,
        base_url: Optional[str] = None,
        default_temperature: float = 0.7,
        default_max_tokens: int = 4096,
    ):
        self.client = LLMClient(
            api_key=api_key,
            model_name=model_name,
            base_url=base_url,
        )
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens

    def _build_messages(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
    ) -> List[Dict[str, str]]:
        """自动加时间前缀"""
        current_time = datetime.now().strftime("%Y年%m月%d日 %H时%M分")
        time_prefix = f"今天的实际时间是 {current_time}。"
        user_content = f"{time_prefix}\n{user_prompt}" if user_prompt else time_prefix

        messages = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt.strip()})
        messages.append({"role": "user", "content": user_content.strip()})
        return messages

    def invoke(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict] = None,
        **kwargs: Any,
    ) -> str:
        """同步调用，返回完整文本"""
        messages = self._build_messages(system_prompt, user_prompt)
        return self.client.invoke(
            messages=messages,
            temperature=temperature or self.default_temperature,
            max_tokens=max_tokens or self.default_max_tokens,
            response_format=response_format,
            **kwargs,
        )

    def stream_invoke(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: Optional[float] = None,
        **kwargs: Any,
    ) -> Generator[str, None, None]:
        """流式调用"""
        messages = self._build_messages(system_prompt, user_prompt)
        return self.client.stream_invoke(
            messages=messages,
            temperature=temperature or self.default_temperature,
            **kwargs,
        )

    def stream_invoke_to_string(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: Optional[float] = None,
        **kwargs: Any,
    ) -> str:
        """流式调用并拼接完整字符串"""
        return "".join(self.stream_invoke(system_prompt, user_prompt, temperature, **kwargs))

    def invoke_json(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        **kwargs: Any,
    ) -> Dict:
        """强制 JSON 输出模式"""
        try:
            response = self.invoke(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format={"type": "json_object"},
                **kwargs,
            )
            parsed = json.loads(response)
            return parsed
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败: {e}\nRaw: {response}")
            return {"error": "JSON 解析失败", "raw_response": response}
        except Exception as e:
            logger.error(f"JSON 调用失败: {e}")
            return {"error": str(e)}

    def generate(self, prompt: str) -> Dict[str, str]:
        """兼容 seaf Reflector 的 generate 接口，返回 dict 格式"""
        text = self.invoke(
            system_prompt="你是一位反思助手",
            user_prompt=prompt,
            temperature=0.5,
            max_tokens=2000,
        )
        return {"content": text}