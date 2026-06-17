"""Session 协作层：事件总线 + 任务黑板测试。"""
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
from utils.session_collab import (
    MissionBoard,
    SessionEventBus,
    build_curator_supplement_task,
    get_session_collab,
    session_collab_enabled,
)


def _setup_redis():
    os.environ["MA4CD_MEMORY_BACKEND"] = "redis"
    os.environ["MA4CD_SESSION_COLLAB"] = "1"
    client = fakeredis.FakeRedis(decode_responses=True)
    bundle = create_redis_backend_from_client(client, prefix="ma4cd", env=f"collab-{uuid.uuid4().hex[:6]}")
    mf._redis_bundle = bundle
    ra._aux_enabled = None
    ra._persistent_cache = None
    return client, bundle.keys


def test_event_bus_and_board_redis():
    client, keys = _setup_redis()
    sid = f"sess-{uuid.uuid4().hex[:8]}"
    bus = SessionEventBus(sid, client, keys)
    board = MissionBoard(sid, client, keys)

    bus.publish("commander.plan_done", {"core_intent": "protein"}, agent="commander")
    board.update(intent="protein", phase="commander_done")
    board.append_scout_urls(["https://rcsb.org", "https://uniprot.org"], source="initial_scout")

    events = bus.recent(10)
    assert any(e.get("type") == "commander.plan_done" for e in events)

    data = board.get()
    assert data.get("intent") == "protein"
    assert "https://rcsb.org" in (data.get("scout_urls") or [])


def test_get_session_collab_factory():
    _setup_redis()
    bus, board = get_session_collab("factory-sess")
    board.update(intent="test")
    assert board.get().get("intent") == "test"
    bus.publish("pipeline.session_started", {})
    assert len(bus.recent(5)) >= 1


def test_build_curator_supplement_task():
    text = build_curator_supplement_task(
        "寻找蛋白质数据",
        ["缺少欧洲蛋白质门户", "缺少PDB元数据"],
        "补搜数据库入口",
    )
    assert "Curator" in text
    assert "欧洲蛋白质门户" in text


def test_file_fallback_board():
    os.environ.pop("MA4CD_MEMORY_BACKEND", None)
    ra._aux_enabled = None
    mf._redis_bundle = None
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["MA4CD_SESSION_COLLAB_DIR"] = tmp
        os.environ["MA4CD_SESSION_COLLAB"] = "1"
        board = MissionBoard("file-sess", None, None)
        board.update(intent="file-mode")
        assert board.get().get("intent") == "file-mode"


def test_collab_and_learning_events_use_separate_keys():
    """协作 Stream 与 Miner 学习 LIST 不得共用同一 Redis key。"""
    client, keys = _setup_redis()
    sid = f"sess-{uuid.uuid4().hex[:8]}"
    bus = SessionEventBus(sid, client, keys)
    bus.publish("miner.round_done", {"assets": 3}, agent="miner")

    learning_key = keys.session_learning_events(sid)
    collab_key = keys.session_collab_events(sid)
    assert learning_key != collab_key
    assert client.type(collab_key) == "stream"
    assert client.type(learning_key) in ("none", "list")

    bundle = mf.get_memory_backend()
    bundle.session.create_session(sid, {"task_intent": "test"})
    bundle.session.record_extraction(
        sid,
        domain="rcsb.org",
        url="https://www.rcsb.org",
        site_profile={"site_name": "rcsb"},
        strategy_used={},
        success=True,
        l3_candidates=[{"url": "https://www.rcsb.org/data"}],
        execution_time=1.0,
    )
    assert client.type(learning_key) == "list"
    assert client.llen(learning_key) == 1
    assert client.type(collab_key) == "stream"


def run_all():
    assert session_collab_enabled() is True
    test_event_bus_and_board_redis()
    test_collab_and_learning_events_use_separate_keys()
    test_get_session_collab_factory()
    test_build_curator_supplement_task()
    test_file_fallback_board()
    print("session collab tests: all passed")


if __name__ == "__main__":
    run_all()
