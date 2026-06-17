"""main_workflow 流水线断点：按 phase 跳过已完成阶段（Redis 主存 + 本地镜像）。"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger

try:
    from agents.miner.memory.backends.redis_aux import get_pipeline_checkpoint, redis_aux_enabled
except ImportError:
    redis_aux_enabled = lambda: False  # type: ignore
    get_pipeline_checkpoint = lambda _k: None  # type: ignore

CHECKPOINT_VERSION = 2

PHASE_PENDING = "pending"
PHASE_COMMANDER_DONE = "commander_done"
PHASE_SCOUT_DONE = "scout_done"
PHASE_FLYWHEEL = "flywheel"
PHASE_REPORT_PENDING = "report_pending"
PHASE_COMPLETED = "completed"
PHASE_FAILED_SCOUT = "failed_scout"

# 飞轮子步骤（存于 artifacts.round_step）
ROUND_STEP_MINER = "miner"
ROUND_STEP_INSPECTOR = "inspector"


def pipeline_checkpoint_enabled() -> bool:
    if os.getenv("MA4CD_PIPELINE_FORCE_FRESH", "0").strip().lower() in ("1", "true", "yes", "on"):
        return False
    return os.getenv("MA4CD_PIPELINE_CHECKPOINT", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def use_redis_pipeline_checkpoint() -> bool:
    explicit = os.getenv("MA4CD_PIPELINE_CHECKPOINT_BACKEND", "auto").strip().lower()
    if explicit == "file":
        return False
    if explicit == "redis":
        return True
    return redis_aux_enabled()


def pipeline_run_key(user_requirement: str) -> str:
    text = (user_requirement or "").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def new_checkpoint_payload(
    user_requirement: str,
    session_id: str,
    run_id: str,
    *,
    phase: str = PHASE_PENDING,
    round_counter: int = 1,
    artifacts: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "version": CHECKPOINT_VERSION,
        "run_key": pipeline_run_key(user_requirement),
        "user_requirement": user_requirement.strip(),
        "session_id": session_id,
        "run_id": run_id,
        "phase": phase,
        "round_counter": int(round_counter or 1),
        "updated_at": datetime.now().isoformat(),
        "artifacts": artifacts or {},
    }


def is_resumable_checkpoint(payload: Dict[str, Any], user_requirement: str) -> bool:
    if not payload:
        return False
    ver = int(payload.get("version") or 1)
    if ver not in (1, CHECKPOINT_VERSION):
        return False
    if payload.get("phase") in (PHASE_COMPLETED, PHASE_FAILED_SCOUT):
        return False
    return payload.get("user_requirement") == (user_requirement or "").strip()


class PipelineCheckpointStore:
    """Redis 主存 + reports/pipeline_checkpoints/{run_key}.json 镜像。"""

    def __init__(self, user_requirement: str, reports_root: Optional[str] = None):
        self.run_key = pipeline_run_key(user_requirement)
        root = reports_root or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "reports",
            "pipeline_checkpoints",
        )
        os.makedirs(root, exist_ok=True)
        self.file_path = os.path.join(root, f"{self.run_key}.json")
        self._redis = (
            get_pipeline_checkpoint(self.run_key)
            if use_redis_pipeline_checkpoint()
            else None
        )

    def load(self) -> Dict[str, Any]:
        if self._redis:
            try:
                data = self._redis.load()
                if data:
                    logger.info(f"🧷 Pipeline Redis 断点已加载: run_key={self.run_key} phase={data.get('phase')}")
                    return data
            except Exception as e:
                logger.warning(f"Pipeline Redis 断点读取失败，回退文件: {e}")
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Pipeline 文件断点读取失败: {e}")
        return {}

    def save(self, payload: Dict[str, Any]) -> None:
        payload = dict(payload)
        payload["updated_at"] = datetime.now().isoformat()
        payload.setdefault("run_key", self.run_key)
        if self._redis:
            try:
                self._redis.save(payload)
            except Exception as e:
                logger.warning(f"Pipeline Redis 断点写入失败: {e}")
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Pipeline 文件断点写入失败: {e}")

    def clear(self) -> None:
        if self._redis:
            try:
                self._redis.clear()
            except Exception as e:
                logger.warning(f"Pipeline Redis 断点清除失败: {e}")
        if os.path.exists(self.file_path):
            try:
                os.remove(self.file_path)
            except Exception as e:
                logger.warning(f"Pipeline 文件断点清除失败: {e}")
