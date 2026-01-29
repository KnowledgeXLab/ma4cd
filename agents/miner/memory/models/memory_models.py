# memory/models/memory_models.py

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum


# =========================
# 基础枚举定义
# =========================

class MemoryType(Enum):
    WORKING = "working"
    SESSION = "session"
    PERSISTENT = "persistent"


class ImportanceLevel(Enum):
    LOW = 0.2
    MEDIUM = 0.5
    HIGH = 0.8
    CRITICAL = 1.0


# =========================
# 基础记忆单元
# =========================

@dataclass
class MemoryItem:
    """
    最基础的记忆项，用于 Working / Session / Persistent Memory
    """
    key: str
    value: Any
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    importance: float = ImportanceLevel.MEDIUM.value
    tags: List[str] = field(default_factory=list)
    ttl_seconds: Optional[int] = None

    def is_expired(self) -> bool:
        """检查记忆是否过期"""
        if self.ttl_seconds is None:
            return False
        return (datetime.now() - self.created_at).total_seconds() > self.ttl_seconds

    def access(self):
        """记录一次访问"""
        self.last_accessed = datetime.now()
        self.access_count += 1


# =========================
# 单次提取上下文 & 结果
# =========================

@dataclass
class ExtractionContext:
    """
    单次 extraction / mining 的上下文
    """
    domain: str
    url: str
    site_profile: Dict[str, Any]
    strategy_used: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ExtractionResult:
    """
    单次 extraction / mining 的结果
    """
    success: bool
    l3_count: int
    l3_candidates: List[Dict[str, Any]]
    execution_time: float
    error_message: Optional[str] = None
    performance_metrics: Dict[str, float] = field(default_factory=dict)


# =========================
# 学习事件（细粒度）
# =========================

@dataclass
class LearningEvent:
    """
    表示一次“可学习的事件”
    注意：它不是一次完整运行，只是其中的一个学习点
    """
    event_id: str
    event_type: str  # success | failure | pattern_discovery | strategy_adjustment
    context: ExtractionContext
    result: ExtractionResult
    insights: List[str] = field(default_factory=list)
    importance: float = ImportanceLevel.MEDIUM.value
    timestamp: datetime = field(default_factory=datetime.now)


# =========================
# 会话级总结
# =========================

@dataclass
class SessionSummary:
    """
    一次 miner session 的统计摘要
    """
    session_id: str
    start_time: datetime
    end_time: Optional[datetime] = None

    total_extractions: int = 0
    successful_extractions: int = 0
    total_l3_found: int = 0

    domains_processed: List[str] = field(default_factory=list)
    learning_events: List[LearningEvent] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_extractions == 0:
            return 0.0
        return self.successful_extractions / self.total_extractions

    @property
    def avg_l3_per_extraction(self) -> float:
        if self.successful_extractions == 0:
            return 0.0
        return self.total_l3_found / self.successful_extractions


# =========================
# ★ 新增：Miner Experience（核心）
# =========================

@dataclass
class MinerExperience:
    """
    一次 miner 完整运行的“经验快照”
    用于持续学习、自我进化、人类反馈融合
    """

    # 标识
    run_id: str
    session_id: str

    # 运行上下文
    seed_url: str
    domain: str
    site_profile: Dict[str, Any]

    # 当次使用的策略快照（进化的核心依据）
    strategy_snapshot: Dict[str, Any]

    # 挖掘结果摘要（不重复存储 L3 实体）
    l3_count: int
    l3_ids: List[str]
    avg_confidence: float

    # 性能指标
    execution_time: float
    success: bool

    # 可选增强信息
    reflection: Optional[Dict[str, Any]] = None
    human_feedback: Optional[Dict[str, Any]] = None

    timestamp: datetime = field(default_factory=datetime.now)
