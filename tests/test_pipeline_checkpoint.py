"""Pipeline checkpoint 单元测试（fakeredis）。"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import fakeredis

from agents.miner.memory.backends.redis_backend import create_redis_backend_from_client
import agents.miner.memory.backends.factory as mf
import agents.miner.memory.backends.redis_aux as ra
from utils.pipeline_checkpoint import (
    PHASE_COMMANDER_DONE,
    PHASE_COMPLETED,
    PHASE_SCOUT_DONE,
    PipelineCheckpointStore,
    is_resumable_checkpoint,
    new_checkpoint_payload,
    pipeline_run_key,
    use_redis_pipeline_checkpoint,
)


def _setup():
    os.environ["MA4CD_MEMORY_BACKEND"] = "redis"
    os.environ["MA4CD_REDIS_AUX"] = "1"
    os.environ["MA4CD_PIPELINE_CHECKPOINT"] = "1"
    os.environ["MA4CD_PIPELINE_CHECKPOINT_BACKEND"] = "redis"
    client = fakeredis.FakeRedis(decode_responses=True)
    bundle = create_redis_backend_from_client(client, prefix="ma4cd", env=f"pipe-{uuid.uuid4().hex[:6]}")
    mf._redis_bundle = bundle
    ra._aux_enabled = None
    ra._persistent_cache = None
    ra._blacklist_cache = None
    ra._scout_cache = None
    return client


def test_pipeline_run_key_stable():
    assert pipeline_run_key("寻找蛋白质") == pipeline_run_key("寻找蛋白质")
    assert pipeline_run_key("a") != pipeline_run_key("b")


def test_pipeline_checkpoint_redis_roundtrip():
    _setup()
    assert use_redis_pipeline_checkpoint() is True
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["MA4CD_PIPELINE_CHECKPOINT_DIR"] = tmp
        req = "寻找蛋白质研究数据"
        store = PipelineCheckpointStore(req, reports_root=tmp)
        payload = new_checkpoint_payload(
            req, "sess-abc", "run-1",
            phase=PHASE_SCOUT_DONE,
            artifacts={"scout_urls": ["https://rcsb.org"], "commander_result": {"task_config": {}}},
        )
        store.save(payload)
        loaded = store.load()
        assert is_resumable_checkpoint(loaded, req)
        assert loaded["phase"] == PHASE_SCOUT_DONE
        assert loaded["artifacts"]["scout_urls"] == ["https://rcsb.org"]

        store.clear()
        assert store.load() == {}


def test_completed_not_resumable():
    req = "task-x"
    payload = new_checkpoint_payload(req, "s1", "r1", phase=PHASE_COMPLETED)
    assert is_resumable_checkpoint(payload, req) is False


def test_phase_skip_logic():
    req = "demo task"
    art = {"commander_result": {"task_config": {"search_queries": []}}}
    ck = new_checkpoint_payload(req, "sid", "rid", phase=PHASE_COMMANDER_DONE, artifacts=art)
    assert is_resumable_checkpoint(ck, req)
    assert ck["phase"] == PHASE_COMMANDER_DONE


def run_all():
    test_pipeline_run_key_stable()
    test_pipeline_checkpoint_redis_roundtrip()
    test_completed_not_resumable()
    test_phase_skip_logic()
    print("pipeline checkpoint tests: all passed")


if __name__ == "__main__":
    run_all()
