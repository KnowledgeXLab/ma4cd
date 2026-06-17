"""批跑断点存储：Redis（多机共享）或本地 JSON 文件。"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from loguru import logger

try:
    from agents.miner.memory.backends.redis_aux import get_batch_checkpoint, redis_aux_enabled
except ImportError:
    redis_aux_enabled = lambda: False  # type: ignore
    get_batch_checkpoint = lambda _id: None  # type: ignore


def use_redis_checkpoint() -> bool:
    explicit = os.getenv("MA4CD_BATCH_CHECKPOINT_BACKEND", "").strip().lower()
    if explicit in ("redis", "file"):
        return explicit == "redis"
    return redis_aux_enabled()


class BatchCheckpointStore:
    """统一批跑断点读写；Redis 优先时仍镜像写本地文件作备份。"""

    def __init__(self, batch_id: str, file_path: str):
        self.batch_id = batch_id
        self.file_path = file_path
        self._redis = get_batch_checkpoint(batch_id) if use_redis_checkpoint() else None

    def load(self) -> Dict[str, Any]:
        if self._redis:
            try:
                data = self._redis.load()
                if data:
                    logger.info(f"🧷 Redis 断点已加载: batch={self.batch_id}")
                    return data
            except Exception as e:
                logger.warning(f"Redis 断点读取失败，回退文件: {e}")
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"文件断点读取失败: {e}")
        return {}

    def save(self, payload: Dict[str, Any]) -> None:
        if self._redis:
            try:
                self._redis.save(payload)
            except Exception as e:
                logger.warning(f"Redis 断点写入失败: {e}")
        try:
            os.makedirs(os.path.dirname(self.file_path) or ".", exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"文件断点写入失败: {e}")
