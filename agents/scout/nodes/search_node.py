"""
搜索执行节点 - 执行单个搜索子任务
"""

import json
import re
from typing import Dict, Any, Optional
from loguru import logger

from .base_node import BaseNode
from ..state.state import SearchSubTask, SearchTrajectory, SearchStatus, Clue
from ..prompts.prompts import SYSTEM_PROMPT_SEARCH_DECISION
from ..tools.web_search import WebSearchTool


class SearchNode(BaseNode):
    """搜索执行节点"""
    
    def __init__(self, llm_client, search_tool: WebSearchTool, max_steps: int = 5):
        super().__init__(llm_client, "SearchNode")
        self.search_tool = search_tool
        self.max_steps = max_steps
        self.current_step = 0
    
    def run(self, input_data: Any, state: Optional[Any] = None, **kwargs) -> SearchSubTask:
        """执行搜索子任务"""
        if not isinstance(input_data, SearchSubTask):
            raise ValueError("输入必须是 SearchSubTask 类型")
        
        subtask = input_data
        subtask.start_execution()
        
        self.log_info(f"开始执行搜索子任务: {subtask.query} ({subtask.tier})")
        
        try:
            # ReAct 循环执行
            for step in range(1, self.max_steps + 1):
                self.current_step = step
                
                # 1. 生成思考
                thought = self._generate_thought(subtask, step)
                
                # 2. 生成行动决策
                action = self._generate_action(subtask, thought, step)
                
                # 3. 执行行动
                observation = self._execute_action(action)
                
                # 4. 提取线索
                clues = self._extract_clues_from_observation(observation, subtask, step)
                
                # 5. 记录轨迹
                trajectory = SearchTrajectory(
                    step=step,
                    thought=thought,
                    action=action,
                    observation=observation,
                    clues_found=clues
                )
                subtask.add_trajectory(trajectory)
                subtask.add_clues(clues)
                
                self.log_info(f"步骤 {step}: 找到 {len(clues)} 条线索")
                
                # 6. 判断是否完成
                if self._should_stop(subtask, step, observation):
                    self.log_info(f"搜索完成，共找到 {subtask.get_clue_count()} 条线索")
                    subtask.mark_success()
                    break
            
            # 如果循环结束但未标记成功，则标记为失败
            if subtask.status == SearchStatus.EXECUTING:
                self.log_warning(f"搜索达到最大步数未完成")
                subtask.mark_failed()
            
            return subtask
            
        except Exception as e:
            self.log_error(f"搜索执行失败: {str(e)}")
            subtask.mark_failed()
            return subtask
    
    def _generate_thought(self, subtask: SearchSubTask, step: int) -> str:
        """生成思考"""
        if step == 1:
            return f"开始搜索: {subtask.query}。这是一个{subtask.tier}级别的搜索，目标是找到相关线索。"
        
        # 后续步骤可以基于之前的轨迹进行更深入的思考
        recent_trajectories = subtask.trajectories[-2:] if len(subtask.trajectories) > 0 else []
        
        if recent_trajectories:
            last_thought = recent_trajectories[-1].thought
            return f"基于上一步的发现，我需要更深入地探索与 '{subtask.query}' 相关的特定方面。"
        
        return f"继续搜索关于 '{subtask.query}' 的信息，尝试不同的搜索角度。"
    
    def _generate_action(self, subtask: SearchSubTask, thought: str, step: int) -> Dict[str, Any]:
        """生成行动决策"""
        # 简化版本：直接调用基础搜索
        # 实际实现应该使用 LLM 决策
        search_query = self._refine_query(subtask.query, step)
        
        return {
            "name": "web_search",
            "arguments": {
                "query": search_query,
                "num_results": 10,
                "engine": "duckduckgo_html"  # 使用能工作的引擎
            }
        }
    
    def _refine_query(self, base_query: str, step: int) -> str:
        """优化搜索查询"""
        if step == 1:
            return base_query
        elif step == 2:
            return f"{base_query} 数据集 site:github.com OR site:kaggle.com"
        elif step == 3:
            return f"{base_query} 研究 论文 最新进展"
        else:
            return f"{base_query} 技术 发展 趋势"
    
    def _execute_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """执行行动"""
        try:
            if action["name"] == "web_search":
                args = action["arguments"]
                results = self.search_tool(**args)
                
                return {
                    "status": "success",
                    "results": results,
                    "count": len(results)
                }
            else:
                return {
                    "status": "error",
                    "message": f"未知工具: {action['name']}"
                }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }
    
    def _extract_clues_from_observation(self, observation: Dict[str, Any], 
                                       subtask: SearchSubTask, step: int) -> list[Clue]:
        """从观察结果中提取线索"""
        clues = []
        
        if observation.get("status") == "success" and "results" in observation:
            results = observation["results"]
            
            for i, result in enumerate(results):
                clue = Clue(
                    url=result.get("url", ""),
                    title=result.get("title", "无标题"),
                    snippet=result.get("snippet", ""),
                    source="web_search",
                    tier=subtask.tier,
                    relevance_score=result.get("relevance_score", 5.0),
                    query=subtask.query,
                    found_at_step=step,
                    metadata={
                        "position": i + 1,
                        "engine": result.get("source", "unknown")
                    }
                )
                clues.append(clue)
        
        return clues
    
    def _should_stop(self, subtask: SearchSubTask, step: int, observation: Dict[str, Any]) -> bool:
        """判断是否应该停止搜索"""
        # 简单策略：找到足够线索或达到最大步数
        min_clues_per_subtask = 5
        
        if subtask.get_clue_count() >= min_clues_per_subtask:
            return True
        
        if step >= self.max_steps:
            return True
        
        # 如果搜索结果很少，可能已经穷尽
        if (observation.get("status") == "success" and 
            observation.get("count", 0) < 3):
            return True
        
        return False