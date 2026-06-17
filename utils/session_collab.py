"""
Session 级协作层：事件总线 + 任务黑板。

Redis 模式（MA4CD_MEMORY_BACKEND=redis）：
  ma4cd:{env}:session:{sid}:collab_events   Stream（协作事件总线）
  ma4cd:{env}:session:{sid}:board             HASH（任务黑板）

Miner 学习事件使用 ma4cd:{env}:session:{sid}:learning_events（LIST），与协作总线分离。

File 模式：reports/session_collab/{sid}/events.jsonl + board.json
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

try:
    from agents.miner.memory.backends.redis_aux import (
        get_redis_client_and_keys,
        redis_aux_enabled,
        _json_dumps,
        _json_loads,
    )
    from agents.miner.memory.backends.redis_backend import RedisKeySpace
except ImportError:
    redis_aux_enabled = lambda: False  # type: ignore
    get_redis_client_and_keys = lambda: (None, None)  # type: ignore

    def _json_dumps(obj):
        return json.dumps(obj, ensure_ascii=False, default=str)

    def _json_loads(raw):
        return json.loads(raw) if raw else None

    RedisKeySpace = None  # type: ignore


def session_collab_enabled() -> bool:
    if os.getenv("MA4CD_SESSION_COLLAB", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    return True


def curator_scout_loop_enabled() -> bool:
    return os.getenv("MA4CD_CURATOR_SCOUT_LOOP", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _collab_root() -> str:
    root = os.getenv("MA4CD_SESSION_COLLAB_DIR", "").strip()
    if root:
        return root if os.path.isabs(root) else os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            root,
        )
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "reports",
        "session_collab",
    )


class SessionEventBus:
    """Session 事件总线（Redis Stream 或 jsonl 文件）。"""

    def __init__(
        self,
        session_id: str,
        client=None,
        keys: Optional[RedisKeySpace] = None,
    ):
        self.session_id = session_id
        self._r = client
        self._stream = keys.session_collab_events(session_id) if keys else None
        self._maxlen = int(os.getenv("MA4CD_SESSION_EVENTS_MAXLEN", "2000") or 2000)
        self._dir = os.path.join(_collab_root(), session_id)
        self._file = os.path.join(self._dir, "events.jsonl")

    def publish(
        self,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        agent: str = "pipeline",
    ) -> None:
        if not session_collab_enabled():
            return
        entry = {
            "type": event_type,
            "agent": agent,
            "ts": datetime.now().isoformat(),
            "payload": _json_dumps(payload or {}),
        }
        try:
            if self._r and self._stream:
                self._r.xadd(self._stream, entry, maxlen=self._maxlen, approximate=True)
            else:
                os.makedirs(self._dir, exist_ok=True)
                with open(self._file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug(f"SessionEventBus.publish 失败: {e}")

    def recent(self, count: int = 50) -> List[Dict[str, Any]]:
        if not session_collab_enabled():
            return []
        try:
            if self._r and self._stream:
                rows = self._r.xrevrange(self._stream, count=count) or []
                out = []
                for _id, fields in reversed(rows):
                    item = dict(fields)
                    item["id"] = _id
                    item["payload"] = _json_loads(item.get("payload")) or {}
                    out.append(item)
                return out
            if os.path.exists(self._file):
                with open(self._file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                out = []
                for line in lines[-count:]:
                    try:
                        item = json.loads(line)
                        item["payload"] = _json_loads(item.get("payload")) if isinstance(
                            item.get("payload"), str
                        ) else item.get("payload", {})
                        out.append(item)
                    except json.JSONDecodeError:
                        continue
                return out
        except Exception as e:
            logger.debug(f"SessionEventBus.recent 失败: {e}")
        return []


class MissionBoard:
    """Session 任务黑板（Redis HASH 或 board.json）。"""

    JSON_FIELDS = frozenset({
        "rubric", "gaps", "directives", "scout_urls", "specific_targets",
        "miner_stats", "inspector_stats", "yield_status",
    })

    def __init__(
        self,
        session_id: str,
        client=None,
        keys: Optional[RedisKeySpace] = None,
    ):
        self.session_id = session_id
        self._r = client
        self._key = keys.session_board(session_id) if keys else None
        self._dir = os.path.join(_collab_root(), session_id)
        self._file = os.path.join(self._dir, "board.json")
        self._local: Dict[str, Any] = {}

    def _read_all(self) -> Dict[str, Any]:
        if self._r and self._key:
            raw = self._r.hgetall(self._key) or {}
            out: Dict[str, Any] = {}
            for k, v in raw.items():
                if k in self.JSON_FIELDS:
                    out[k] = _json_loads(v) if isinstance(v, str) else v
                else:
                    out[k] = v
            return out
        if os.path.exists(self._file):
            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return dict(self._local)

    def _write_all(self, data: Dict[str, Any]) -> None:
        self._local = dict(data)
        try:
            if self._r and self._key:
                mapping: Dict[str, str] = {}
                for k, v in data.items():
                    if k in self.JSON_FIELDS:
                        mapping[k] = _json_dumps(v)
                    else:
                        mapping[k] = str(v) if v is not None else ""
                if mapping:
                    self._r.hset(self._key, mapping=mapping)
            else:
                os.makedirs(self._dir, exist_ok=True)
                with open(self._file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"MissionBoard 写入失败: {e}")

    def get(self) -> Dict[str, Any]:
        if not session_collab_enabled():
            return {}
        return self._read_all()

    def update(self, **fields: Any) -> None:
        if not session_collab_enabled():
            return
        data = self._read_all()
        data.update(fields)
        data["updated_at"] = datetime.now().isoformat()
        self._write_all(data)

    def append_scout_urls(self, urls: List[str], *, source: str = "scout") -> List[str]:
        if not session_collab_enabled() or not urls:
            return []
        data = self._read_all()
        existing = data.get("scout_urls") or []
        if not isinstance(existing, list):
            existing = []
        seen = {str(u).strip() for u in existing if u}
        added = []
        for u in urls:
            u = str(u).strip()
            if u and u not in seen:
                seen.add(u)
                existing.append(u)
                added.append(u)
        data["scout_urls"] = existing
        meta = data.get("scout_url_sources") or {}
        if not isinstance(meta, dict):
            meta = {}
        meta[source] = int(meta.get(source, 0)) + len(added)
        data["scout_url_sources"] = meta
        data["updated_at"] = datetime.now().isoformat()
        self._write_all(data)
        return added


_collab_cache: Dict[str, Tuple[SessionEventBus, MissionBoard]] = {}


def get_session_collab(session_id: str) -> Tuple[SessionEventBus, MissionBoard]:
    if session_id in _collab_cache:
        return _collab_cache[session_id]
    client, keys = get_redis_client_and_keys() if redis_aux_enabled() else (None, None)
    bus = SessionEventBus(session_id, client, keys)
    board = MissionBoard(session_id, client, keys)
    _collab_cache[session_id] = (bus, board)
    return bus, board


def build_curator_supplement_task(
    user_requirement: str,
    gaps: List[str],
    directives: str = "",
) -> str:
    try:
        from utils.curator_supplement import build_curator_supplement_task as _skill_build
        return _skill_build(user_requirement, gaps, directives)
    except Exception:
        pass
    lines = [
        user_requirement.strip(),
        "",
        "[Curator 战术补搜] 请针对以下数据/学科盲区补充检索，优先 L1/L2 门户与 L3 数据库入口：",
    ]
    for g in (gaps or [])[:8]:
        lines.append(f"- {g}")
    if directives:
        lines.extend(["", f"战略指导: {directives}"])
    return "\n".join(lines)
