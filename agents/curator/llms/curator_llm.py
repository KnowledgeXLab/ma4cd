# agents/curator/llms/curator_llm.py

import os
import json
import re
import asyncio
from typing import Dict, List, Union, Optional
from functools import wraps
from loguru import logger
from utils.env import get_llm_api_key, get_llm_base_url, normalize_model_for_endpoint

try:
    from openai import AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

# =============================================================================
# 🛡️ 核心装甲：异步重试装饰器 (完美适配中转站网络波动)
# =============================================================================
def async_retry(retries=3, delay=2, backoff=2):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            for attempt in range(1, retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    error_msg = str(e).lower()
                    if any(k in error_msg for k in ["timeout", "rate limit", "429", "502", "503", "504", "connection"]):
                        if attempt == retries:
                            logger.error(f"❌ [重试耗尽] {func.__name__} 失败 {retries} 次: {e}")
                            raise e
                        logger.warning(f"⏳ [中转站拥堵] {current_delay}秒后进行第 {attempt}/{retries} 次重试... (报错: {str(e)[:40]})")
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        raise e
        return wrapper
    return decorator

class CuratorLLMClient:
    """
    Curator 专属的轻量级 LLM 客户端。
    剔除了复杂的进化记忆和大小脑路由，专注于稳定的战略推演和严格的 JSON 输出。
    """
    def __init__(
        self,
        api_key: str = None,
        model_name: str = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0
    ):
        self.api_key = get_llm_api_key(api_key)
        self.base_url = get_llm_base_url(base_url)
        
        if not self.api_key:
            logger.warning("⚠️ 警告: OPENAI_API_KEY 未找到，Curator LLM 可能无法工作。")

        requested_model = model_name or os.getenv("MA4CD_CURATOR_MODEL", "deepseek-chat")
        self.model, fallback_reason = normalize_model_for_endpoint(requested_model, self.base_url)
        self.timeout = timeout

        if HAS_OPENAI:
            self.aclient = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, max_retries=0)

        if fallback_reason:
            logger.warning(f"⚙️ [模型兼容] Curator 模型自动回退: {fallback_reason}")
        logger.info(f"🏛️ Curator LLM 就绪 | 接入点: {self.base_url} | 模型: {self.model}")

    def _build_messages(self, system_prompt: str, user_prompt: str) -> List[Dict]:
        return [
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": user_prompt.strip()}
        ]

    @async_retry(retries=3, delay=2, backoff=2)
    async def ainvoke(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        """纯文本异步调用"""
        if not HAS_OPENAI:
            raise RuntimeError("OpenAI 库未安装。")
            
        target_model = kwargs.get("model", self.model)
        
        response = await self.aclient.chat.completions.create(
            model=target_model,
            messages=self._build_messages(system_prompt, user_prompt),
            temperature=kwargs.get("temperature", 0.3), # 较低的温度保证战略报告的严谨性
            timeout=self.timeout
        )
        return response.choices[0].message.content.strip()

    async def ainvoke_json(self, system_prompt: str, user_prompt: str, **kwargs) -> Dict:
        """
        异步调用并严格返回 JSON 字典。
        Strategic Node 高度依赖此方法。
        """
        raw_response = await self.ainvoke(system_prompt, user_prompt, **kwargs)
        return self._extract_and_repair_json(raw_response)

    # --- 强悍的 JSON 提取与修复引擎 (原样保留，非常重要) ---
    def _extract_and_repair_json(self, response: str) -> Union[Dict, List]:
        content = response.strip()
        if not content: 
            return {"error": "empty_response"}
            
        try: return json.loads(content)
        except json.JSONDecodeError: pass

        if "```" in content:
            content = re.sub(r'^```[a-zA-Z]*\n|```$', '', content, flags=re.MULTILINE).strip()
            try: return json.loads(content)
            except json.JSONDecodeError: pass

        obj_match = re.search(r'\{.*\}', content, re.DOTALL)
        arr_match = re.search(r'\[.*\]', content, re.DOTALL)
        json_str = ""
        if obj_match and arr_match:
            json_str = obj_match.group(0) if obj_match.start() < arr_match.start() else arr_match.group(0)
        elif obj_match: json_str = obj_match.group(0)
        elif arr_match: json_str = arr_match.group(0)
        else: json_str = content

        try: return json.loads(json_str)
        except json.JSONDecodeError: pass
        json_str = re.sub(r',\s*([\}\]])', r'\1', json_str)
        try: return json.loads(json_str)
        except json.JSONDecodeError: pass
        json_str_no_newlines = json_str.replace('\n', ' ').replace('\r', '')
        try: return json.loads(json_str_no_newlines)
        except json.JSONDecodeError: pass
        json_str_quotes = re.sub(r"\'([^\']+)\'\s*:", r'"\1":', json_str_no_newlines)
        try: return json.loads(json_str_quotes)
        except Exception as e:
            logger.error(f"🧩 Curator JSON 终极修复失败: {e}")
            return {"error": "parse_failure", "raw_response": content[:500]}

def create_curator_llm(api_key=None, model_name=None, base_url=None) -> CuratorLLMClient:
    return CuratorLLMClient(api_key=api_key, model_name=model_name, base_url=base_url)
