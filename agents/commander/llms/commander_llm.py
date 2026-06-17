import json
import re
import inspect
import os
from typing import Dict, Any, Optional
from loguru import logger

class CommanderLLM:
    """
    Commander 专用 LLM 客户端 (强力解析版)
    集成 Regex JSON 提取器，防止因格式问题导致计划失败
    """

    def __init__(self, model: str = None, temperature: float = 0.3):
        self.model = model or os.getenv("MA4CD_COMMANDER_MODEL", "deepseek-chat")
        self.temperature = temperature
        self.client = self._initialize_backend()
        
        self.base_system_prompt = (
            "你是 MA4CD (Multi-Agent Data Mining System) 的最高指挥官。\n"
            "你的职责是将模糊的人类业务需求，拆解为精准、可执行的技术搜索策略。\n"
            "你需要具备战略眼光，能够识别用户的潜在意图，并具备自我反思能力。\n"
            "在输出时，请保持逻辑严密，优先使用结构化数据（JSON）。"
        )

    def _initialize_backend(self):
        try:
            from agents.miner.llms.miner_llm import MinerLLMClient
            client = MinerLLMClient(model_name=self.model)
            if client.client: 
                return client
            return None
        except Exception as e:
            logger.error(f"❌ 初始化 MinerLLMClient 失败: {e}")
            return None

    async def invoke(self, prompt: str, system_instruction: str = "") -> str:
        """通用文本生成接口"""
        full_system_prompt = f"{self.base_system_prompt}\n{system_instruction}"
        
        if self.client:
            try:
                # 获取返回值
                result = self.client.invoke(
                    system_prompt=full_system_prompt,
                    user_prompt=prompt
                )
                
                # 兼容异步/同步返回
                if inspect.iscoroutine(result):
                    return await result
                return str(result)
                
            except Exception as e:
                logger.error(f"❌ CommanderLLM 调用后端失败: {e}")
        
        return f"[Mock Output] 收到请求: {prompt[:30]}..."

    async def invoke_json(self, prompt: str, system_instruction: str = "") -> Dict[str, Any]:
        """
        强制返回 JSON 格式的接口 (带强力清洗)
        """
        full_system_prompt = f"{self.base_system_prompt}\n{system_instruction}"
        
        if self.client:
            try:
                # 1. 调用 LLM
                raw_response = self.client.invoke_json(
                    system_prompt=full_system_prompt,
                    user_prompt=prompt
                )
                
                # 兼容异步返回
                if inspect.iscoroutine(raw_response):
                    raw_response = await raw_response

                # 2. 如果已经是字典，直接返回
                if isinstance(raw_response, dict):
                    return raw_response

                # 3. 如果是字符串，进行强力清洗
                if isinstance(raw_response, str):
                    return self._robust_json_parse(raw_response)
                
            except Exception as e:
                logger.error(f"❌ CommanderLLM JSON 处理严重错误: {e}")

        return {}

    def _robust_json_parse(self, text: str) -> Dict[str, Any]:
        """
        [核心修复] 使用正则表达式提取 JSON，无视 Markdown 和废话
        """
        try:
            # 1. 尝试直接解析
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        try:
            # 2. 使用正则提取最外层的 {}
            # match = re.search(r"\{.*\}", text, re.DOTALL) # 贪婪匹配
            # 更好的是寻找第一个 { 和最后一个 }
            start = text.find('{')
            end = text.rfind('}')
            
            if start != -1 and end != -1:
                json_str = text[start : end + 1]
                return json.loads(json_str)
            else:
                logger.warning(f"⚠️ 无法在响应中找到 JSON 对象: {text[:50]}...")
                return {}
        except Exception as e:
            logger.error(f"❌ JSON 正则提取失败: {e}")
            # 调试用：打印出有问题的文本
            logger.debug(f"Failed Text Snippet: {text[:100]}")
            return {}
