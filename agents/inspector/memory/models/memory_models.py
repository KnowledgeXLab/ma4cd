from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Dict, Optional, Literal, Any
from datetime import datetime
import time
import logging

logger = logging.getLogger("inspector.models")

class AuditEntry(BaseModel):
    """
    Inspector 专属单条审计记忆模型
    🔥 终极防御版：自带 LLM 幻觉分数自动纠正机制
    """
    # 允许通过别名填充数据 (兼容 agent.py 中传过来的不同键名)
    model_config = ConfigDict(populate_by_name=True)

    url: str
    title: Optional[str] = None
    
    # 1. 严格限制状态值 (补充了日志中实际出现的 REJECT 和 pending)
    status: Literal["PASS", "FAIL", "REVIEW", "ERROR", "REJECT", "pending"] = "pending"
    
    # 2. 置信度评分：去掉硬性的 ge/le，完全交由下面的 clamp_score 拦截器处理
    score: float = Field(default=0.5, description="置信度评分 (0.0 - 1.0)")
    
    # 3. 兼容性字段：Miner/Agent 传过来的可能是 'analysis' 也可能是 'reason'
    reason: str = Field(default="No reason provided", alias="analysis")
    
    # 4. 时间戳：float 更有利于存储和排序
    timestamp: float = Field(default_factory=time.time) 
    
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator('score', mode='before')
    @classmethod
    def clamp_score(cls, v: Any) -> float:
        """
        🪓 核心防御：在 Pydantic 报错前，暴力修正大模型给出的离谱分数。
        比如 LLM 给出 15.0，这里会悄无声息地把它压制成 1.0，保证系统永不崩溃。
        """
        try:
            if v is None: return 0.5
            val = float(v)
            return max(0.0, min(1.0, val))
        except (ValueError, TypeError):
            logger.warning(f"⚠️ 捕获到无法解析的异常分数: {v}，已自动归一化为 0.5")
            return 0.5

    @property
    def human_time(self) -> str:
        """Helper 方法：供人类阅读的格式化时间"""
        return datetime.fromtimestamp(self.timestamp).strftime('%Y-%m-%d %H:%M:%S')


class MemorySchema(BaseModel):
    """
    长效记忆存储结构 (Vector DB / JSON 备份的骨架)
    """
    version: str = "2.0"
    last_updated: float = Field(default_factory=time.time)
    
    # Key 建议使用 URL 的 MD5 哈希，而不是 URL 本身
    entries: Dict[str, AuditEntry] = Field(default_factory=dict)

    def total_count(self) -> int:
        return len(self.entries)
        
    def add_entry(self, entry: AuditEntry, key: str):
        """安全添加记录并更新时间戳"""
        self.entries[key] = entry
        self.last_updated = time.time()