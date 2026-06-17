"""Session 关闭归档：Redis / 文件 → SQLite session_snapshots。"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger


def archive_session(
    session_id: str,
    session_storage: Any,
    persistent_memory: Any,
    *,
    bundle: Any = None,
) -> bool:
    """
    将 session 全量快照写入 SQLite，再允许 Redis 层设置归档 TTL。

    persistent_memory.save_session_snapshot(session_id, domain, data)
    中 domain 使用固定占位符 ``__session__``。
    """
    if not session_id or not persistent_memory:
        return False
    if not hasattr(persistent_memory, "save_session_snapshot"):
        return False

    payload = _export_session_payload(session_storage, session_id)
    if not payload:
        logger.warning(f"Session 归档跳过：无数据 session_id={session_id}")
        return False

    payload["archived_at"] = datetime.now().isoformat()
    payload["backend"] = "redis" if bundle else "file"

    try:
        ok = persistent_memory.save_session_snapshot(session_id, "__session__", payload)
        if ok:
            logger.info(f"📦 Session 已归档至 SQLite: {session_id}")
        return bool(ok)
    except Exception as e:
        logger.error(f"Session 归档失败 ({session_id}): {e}")
        return False


def _export_session_payload(session_storage: Any, session_id: str) -> Optional[Dict[str, Any]]:
    if hasattr(session_storage, "export_session"):
        data = session_storage.export_session(session_id)
        if data:
            return data

    if not hasattr(session_storage, "get_session"):
        return None

    session = session_storage.get_session(session_id)
    if not session:
        return None

    learning_events = []
    for event in getattr(session, "learning_events", []) or []:
        if hasattr(session_storage, "_serialize_learning_event"):
            learning_events.append(session_storage._serialize_learning_event(event))
        else:
            learning_events.append(_fallback_event_dict(event))

    return {
        "session_id": session.session_id,
        "start_time": _iso(getattr(session, "start_time", None)),
        "end_time": _iso(getattr(session, "end_time", None)),
        "total_extractions": getattr(session, "total_extractions", 0),
        "successful_extractions": getattr(session, "successful_extractions", 0),
        "total_l3_found": getattr(session, "total_l3_found", 0),
        "domains_processed": list(getattr(session, "domains_processed", []) or []),
        "learning_events": learning_events,
    }


def _iso(dt: Any) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def _fallback_event_dict(event: Any) -> Dict[str, Any]:
    try:
        if hasattr(event, "__dict__"):
            return json.loads(json.dumps(event.__dict__, default=str))
    except Exception:
        pass
    return {"raw": str(event)}
