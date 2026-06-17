
import json
import re
import asyncio
import logging
import traceback
import os
from typing import Dict, Any, List

# 配置日志
logger = logging.getLogger("commander")

# 1. 导入 MinerLLMClient
try:
    from agents.miner.llms.miner_llm import MinerLLMClient
except ImportError:
    raise ImportError("❌ 严重错误: Commander 找不到 MinerLLMClient")

# 2. 导入 Prompts
try:
    from agents.commander.prompts.planning_prompts import (
        PLANNING_TASK_PROMPT, 
        COMMANDER_CORE_IDENTITY
    )
except ImportError:
    logger.warning("⚠️ 无法导入 planning_prompts.py，使用内置 Prompt")
    COMMANDER_CORE_IDENTITY = "你是指挥官。"
    PLANNING_TASK_PROMPT = "{identity}\n请输出纯 JSON 计划。"

from utils.prompt_contracts import normalize_commander_task_config
from utils.prompt_gateway import invoke_json_contract
from utils.commander_skill import apply_commander_skill_defaults, get_planning_guidance_block

class CommanderAgent:
    def __init__(self, model_name=None):
        self.model_name = model_name
        self.llm = MinerLLMClient(model_name=model_name or os.getenv("MA4CD_COMMANDER_MODEL", "deepseek-chat"))
        self.extra_instruction = "" # 🔥 存储人类反馈指令
        logger.info(f"🫡 Commander Agent ({model_name}) 已就绪 | 模式: HITL反馈增强")

    def apply_amendment(self, amendment: Dict):
        """
        🔥 [核心接口] 应用人类反馈修正
        """
        if not amendment: return
        
        # 1. 追加 Prompt 指令
        new_instruction = amendment.get("system_prompt_append")
        if new_instruction:
            logger.info(f"🚩 Commander 收到人类最高指令: {new_instruction}")
            self.extra_instruction = new_instruction

    async def run(self, user_request: str, history_reports: List[str] = None, session_id: str = None) -> Dict[str, Any]:
        """执行规划"""
        logger.info(f"🚩 [Session: {session_id}] Commander 收到新任务: {user_request}")
        
        # 准备 Prompt
        system_message = PLANNING_TASK_PROMPT.format(
            identity=COMMANDER_CORE_IDENTITY,
            user_request="" 
        )
        
        # 🔥 [关键逻辑] 如果有 extra_instruction，拼接到 System Prompt
        if self.extra_instruction:
            system_message += f"\n\n【⚠️ 人类最高修正指令】\n{self.extra_instruction}\n请务必优先满足上述修正要求！"

        skill_block = get_planning_guidance_block()
        if skill_block:
            system_message += f"\n\n【🧩 领域 Skill 战术指引】\n{skill_block}\n"

        user_message = f"当前任务需求: {user_request}"
        
        MAX_RETRIES = 3
        
        for attempt in range(MAX_RETRIES):
            raw_response = "（尚未获取响应）"

            try:
                if attempt > 0:
                    logger.info(f"🔄 [重试 {attempt+1}/{MAX_RETRIES}] ...")
                
                # 同步调用
                raw_response = self._invoke_llm_sync(system_message, user_message)
                
                # 正则提取 JSON
                plan = self._extract_json_with_regex(raw_response)
                normalized_plan = normalize_commander_task_config(plan, user_request=user_request)
                normalized_plan = apply_commander_skill_defaults(normalized_plan, user_request=user_request)
                
                # 校验
                if not normalized_plan.get("search_queries") or len(normalized_plan["search_queries"]) == 0:
                    raise ValueError("解析成功但 search_queries 为空")

                logger.info(f"✅ 战略计划制定成功 (包含 {len(normalized_plan['search_queries'])} 个搜索词)")
                return {
                    "status": "success",
                    "core_intent": normalized_plan.get("core_intent", user_request),
                    "task_config": normalized_plan,
                    "raw_response": raw_response
                }

            except Exception as e:
                logger.warning(f"⚠️ [Attempt {attempt+1}] 失败: {e}")
                if attempt == MAX_RETRIES - 1:
                    logger.error(f"💀 最后一次失败现场: >>> {str(raw_response)[:200]}... <<<")
                    logger.error(traceback.format_exc())
                await asyncio.sleep(1)
        
        error_msg = f"❌ Commander 彻底崩溃: 连续 {MAX_RETRIES} 次失败。"
        logger.critical(error_msg)
        raise RuntimeError(error_msg)

    def _invoke_llm_sync(self, sys_prompt: str, user_prompt: str) -> str:
        """同步调用 LLM"""
        response = invoke_json_contract(self.llm, sys_prompt, user_prompt, temperature=0.2)
        if isinstance(response, dict):
            return json.dumps(response, ensure_ascii=False)
        return str(response)

    def _extract_json_with_regex(self, text: str) -> Dict:
        """正则提取 JSON"""
        if not text:
            raise ValueError("LLM 返回空字符串")
        
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except: pass

        clean_text = text.strip()
        if "```json" in clean_text:
            clean_text = clean_text.split("```json")[1].split("```")[0]
        elif "```" in clean_text:
            clean_text = clean_text.split("```")[1].split("```")[0]
        
        clean_text = clean_text.strip()
        try:
            return json.loads(clean_text)
        except json.JSONDecodeError as e:
            if not clean_text.endswith("}"):
                try: return json.loads(clean_text + "}")
                except: pass
            raise ValueError(f"JSON 格式错误: {e}")
