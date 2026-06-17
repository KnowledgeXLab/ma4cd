"""
任务规划节点 - 将用户任务分解为搜索子任务
升级：支持动态指令更新 (update_instruction)，实现最高优先级的语义覆盖。
全面适配 OSINT 深度查询扩展 (Query Expansion)
"""

import json
import uuid
from typing import List, Dict, Any, Optional
from loguru import logger

from .base_node import StateMutationNode
from ..state.state import ScoutState, SearchSubTask, SearchStatus
from ..prompts.prompts import SYSTEM_PROMPT_PLANNING
from utils.prompt_gateway import invoke_json_contract
from utils.prompt_contracts import normalize_search_query_item, normalize_scoring_rubric


class PlanningNode(StateMutationNode):
    """任务规划节点"""
    
    # 🌟 核心升级 1：将最大子任务数从 5 放宽到 15，彻底释放大模型扩展火力
    def __init__(self, llm_client, max_subtasks: int = 15):
        super().__init__(llm_client, "PlanningNode")
        self.max_subtasks = max_subtasks
        # 🧠 核心新增：存储来自 Agent 的动态修正指令
        self.dynamic_instruction = ""
        self.latest_scoring_rubric: Dict[str, Any] = {}
    
    def update_instruction(self, instruction: str):
        """
        🔥 [核心接口] 由 ScoutAgent 调用，注入人类反馈。
        """
        if instruction:
            self.dynamic_instruction = instruction
            self.log_info(f"🧬 PlanningNode 已注入动态进化基因: {instruction[:30]}...")

    def _build_user_prompt(self, input_data: Any) -> str:
        if isinstance(input_data, dict):
            payload = {
                "user_request": str(input_data.get("user_request", "")).strip(),
                "commander_task_config": input_data.get("commander_task_config", {}),
                "runtime_config": input_data.get("runtime_config", {}),
            }
        else:
            payload = {
                "user_request": str(input_data),
                "commander_task_config": {},
                "runtime_config": {},
            }

        if self.dynamic_instruction:
            payload["priority_instruction"] = self.dynamic_instruction

        return (
            "请基于以下结构化输入生成搜索规划（必须输出 JSON）。\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def run(self, input_data: Any, state: Optional[ScoutState] = None, **kwargs) -> List[Dict[str, Any]]:
        """生成搜索子任务规划"""
        input_repr = input_data if isinstance(input_data, str) else json.dumps(input_data, ensure_ascii=False)
        
        self.log_info(f"开始 OSINT 深度规划任务: {input_repr[:80]}...")
        
        final_user_prompt = self._build_user_prompt(input_data)

        try:
            # 第二步：统一调用入口，拿结构化结果
            response = invoke_json_contract(
                self.llm_client,
                SYSTEM_PROMPT_PLANNING,
                final_user_prompt,
                temperature=0.3,
                max_tokens=2200
            )
            
            # 第三步：解析规划结果
            subtasks = self._parse_planning_response(response)
            
            self.log_info(f"战略规划完成，生成 {len(subtasks)} 个多维检索子任务")
            return subtasks
            
        except Exception as e:
            self.log_error(f"任务规划失败: {str(e)}，不生成默认/规则 query")
            return []
    
    def _parse_planning_response(self, response: Any) -> List[Dict[str, Any]]:
        """解析规划结果，兼容 dict 与文本回退。"""
        data: Dict[str, Any] = {}
        if isinstance(response, dict):
            data = response
        elif isinstance(response, str):
            try:
                start_idx = response.find('{')
                end_idx = response.rfind('}') + 1
                if start_idx != -1 and end_idx > start_idx:
                    data = json.loads(response[start_idx:end_idx])
            except Exception as e:
                self.log_warning(f"JSON 解析失败: {e}, 尝试进入文本解析回退")
                return self._parse_text_response(response)
        else:
            return []

        # --- 1. 解析并打印大模型的战略推理 ---
        analysis = data.get("strategic_analysis", {})
        if isinstance(analysis, dict) and analysis:
            self.log_info("="*50)
            self.log_info("🧠 [Scout OSINT 战术拆解]")
            self.log_info(f"🎯 目标领域: {analysis.get('target_domain', 'Unknown')}")
            self.log_info(f"🌍 目标区域: {analysis.get('target_region', 'Global')} | 采用语种: {analysis.get('native_language_used', 'en')}")
            sub_disciplines = analysis.get('identified_sub_disciplines', [])
            if isinstance(sub_disciplines, list) and sub_disciplines:
                self.log_info(f"🧩 子领域裂变: {', '.join(sub_disciplines)}")
            self.log_info("="*50)

        # --- 1.1 解析评分规则（统一契约） ---
        rubric = normalize_scoring_rubric(data.get("scoring_rubric", {}))
        self.latest_scoring_rubric = rubric

        # --- 2. 解析并组装扩展检索词 ---
        queries_data = data.get("search_queries", [])
        if not isinstance(queries_data, list):
            queries_data = []

        subtasks = []
        for i, item in enumerate(queries_data[:self.max_subtasks]):
            normalized_item = normalize_search_query_item(item)
            if not normalized_item:
                continue

            query = normalized_item["search_query"]
            tier = normalized_item["tier"]
            lang = normalized_item["language"]
            desc = normalized_item["description"]
            score_hint = normalized_item.get("score_hint", {})

            self.log_info(f"🔎 [火力分配] ({tier}) [{lang}]: {query}")

            subtask = {
                "id": f"subtask_{uuid.uuid4().hex[:8]}",
                "query": query,
                "tier": tier,
                "description": f"{desc} | score_hint={score_hint}",
                "order": i
            }
            subtasks.append(subtask)

        return subtasks
    
    def _parse_text_response(self, response: str) -> List[Dict[str, Any]]:
        """文本格式解析回退"""
        lines = response.strip().split('\n')
        subtasks = []
        
        for i, line in enumerate(lines[:self.max_subtasks]):
            clean_line = line.strip().lstrip('0123456789.-* "') # 清除列表序号和引号
            if clean_line and len(clean_line) > 5:
                subtask = {
                    "id": f"subtask_{uuid.uuid4().hex[:8]}",
                    "query": clean_line,
                    "tier": "tier1", # 默认定级
                    "description": f"回退提取搜索: {clean_line}",
                    "order": i
                }
                subtasks.append(subtask)
        
        return subtasks
    
    def mutate_state(self, input_data: Any, state: ScoutState, **kwargs) -> ScoutState:
        """将规划结果写入状态"""
        if not isinstance(input_data, str):
            input_data = str(input_data)
        
        # 设置任务描述
        state.task = input_data
        
        # 生成规划
        subtask_plans = self.run(input_data, state, **kwargs)
        
        # 创建子任务并添加到状态
        for plan in subtask_plans:
            subtask = SearchSubTask(
                id=plan["id"],
                query=plan["query"],
                tier=plan["tier"],
                description=plan["description"]
            )
            state.add_subtask(subtask)
        
        self.log_info(f"状态更新完成，已下发 {len(subtask_plans)} 个并发搜索任务至 SearchNode")
        return state
