import os
import json
import logging
import time
import random
from typing import Dict, Any, Optional, Union
from openai import OpenAI  # 假设使用 OpenAI 兼容接口
from utils.env import get_llm_api_key, get_llm_base_url, normalize_model_for_endpoint
from utils.llm_budgeter import before_call, record_error, record_success

# 配置日志
logger = logging.getLogger(__name__)

class InspectorLLM:
    """
    Inspector 专用的大模型接口。
    特点：低温度、强制 JSON 输出、内置错误重试。
    """

    def __init__(self, model: str = None, temperature: float = 0.0, api_key: str = None, base_url: str = None):
        """
        初始化 Inspector LLM。
        
        Args:
            model: 模型名称，建议使用推理能力强的模型 (如 gpt-4o)
            temperature: 严谨模式默认为 0
            api_key: 如果不传则读取环境变量
        """
        self.temperature = temperature
        self.timeout = float(os.getenv("MA4CD_INSPECTOR_TIMEOUT", "90"))
        self.max_retries = int(os.getenv("MA4CD_INSPECTOR_LLM_RETRIES", "4"))
        self.base_retry_delay = float(os.getenv("MA4CD_INSPECTOR_RETRY_DELAY", "1.5"))
        self.retry_backoff = float(os.getenv("MA4CD_INSPECTOR_RETRY_BACKOFF", "2.0"))
        self.api_key = get_llm_api_key(api_key)
        self.base_url = get_llm_base_url(base_url)
        requested_model = model or os.getenv("MA4CD_INSPECTOR_MODEL", "deepseek-chat")
        self.model, fallback_reason = normalize_model_for_endpoint(requested_model, self.base_url)
        
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not found in environment variables.")

        # 初始化客户端
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        if fallback_reason:
            logger.warning(f"[模型兼容] Inspector 模型自动回退: {fallback_reason}")
        
        # 基础系统提示词：确立“质检员”人设
        self.system_persona = (
            "You are a rigorous Data Inspector for a global scientific database pipeline. "
            "Your job is to validate URLs, assess data quality, and detect fraud/noise with high precision. "
            "You must output strict JSON format."
        )

    @staticmethod
    def _is_retryable_error(err_msg: str) -> bool:
        msg = str(err_msg or "").lower()
        retryable_markers = [
            "timeout", "timed out", "rate limit", "429", "502", "503", "504",
            "connection", "system_memory_overloaded", "bad gateway", "service unavailable"
        ]
        return any(m in msg for m in retryable_markers)

    def invoke(self, prompt: str, system_message: Optional[str] = None, require_json: bool = True) -> Union[Dict, str]:
        """
        调用大模型并获取结果。
        
        Args:
            prompt: 用户提示词
            system_message: 可选的系统提示词覆盖
            require_json: 是否强制解析为 JSON 字典
        
        Returns:
            Dict (如果 require_json=True) 或 str
        """
        messages = [
            {"role": "system", "content": system_message or self.system_persona},
            {"role": "user", "content": prompt}
        ]

        delay = self.base_retry_delay
        for attempt in range(1, self.max_retries + 1):
            try:
                before_call("inspector")
                # 构造请求参数
                params = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "timeout": self.timeout,
                }

                # 强制 JSON 模式 (针对支持 response_format 的模型，如 GPT-4o/Turbo)
                if require_json:
                    params["response_format"] = {"type": "json_object"}

                response = self.client.chat.completions.create(**params)
                content = response.choices[0].message.content.strip()
                record_success("inspector")

                if require_json:
                    return self._parse_json(content)
                return content

            except Exception as e:
                record_error("inspector", str(e))
                retryable = self._is_retryable_error(str(e))
                if retryable and attempt < self.max_retries:
                    logger.warning(
                        f"InspectorLLM transient error, retry {attempt}/{self.max_retries} after {delay:.1f}s: {str(e)[:120]}"
                    )
                    time.sleep(delay + random.uniform(0.0, 0.4))
                    delay *= self.retry_backoff
                    continue

                logger.error(f"LLM Invocation Failed: {e}")
                # 返回空结构或错误信息，避免让 Agent 崩溃
                return {"error": str(e), "is_valid": False} if require_json else f"Error: {e}"

    def _parse_json(self, content: str) -> Dict[str, Any]:
        """
        解析并清洗 JSON 字符串，处理 Markdown 代码块包裹的情况。
        """
        try:
            # 1. 尝试直接解析
            return json.loads(content)
        except json.JSONDecodeError:
            # 2. 清洗 Markdown 标记 (```json ... ```)
            cleaned_content = content
            if "```json" in cleaned_content:
                cleaned_content = cleaned_content.split("```json")[1].split("```")[0]
            elif "```" in cleaned_content:
                cleaned_content = cleaned_content.split("```")[1].split("```")[0]
            
            try:
                return json.loads(cleaned_content.strip())
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON from LLM output: {content[:100]}...")
                # 返回一个安全的空字典或错误标识，防止下游 KeyError
                return {"error": "JSON_PARSE_ERROR", "raw_content": content}

    def structured_invoke(self, prompt: str, schema: Dict) -> Dict:
        """
        (高级功能) 传入一个 Schema 结构，要求 LLM 严格按字段填充。
        这里可以简单通过 Prompt Engineering 实现，也可以用 Function Calling。
        """
        schema_str = json.dumps(schema, indent=2)
        enhanced_prompt = (
            f"{prompt}\n\n"
            f"Please output strictly according to the following JSON schema:\n"
            f"{schema_str}"
        )
        return self.invoke(enhanced_prompt, require_json=True)
