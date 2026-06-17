"""
Commander State Definition
定义指挥官智能体在生命周期内的数据流状态
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class CommanderState:
    # ==========================================
    # 1. 输入阶段 (Inputs)
    # ==========================================
    user_request: str = ""  
    """用户输入的原始自然语言需求"""
    
    history_reports: List[Dict[str, Any]] = field(default_factory=list) 
    """来自 Inspector 或上一轮执行的历史反馈报告 (用于进化)"""

    # ==========================================
    # 2. 规划阶段 (Planning Phase)
    # ==========================================
    draft_plan: Dict[str, Any] = field(default_factory=dict)
    """
    PlanningNode 生成的初版计划。
    结构应包含: target_tier, scout_config, search_queries 等
    """

    # ==========================================
    # 3. 反思阶段 (Reflection Phase)
    # ==========================================
    reflection_result: Dict[str, Any] = field(default_factory=dict)
    """ReflectionNode 的原始输出，包含 critique (批评意见)"""
    
    is_refined: bool = False
    """标志位：是否经过了反思修正 (True = 被修改过, False = 初稿直接通过)"""

    # ==========================================
    # 4. 最终输出 (Final Output -> Scout)
    # ==========================================
    final_task_json: Dict[str, Any] = field(default_factory=dict)
    """
    最终传给 Scout Agent 的标准指令 JSON。
    如果 is_refined=False，这里的内容等于 draft_plan。
    如果 is_refined=True，这里是修正后的计划。
    """

    # ==========================================
    # 5. 统计与汇报 (Reporting Phase)
    # ==========================================
    execution_stats: Dict[str, Any] = field(default_factory=dict)
    """
    下游任务执行后的统计数据 (如: 搜索到多少URL, 入库多少数据)。
    由外部调用者回填，用于生成最终报告。
    """
    
    final_report: str = ""
    """最终生成的 Markdown 格式统计报告"""

    def update_final_plan(self, plan: Dict[str, Any], refined: bool = False):
        """辅助方法：更新最终计划"""
        self.final_task_json = plan
        self.is_refined = refined