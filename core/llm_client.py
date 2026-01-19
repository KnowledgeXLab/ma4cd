# ma4cd/core/llm_client.py
"""
ma4cd 项目统一的 OpenAI-compatible LLM 客户端。
特点：
- 极简传输层 + 业务封装双层设计
- 内置重试、超时、流式输出、时间前缀
- 支持任何 OpenAI 兼容端点（OpenAI、Groq、DeepSeek、Moonshot、Ollama 等）
- 无外部依赖（除 openai 和 tenacity 外）
"""

import os
import json
from datetime import datetime
from typing import Any, Dict, Optional, Generator, List, Callable

from loguru import logger
from openai import OpenAI, OpenAIError, APIConnectionError, RateLimitError, Timeout
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


class LLMClient:
    """
    纯粹的 LLM 传输层：
    只负责调用 API、返回原始响应，不做任何业务处理。
    """

    def __init__(
        self,
        api_key: str,
        model_name: str,
        base_url: Optional[str] = None,
        timeout: float = 1800.0,
        max_retries: int = 3,
    ):
        if not api_key:
            raise ValueError("API key is required.")
        if not model_name:
            raise ValueError("Model name is required.")

        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries

        client_kwargs = {
            "api_key": api_key,
            "max_retries": 0,  # 重试交给 tenacity
        }
        if base_url:
            client_kwargs["base_url"] = base_url

        self.client = OpenAI(**client_kwargs)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((APIConnectionError, RateLimitError, Timeout, OpenAIError)),
        before_sleep=lambda retry_state: logger.warning(
            f"LLM 调用失败，重试 {retry_state.attempt_number}/3: {retry_state.outcome.exception()}"
        )
    )
    def invoke(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """同步调用，返回完整文本"""
        timeout = kwargs.pop("timeout", self.timeout)
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            timeout=timeout,
            **kwargs,
        )
        if response.choices and response.choices[0].message.content:
            return response.choices[0].message.content.strip()
        return ""

    def stream_invoke(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> Generator[str, None, None]:
        """流式调用，逐块 yield"""
        kwargs["stream"] = True
        timeout = kwargs.pop("timeout", self.timeout)
        try:
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                timeout=timeout,
                **kwargs,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"流式调用失败: {str(e)}")
            raise

    def stream_invoke_to_string(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """流式调用并拼接完整字符串（防 UTF-8 截断）"""
        chunks = []
        for chunk in self.stream_invoke(messages, **kwargs):
            chunks.append(chunk)
        return "".join(chunks)

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model": self.model_name,
            "base_url": self.base_url or "https://api.openai.com/v1",
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }


