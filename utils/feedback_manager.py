
'''import json
import logging
from typing import Dict, Any

# 复用 MinerLLMClient
try:
    from agents.miner.llms.miner_llm import MinerLLMClient
except ImportError:
    raise ImportError("需要 MinerLLMClient 支持")

logger = logging.getLogger("feedback_manager")

class FeedbackManager:
    """
    反馈指令官
    职责：接收人类自然语言，解析为针对 4 个 Agent 的具体参数或 Prompt 修正。
    """
    def __init__(self):
        self.llm = MinerLLMClient()

    async def translate_feedback(self, user_feedback: str, current_context: str) -> Dict[str, Any]:
        """
        核心方法：将自然语言转化为结构化调整指令
        """
        logger.info("👂 正在解析人类反馈指令...")
        
        system_prompt = """
        你是一个 AI 系统的调试专家。该系统包含 4 个智能体：
        1. Commander (指挥官): 负责生成搜索词 (Search Queries) 和策略 (Tier 1/2/3)。
        2. Scout (侦察兵): 负责执行搜索，过滤黑名单。
        3. Miner (矿工): 负责从网页挖掘链接。
        4. Inspector (审查官): 负责 L1-L4 分级和质量评分。

        任务：
        根据用户的【自然语言反馈】，生成针对特定 Agent 的【修正指令 (Amendment)】。
        
        输出格式 (JSON):
        {
            "target_agent": "Commander" 或 "Scout" 或 "Miner" 或 "Inspector" 或 "All",
            "action": "retry" (重试) 或 "stop" (结束),
            "amendments": {
                "system_prompt_append": "附加给该 Agent 的额外系统提示词...",
                "config_update": { "key": "value" } (例如 max_depth, filters 等)
            },
            "reasoning": "解析思路..."
        }
        """

        user_prompt = f"""
        当前任务上下文: {current_context}
        用户反馈: "{user_feedback}"
        
        请分析用户的意图，他是想修改搜索词？还是想放宽审查标准？还是想换个国家搜？
        请输出 JSON。
        """

        try:
            # 调用 LLM 解析
            response = await self.llm.invoke_json(system_prompt, user_prompt)
            # 兼容性处理（同 Commander）
            if not isinstance(response, dict):
                import json
                # 尝试解析
                # ... (这里可以使用 commander 中那种正则提取逻辑) ...
                pass 
            return response
        except Exception as e:
            logger.error(f"反馈解析失败: {e}")
            return {"target_agent": "None", "action": "stop"}'''


"""
Feedback Manager (Multi-Agent Directed Version)
职责：
1. 接收针对特定 Agent 的自然语言反馈 (Map 结构)。
2. 将其精准翻译为该 Agent 可执行的 System Prompt 或 Config 更新。
"""


import json
import logging
import re
import ast
import asyncio
from typing import Dict, Any, List, Union

# 复用 MinerLLMClient (做 Mock 防止导入失败)
try:
    from agents.miner.llms.miner_llm import MinerLLMClient
except ImportError:
    class MinerLLMClient:
        async def invoke_json(self, *args, **kwargs): return []
    print("❌ 警告: 无法导入 MinerLLMClient")

logger = logging.getLogger("feedback_manager")

class FeedbackManager:
    def __init__(self):
        self.llm = MinerLLMClient()

    async def parse_structured_feedback(self, feedback_map: Dict[str, str], current_context: str = "") -> List[Dict[str, Any]]:
        """
        🔥 终极稳定版 v4.1 (修复 Logger 崩溃问题)：
        策略：先让 LLM 尝试结构化 -> 如果失败，直接使用原始输入兜底。
        保证：绝不丢单！
        """
        # 1. 过滤掉空反馈
        active_feedbacks = {k: v for k, v in feedback_map.items() if v and v.strip()}
        
        if not active_feedbacks:
            return []

        logger.info(f"👂 收到反馈，目标: {list(active_feedbacks.keys())}")

        # =========================================================
        # 尝试阶段：让 LLM 把它变得更像“机器指令”
        # =========================================================
        system_prompt = """
        你是一个 AI 系统指令转化器。
        请将用户的自然语言建议转化为 JSON 配置。
        涉及角色：[Commander], [Scout], [Miner], [Inspector]。
        
        如果用户想修改配置（如"把最大深度设为3"），请生成 "config_update": {"max_depth": 3}。
        如果用户只是给建议（如"不要找维基百科"），请生成 "system_prompt_append": "..."。
        
        格式示例：
        [
            {
                "target_agent": "Commander",
                "amendments": { "system_prompt_append": "..." },
                "reasoning": "..."
            }
        ]
        只输出 JSON，不要 Markdown。
        """

        user_prompt = f"""
        【用户原始反馈】: 
        {json.dumps(active_feedbacks, ensure_ascii=False)}
        
        请转化为标准 JSON List。
        """

        parsed_data = None
        try:
            # 调用 LLM
            raw_res = await self.llm.invoke_json(system_prompt, user_prompt)
            # 兼容异步/同步返回
            if asyncio.iscoroutine(raw_res): raw_res = await raw_res
            
            # 解析结果
            parsed_data = self._clean_and_parse_json(raw_res)
            
        except Exception as e:
            logger.warning(f"⚠️ LLM 结构化解析出现异常: {e}")

        # =========================================================
        # 🔥 核心修正：兜底机制 (Fallback Mechanism)
        # =========================================================
        final_list = []

        # 分支 A: LLM 解析成功，使用高级结构
        if parsed_data and isinstance(parsed_data, list) and len(parsed_data) > 0:
            logger.info("✨ 使用 LLM 结构化后的指令")
            for item in parsed_data:
                final_list.append(self._normalize_item(item))
                
        # 分支 B: LLM 解析失败（或返回空），直接使用原始输入
        else:
            logger.warning("🛡️ LLM 解析失败，启动【强制兜底模式】。直接使用用户原始文本。")
            for agent_name, raw_text in active_feedbacks.items():
                final_list.append({
                    "target_agent": agent_name,
                    "amendments": {"system_prompt_append": raw_text}, # 原话传进去
                    "reasoning": "User Raw Input (Fallback)"
                })

        # 🔥 [修复点] 原来是 logger.success (会导致报错)，现在改为 logger.info
        logger.info(f"✅ 最终生成 {len(final_list)} 条指令")
        return final_list

    def _normalize_item(self, item: Dict) -> Dict:
        """确保 amendments 是字典结构"""
        if "amendments" in item:
            if not isinstance(item["amendments"], dict):
                item["amendments"] = {"system_prompt_append": str(item["amendments"])}
        else:
            content = item.get("instruction") or item.get("prompt") or item.get("content") or "No content"
            item["amendments"] = {"system_prompt_append": str(content)}
        return item

    def _clean_and_parse_json(self, raw_input: Any) -> Union[Dict, List, None]:
        """强力 JSON 解析器"""
        if isinstance(raw_input, (dict, list)):
            return raw_input

        text = str(raw_input).strip()
        if not text: return None

        # 1. 去除 Markdown
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if match: text = match.group(1).strip()

        # 2. 尝试标准 JSON
        try:
            return json.loads(text)
        except:
            pass

        # 3. 尝试 AST Eval (处理单引号)
        try:
            if (text.startswith('[') and text.endswith(']')) or (text.startswith('{') and text.endswith('}')):
                return ast.literal_eval(text)
        except:
            pass
            
        # 4. 尝试修复常见错误 (未转义换行)
        try:
            fixed_text = text.replace('\n', '\\n')
            return json.loads(fixed_text)
        except:
            pass

        return None