import json
import re
import traceback
from typing import Dict, Any, List
from loguru import logger

# =============================================================================
# 📦 依赖导入 (使用绝对路径，确保稳定)
# =============================================================================
try:
    from agents.commander.state.commander_state import CommanderState
    from agents.commander.llms.commander_llm import CommanderLLM
    from agents.commander.prompts.planning_prompts import COMMANDER_CORE_IDENTITY, PLANNING_TASK_PROMPT
except ImportError:
    # 兼容性导入，防止在非标准环境下运行报错
    from ..state.commander_state import CommanderState
    from ..llms.commander_llm import CommanderLLM
    from ..prompts import PLANNING_TASK_PROMPT, COMMANDER_CORE_IDENTITY

class PlanningNode:
    """
    Planning Node (增强版)
    职责：接收用户自然语言需求，生成结构化的 JSON 搜索策略。
    特性：具备抗噪 JSON 解析能力和自动降级机制。
    """
    
    def __init__(self, llm: CommanderLLM):
        self.llm = llm

    async def execute(self, state: CommanderState) -> CommanderState:
        logger.info(f"🧠 [PlanningNode] 开始规划任务: {state.user_request[:50]}...")

        # 1. 整理历史记忆 (进化机制)
        history_context = "无历史反馈 (本次为全新任务)"
        if state.history_reports:
            # 提取最近 3 条报告的摘要或关键问题
            history_summary = []
            for r in state.history_reports[-3:]:
                if isinstance(r, dict):
                    history_summary.append(r.get("summary", "No Summary") + " Issues: " + str(r.get("issues", [])))
                else:
                    history_summary.append(str(r))
            
            history_context = json.dumps(history_summary, ensure_ascii=False, indent=2)
            logger.info(f"🧬 [Evolution] 已注入 {len(history_summary)} 条历史经验")

        # 2. 构建 Prompt (System/User 分离)
        # System: 定义身份和输出格式
        system_content = PLANNING_TASK_PROMPT.format(
            identity=COMMANDER_CORE_IDENTITY,
            user_request=state.user_request, # 这里虽然传了，但在 User Prompt 再强调一次
            history_context=history_context
        )
        
        # User: 传入具体指令
        user_content = f"""
        【当前任务】
        用户需求: "{state.user_request}"
        
        【历史教训】
        {history_context}
        
        请输出 JSON 格式的搜索计划，不要包含任何 Markdown 标记。
        """

        # 3. 调用 LLM & 解析
        try:
            # 尝试调用 chat 方法 (假设返回字符串)
            # 如果你的 CommanderLLM 是 ainvoke 风格，这里会自动适配
            response_str = ""
            if hasattr(self.llm, 'chat'):
                response_str = await self.llm.chat(
                    system_prompt=system_content, 
                    user_prompt=user_content
                )
            elif hasattr(self.llm, 'invoke_json'):
                # 兼容旧接口
                response_str = await self.llm.invoke_json(
                    prompt=user_content,
                    system_instruction=system_content
                )
            else:
                # 尝试直接调用
                response_str = await self.llm(user_content)

            # 4. 鲁棒解析 JSON
            if isinstance(response_str, dict):
                draft_plan = response_str
            else:
                draft_plan = self._robust_json_parse(str(response_str))
            
            # 校验关键字段
            if not draft_plan or "search_queries" not in draft_plan:
                raise ValueError("LLM 返回的 JSON 缺少 'search_queries' 关键字段")

            # 5. 更新状态
            state.draft_plan = draft_plan
            
            # 打印调试信息
            tier = draft_plan.get('target_tier', 'Unknown')
            queries_count = len(draft_plan.get('search_queries', []))
            logger.info(f"📝 初版计划生成完毕 (Target: {tier} | Queries: {queries_count})")

        except Exception as e:
            logger.error(f"❌ 规划阶段异常: {e}")
            logger.debug(traceback.format_exc())
            
            # 🚨 降级兜底策略 (Fallback Strategy)
            # 确保即使 LLM 挂了，Scout 也有活干
            logger.warning("⚠️ 启用降级策略: 使用原始需求作为搜索词")
            
            # 简单的关键词提取（按空格拆分取前几个，或者直接用整句）
            fallback_queries = [state.user_request]
            if len(state.user_request) > 10:
                fallback_queries.append(state.user_request[:20]) # 尝试截取短语
            
            state.draft_plan = {
                "target_tier": "Tier 1", # 默认最高优先级
                "task_type": "general",
                "scout_config": {
                    "max_concurrent": 3,
                    "search_depth": 2,
                    "enable_translation": True, # 保守起见开启翻译
                    "country_code": "us, cn"    # 默认覆盖主要区域
                },
                "search_queries": fallback_queries,
                "reasoning": f"System Fallback: PlanningNode crashed due to {str(e)}"
            }

        return state

    def _robust_json_parse(self, text: str) -> Dict[str, Any]:
        """
        增强型 JSON 解析器
        能够处理 Markdown 代码块、不规范的格式等
        """
        text = text.strip()
        
        # 1. 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2. 提取 Markdown 代码块 (```json ... ```)
        try:
            pattern = r"```(?:json)?\s*(.*?)\s*```"
            match = re.search(pattern, text, re.DOTALL)
            if match:
                clean_text = match.group(1)
                return json.loads(clean_text)
        except:
            pass

        # 3. 暴力提取最外层大括号
        try:
            pattern = r"(\{.*\})"
            match = re.search(pattern, text, re.DOTALL)
            if match:
                clean_text = match.group(1)
                return json.loads(clean_text)
        except:
            pass
            
        logger.warning(f"无法从响应中提取 JSON: {text[:100]}...")
        return {}