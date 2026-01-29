import os
import sys
import json
import re
import asyncio
from datetime import datetime
from typing import Any, Dict, Optional, List, Union
from loguru import logger

try:
    from openai import OpenAI, AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

class MinerLLMClient:
    def __init__(
        self,
        api_key: str = None,
        model_name: str = "gpt-4o-mini",
        base_url: Optional[str] = None,
        timeout: float = 90.0,
        max_retries: int = 5
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
        if not self.api_key:
            raise ValueError("LLM API key is required.")
        
        self.model_name = model_name
        self.base_url = base_url
        self.timeout = timeout
        self.prompt_overrides = {}
        
        # 初始化客户端
        self.client = OpenAI(api_key=self.api_key, base_url=base_url, max_retries=0)
        self.aclient = AsyncOpenAI(api_key=self.api_key, base_url=base_url, max_retries=0)
        logger.info(f"MinerLLMClient 已优化: {model_name} (记忆自进化引擎已就绪)")

    def _build_messages(
        self, 
        system_prompt: str, 
        user_prompt: str, 
        evolutionary_memory: Optional[Union[str, Dict]] = None
    ) -> List[Dict]:
        """
        构建消息体，并将进化记忆织入 System Prompt
        """
        full_system_prompt = system_prompt.strip()

        # 如果存在进化记忆（来自 ReflectionNode 的历史输出）
        if evolutionary_memory:
            memory_text = ""
            if isinstance(evolutionary_memory, dict):
                # 提取 Issues 和 Adjustments 转化为可读文本
                issues = evolutionary_memory.get("issues", [])
                adjustments = evolutionary_memory.get("strategy_adjustments", {})
                
                memory_parts = []
                if issues:
                    memory_parts.append(f"- 历史发现的问题: {', '.join(issues)}")
                if adjustments:
                    adj_str = json.dumps(adjustments, ensure_ascii=False)
                    memory_parts.append(f"- 已固化的优化策略: {adj_str}")
                memory_text = "\n".join(memory_parts)
            else:
                memory_text = str(evolutionary_memory)

            if memory_text:
                full_system_prompt += (
                    "\n\n"
                    "⚠️ 重要：以下是基于历史运行结果的【自进化记忆】，请务必参考并改进本次执行策略：\n"
                    f"{memory_text}"
                )

        # 建议在 _build_messages 结尾返回前加一行：
        logger.debug(f"📤 发送给 GPT 的最终系统提示词长度: {len(full_system_prompt)}")
        # 或者直接打印出注入的片段
        if "⚠️" in full_system_prompt:
            logger.info("🧠 提示词注入成功：Agent 正在阅读自己的进化记忆...")
            
        return [
            {"role": "system", "content": full_system_prompt},
            {"role": "user", "content": user_prompt.strip()}
        ]

    def invoke(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        """同步调用"""
        evo_memory = kwargs.get("evolutionary_memory")
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=self._build_messages(system_prompt, user_prompt, evo_memory),
            temperature=kwargs.get("temperature", 0.3),
            timeout=self.timeout
        )
        return response.choices[0].message.content.strip()

    async def ainvoke(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        """异步调用 (推荐)"""
        evo_memory = kwargs.get("evolutionary_memory")
        response = await self.aclient.chat.completions.create(
            model=self.model_name,
            messages=self._build_messages(system_prompt, user_prompt, evo_memory),
            temperature=kwargs.get("temperature", 0.3),
            timeout=self.timeout
        )
        return response.choices[0].message.content.strip()

    def invoke_json(self, system_prompt: str, user_prompt: str, **kwargs) -> Dict:
        """同步获取 JSON"""
        raw = self.invoke(system_prompt, user_prompt, **kwargs)
        return self._extract_and_repair_json(raw)

    async def ainvoke_json(self, system_prompt: str, user_prompt: str, **kwargs) -> Dict:
        """异步获取 JSON"""
        raw = await self.ainvoke(system_prompt, user_prompt, **kwargs)
        return self._extract_and_repair_json(raw)
    
    def get_evolved_prompt(self, base_prompt, domain):
        # 调用进化引擎获取当前最优配置
        config = self.evolution_engine.get_global_best_config(domain)
        hint = config.get('prompt_hint', "")
        
        if hint:
            return f"{base_prompt}\n\n【历史经验注入】：{hint}"
        return base_prompt

    def _extract_and_repair_json(self, response: str) -> Dict:
        """高级 JSON 提取与修复逻辑"""
        content = response.strip()
        
        # 修复日志中的 SyntaxWarning: 使用 r'' 前缀处理反斜杠
        match = re.search(r'```(?:json)?\s*(\{[\s\S]*\})\s*```', content)
        if not match:
            match = re.search(r'(\{[\s\S]*\})', content)
        
        json_str = match.group(1) if match else content

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            try:
                # 修复末尾逗号逻辑
                fixed_str = re.sub(r',\s*([\]}])', r'\1', json_str)
                # 修复常见的控制字符问题
                fixed_str = fixed_str.replace('\n', ' ').replace('\r', '')
                return json.loads(fixed_str)
            except:
                logger.error(f"JSON 修复失败。原始响应片段: {response[:100]}...")
                return {"error": "parse_failure", "raw": response}

def create_miner_llm(
    api_key: Optional[str] = None,
    model_name: str = "gpt-4o-mini",
    base_url: Optional[str] = None
) -> MinerLLMClient:
    return MinerLLMClient(api_key=api_key, model_name=model_name, base_url=base_url)