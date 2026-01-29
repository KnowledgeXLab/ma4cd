# agents/miner/state/miner_state.py
"""
Miner Agent 的核心状态类
用于在 ReAct 循环中传递和更新数据
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import time


@dataclass
class MinerState:
    """
    Miner 的运行时状态
    - 所有字段都可序列化为 JSON
    - 支持深拷贝和调试
    """

    # 基本任务信息（不变）
    task: str = ""                              # 当前整体任务描述（e.g. "挖掘固态电池公开数据集"）
    task_id: str = ""                           # 唯一任务 ID（可选，用于日志追踪）

    # 当前正在处理的线索（从 Scout 或上游传入）
    current_clue: Dict[str, Any] = field(default_factory=dict)  # {url, title, snippet, tier, likely_level, ...}

    # 待处理线索队列（初始为空，extract_node 会分裂新线索加入）
    pending_clues: List[Dict[str, Any]] = field(default_factory=list)

    # 已提取的原始数据（extract_node 输出）
    extracted_content: str = ""                 # HTML 或 Markdown 全文（可选压缩存储）
    raw_links: List[Dict[str, Any]] = field(default_factory=list)     # 所有 <a href> 链接
    nav_links: List[Dict[str, Any]] = field(default_factory=list)     # 导航栏相关链接（优先级高）

    # 结构化中间结果（structure_node 输出）
    structured_data: Dict[str, Any] = field(default_factory=dict)     # {nav_tree: [...], candidates: [...]}
    metadata: Dict[str, Any] = field(default_factory=dict)            # {title, description, html_length, ...}

    # 最终产出（validate_node 输出）
    mined_items: List[Dict[str, Any]] = field(default_factory=list)   # 已确认的 L3 子线索

    # 🧬 新增：反思和进化相关字段
    reflection_result: Optional[Any] = None     # 反思结果对象（ReflectionResult）
    quality_score: float = 0.5                 # 质量分数 (0.0-1.0)
    reflection_duration: float = 0.0           # 反思耗时（秒）
    evolution_generation: int = 0              # 进化代数
    needs_human_review: bool = False           # 是否需要人工审核
    confidence_adjustments: Dict[str, float] = field(default_factory=dict)  # 置信度调整记录
    classification_feedback: List[Dict[str, Any]] = field(default_factory=list)  # 分类反馈
    
    # 执行状态
    is_valid: bool = False                      # 当前步骤是否成功
    error: Optional[str] = None                 # 错误信息（如果失败）
    step_start_time: float = 0.0                # 当前节点开始时间
    step_duration: float = 0.0                  # 当前节点耗时（秒）

    # 全局统计（可选，用于日志/监控）
    total_retries: int = 0                      # 本次任务总重试次数
    split_count: int = 0                        # 已分裂出的子线索数量

    def update_duration(self):
        """更新当前步骤耗时"""
        if self.step_start_time > 0:
            self.step_duration = time.time() - self.step_start_time
            self.step_start_time = 0.0

    def start_step(self):
        """开始一个新步骤时调用"""
        self.step_start_time = time.time()
        self.error = None
        self.is_valid = False

    # 🧬 新增：反思相关方法
    def start_reflection(self):
        """开始反思步骤"""
        self.reflection_start_time = time.time()
    
    def end_reflection(self):
        """结束反思步骤"""
        if hasattr(self, 'reflection_start_time') and self.reflection_start_time > 0:
            self.reflection_duration = time.time() - self.reflection_start_time
    
    def apply_confidence_adjustment(self, item_url: str, adjustment: float):
        """应用置信度调整"""
        self.confidence_adjustments[item_url] = adjustment
    
    def add_classification_feedback(self, feedback: Dict[str, Any]):
        """添加分类反馈"""
        self.classification_feedback.append(feedback)
    
    def get_reflection_summary(self) -> Dict[str, Any]:
        """获取反思摘要"""
        return {
            'quality_score': self.quality_score,
            'needs_human_review': self.needs_human_review,
            'reflection_duration': self.reflection_duration,
            'evolution_generation': self.evolution_generation,
            'confidence_adjustments_count': len(self.confidence_adjustments),
            'classification_feedback_count': len(self.classification_feedback)
        }

    def to_dict(self) -> Dict[str, Any]:
        """转换为可序列化的 dict（用于保存/日志）"""
        return {
            "task": self.task,
            "task_id": self.task_id,
            "current_clue": self.current_clue,
            "pending_clues": self.pending_clues,
            "extracted_content_length": len(self.extracted_content),
            "raw_links_count": len(self.raw_links),
            "mined_items_count": len(self.mined_items),
            "is_valid": self.is_valid,
            "error": self.error,
            "step_duration": self.step_duration,
            "total_retries": self.total_retries,
            "split_count": self.split_count,
            
            # 🧬 新增：反思和进化字段
            "quality_score": self.quality_score,
            "reflection_duration": self.reflection_duration,
            "evolution_generation": self.evolution_generation,
            "needs_human_review": self.needs_human_review,
            "confidence_adjustments": self.confidence_adjustments,
            "classification_feedback": self.classification_feedback,
            "reflection_summary": self.get_reflection_summary()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """从 dict 恢复状态（用于加载历史状态）"""
        state = cls()
        for key, value in data.items():
            if hasattr(state, key) and key != "reflection_summary":  # 跳过计算字段
                setattr(state, key, value)
        return state
    
    # 🧬 新增：状态复制方法（用于反思节点）
    def copy_for_reflection(self):
        """为反思创建状态副本"""
        # 创建一个新的状态对象，复制关键数据
        reflection_state = MinerState()
        reflection_state.task = self.task
        reflection_state.task_id = self.task_id
        reflection_state.current_clue = self.current_clue.copy()
        reflection_state.mined_items = [item.copy() for item in self.mined_items]
        reflection_state.metadata = self.metadata.copy()
        reflection_state.is_valid = self.is_valid
        reflection_state.error = self.error
        reflection_state.evolution_generation = self.evolution_generation
        
        return reflection_state
    
    # 🧬 新增：合并反思结果
    def merge_reflection_result(self, reflection_state):
        """合并反思结果到当前状态"""
        if hasattr(reflection_state, 'reflection_result'):
            self.reflection_result = reflection_state.reflection_result
        if hasattr(reflection_state, 'quality_score'):
            self.quality_score = reflection_state.quality_score
        if hasattr(reflection_state, 'reflection_duration'):
            self.reflection_duration = reflection_state.reflection_duration
        if hasattr(reflection_state, 'needs_human_review'):
            self.needs_human_review = reflection_state.needs_human_review
        if hasattr(reflection_state, 'confidence_adjustments'):
            self.confidence_adjustments.update(reflection_state.confidence_adjustments)
        if hasattr(reflection_state, 'classification_feedback'):
            self.classification_feedback.extend(reflection_state.classification_feedback)
        
        # 如果反思后的 mined_items 有调整，也要合并
        if hasattr(reflection_state, 'mined_items') and reflection_state.mined_items:
            self.mined_items = reflection_state.mined_items

    def copy_for_reflection(self):
        """为反思创建状态副本"""
        # 创建一个新的状态对象，复制关键数据
        reflection_state = MinerState()
        reflection_state.task = self.task
        reflection_state.task_id = self.task_id
        reflection_state.current_clue = self.current_clue.copy() if self.current_clue else {}
        reflection_state.mined_items = [item.copy() for item in self.mined_items] if self.mined_items else []
        reflection_state.metadata = self.metadata.copy() if self.metadata else {}
        reflection_state.is_valid = self.is_valid
        reflection_state.error = self.error
        reflection_state.evolution_generation = self.evolution_generation
        
        return reflection_state

    def merge_reflection_result(self, reflection_state):
        """合并反思结果到当前状态"""
        if hasattr(reflection_state, 'reflection_result'):
            self.reflection_result = reflection_state.reflection_result
        if hasattr(reflection_state, 'quality_score'):
            self.quality_score = reflection_state.quality_score
        if hasattr(reflection_state, 'reflection_duration'):
            self.reflection_duration = reflection_state.reflection_duration
        if hasattr(reflection_state, 'needs_human_review'):
            self.needs_human_review = reflection_state.needs_human_review
        if hasattr(reflection_state, 'confidence_adjustments'):
            self.confidence_adjustments.update(reflection_state.confidence_adjustments)
        if hasattr(reflection_state, 'classification_feedback'):
            self.classification_feedback.extend(reflection_state.classification_feedback)
        
        # 如果反思后的 mined_items 有调整，也要合并
        if hasattr(reflection_state, 'mined_items') and reflection_state.mined_items:
            self.mined_items = reflection_state.mined_items
