"""
Reflection Node (自我反思与修正)
职责：扮演“审查官”，对比原始需求与初版计划，修正偏差。
"""
import json
from loguru import logger
from ..state.commander_state import CommanderState
from ..llms.commander_llm import CommanderLLM
from ..prompts import COMMANDER_CORE_IDENTITY, REFLECTION_TASK_PROMPT

class ReflectionNode:
    def __init__(self, llm: CommanderLLM):
        self.llm = llm

    async def execute(self, state: CommanderState) -> CommanderState:
        logger.info("🪞 [ReflectionNode] 开始自我反思与审查...")

        # 1. 准备输入数据
        draft_str = json.dumps(state.draft_plan, ensure_ascii=False, indent=2)
        
        # 2. 构建反思 Prompt
        formatted_system_prompt = REFLECTION_TASK_PROMPT.format(
            identity=COMMANDER_CORE_IDENTITY,
            user_request=state.user_request,
            draft_plan=draft_str
        )

        try:
            # 3. 调用 LLM 进行批判
            reflection_result = await self.llm.invoke_json(
                prompt="请审查上述计划，如果不完美请提供修正后的 JSON。",
                system_instruction=formatted_system_prompt
            )
            
            # 4. 解析结果并决策
            state.reflection_result = reflection_result
            
            # 检查 LLM 是否认为完美
            # 注意：JSON 中的 boolean 有时可能是字符串 "true"/"false"，这里做个兼容处理
            is_perfect = reflection_result.get("is_perfect", False)
            if isinstance(is_perfect, str):
                is_perfect = is_perfect.lower() == "true"

            critique = reflection_result.get("critique", "无评论")
            
            if is_perfect:
                # 完美，直接通过
                state.update_final_plan(state.draft_plan, refined=False)
                logger.info(f"✅ 自我反思通过: {critique}")
            else:
                # 不完美，提取修正后的计划
                revised_plan = reflection_result.get("revised_plan")
                if revised_plan and isinstance(revised_plan, dict):
                    state.update_final_plan(revised_plan, refined=True)
                    logger.warning(f"⚠️ 自我反思触发修正: {critique}")
                    logger.info("🔄 已应用修正后的计划。")
                else:
                    # 如果 LLM 说要改，但没给 revised_plan，只能沿用旧的
                    logger.error("❌ 反思建议修改，但未提供修正后的 JSON。沿用初稿。")
                    state.update_final_plan(state.draft_plan, refined=False)

        except Exception as e:
            logger.error(f"❌ 反思阶段异常: {e}，跳过反思，直接使用初稿。")
            state.update_final_plan(state.draft_plan, refined=False)

        return state