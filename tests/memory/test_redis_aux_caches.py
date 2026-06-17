"""Redis 辅助缓存层集成测试（fakeredis）。"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import fakeredis

from agents.miner.memory.backends.redis_backend import create_redis_backend_from_client
from agents.miner.memory.backends.redis_aux import (
    RedisBatchCheckpoint,
    RedisBlacklistCache,
    RedisPersistentReadCache,
    RedisScoutSearchCache,
    _MISS,
    get_persistent_read_cache,
)
import agents.miner.memory.backends.factory as mf
import agents.miner.memory.backends.redis_aux as ra
from agents.miner.memory.storage.persistent_memory import PersistentMemoryStorage
from utils.batch_checkpoint import BatchCheckpointStore, use_redis_checkpoint


def _setup_redis_env(env_suffix: str):
    os.environ["MA4CD_MEMORY_BACKEND"] = "redis"
    os.environ["MA4CD_REDIS_AUX"] = "1"
    client = fakeredis.FakeRedis(decode_responses=True)
    bundle = create_redis_backend_from_client(client, prefix="ma4cd", env=f"aux-{env_suffix}")
    mf._redis_bundle = bundle
    ra._aux_enabled = None
    ra._persistent_cache = None
    ra._blacklist_cache = None
    ra._scout_cache = None
    return client, bundle.keys


def test_persistent_read_cache_roundtrip():
    client, keys = _setup_redis_env(uuid.uuid4().hex[:6])
    cache = RedisPersistentReadCache(client, keys)
    strategy = {"config": {"depth": 2}, "version": 1, "score": 0.9}
    cache.set_strategy("nasa.gov", "best", strategy)
    assert cache.get_strategy("nasa.gov", "best") == strategy
    cache.invalidate_domain("nasa.gov")
    assert cache.get_strategy("nasa.gov", "best") is _MISS


def test_persistent_memory_uses_redis_cache():
    client, keys = _setup_redis_env(uuid.uuid4().hex[:6])
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "pm.db")
        pm = PersistentMemoryStorage(db_path=db)
        pm.store_strategy_evolution("example.com", {"a": 1}, 0.8)
        first = pm.get_best_strategy("example.com")
        assert first and first["score"] == 0.8
        cache = get_persistent_read_cache()
        assert cache is not None
        hit = cache.get_strategy("example.com", "best")
        assert hit is not _MISS and hit["score"] == 0.8


def test_blacklist_cache():
    client, keys = _setup_redis_env(uuid.uuid4().hex[:6])
    bl = RedisBlacklistCache(client, keys)
    url = "https://spam.example.com/page#frag"
    assert bl.is_blacklisted(url) is None
    bl.mark_blacklisted(url, "noise")
    assert bl.is_blacklisted(url) is True


def test_scout_search_cache():
    client, keys = _setup_redis_env(uuid.uuid4().hex[:6])
    sc = RedisScoutSearchCache(client, keys)
    results = [{"url": "https://rcsb.org", "source": "tavily"}]
    sc.set_search("protein pdb", 5, results, tavily_only=True)
    hit = sc.get_search("protein pdb", 5, tavily_only=True)
    assert hit == results
    sc.add_session_url("sess-1", "https://rcsb.org/")
    assert sc.is_session_url_seen("sess-1", "https://rcsb.org#x") is True


def test_batch_checkpoint_store():
    client, keys = _setup_redis_env(uuid.uuid4().hex[:6])
    batch_id = f"test-batch-{uuid.uuid4().hex[:6]}"
    ck = RedisBatchCheckpoint(client, keys, batch_id)
    payload = {"run_id": "r1", "done_ids": [1, 2], "results": [{"idx": 1}]}
    ck.save(payload)
    loaded = ck.load()
    assert loaded.get("results") == [{"idx": 1}]
    assert 1 in loaded.get("done_ids", []) or "1" in str(loaded.get("done_ids"))

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "checkpoint.json")
        store = BatchCheckpointStore(batch_id, path)
        assert use_redis_checkpoint() is True
        store.save(payload)
        assert store.load().get("run_id") == "r1"
        assert os.path.exists(path)


def run_all():
    test_persistent_read_cache_roundtrip()
    test_persistent_memory_uses_redis_cache()
    test_blacklist_cache()
    test_scout_search_cache()
    test_batch_checkpoint_store()
    print("redis aux cache tests: all passed")


if __name__ == "__main__":
    run_all()
