"""
任务规划节点 - 将用户任务分解为搜索子任务
"""

import json
import uuid
from typing import List, Dict, Any, Optional
from loguru import logger

from .base_node import StateMutationNode
from ..state.state import ScoutState, SearchSubTask, SearchStatus
from ..prompts.prompts import SYSTEM_PROMPT_PLANNING


class PlanningNode(StateMutationNode):
    """任务规划节点"""
    
    def __init__(self, llm_client, max_subtasks: int = 5):
        super().__init__(llm_client, "PlanningNode")
        self.max_subtasks = max_subtasks
    
    def run(self, input_data: Any, state: Optional[ScoutState] = None, **kwargs) -> List[Dict[str, Any]]:
        """生成搜索子任务规划"""
        if not isinstance(input_data, str):
            input_data = str(input_data)
        
        self.log_info(f"开始规划任务: {input_data[:50]}...")
        
        try:
            # 调用 LLM 进行规划
            response = self.llm_client.invoke(
                system_prompt=SYSTEM_PROMPT_PLANNING,
                user_prompt=input_data,
                temperature=0.3,
                max_tokens=1000
            )
            
            # 解析规划结果
            subtasks = self._parse_planning_response(response)
            
            self.log_info(f"规划完成，生成 {len(subtasks)} 个子任务")
            return subtasks
            
        except Exception as e:
            self.log_error(f"任务规划失败: {str(e)}")
            # 返回默认规划
            return self._get_default_plan(input_data)
    
    def _parse_planning_response(self, response: str) -> List[Dict[str, Any]]:
        """解析 LLM 返回的规划结果"""
        try:
            # 尝试解析 JSON
            start_idx = response.find('[')
            end_idx = response.rfind(']') + 1
            
            if start_idx != -1 and end_idx > start_idx:
                json_str = response[start_idx:end_idx]
                data = json.loads(json_str)
                
                if isinstance(data, list):
                    subtasks = []
                    for i, item in enumerate(data[:self.max_subtasks]):
                        subtask = {
                            "id": f"subtask_{uuid.uuid4().hex[:8]}",
                            "query": item.get("search_query", ""),
                            "tier": item.get("tier", "tier1"),
                            "description": item.get("description", ""),
                            "order": i
                        }
                        subtasks.append(subtask)
                    return subtasks
        except json.JSONDecodeError as e:
            self.log_warning(f"JSON 解析失败: {e}, 使用文本解析")
        
        # 文本解析回退
        return self._parse_text_response(response)
    
    def _parse_text_response(self, response: str) -> List[Dict[str, Any]]:
        """文本格式解析回退"""
        lines = response.strip().split('\n')
        subtasks = []
        
        for i, line in enumerate(lines[:self.max_subtasks]):
            if line.strip() and len(line.strip()) > 10:  # 简单过滤
                subtask = {
                    "id": f"subtask_{uuid.uuid4().hex[:8]}",
                    "query": line.strip(),
                    "tier": "tier1",
                    "description": f"搜索: {line.strip()}",
                    "order": i
                }
                subtasks.append(subtask)
        
        return subtasks if subtasks else self._get_default_plan("通用搜索")
    
    def _get_default_plan(self, task: str) -> List[Dict[str, Any]]:
        """获取默认规划"""
        return [
            {
                "id": f"subtask_{uuid.uuid4().hex[:8]}",
                "query": task,
                "tier": "tier1",
                "description": f"主搜索: {task}",
                "order": 0
            }
        ]
    
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
        
        self.log_info(f"状态更新完成，添加 {len(subtask_plans)} 个子任务")
        return state