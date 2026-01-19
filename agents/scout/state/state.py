"""
Scout Agent 状态管理
基于 QueryEngine 的 State 模式重构
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json
from datetime import datetime
from enum import Enum


class SearchStatus(str, Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class Clue:
    """线索数据类"""
    url: str = ""
    title: str = ""
    snippet: str = ""
    source: str = ""  # web_search, database, api 等
    tier: str = "tier1"  # 线索层级
    relevance_score: float = 0.0
    query: str = ""  # 产生此线索的查询
    found_at_step: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Clue":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class SearchTrajectory:
    """搜索轨迹记录"""
    step: int = 0
    thought: str = ""
    action: Dict[str, Any] = field(default_factory=dict)
    observation: Dict[str, Any] = field(default_factory=dict)
    clues_found: List[Clue] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "thought": self.thought,
            "action": self.action,
            "observation": self.observation,
            "clues_found": [c.to_dict() for c in self.clues_found]
        }


@dataclass
class SearchSubTask:
    """搜索子任务状态"""
    id: str = ""
    query: str = ""
    tier: str = "tier1"
    description: str = ""
    status: SearchStatus = SearchStatus.PENDING
    trajectories: List[SearchTrajectory] = field(default_factory=list)
    clues: List[Clue] = field(default_factory=list)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    
    def start_execution(self):
        self.status = SearchStatus.EXECUTING
        self.start_time = datetime.now().isoformat()
    
    def mark_success(self):
        self.status = SearchStatus.SUCCESS
        self.end_time = datetime.now().isoformat()
    
    def mark_failed(self):
        self.status = SearchStatus.FAILED
        self.end_time = datetime.now().isoformat()
    
    def add_trajectory(self, trajectory: SearchTrajectory):
        self.trajectories.append(trajectory)
    
    def add_clues(self, clues: List[Clue]):
        self.clues.extend(clues)
    
    def get_clue_count(self) -> int:
        return len(self.clues)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "query": self.query,
            "tier": self.tier,
            "description": self.description,
            "status": self.status.value,
            "trajectories": [t.to_dict() for t in self.trajectories],
            "clues": [c.to_dict() for c in self.clues],
            "clue_count": self.get_clue_count(),
            "start_time": self.start_time,
            "end_time": self.end_time
        }


@dataclass
class ScoutState:
    """Scout Agent 整体状态"""
    task: str = ""  # 原始任务描述
    subtasks: List[SearchSubTask] = field(default_factory=list)
    all_clues: List[Clue] = field(default_factory=list)  # 所有线索聚合
    coverage_score: float = 0.0  # 覆盖率评分
    missing_aspects: List[str] = field(default_factory=list)
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: Optional[str] = None
    is_completed: bool = False
    
    def add_subtask(self, subtask: SearchSubTask):
        self.subtasks.append(subtask)
    
    def update_aggregated_clues(self):
        """更新聚合线索"""
        self.all_clues = []
        for subtask in self.subtasks:
            self.all_clues.extend(subtask.clues)
        # 去重（基于 URL）
        seen_urls = set()
        unique_clues = []
        for clue in self.all_clues:
            if clue.url not in seen_urls:
                seen_urls.add(clue.url)
                unique_clues.append(clue)
        self.all_clues = unique_clues
    
    def get_total_clue_count(self) -> int:
        return len(self.all_clues)
    
    def get_success_rate(self) -> float:
        if not self.subtasks:
            return 0.0
        successful = sum(1 for st in self.subtasks if st.status == SearchStatus.SUCCESS)
        return successful / len(self.subtasks)
    
    def mark_completed(self):
        self.is_completed = True
        self.end_time = datetime.now().isoformat()
        self.update_aggregated_clues()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "subtasks": [st.to_dict() for st in self.subtasks],
            "total_clues": self.get_total_clue_count(),
            "success_rate": self.get_success_rate(),
            "coverage_score": self.coverage_score,
            "missing_aspects": self.missing_aspects,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "is_completed": self.is_completed,
            "execution_time": self._get_execution_time_seconds()
        }
    
    def _get_execution_time_seconds(self) -> float:
        if not self.end_time:
            return 0.0
        start = datetime.fromisoformat(self.start_time)
        end = datetime.fromisoformat(self.end_time)
        return (end - start).total_seconds()
    
    def save(self, filepath: str):
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
    
    @classmethod
    def load(cls, filepath: str) -> "ScoutState":
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls._from_dict(data)
    
    @classmethod
    def _from_dict(cls, data: Dict[str, Any]) -> "ScoutState":
        # 简化版本，实际需要完整反序列化
        state = cls(task=data.get("task", ""))
        state.is_completed = data.get("is_completed", False)
        state.start_time = data.get("start_time", datetime.now().isoformat())
        state.end_time = data.get("end_time")
        return state