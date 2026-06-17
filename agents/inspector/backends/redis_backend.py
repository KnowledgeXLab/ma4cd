"""Inspector 状态 Redis 实现：全局审计缓存 + Session 级 remine 队列。"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from agents.miner.memory.backends.redis_backend import RedisKeySpace


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _json_loads(raw: Optional[str]) -> Any:
    if not raw:
        return None
    return json.loads(raw)


class RedisInspectorState:
    """
    Redis 版 InspectorState。

    Key 设计：
    - ma4cd:{env}:inspector:reports              HASH  url -> audit json（全局）
    - ma4cd:{env}:inspector:session:{sid}:remine SET   L2 回挖 URL
    - ma4cd:{env}:inspector:session:{sid}:stats  HASH  pass/fail/remine 计数
    """

    def __init__(
        self,
        client,
        keys: RedisKeySpace,
        *,
        session_id: str = "global",
        report_ttl: int = 0,
    ):
        self._r = client
        self._keys = keys
        self._session_id = session_id or "global"
        self._report_ttl = int(report_ttl or 0)

    def bind_session(self, session_id: Optional[str]) -> None:
        if session_id:
            self._session_id = session_id

    @property
    def session_id(self) -> str:
        return self._session_id

    def get_cached_result(self, url: str) -> Optional[Dict[str, Any]]:
        raw = self._r.hget(self._keys.inspector_reports(), url)
        data = _json_loads(raw)
        return data if isinstance(data, dict) else None

    def update_state(self, url: str, report: Dict[str, Any]) -> None:
        payload = {
            "status": report.get("status"),
            "score": report.get("metrics", {}).get("ai_score"),
            "risk_level": report.get("metrics", {}).get("risk_level"),
            "analysis": report.get("analysis"),
            "last_check": datetime.now().isoformat(),
        }
        reports_key = self._keys.inspector_reports()
        self._r.hset(reports_key, url, _json_dumps(payload))
        if self._report_ttl > 0:
            self._r.expire(reports_key, self._report_ttl)

        status = str(payload.get("status") or "ERROR")
        stats_key = self._keys.inspector_session_stats(self._session_id)
        self._r.hincrby(stats_key, status, 1)

    def add_to_remine_queue(self, l2_url: str) -> None:
        if not l2_url:
            return
        remine_key = self._keys.inspector_remine(self._session_id)
        added = self._r.sadd(remine_key, l2_url)
        if added:
            logger.info(f"📥 [Inspector Redis] L2 已入队 session={self._session_id[:8]}: {l2_url}")
            self._r.hincrby(self._keys.inspector_session_stats(self._session_id), "REMINE_ADDED", 1)

    def get_and_clear_remine_queue(self) -> List[str]:
        remine_key = self._keys.inspector_remine(self._session_id)
        urls = list(self._r.smembers(remine_key) or [])
        if urls:
            self._r.delete(remine_key)
            logger.info(
                f"📤 [Inspector Redis] 释放 {len(urls)} 个 L2 任务 "
                f"session={self._session_id[:8]}"
            )
        return urls

    def get_summary(self) -> Dict[str, int]:
        summary = {"PASS": 0, "FAIL": 0, "REVIEW": 0, "ERROR": 0}
        reports_key = self._keys.inspector_reports()
        # 全量扫描成本高；优先读 session stats，再补 remine 待办数
        stats = self._r.hgetall(self._keys.inspector_session_stats(self._session_id)) or {}
        for k, v in stats.items():
            if k in summary:
                try:
                    summary[k] = int(v)
                except (TypeError, ValueError):
                    pass
        if not any(summary.values()):
            for raw in self._r.hvals(reports_key) or []:
                item = _json_loads(raw) or {}
                status = str(item.get("status") or "ERROR")
                summary[status] = summary.get(status, 0) + 1
        summary["PENDING_L2_MINES"] = int(self._r.scard(self._keys.inspector_remine(self._session_id)) or 0)
        return summary

    def save_state(self) -> None:
        """Redis 实时写入，保留接口兼容。"""
        return None
