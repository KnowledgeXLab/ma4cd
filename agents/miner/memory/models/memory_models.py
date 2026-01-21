# memory/models/memory_models.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum


class MemoryType(Enum):
    WORKING = "working"
    SESSION = "session" 
    PERSISTENT = "persistent"


class ImportanceLevel(Enum):
    LOW = 0.2
    MEDIUM = 0.5
    HIGH = 0.8
    CRITICAL = 1.0


@dataclass
class MemoryItem:
    """基础记忆项"""
    key: str
    value: Any
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    importance: float = ImportanceLevel.MEDIUM.value
    tags: List[str] = field(default_factory=list)
    ttl_seconds: Optional[int] = None
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.ttl_seconds is None:
            return False
        return (datetime.now() - self.created_at).total_seconds() > self.ttl_seconds
    
    def access(self):
        """记录访问"""
        self.last_accessed = datetime.now()
        self.access_count += 1


@dataclass
class ExtractionContext:
    """提取上下文"""
    domain: str
    url: str
    site_profile: Dict[str, Any]
    strategy_used: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ExtractionResult:
    """提取结果"""
    success: bool
    l3_count: int
    l3_candidates: List[Dict[str, Any]]
    execution_time: float
    error_message: Optional[str] = None
    performance_metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class LearningEvent:
    """学习事件"""
    event_id: str
    event_type: str  # success, failure, pattern_discovery, strategy_adjustment
    context: ExtractionContext
    result: ExtractionResult
    insights: List[str] = field(default_factory=list)
    importance: float = ImportanceLevel.MEDIUM.value
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class SessionSummary:
    """会话摘要"""
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
