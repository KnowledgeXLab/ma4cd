"""
Scout Agent 主协调器 - 修复版
"""
import os
import time
import json
from typing import List, Dict, Any, Optional
from pathlib import Path
from loguru import logger
from dataclasses import asdict, is_dataclass

# 导入核心模块
from .llms.base import LLMClient
from .tools.web_search import WebSearchTool
from .state.state import ScoutState
from .nodes.planning_node import PlanningNode
from .nodes.search_node import SearchNode


class ScoutAgent:
    """
    Scout Agent - 广域侦察兵
    专注于快速广度搜索
    """
    
    def __init__(
        self,
        llm_client: LLMClient,
        output_dir: str = "./artifacts/scout",
        max_concurrent_searches: int = 3,
        search_max_steps: int = 4,  # 新增：SearchNode 需要的参数
        enable_cache: bool = True
    ):
        """
        初始化 Scout Agent
        
        Args:
            llm_client: LLM 客户端
            output_dir: 输出目录
            max_concurrent_searches: 最大并发搜索数
            search_max_steps: 每个搜索的最大步骤数
            enable_cache: 是否启用缓存
        """
        # 核心组件
        self.llm_client = llm_client
        
        # 🛠️ 修复：使用正确的搜索工具构造函数
        self.search_tool = WebSearchTool(config={
            "google_api_key": os.getenv("GOOGLE_API_KEY"),
            "google_cx": os.getenv("GOOGLE_CX"),
            "github_token": os.getenv("GITHUB_TOKEN"),
            "max_results": 15,
            "enable_cache": True
        })
        
        # 🛠️ 修复：创建节点时传入正确参数
        self.planning_node = PlanningNode(llm_client, max_subtasks=5)
        self.search_node = SearchNode(
            llm_client=llm_client,
            search_tool=self.search_tool,
            max_steps=search_max_steps
        )
        
        # 配置
        self.max_concurrent_searches = max_concurrent_searches
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 运行状态
        self.current_state: Optional[ScoutState] = None
        
        logger.info(f"Scout Agent 初始化完成，输出目录: {self.output_dir}")
    
    def run(self, task: str, **kwargs) -> Dict[str, Any]:
        """
        执行搜索任务 - 同步版本
        
        Args:
            task: 用户任务描述
            **kwargs: 额外参数，如 country_code, task_type 等
            
        Returns:
            包含所有结果的字典
        """
        start_time = time.time()
        
        try:
            logger.info(f"🚀 开始执行任务: {task}")
            
            # 🛠️ 修复：从 kwargs 获取国家代码等参数
            country_code = kwargs.get('country_code', 'us')
            task_type = kwargs.get('task_type', 'general')
            
            # 1. 初始化状态
            self.current_state = ScoutState(task=task)
            # 🛠️ 修复：设置状态中的额外参数
            if hasattr(self.current_state, 'country'):
                self.current_state.country = country_code
            if hasattr(self.current_state, 'task_type'):
                self.current_state.task_type = task_type
            
            # 2. 规划阶段 (Planning Node)
            logger.info("📋 阶段 1/2: 任务规划")
            self.current_state = self.planning_node.mutate_state(
                input_data=task,
                state=self.current_state
            )
            
            logger.info(f"📋 规划完成，生成 {len(self.current_state.subtasks)} 个子任务")
            
            # 3. 🎯 搜索执行阶段 (Search Node)
            logger.info(f"🔍 阶段 2/2: 搜索执行")
            
            successful_searches = 0
            total_clues = 0
            
            # 🛠️ 修复：同步执行搜索，而不是异步
            for i, subtask in enumerate(self.current_state.subtasks):
                logger.info(f"🔍 执行子任务 {i+1}/{len(self.current_state.subtasks)}: {subtask.query}")
                
                try:
                    # 执行搜索
                    completed_subtask = self.search_node.run(
                        input_data=subtask,
                        state=self.current_state
                    )
                    
                    # 更新子任务状态
                    for j, st in enumerate(self.current_state.subtasks):
                        if st.id == completed_subtask.id:
                            self.current_state.subtasks[j] = completed_subtask
                            break
                    
                    # 统计
                    clue_count = completed_subtask.get_clue_count()
                    total_clues += clue_count
                    
                    if completed_subtask.status.value == "success":
                        successful_searches += 1
                    
                    logger.info(f"   ✅ 完成，状态: {completed_subtask.status.value}, 线索: {clue_count}")
                    
                except Exception as e:
                    logger.error(f"   ❌ 子任务失败: {str(e)}")
                    subtask.mark_failed()
                
                # 🛠️ 修复：添加延迟避免请求过快
                if i < len(self.current_state.subtasks) - 1:
                    time.sleep(1)  # 1秒延迟
            
            # 4. 完成处理
            self.current_state.mark_completed()
            
            # 🛠️ 修复：检查是否有 update_aggregated_clues 方法
            if hasattr(self.current_state, 'update_aggregated_clues'):
                self.current_state.update_aggregated_clues()
            
            # 5. 保存结果
            result = self._prepare_final_result(start_time, total_clues, successful_searches)
            self._save_results(result)
            
            success_rate = successful_searches / len(self.current_state.subtasks) if self.current_state.subtasks else 0
            logger.info(f"🎉 任务完成! 找到 {total_clues} 条线索，成功率: {success_rate:.1%}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 任务执行失败: {str(e)}")
            import traceback
            traceback.print_exc()
            
            error_result = self._prepare_error_result(start_time, str(e))
            self._save_results(error_result, is_error=True)
            return error_result
    
    '''
    def _prepare_final_result(self, start_time: float, total_clues: int, successful_searches: int) -> Dict[str, Any]:
        """准备最终结果"""
        exec_time = time.time() - start_time
        
        # 🛠️ 修复：安全地访问状态属性
        subtasks_summary = []
        sample_clues = []
        
        if self.current_state and hasattr(self.current_state, 'subtasks'):
            for st in self.current_state.subtasks:
                subtask_info = {
                    "query": getattr(st, 'query', 'Unknown'),
                    "status": getattr(st.status, 'value', 'unknown') if hasattr(st, 'status') else 'unknown',
                    "tier": getattr(st, 'tier', 'tier1')
                }
                
                # 获取线索数
                if hasattr(st, 'get_clue_count'):
                    subtask_info["clue_count"] = st.get_clue_count()
                elif hasattr(st, 'clues'):
                    subtask_info["clue_count"] = len(st.clues)
                else:
                    subtask_info["clue_count"] = 0
                
                subtasks_summary.append(subtask_info)
        
        # 获取示例线索
        if self.current_state and hasattr(self.current_state, 'all_clues'):
            for clue in self.current_state.all_clues[:5]:  # 只取前5个
                sample_clues.append({
                    "title": getattr(clue, 'title', 'No title'),
                    "url": getattr(clue, 'url', ''),
                    "source": getattr(clue, 'source', 'unknown'),
                    "relevance": getattr(clue, 'relevance_score', 0),
                    "query": getattr(clue, 'query', '')
                })
        
        result = {
            "task": getattr(self.current_state, 'task', 'Unknown task') if self.current_state else 'Unknown task',
            "clues_count": total_clues,
            "subtasks_count": len(self.current_state.subtasks) if self.current_state and hasattr(self.current_state, 'subtasks') else 0,
            "successful_searches": successful_searches,
            "success_rate": successful_searches / len(self.current_state.subtasks) if self.current_state and hasattr(self.current_state, 'subtasks') and self.current_state.subtasks else 0,
            "execution_time": round(exec_time, 2),
            "is_completed": getattr(self.current_state, 'is_completed', False) if self.current_state else False,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "subtasks_summary": subtasks_summary,
            "sample_clues": sample_clues
        }
        
        return result'''
    
    def _prepare_final_result(self, start_time: float, total_clues: int, successful_searches: int) -> Dict[str, Any]:
        """准备最终结果 - 修复版：保存所有线索"""
        exec_time = time.time() - start_time

        # 初始化默认值
        subtasks_count = 0
        success_rate = 0.0
        subtasks_summary = []
        sample_clues = []
        all_clues_dicts = []  # 改名，避免与对象混淆

        # 安全访问 current_state
        state = getattr(self, 'current_state', None)
        if not state:
            logger.warning("current_state 不存在，使用默认结果")
            return {
                "task": "未知任务",
                "clues_count": total_clues,
                "subtasks_count": 0,
                "successful_searches": successful_searches,
                "success_rate": 0.0,
                "execution_time": round(exec_time, 2),
                "is_completed": False,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "subtasks_summary": [],
                "all_clues": [],
                "sample_clues": []
            }

        # 任务描述
        task = getattr(state, 'task', "未知任务")

        # 子任务
        subtasks = getattr(state, 'subtasks', [])
        subtasks_count = len(subtasks)

        # 收集所有线索并转成 dict
        raw_clues = []
        if hasattr(state, 'all_clues') and state.all_clues:
            raw_clues = state.all_clues
        elif subtasks:
            for subtask in subtasks:
                clues = getattr(subtask, 'clues', [])
                if clues:
                    raw_clues.extend(clues)

        # 转成 dict
        for clue in raw_clues:
            if isinstance(clue, dict):
                all_clues_dicts.append(clue)
            elif is_dataclass(clue):
                all_clues_dicts.append(asdict(clue))
            elif hasattr(clue, 'to_dict'):
                all_clues_dicts.append(clue.to_dict())
            else:
                # 兜底：强制转字符串表示（避免序列化失败）
                all_clues_dicts.append({"raw_object": str(clue), "type": str(type(clue))})

        # 子任务摘要
        for subtask in subtasks:
            status = getattr(getattr(subtask, 'status', None), 'value', 'unknown') if hasattr(subtask, 'status') else 'unknown'
            clue_count = len(getattr(subtask, 'clues', []))
            subtasks_summary.append({
                "query": getattr(subtask, 'query', '未知'),
                "status": status,
                "tier": getattr(subtask, 'tier', 'tier1'),
                "clue_count": clue_count
            })

        # 成功率
        if subtasks_count > 0:
            success_count = sum(1 for s in subtasks_summary if s["status"] == "success")
            success_rate = success_count / subtasks_count

        # 示例线索
        sample_clues = all_clues_dicts[:5]

        result = {
            "task": task,
            "clues_count": len(all_clues_dicts),
            "subtasks_count": subtasks_count,
            "successful_searches": successful_searches,
            "success_rate": success_rate,
            "execution_time": round(exec_time, 2),
            "is_completed": getattr(state, 'is_completed', False),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "subtasks_summary": subtasks_summary,
            "all_clues": all_clues_dicts,      # 完整列表，已转 dict
            "sample_clues": sample_clues       # 前5条
        }

        return result
    
    def _prepare_error_result(self, start_time: float, error_msg: str) -> Dict[str, Any]:
        """准备错误结果"""
        exec_time = time.time() - start_time
        
        return {
            "task": getattr(self.current_state, 'task', 'Unknown task') if self.current_state else 'Unknown task',
            "error": error_msg,
            "execution_time": round(exec_time, 2),
            "is_completed": False,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "clues_count": 0,
            "subtasks_count": 0,
            "success_rate": 0
        }
    
    def _save_results(self, result: Dict[str, Any], is_error: bool = False):
        """保存结果到文件"""
        try:
            # 生成文件名
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            status = "error" if is_error else "success"
            filename = f"run_{timestamp}_{status}.json"
            filepath = self.output_dir / filename
            
            # 保存 JSON
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            
            logger.info(f"💾 结果保存到: {filepath}")
            
        except Exception as e:
            logger.error(f"❌ 保存结果失败: {str(e)}")
    
    def quick_search(self, query: str, **kwargs) -> List[Dict[str, Any]]:
        """
        快速搜索 - 不经过规划，直接执行搜索
        
        Args:
            query: 搜索查询
            **kwargs: 搜索参数
            
        Returns:
            搜索结果列表
        """
        try:
            logger.info(f"🔍 快速搜索: {query}")
            
            # 直接使用搜索工具
            country_code = kwargs.get('country_code', 'us')
            task_type = kwargs.get('task_type', 'general')
            num_results = kwargs.get('num_results', 10)
            
            results = self.search_tool(
                query=query,
                num_results=num_results,
                country_code=country_code,
                task_type=task_type
            )
            
            logger.info(f"✅ 快速搜索完成，找到 {len(results)} 个结果")
            return results
            
        except Exception as e:
            logger.error(f"❌ 快速搜索失败: {str(e)}")
            return []