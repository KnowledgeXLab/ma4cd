"""
Redis 记忆后端草案。

启用方式（计划）：
    MA4CD_MEMORY_BACKEND=redis
    MA4CD_REDIS_URL=redis://localhost:6379/0
    MA4CD_REDIS_KEY_PREFIX=ma4cd          # 可选，默认 ma4cd
    MA4CD_REDIS_ENV=dev                   # 可选，多环境隔离

Key 命名规范
============
所有 key 使用冒号分隔，统一前缀：

    {prefix}:{env}:{layer}:{session_id?}:{resource}

其中 prefix = MA4CD_REDIS_KEY_PREFIX（默认 ma4cd）
     env    = MA4CD_REDIS_ENV（默认 dev）

┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. 协调层 (coord) — TTL 随 session 续期                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ ma4cd:dev:coord:active_session              STRING   当前主 session_id      │
│ ma4cd:dev:coord:sessions:active             SET      活跃 session 集合       │
│ ma4cd:dev:coord:session:{sid}:runtime       HASH    UMM 运行时镜像          │
│   fields: started_at, extraction_count, task_info (json)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. Working 短期 KV — TTL = MA4CD_WORKING_TTL (默认 7200s)                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ ma4cd:dev:working:{sid}:kv                  HASH    key → MemoryItem json   │
│ ma4cd:dev:working:{sid}:tag:{tag}           SET     反向索引               │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3. 轨迹追踪 — TTL 同 working                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ ma4cd:dev:traj:{sid}:url                    HASH    norm_url → TrajectoryNode│
│ ma4cd:dev:traj:{sid}:timeline               LIST    norm_url 有序时间线       │
│ ma4cd:dev:traj:{sid}:drop_streak            STRING  连续 DROP 计数（防循环） │
├─────────────────────────────────────────────────────────────────────────────┤
│ 4. Miner 并发协调 — TTL 同 working                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ ma4cd:dev:miner:{sid}:visited               SET     已完成 URL               │
│ ma4cd:dev:miner:{sid}:processing            SET     处理中 URL               │
│ ma4cd:dev:miner:{sid}:proc:{url_hash}       STRING  单 URL 细粒度锁 (SET NX) │
│ ma4cd:dev:miner:{sid}:domain_fails          HASH    domain → fail_count      │
│ ma4cd:dev:miner:{sid}:url_retries           HASH    url_hash → retry_count  │
├─────────────────────────────────────────────────────────────────────────────┤
│ 5. Session 中期记忆 — 活跃期无 TTL；close 后 TTL = MA4CD_SESSION_ARCHIVE_TTL│
│    (默认 604800 = 7d，到期前应由 archiver 落盘 SQLite)                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ ma4cd:dev:session:{sid}:meta                HASH    SessionSummary 标量字段  │
│   session_id, start_time, end_time, total_extractions, ...                  │
│   task_info (json)                                                          │
│ ma4cd:dev:session:{sid}:domains             SET     domains_processed        │
│ ma4cd:dev:session:{sid}:learning_events     LIST    LearningEvent json       │
│ ma4cd:dev:session:{sid}:collab_events       STREAM  Pipeline 协作事件         │
│   LPUSH + LTRIM 保留最近 MA4CD_SESSION_MAX_EVENTS (默认 5000)               │
│ ma4cd:dev:session:index                     ZSET    score=start_ts member=sid│
├─────────────────────────────────────────────────────────────────────────────┤
│ 6. 持久层读缓存（可选，非主存储）— TTL = MA4CD_REDIS_CACHE_TTL (默认 300s)  │
├─────────────────────────────────────────────────────────────────────────────┤
│ ma4cd:dev:cache:strategy:{domain}           STRING  json                    │
│ ma4cd:dev:cache:instructions:{domain}:{agent} STRING  json                  │
│ ma4cd:dev:cache:supervision:{domain}        STRING  json                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ 7. 批跑断点（扩展，非 UMM 核心）                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│ ma4cd:dev:batch:{batch_id}:checkpoint       HASH                            │
│ ma4cd:dev:batch:{batch_id}:done             SET                             │
└─────────────────────────────────────────────────────────────────────────────┘

不迁入 Redis 的数据（保持现状）：
- persistent_memory.db（进化策略、路径效率、监督反馈）
- Chroma / DataMemoryCenter 向量库
- 大块 extracted_content（页面全文）

Session 关闭归档流：
    close_session → 写 SQLite session_snapshots → 给 Redis session key 设 TTL

"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from loguru import logger

from agents.miner.memory.backends.base import (
    CoordinationBackend,
    MemoryBackendBundle,
    SessionMemoryBackend,
    WorkingMemoryBackend,
)
from agents.miner.memory.models.memory_models import (
    ExtractionContext,
    ExtractionResult,
    LearningEvent,
    SessionSummary,
)

# redis-py 为可选依赖，file 模式不强制安装
try:
    import redis
except ImportError:
    redis = None  # type: ignore


# ---------------------------------------------------------------------------
# Key builder
# ---------------------------------------------------------------------------

class RedisKeySpace:
  """集中管理 key 生成，避免散落硬编码。"""

  def __init__(
      self,
      prefix: str = "ma4cd",
      env: str = "dev",
  ):
      self.prefix = prefix.rstrip(":")
      self.env = env

  def _k(self, *parts: str) -> str:
      return ":".join([self.prefix, self.env, *parts])

  # coord
  def active_session(self) -> str:
      return self._k("coord", "active_session")

  def sessions_active(self) -> str:
      return self._k("coord", "sessions", "active")

  def session_runtime(self, session_id: str) -> str:
      return self._k("coord", "session", session_id, "runtime")

  # working
  def working_kv(self, session_id: str) -> str:
      return self._k("working", session_id, "kv")

  def working_tag(self, session_id: str, tag: str) -> str:
      return self._k("working", session_id, "tag", tag)

  # trajectory
  def traj_url(self, session_id: str) -> str:
      return self._k("traj", session_id, "url")

  def traj_timeline(self, session_id: str) -> str:
      return self._k("traj", session_id, "timeline")

  def traj_drop_streak(self, session_id: str) -> str:
      return self._k("traj", session_id, "drop_streak")

  # miner coordination
  def miner_visited(self, session_id: str) -> str:
      return self._k("miner", session_id, "visited")

  def miner_processing(self, session_id: str) -> str:
      return self._k("miner", session_id, "processing")

  def miner_proc_lock(self, session_id: str, url_hash: str) -> str:
      return self._k("miner", session_id, "proc", url_hash)

  def miner_domain_fails(self, session_id: str) -> str:
      return self._k("miner", session_id, "domain_fails")

  def miner_url_retries(self, session_id: str) -> str:
      return self._k("miner", session_id, "url_retries")

  # session
  def session_meta(self, session_id: str) -> str:
      return self._k("session", session_id, "meta")

  def session_domains(self, session_id: str) -> str:
      return self._k("session", session_id, "domains")

  def session_events(self, session_id: str) -> str:
      """Miner 学习事件（Redis LIST）。别名保留，实际键为 learning_events。"""
      return self.session_learning_events(session_id)

  def session_learning_events(self, session_id: str) -> str:
      return self._k("session", session_id, "learning_events")

  def session_collab_events(self, session_id: str) -> str:
      """Pipeline 协作事件总线（Redis Stream）。"""
      return self._k("session", session_id, "collab_events")

  def session_index(self) -> str:
      return self._k("session", "index")

  # cache (persistent read-through L1)
  def cache_strategy(self, domain: str, kind: str = "best") -> str:
      return self._k("cache", "strategy", domain, kind)

  def cache_instructions(self, domain: str, agent: str) -> str:
      return self._k("cache", "instructions", domain, agent)

  def cache_supervision(self, domain: str) -> str:
      return self._k("cache", "supervision", domain)

  # blacklist hot path
  def blacklist_urls(self) -> str:
      return self._k("blacklist", "urls")

  def blacklist_reason(self, url_hash: str) -> str:
      return self._k("blacklist", "reason", url_hash)

  # scout search cache
  def scout_search(self, query_hash: str) -> str:
      return self._k("scout", "search", query_hash)

  def scout_session_urls(self, session_id: str) -> str:
      return self._k("scout", "session", session_id, "urls")

  # batch checkpoint
  def batch_checkpoint(self, batch_id: str) -> str:
      return self._k("batch", batch_id, "checkpoint")

  def batch_done(self, batch_id: str) -> str:
      return self._k("batch", batch_id, "done")

  def pipeline_checkpoint(self, run_key: str) -> str:
      return self._k("pipeline", run_key, "checkpoint")

  def session_board(self, session_id: str) -> str:
      return self._k("session", session_id, "board")

  # inspector
  def inspector_reports(self) -> str:
      """全局 URL 审计缓存（跨 session 去重）。"""
      return self._k("inspector", "reports")

  def inspector_remine(self, session_id: str) -> str:
      """Session 级 L2 回挖队列。"""
      return self._k("inspector", "session", session_id, "remine")

  def inspector_session_stats(self, session_id: str) -> str:
      return self._k("inspector", "session", session_id, "stats")

  @staticmethod
  def url_hash(url: str) -> str:
      return hashlib.sha1(url.encode()).hexdigest()[:16]

  @staticmethod
  def normalize_url(url: str) -> str:
      if not url:
          return ""
      return str(url).split("#")[0].rstrip("/")


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _json_dumps(obj: Any) -> str:
  return json.dumps(obj, ensure_ascii=False, default=str)


def _json_loads(raw: Optional[str]) -> Any:
  if not raw:
      return None
  return json.loads(raw)


def _dt_iso(dt: Optional[datetime]) -> str:
  return dt.isoformat() if dt else ""


def _dt_parse(s: Optional[str]) -> Optional[datetime]:
  if not s:
      return None
  return datetime.fromisoformat(s)


# ---------------------------------------------------------------------------
# RedisWorkingMemoryStorage
# ---------------------------------------------------------------------------

class RedisWorkingMemoryStorage:
  """
  Working 层 Redis 实现草案。
  注意：session_id 为必填上下文；由 CoordinationBackend 提供默认值。
  """

  def __init__(
      self,
      client: "redis.Redis",
      keys: RedisKeySpace,
      *,
      default_session_id: str = "default",
      working_ttl: int = 7200,
      max_trajectory: int = 5000,
  ):
      self._r = client
      self._keys = keys
      self._default_session_id = default_session_id
      self._working_ttl = working_ttl
      self._max_trajectory = max_trajectory

  def _sid(self, session_id: Optional[str]) -> str:
      return session_id or self._default_session_id

  def _touch_ttl(self, *redis_keys: str) -> None:
      if self._working_ttl > 0:
          pipe = self._r.pipeline()
          for k in redis_keys:
              pipe.expire(k, self._working_ttl)
          pipe.execute()

  def set(
      self,
      key: str,
      value: Any,
      ttl_seconds: Optional[int] = 3600,
      importance: float = 0.5,
      tags: Optional[List[str]] = None,
      *,
      session_id: Optional[str] = None,
  ) -> bool:
      sid = self._sid(session_id)
      kv_key = self._keys.working_kv(sid)
      item = {
          "key": key,
          "value": value,
          "importance": importance,
          "tags": tags or [],
          "created_at": datetime.now().isoformat(),
          "ttl_seconds": ttl_seconds,
      }
      pipe = self._r.pipeline()
      pipe.hset(kv_key, key, _json_dumps(item))
      for tag in tags or []:
          pipe.sadd(self._keys.working_tag(sid, tag), key)
      pipe.execute()
      self._touch_ttl(kv_key)
      return True

  def get(self, key: str, *, session_id: Optional[str] = None) -> Any:
      sid = self._sid(session_id)
      raw = self._r.hget(self._keys.working_kv(sid), key)
      item = _json_loads(raw)
      return item.get("value") if isinstance(item, dict) else None

  def delete(self, key: str, *, session_id: Optional[str] = None) -> bool:
      sid = self._sid(session_id)
      return bool(self._r.hdel(self._keys.working_kv(sid), key))

  def get_stats(self, *, session_id: Optional[str] = None) -> Dict[str, Any]:
      sid = self._sid(session_id)
      return {
          "backend": "redis",
          "session_id": sid,
          "kv_count": self._r.hlen(self._keys.working_kv(sid)),
          "traj_count": self._r.hlen(self._keys.traj_url(sid)),
      }

  def check_url_status(self, url: str, *, session_id: Optional[str] = None) -> Optional[str]:
      sid = self._sid(session_id)
      norm = self._keys.normalize_url(url)
      raw = self._r.hget(self._keys.traj_url(sid), norm)
      node = _json_loads(raw)
      return node.get("action_state") if isinstance(node, dict) else None

  def record_step(
      self,
      url: str,
      action_state: str,
      depth: int,
      reason: str = "",
      *,
      session_id: Optional[str] = None,
  ) -> None:
      sid = self._sid(session_id)
      norm = self._keys.normalize_url(url)
      node = {
          "url": norm,
          "action_state": action_state,
          "depth": depth,
          "reason": reason,
          "timestamp": datetime.now().timestamp(),
      }
      url_key = self._keys.traj_url(sid)
      tl_key = self._keys.traj_timeline(sid)
      streak_key = self._keys.traj_drop_streak(sid)

      pipe = self._r.pipeline()
      pipe.hset(url_key, norm, _json_dumps(node))
      pipe.rpush(tl_key, norm)
      if action_state.startswith("DROP"):
          pipe.incr(streak_key)
      else:
          pipe.set(streak_key, 0)
      pipe.execute()

      # 裁剪 timeline
      self._r.ltrim(tl_key, -self._max_trajectory, -1)
      self._touch_ttl(url_key, tl_key, streak_key)

  def get_recent_trajectory_context(
      self, steps: int = 4, *, session_id: Optional[str] = None
  ) -> str:
      sid = self._sid(session_id)
      tl_key = self._keys.traj_timeline(sid)
      url_key = self._keys.traj_url(sid)
      recent_urls = self._r.lrange(tl_key, -steps, -1) or []
      if not recent_urls:
          return "尚无探索轨迹。"
      lines = []
      for i, norm in enumerate(reversed(recent_urls), 1):
          raw = self._r.hget(url_key, norm)
          node = _json_loads(raw) or {}
          lines.append(
              f"Step -{i}:\n"
              f"  - 访问 URL: {node.get('url', norm)}\n"
              f"  - 判定结果: {node.get('action_state', '')}\n"
              f"  - 结论依据: {node.get('reason', '')}"
          )
      return "\n".join(lines)

  def is_looping(self, drop_threshold: int = 3, *, session_id: Optional[str] = None) -> bool:
      sid = self._sid(session_id)
      streak = self._r.get(self._keys.traj_drop_streak(sid))
      try:
          return int(streak or 0) >= drop_threshold
      except (TypeError, ValueError):
          return False

  def reset_session(self, session_id: str) -> None:
      sid = self._sid(session_id)
      self._r.delete(
          self._keys.working_kv(sid),
          self._keys.traj_url(sid),
          self._keys.traj_timeline(sid),
          self._keys.traj_drop_streak(sid),
      )


# ---------------------------------------------------------------------------
# RedisSessionMemoryStorage
# ---------------------------------------------------------------------------

class RedisSessionMemoryStorage:
  """Session 层 Redis 实现草案。"""

  def __init__(
      self,
      client: "redis.Redis",
      keys: RedisKeySpace,
      coordination: "RedisCoordinationBackend",
      *,
      max_events: int = 5000,
      archive_ttl: int = 604800,
  ):
      self._r = client
      self._keys = keys
      self._coord = coordination
      self._max_events = max_events
      self._archive_ttl = archive_ttl

  def create_session(
      self, session_id: str, session_info: Optional[Dict[str, Any]] = None
  ) -> SessionSummary:
      now = datetime.now()
      meta_key = self._keys.session_meta(session_id)
      pipe = self._r.pipeline()
      pipe.hset(
          meta_key,
          mapping={
              "session_id": session_id,
              "start_time": _dt_iso(now),
              "end_time": "",
              "total_extractions": 0,
              "successful_extractions": 0,
              "total_l3_found": 0,
              "task_info": _json_dumps(session_info or {}),
          },
      )
      pipe.zadd(self._keys.session_index(), {session_id: now.timestamp()})
      pipe.sadd(self._keys.sessions_active(), session_id)
      pipe.execute()

      self._coord.set_active_session_id(session_id)
      return self._hydrate_summary(session_id)

  def get_session(self, session_id: str) -> Optional[SessionSummary]:
      if not self._r.exists(self._keys.session_meta(session_id)):
          return None
      return self._hydrate_summary(session_id)

  def _hydrate_summary(self, session_id: str) -> SessionSummary:
      meta = self._r.hgetall(self._keys.session_meta(session_id))
      session = SessionSummary(
          session_id=session_id,
          start_time=_dt_parse(meta.get("start_time")) or datetime.now(),
      )
      session.end_time = _dt_parse(meta.get("end_time"))
      session.total_extractions = int(meta.get("total_extractions") or 0)
      session.successful_extractions = int(meta.get("successful_extractions") or 0)
      session.total_l3_found = int(meta.get("total_l3_found") or 0)
      session.domains_processed = list(self._r.smembers(self._keys.session_domains(session_id)) or [])
      # learning_events 按需懒加载；完整列表走 list_sessions / archiver
      session.learning_events = []
      return session

  def record_extraction(
      self,
      session_id: str,
      domain: str,
      url: str,
      site_profile: Dict,
      strategy_used: Dict,
      success: bool,
      l3_candidates: List[Dict],
      execution_time: float,
      error_message: Optional[str] = None,
  ) -> bool:
      active = self._coord.get_active_session_id()
      if not self._r.exists(self._keys.session_meta(session_id)) and active:
          session_id = active

      if not self.get_session(session_id):
          self.create_session(session_id, {"auto_created": True})

      context = ExtractionContext(
          domain=domain, url=url,
          site_profile=site_profile or {},
          strategy_used=strategy_used or {},
      )
      result = ExtractionResult(
          success=success,
          l3_count=len(l3_candidates or []),
          l3_candidates=l3_candidates or [],
          execution_time=execution_time,
          error_message=error_message,
      )
      event = LearningEvent(
          event_id=str(uuid.uuid4()),
          event_type="extraction_flow",
          context=context,
          result=result,
          importance=0.8 if success else 0.2,
      )
      return self.add_learning_event(session_id, event)

  def add_learning_event(self, session_id: str, event: LearningEvent) -> bool:
      if not self.get_session(session_id):
          return False

      meta_key = self._keys.session_meta(session_id)
      events_key = self._keys.session_events(session_id)
      domains_key = self._keys.session_domains(session_id)

      payload = _json_dumps({
          "event_id": event.event_id,
          "event_type": event.event_type,
          "context": {
              "domain": event.context.domain,
              "url": event.context.url,
              "site_profile": event.context.site_profile,
              "strategy_used": event.context.strategy_used,
              "timestamp": _dt_iso(event.context.timestamp),
          },
          "result": {
              "success": event.result.success,
              "l3_count": event.result.l3_count,
              "l3_candidates": event.result.l3_candidates,
              "execution_time": event.result.execution_time,
              "error_message": event.result.error_message,
          },
          "importance": event.importance,
          "timestamp": _dt_iso(event.timestamp),
      })

      pipe = self._r.pipeline()
      pipe.hincrby(meta_key, "total_extractions", 1)
      if event.result.success:
          pipe.hincrby(meta_key, "successful_extractions", 1)
          pipe.hincrby(meta_key, "total_l3_found", event.result.l3_count)
      pipe.sadd(domains_key, event.context.domain)
      pipe.lpush(events_key, payload)
      pipe.ltrim(events_key, 0, self._max_events - 1)
      pipe.execute()
      return True

  def close_session(self, session_id: str) -> bool:
      if not self.get_session(session_id):
          return False

      meta_key = self._keys.session_meta(session_id)
      self._r.hset(meta_key, "end_time", _dt_iso(datetime.now()))
      self._r.srem(self._keys.sessions_active(), session_id)

      if self._coord.get_active_session_id() == session_id:
          self._coord.set_active_session_id(None)

      # 关闭后给 session 相关 key 加归档 TTL（由 archiver 提前落 SQLite）
      ttl = self._archive_ttl
      for k in (
          meta_key,
          self._keys.session_domains(session_id),
          self._keys.session_events(session_id),
      ):
          self._r.expire(k, ttl)
      return True

  def end_session(self, session_id: str) -> bool:
      return self.close_session(session_id)

  def update_session(self, session_id: str, **updates) -> bool:
      if not self.get_session(session_id):
          return False
      mapping = {k: str(v) for k, v in updates.items() if v is not None}
      if mapping:
          self._r.hset(self._keys.session_meta(session_id), mapping=mapping)
      return True

  def list_sessions(self, days_back: int = 7) -> List[Dict[str, Any]]:
      cutoff = (datetime.now() - timedelta(days=days_back)).timestamp()
      session_ids = self._r.zrangebyscore(self._keys.session_index(), cutoff, "+inf") or []
      out = []
      for sid in session_ids:
          sid_str = sid.decode() if isinstance(sid, bytes) else sid
          meta = self._r.hgetall(self._keys.session_meta(sid_str))
          if not meta:
              continue
          out.append({
              "session_id": sid_str,
              "start_time": _dt_parse(meta.get("start_time")),
              "end_time": _dt_parse(meta.get("end_time")),
              "total_extractions": int(meta.get("total_extractions") or 0),
          })
      out.sort(key=lambda x: x["start_time"] or datetime.min, reverse=True)
      return out

  def get_session_stats(self, session_id: str) -> Dict[str, Any]:
      session = self.get_session(session_id)
      if not session:
          return {}
      end = session.end_time or datetime.now()
      duration = (end - session.start_time).total_seconds()
      total = session.total_extractions
      success = session.successful_extractions
      events_count = self._r.llen(self._keys.session_events(session_id))
      return {
          "session_id": session_id,
          "duration_seconds": duration,
          "total_extractions": total,
          "successful_extractions": success,
          "success_rate": (success / total) if total else 0,
          "total_l3_found": session.total_l3_found,
          "learning_events_count": events_count,
      }

  def get_stats(self) -> Dict[str, Any]:
      return {
          "backend": "redis",
          "active_sessions": self._r.scard(self._keys.sessions_active()),
      }

  def export_session(self, session_id: str) -> Optional[Dict[str, Any]]:
      if not self._r.exists(self._keys.session_meta(session_id)):
          return None
      meta = self._r.hgetall(self._keys.session_meta(session_id))
      raw_events = self._r.lrange(self._keys.session_events(session_id), 0, -1) or []
      events = []
      for raw in reversed(raw_events):
          parsed = _json_loads(raw)
          if parsed:
              events.append(parsed)
      domains = list(self._r.smembers(self._keys.session_domains(session_id)) or [])
      return {
          "session_id": session_id,
          "start_time": meta.get("start_time"),
          "end_time": meta.get("end_time"),
          "total_extractions": int(meta.get("total_extractions") or 0),
          "successful_extractions": int(meta.get("successful_extractions") or 0),
          "total_l3_found": int(meta.get("total_l3_found") or 0),
          "task_info": _json_loads(meta.get("task_info")) or {},
          "domains_processed": domains,
          "learning_events": events,
      }


# ---------------------------------------------------------------------------
# RedisCoordinationBackend
# ---------------------------------------------------------------------------

class RedisCoordinationBackend:
  """跨 worker 协调：active session、visited、processing 锁。"""

  def __init__(
      self,
      client: "redis.Redis",
      keys: RedisKeySpace,
      *,
      working_ttl: int = 7200,
      lock_ttl: int = 600,
  ):
      self._r = client
      self._keys = keys
      self._working_ttl = working_ttl
      self._lock_ttl = lock_ttl

  def _touch(self, key: str) -> None:
      if self._working_ttl > 0:
          self._r.expire(key, self._working_ttl)

  def get_active_session_id(self) -> Optional[str]:
      val = self._r.get(self._keys.active_session())
      if not val:
          return None
      return val.decode() if isinstance(val, bytes) else val

  def set_active_session_id(self, session_id: Optional[str]) -> None:
      key = self._keys.active_session()
      if session_id:
          self._r.set(key, session_id)
      else:
          self._r.delete(key)

  def mark_visited(self, session_id: str, url: str) -> bool:
      key = self._keys.miner_visited(session_id)
      added = self._r.sadd(key, self._keys.normalize_url(url))
      self._touch(key)
      return added == 1

  def is_visited(self, session_id: str, url: str) -> bool:
      return bool(self._r.sismember(
          self._keys.miner_visited(session_id),
          self._keys.normalize_url(url),
      ))

  def try_acquire_processing(self, session_id: str, url: str, ttl_seconds: int = 600) -> bool:
      norm = self._keys.normalize_url(url)
      lock_key = self._keys.miner_proc_lock(session_id, self._keys.url_hash(norm))
      acquired = self._r.set(lock_key, "1", nx=True, ex=ttl_seconds or self._lock_ttl)
      if acquired:
          proc_key = self._keys.miner_processing(session_id)
          self._r.sadd(proc_key, norm)
          self._touch(proc_key)
      return bool(acquired)

  def release_processing(self, session_id: str, url: str) -> None:
      norm = self._keys.normalize_url(url)
      self._r.srem(self._keys.miner_processing(session_id), norm)
      self._r.delete(self._keys.miner_proc_lock(session_id, self._keys.url_hash(norm)))

  def incr_domain_fail(self, session_id: str, domain: str) -> int:
      key = self._keys.miner_domain_fails(session_id)
      val = int(self._r.hincrby(key, domain, 1))
      self._touch(key)
      return val

  def get_domain_fail(self, session_id: str, domain: str) -> int:
      return int(self._r.hget(self._keys.miner_domain_fails(session_id), domain) or 0)

  def incr_url_retry(self, session_id: str, url: str) -> int:
      h = self._keys.url_hash(self._keys.normalize_url(url))
      key = self._keys.miner_url_retries(session_id)
      val = int(self._r.hincrby(key, h, 1))
      self._touch(key)
      return val

  def get_url_retry(self, session_id: str, url: str) -> int:
      h = self._keys.url_hash(self._keys.normalize_url(url))
      return int(self._r.hget(self._keys.miner_url_retries(session_id), h) or 0)

  def reset_batch(self, session_id: str) -> None:
      self._r.delete(
          self._keys.miner_visited(session_id),
          self._keys.miner_processing(session_id),
          self._keys.miner_domain_fails(session_id),
          self._keys.miner_url_retries(session_id),
      )

  def sync_runtime(
      self,
      session_id: str,
      *,
      task_info: Optional[Dict[str, Any]] = None,
      extraction_count: Optional[int] = None,
  ) -> None:
      runtime_key = self._keys.session_runtime(session_id)
      mapping: Dict[str, str] = {}
      if task_info is not None:
          mapping["task_info"] = _json_dumps(task_info)
      if extraction_count is not None:
          mapping["extraction_count"] = str(extraction_count)
      if mapping:
          self._r.hset(runtime_key, mapping=mapping)
      if self._working_ttl > 0:
          self._r.expire(runtime_key, self._working_ttl)


# ---------------------------------------------------------------------------
# Bundle factory
# ---------------------------------------------------------------------------

class RedisMemoryBackend(MemoryBackendBundle):
  """Redis 后端组合入口。"""

  def __init__(self, client: "redis.Redis", keys: RedisKeySpace, **kwargs):
      self._keys = keys
      self._coord = RedisCoordinationBackend(
          client,
          keys,
          working_ttl=kwargs.get("working_ttl", 7200),
          lock_ttl=kwargs.get("lock_ttl", 600),
      )
      self._working = RedisWorkingMemoryStorage(
          client, keys,
          default_session_id=kwargs.get("default_session_id", "default"),
          working_ttl=kwargs.get("working_ttl", 7200),
          max_trajectory=kwargs.get("max_trajectory", 5000),
      )
      self._session = RedisSessionMemoryStorage(
          client, keys, self._coord,
          max_events=kwargs.get("max_events", 5000),
          archive_ttl=kwargs.get("archive_ttl", 604800),
      )
      self._client = client

  @property
  def working(self) -> WorkingMemoryBackend:
      return self._working

  @property
  def session(self) -> SessionMemoryBackend:
      return self._session

  @property
  def keys(self) -> RedisKeySpace:
      return self._keys

  @property
  def client(self) -> "redis.Redis":
      return self._client

  def inspector_state(self, session_id: str = "global"):
      from agents.inspector.backends.redis_backend import RedisInspectorState
      return RedisInspectorState(
          self._client,
          self._keys,
          session_id=session_id or "global",
          report_ttl=int(os.getenv("MA4CD_INSPECTOR_REPORT_TTL", "0") or 0),
      )

  @property
  def coordination(self) -> CoordinationBackend:
      return self._coord

  def ping(self) -> bool:
      return bool(self._client.ping())

  def close(self) -> None:
      self._client.close()


def create_redis_backend_from_client(
    client: "redis.Redis",
    *,
    prefix: str = "ma4cd",
    env: str = "test",
    **kwargs,
) -> RedisMemoryBackend:
    """供集成测试注入 fakeredis / 内存 Redis 客户端。"""
    keys = RedisKeySpace(prefix=prefix, env=env)
    return RedisMemoryBackend(client, keys, **kwargs)


def create_redis_backend_from_env() -> RedisMemoryBackend:
  """
  从环境变量构建 Redis 后端。

  MA4CD_REDIS_URL=redis://localhost:6379/0
  MA4CD_REDIS_KEY_PREFIX=ma4cd
  MA4CD_REDIS_ENV=dev
  MA4CD_WORKING_TTL=7200
  MA4CD_SESSION_ARCHIVE_TTL=604800
  MA4CD_SESSION_MAX_EVENTS=5000
  """
  if redis is None:
      raise RuntimeError("redis 包未安装，请执行: pip install redis")

  url = os.getenv("MA4CD_REDIS_URL", "redis://localhost:6379/0")
  prefix = os.getenv("MA4CD_REDIS_KEY_PREFIX", "ma4cd")
  env = os.getenv("MA4CD_REDIS_ENV", "dev")

  client = redis.Redis.from_url(url, decode_responses=True)
  keys = RedisKeySpace(prefix=prefix, env=env)

  backend = RedisMemoryBackend(
      client,
      keys,
      working_ttl=int(os.getenv("MA4CD_WORKING_TTL", "7200")),
      archive_ttl=int(os.getenv("MA4CD_SESSION_ARCHIVE_TTL", "604800")),
      max_events=int(os.getenv("MA4CD_SESSION_MAX_EVENTS", "5000")),
      max_trajectory=int(os.getenv("MA4CD_WORKING_MAX_TRAJECTORY", "5000")),
  )
  if not backend.ping():
      raise RuntimeError(f"Redis 连接失败: {url}")
  logger.info(f"RedisMemoryBackend 就绪 | url={url} prefix={prefix}:{env}")
  return backend
