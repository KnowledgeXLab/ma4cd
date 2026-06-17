import os
import sys
import json
import re
import asyncio
import time
import random
from datetime import datetime
from typing import Any, Dict, Optional, List, Union
from functools import wraps
from loguru import logger
from utils.env import get_llm_api_key, get_llm_base_url, normalize_model_for_endpoint
from utils.llm_budgeter import before_call, record_error, record_success

# 仅保留 OpenAI 导入，因为中转站兼容 OpenAI 协议
try:
    from openai import OpenAI, AsyncOpenAI
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
                    # 中转站常见的 429 (限流) 或 50x (上游超时) 均在此捕获
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

class MinerLLMClient:
    def __init__(
        self,
        api_key: str = None,
        model_name: str = None,
        base_url: Optional[str] = None,
        timeout: float = 90.0,
        max_retries: int = 5
    ):
        # 1. 优先级：参数 > 环境变量
        self.api_key = get_llm_api_key(api_key)
        self.base_url = get_llm_base_url(base_url)
        
        if not self.api_key:
            raise ValueError("API key is required.")

        # 2. 模型定义
        default_small_model = os.getenv("MA4CD_MINER_SMALL_MODEL", "deepseek-chat")
        default_big_model = os.getenv("MA4CD_MINER_BIG_MODEL", "deepseek-chat")
        requested_small_model = model_name or default_small_model
        requested_big_model = default_big_model
        self.small_model, small_fallback_reason = normalize_model_for_endpoint(
            requested_small_model, self.base_url
        )
        self.big_model, big_fallback_reason = normalize_model_for_endpoint(
            requested_big_model, self.base_url
        )
        
        self.timeout = timeout
        self.sync_max_retries = int(os.getenv("MA4CD_LLM_SYNC_RETRIES", "4"))
        self.sync_retry_delay = float(os.getenv("MA4CD_LLM_SYNC_RETRY_DELAY", "1.5"))
        self.sync_retry_backoff = float(os.getenv("MA4CD_LLM_SYNC_RETRY_BACKOFF", "2.0"))

        # 3. 初始化 OpenAI 格式客户端
        # 注意：中转站模式下，我们只需一套 OpenAI 客户端即可通过 model 切换厂商
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, max_retries=0)
        self.aclient = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, max_retries=0)

        logger.info(f"🚀 MA4CD 中转动力就绪 | 接入点: {self.base_url}")
        if small_fallback_reason:
            logger.warning(f"⚙️ [模型兼容] 小脑模型自动回退: {small_fallback_reason}")
        if big_fallback_reason:
            logger.warning(f"⚙️ [模型兼容] 大脑模型自动回退: {big_fallback_reason}")
        logger.info(f"🧠 模型配置 | 🟢 小脑: {self.small_model} | 🔴 大脑: {self.big_model}")

    def _build_messages(self, system_prompt: str, user_prompt: str, evolutionary_memory: Optional[Union[str, Dict]] = None) -> List[Dict]:
        """构建标准消息体"""
        full_system_prompt = system_prompt.strip()
        if evolutionary_memory:
            memory_text = ""
            if isinstance(evolutionary_memory, dict):
                issues = evolutionary_memory.get("issues", [])
                adjustments = evolutionary_memory.get("strategy_adjustments", {})
                memory_parts = []
                if issues: memory_parts.append(f"- 历史问题: {', '.join(issues)}")
                if adjustments: memory_parts.append(f"- 优化策略: {json.dumps(adjustments, ensure_ascii=False)}")
                memory_text = "\n".join(memory_parts)
            else:
                memory_text = str(evolutionary_memory)
            if memory_text:
                full_system_prompt += f"\n\n⚠️ 【进化记忆注入】：\n{memory_text}"

        return [
            {"role": "system", "content": full_system_prompt},
            {"role": "user", "content": user_prompt.strip()}
        ]

    @async_retry(retries=5, delay=2, backoff=2)
    async def ainvoke(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        """异步调用：根据 use_big_brain 自动路由模型"""
        use_big_brain = kwargs.get("use_big_brain", False)
        target_model = self.big_model if use_big_brain else self.small_model
        
        if use_big_brain:
            logger.debug(f"🔴 路由至大脑模型 -> {target_model}")
        else:
            logger.debug(f"🟢 路由至小脑模型 -> {target_model}")
            
        evo_memory = kwargs.get("evolutionary_memory")
        try:
            before_call("miner")
            response = await self.aclient.chat.completions.create(
                model=target_model,
                messages=self._build_messages(system_prompt, user_prompt, evo_memory),
                temperature=kwargs.get("temperature", 0.3),
                timeout=self.timeout
            )
            record_success("miner")
            return response.choices[0].message.content.strip()
        except Exception as e:
            record_error("miner", str(e))
            raise

    def invoke(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        """同步调用：中转站兼容模式"""
        use_big_brain = kwargs.get("use_big_brain", False)
        target_model = self.big_model if use_big_brain else self.small_model
        
        evo_memory = kwargs.get("evolutionary_memory")
        delay = self.sync_retry_delay
        for attempt in range(1, self.sync_max_retries + 1):
            try:
                before_call("miner")
                response = self.client.chat.completions.create(
                    model=target_model,
                    messages=self._build_messages(system_prompt, user_prompt, evo_memory),
                    temperature=kwargs.get("temperature", 0.3),
                    timeout=self.timeout
                )
                record_success("miner")
                return response.choices[0].message.content.strip()
            except Exception as e:
                record_error("miner", str(e))
                error_msg = str(e).lower()
                retryable = any(
                    k in error_msg for k in
                    ["timeout", "rate limit", "429", "502", "503", "504", "connection", "bad gateway", "system_memory_overloaded"]
                )
                if retryable and attempt < self.sync_max_retries:
                    logger.warning(
                        f"⏳ [同步调用拥堵] {delay:.1f}秒后进行第 {attempt}/{self.sync_max_retries} 次重试... (报错: {str(e)[:80]})"
                    )
                    time.sleep(delay + random.uniform(0.0, 0.4))
                    delay *= self.sync_retry_backoff
                    continue
                raise

    # --- 以下保留你所有的 JSON 修复和辅助逻辑 ---
    
    async def ainvoke_json(self, system_prompt: str, user_prompt: str, **kwargs) -> Dict:
        raw = await self.ainvoke(system_prompt, user_prompt, **kwargs)
        return self._extract_and_repair_json(raw)

    def invoke_json(self, system_prompt: str, user_prompt: str, **kwargs) -> Dict:
        raw = self.invoke(system_prompt, user_prompt, **kwargs)
        return self._extract_and_repair_json(raw)

    async def ask(self, prompt: str, response_format: str = "text", **kwargs) -> Union[str, Dict]:
        default_system = "You are a professional web data mining assistant."
        if response_format.lower() == "json":
            return await self.ainvoke_json(default_system, prompt, **kwargs)
        return await self.ainvoke(default_system, prompt, **kwargs)

    def get_evolved_prompt(self, base_prompt, domain):
        if not hasattr(self, 'evolution_engine') or not self.evolution_engine:
            return base_prompt
        try:
            config = self.evolution_engine.get_global_best_config(domain)
            hint = config.get('prompt_hint', "")
            if hint: return f"{base_prompt}\n\n【历史经验注入】：{hint}"
        except Exception as e:
            logger.error(f"提取进化提示词失败: {e}")
        return base_prompt

    def _extract_and_repair_json(self, response: str) -> Union[Dict, List]:
        content = response.strip()
        if not content: return {"error": "empty_response"}
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
            logger.error(f"🧩 JSON 终极修复失败: {e}")
            return {"error": "parse_failure", "raw_response": content[:500]}

def create_miner_llm(api_key=None, model_name=None, base_url=None) -> MinerLLMClient:
    return MinerLLMClient(api_key=api_key, model_name=model_name, base_url=base_url)
