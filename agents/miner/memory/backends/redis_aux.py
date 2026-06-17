"""
Redis 辅助缓存层：Persistent 读缓存、黑名单、Scout 搜索、批跑断点。

在 MA4CD_MEMORY_BACKEND=redis 时自动启用（可通过 MA4CD_REDIS_AUX=0 关闭）。
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

from agents.miner.memory.backends.redis_backend import RedisKeySpace, _json_dumps, _json_loads

_NULL_MARKER = "__NULL__"
_MISS = object()

_aux_enabled: Optional[bool] = None
_persistent_cache = None
_blacklist_cache = None
_scout_cache = None


def redis_aux_enabled() -> bool:
    global _aux_enabled
    if _aux_enabled is not None:
        return _aux_enabled
    if os.getenv("MA4CD_REDIS_AUX", "1").strip().lower() in ("0", "false", "no", "off"):
        _aux_enabled = False
        return False
    backend = os.getenv("MA4CD_MEMORY_BACKEND", "file").strip().lower()
    _aux_enabled = backend == "redis"
    return _aux_enabled


def get_redis_client_and_keys() -> Tuple[Optional[Any], Optional[RedisKeySpace]]:
    if not redis_aux_enabled():
        return None, None
    try:
        from agents.miner.memory.backends.factory import get_memory_backend
        bundle = get_memory_backend()
        if bundle is not None:
            return bundle.client, bundle.keys
    except Exception as e:
        logger.debug(f"Redis aux 不可用: {e}")
    return None, None


def _cache_ttl(env_name: str, default: int) -> int:
    return int(os.getenv(env_name, str(default)) or default)


def _cache_get(client, key: str) -> Any:
    raw = client.get(key)
    if raw is None:
        return _MISS
    if raw == _NULL_MARKER:
        return None
    return _json_loads(raw)


def _cache_set(client, key: str, value: Any, ttl: int) -> None:
    payload = _NULL_MARKER if value is None else _json_dumps(value)
    if ttl > 0:
        client.setex(key, ttl, payload)
    else:
        client.set(key, payload)


class RedisPersistentReadCache:
    """PersistentMemoryStorage 读路径 L1 缓存。"""

    def __init__(self, client, keys: RedisKeySpace):
        self._r = client
        self._keys = keys
        self._ttl = _cache_ttl("MA4CD_REDIS_CACHE_TTL", 300)

    def get_strategy(self, domain: str, kind: str) -> Any:
        key = self._keys.cache_strategy(domain, kind)
        return _cache_get(self._r, key)

    def set_strategy(self, domain: str, kind: str, value: Optional[Dict[str, Any]]) -> None:
        _cache_set(self._r, self._keys.cache_strategy(domain, kind), value, self._ttl)

    def get_instructions(self, domain: str, agent: str) -> Any:
        return _cache_get(self._r, self._keys.cache_instructions(domain, agent))

    def set_instructions(self, domain: str, agent: str, value: List[str]) -> None:
        _cache_set(self._r, self._keys.cache_instructions(domain, agent), value, self._ttl)

    def get_supervision(self, domain: str) -> Any:
        return _cache_get(self._r, self._keys.cache_supervision(domain))

    def set_supervision(self, domain: str, value: Dict[str, Any]) -> None:
        _cache_set(self._r, self._keys.cache_supervision(domain), value, self._ttl)

    def invalidate_domain(self, domain: str) -> None:
        for kind in ("best", "active", "latest"):
            self._r.delete(self._keys.cache_strategy(domain, kind))
        for agent in ("Miner", "Commander", "Scout", "Inspector", "Curator", "ALL"):
            self._r.delete(self._keys.cache_instructions(domain, agent))
            self._r.delete(self._keys.cache_instructions("GLOBAL", agent))
        self._r.delete(self._keys.cache_supervision(domain))

    def invalidate_instructions(self, domain: str) -> None:
        for agent in ("Miner", "Commander", "Scout", "Inspector", "Curator", "ALL"):
            self._r.delete(self._keys.cache_instructions(domain, agent))
        self._r.delete(self._keys.cache_instructions("GLOBAL", "ALL"))


class RedisBlacklistCache:
    """黑名单 O(1) 热路径；Chroma 仍为权威存储。"""

    def __init__(self, client, keys: RedisKeySpace):
        self._r = client
        self._keys = keys

    @staticmethod
    def url_variants(url: str) -> List[str]:
        if not url:
            return []
        base = RedisKeySpace.normalize_url(url.strip())
        variants = {
            url.strip(),
            base,
            base.lower(),
            base.lower().rstrip("/"),
            url.strip().rstrip("/"),
        }
        return [v for v in variants if v]

    def is_blacklisted(self, url: str) -> Optional[bool]:
        """命中返回 True/False；未缓存返回 None。"""
        variants = self.url_variants(url)
        if not variants:
            return False
        set_key = self._keys.blacklist_urls()
        pipe = self._r.pipeline()
        for v in variants:
            pipe.sismember(set_key, v)
        hits = pipe.execute()
        if any(hits):
            return True
        # 负缓存：若主 URL 规范化形式曾查过且不在 set，需区分「未查」与「非黑名单」
        # 简化：仅正缓存 SET，未命中走 Chroma
        return None

    def mark_blacklisted(self, url: str, reason: str = "") -> None:
        variants = self.url_variants(url)
        if not variants:
            return
        set_key = self._keys.blacklist_urls()
        self._r.sadd(set_key, *variants)
        if reason:
            for v in variants:
                h = RedisKeySpace.url_hash(v)
                self._r.set(self._keys.blacklist_reason(h), reason[:500])


class RedisScoutSearchCache:
    """Tavily 查询结果与会话级 URL 去重。"""

    def __init__(self, client, keys: RedisKeySpace):
        self._r = client
        self._keys = keys
        self._search_ttl = _cache_ttl("MA4CD_SCOUT_SEARCH_CACHE_TTL", 86400)

    @staticmethod
    def search_hash(query: str, num_results: int, **kwargs) -> str:
        payload = {
            "q": (query or "").strip().lower(),
            "n": int(num_results),
            "tavily_only": bool(kwargs.get("tavily_only", True)),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    def get_search(self, query: str, num_results: int, **kwargs) -> Any:
        h = self.search_hash(query, num_results, **kwargs)
        return _cache_get(self._r, self._keys.scout_search(h))

    def set_search(self, query: str, num_results: int, results: List[Dict[str, Any]], **kwargs) -> None:
        h = self.search_hash(query, num_results, **kwargs)
        _cache_set(self._r, self._keys.scout_search(h), results, self._search_ttl)

    def add_session_url(self, session_id: str, url: str) -> None:
        if not session_id or not url:
            return
        norm = RedisKeySpace.normalize_url(url)
        if norm:
            self._r.sadd(self._keys.scout_session_urls(session_id), norm)

    def is_session_url_seen(self, session_id: str, url: str) -> bool:
        if not session_id or not url:
            return False
        norm = RedisKeySpace.normalize_url(url)
        return bool(self._r.sismember(self._keys.scout_session_urls(session_id), norm))


class RedisBatchCheckpoint:
    """批跑断点：HASH 存 payload 字段，SET 存已完成任务 id。"""

    def __init__(self, client, keys: RedisKeySpace, batch_id: str):
        self._r = client
        self._keys = keys
        self._batch_id = batch_id
        self._ckpt_key = keys.batch_checkpoint(batch_id)
        self._done_key = keys.batch_done(batch_id)

    def load(self) -> Dict[str, Any]:
        data = self._r.hgetall(self._ckpt_key) or {}
        if not data:
            return {}
        out: Dict[str, Any] = {}
        for k, v in data.items():
            if k in ("done_ids", "results"):
                out[k] = _json_loads(v) or ([] if k == "done_ids" else [])
            else:
                out[k] = v
        if "done_ids" not in out:
            members = self._r.smembers(self._done_key) or set()
            out["done_ids"] = sorted(int(x) for x in members if str(x).isdigit())
        return out

    def save(self, payload: Dict[str, Any]) -> None:
        mapping: Dict[str, str] = {}
        for k, v in payload.items():
            if k == "done_ids":
                if v:
                    self._r.delete(self._done_key)
                    self._r.sadd(self._done_key, *[str(x) for x in v])
                continue
            if k == "results":
                mapping[k] = _json_dumps(v)
            else:
                mapping[k] = str(v) if not isinstance(v, str) else v
        if mapping:
            self._r.hset(self._ckpt_key, mapping=mapping)

    def mark_done(self, task_id: int) -> None:
        self._r.sadd(self._done_key, str(task_id))


def get_persistent_read_cache() -> Optional[RedisPersistentReadCache]:
    global _persistent_cache
    if _persistent_cache is not None:
        return _persistent_cache
    client, keys = get_redis_client_and_keys()
    if not client:
        return None
    _persistent_cache = RedisPersistentReadCache(client, keys)
    return _persistent_cache


def get_blacklist_cache() -> Optional[RedisBlacklistCache]:
    global _blacklist_cache
    if _blacklist_cache is not None:
        return _blacklist_cache
    client, keys = get_redis_client_and_keys()
    if not client:
        return None
    _blacklist_cache = RedisBlacklistCache(client, keys)
    return _blacklist_cache


def get_scout_search_cache() -> Optional[RedisScoutSearchCache]:
    global _scout_cache
    if _scout_cache is not None:
        return _scout_cache
    client, keys = get_redis_client_and_keys()
    if not client:
        return None
    _scout_cache = RedisScoutSearchCache(client, keys)
    return _scout_cache


def get_batch_checkpoint(batch_id: str) -> Optional[RedisBatchCheckpoint]:
    client, keys = get_redis_client_and_keys()
    if not client or not batch_id:
        return None
    return RedisBatchCheckpoint(client, keys, batch_id)


class RedisPipelineCheckpoint:
    """单条 main_workflow 流水线断点（JSON STRING）。"""

    def __init__(self, client, keys: RedisKeySpace, run_key: str):
        self._r = client
        self._key = keys.pipeline_checkpoint(run_key)
        self._ttl = _cache_ttl("MA4CD_PIPELINE_CHECKPOINT_TTL", 604800)

    def load(self) -> Dict[str, Any]:
        return _json_loads(self._r.get(self._key)) or {}

    def save(self, payload: Dict[str, Any]) -> None:
        if self._ttl > 0:
            self._r.setex(self._key, self._ttl, _json_dumps(payload))
        else:
            self._r.set(self._key, _json_dumps(payload))

    def clear(self) -> None:
        self._r.delete(self._key)


def get_pipeline_checkpoint(run_key: str) -> Optional[RedisPipelineCheckpoint]:
    client, keys = get_redis_client_and_keys()
    if not client or not run_key:
        return None
    return RedisPipelineCheckpoint(client, keys, run_key)
