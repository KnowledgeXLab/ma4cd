"""
Redis 记忆后端集成测试（fakeredis，无需真实 Redis 服务）。

运行：
    python -m tests.memory.test_redis_backend_integration
    # 或
    python -c "from tests.memory.test_redis_backend_integration import run_all; run_all()"
"""
from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import MagicMock

# 确保项目根在 path
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import fakeredis

from agents.miner.memory.backends.redis_backend import (
    RedisKeySpace,
    create_redis_backend_from_client,
)
from agents.miner.memory.backends.session_archiver import archive_session
from agents.miner.memory.managers.memory_manager import UnifiedMemoryManager
from agents.miner.memory.storage.working_memory import WorkingMemory
from agents.miner.state.miner_state import MinerState


def _fresh_backend(env_suffix: str | None = None):
    """每个用例独立 namespace，避免 key 污染。"""
    suffix = env_suffix or uuid.uuid4().hex[:8]
    client = fakeredis.FakeRedis(decode_responses=True)
    return create_redis_backend_from_client(
        client,
        prefix="ma4cd",
        env=f"it-{suffix}",
        working_ttl=3600,
        archive_ttl=86400,
    )


def test_coordination_cross_worker_dedup():
    bundle = _fresh_backend("coord")
    coord = bundle.coordination
    sid = "session-coord-1"
    url = "https://data.example.com/page"

    state_a = MinerState(coordination=coord, session_id=sid)
    state_b = MinerState(coordination=coord, session_id=sid)

    assert state_a.acquire_processing_lock(url) is True
    assert state_b.acquire_processing_lock(url) is False

    state_a.release_processing_lock(url, success=True)
    assert state_a.acquire_processing_lock(url) is False
    assert state_b.acquire_processing_lock(url) is False

    coord.reset_batch(sid)
    assert state_a.acquire_processing_lock(url) is True


def test_session_record_and_export():
    bundle = _fresh_backend("session")
    session = bundle.session
    sid = "session-rec-1"

    session.create_session(sid, {"task_intent": "integration test"})
    ok = session.record_extraction(
        sid,
        domain="example.com",
        url="https://example.com/data",
        site_profile={"type": "portal"},
        strategy_used={"approach": "dfs"},
        success=True,
        l3_candidates=[{"url": "https://example.com/db", "title": "DB"}],
        execution_time=0.5,
    )
    assert ok is True

    exported = session.export_session(sid)
    assert exported is not None
    assert exported["total_extractions"] == 1
    assert exported["successful_extractions"] == 1
    assert len(exported["learning_events"]) == 1
    assert "example.com" in exported["domains_processed"]


def test_working_trajectory_and_loop_detection():
    bundle = _fresh_backend("working")
    sid = "session-wm-1"
    wm = WorkingMemory(backend=bundle.working)
    wm.bind_session(sid)

    assert wm.check_url_status("https://example.com/a") is None
    wm.record_step("https://example.com/a", "DROP_IRRELEVANT", 1, "noise")
    wm.record_step("https://example.com/b", "DROP", 2, "noise")
    wm.record_step("https://example.com/c", "DROP_IRRELEVANT", 3, "noise")

    assert wm.check_url_status("https://example.com/a") == "DROP_IRRELEVANT"
    assert wm.is_looping(drop_threshold=3) is True

    ctx = wm.get_recent_trajectory_context(steps=2)
    assert "example.com/b" in ctx or "example.com/c" in ctx

    bundle.working.reset_session(sid)
    assert wm.check_url_status("https://example.com/a") is None


def test_unified_memory_manager_redis_lifecycle(monkeypatch=None):
    """模拟 MA4CD_MEMORY_BACKEND=redis 的 UMM 全链路。"""
    bundle = _fresh_backend("umm")

    # 注入 bundle，绕过 env 读取
    mm = UnifiedMemoryManager()
    mm._bundle = bundle
    mm._working_memory = bundle.working
    mm._session_memory = bundle.session

    sid = mm.start_session({"task_intent": "redis umm test"}, session_id="umm-sess-1")
    assert sid == "umm-sess-1"
    assert mm.coordination.get_active_session_id() == sid

    mm.record_extraction(
        sid,
        "nasa.gov",
        "https://data.nasa.gov/",
        {},
        {},
        True,
        [{"url": "https://data.nasa.gov/dataset/1"}],
        1.1,
    )

    persistent = MagicMock()
    persistent.save_session_snapshot.return_value = True
    mm._persistent_memory = persistent

    mm.end_session(sid)
    persistent.save_session_snapshot.assert_called_once()
    assert mm.active_session_id is None

    exported = bundle.session.export_session(sid)
    assert exported is not None
    assert exported["total_extractions"] >= 1


def test_archive_from_redis_session():
    bundle = _fresh_backend("archive")
    sid = "archive-sess-1"
    bundle.session.create_session(sid, {"task": "archive"})
    bundle.session.record_extraction(
        sid, "ex.com", "https://ex.com", {}, {}, False, [], 0.1, error_message="timeout"
    )

    persistent = MagicMock()
    persistent.save_session_snapshot.return_value = True
    ok = archive_session(sid, bundle.session, persistent, bundle=bundle)
    assert ok is True
    payload = persistent.save_session_snapshot.call_args[0][2]
    assert payload["backend"] == "redis"
    assert payload["total_extractions"] == 1


def run_all():
    test_coordination_cross_worker_dedup()
    test_session_record_and_export()
    test_working_trajectory_and_loop_detection()
    test_unified_memory_manager_redis_lifecycle()
    test_archive_from_redis_session()
    print("redis backend integration tests: all passed")


if __name__ == "__main__":
    run_all()
