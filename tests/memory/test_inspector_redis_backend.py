"""Inspector Redis 状态后端测试（fakeredis）。"""
from __future__ import annotations

import os
import sys
import uuid

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import fakeredis

from agents.miner.memory.backends.redis_backend import RedisKeySpace, create_redis_backend_from_client
from agents.inspector.backends.redis_backend import RedisInspectorState


def _state(env_suffix: str):
    client = fakeredis.FakeRedis(decode_responses=True)
    bundle = create_redis_backend_from_client(client, prefix="ma4cd", env=f"insp-{env_suffix}")
    return bundle.inspector_state(f"session-{env_suffix}")


def test_inspector_reports_global_and_remine_isolated_by_session():
    client = fakeredis.FakeRedis(decode_responses=True)
    env = f"insp-{uuid.uuid4().hex[:6]}"
    bundle = create_redis_backend_from_client(client, prefix="ma4cd", env=env)
    s1 = bundle.inspector_state("session-a")
    s2 = bundle.inspector_state("session-b")

    s1.update_state("https://example.com/a", {"status": "PASS", "metrics": {"ai_score": 0.9}})
    assert s1.get_cached_result("https://example.com/a")["status"] == "PASS"
    assert s2.get_cached_result("https://example.com/a")["status"] == "PASS"

    s1.add_to_remine_queue("https://l2.example.com/hub")
    s2.add_to_remine_queue("https://l2.other.com/hub")

    q1 = s1.get_and_clear_remine_queue()
    q2 = s2.get_and_clear_remine_queue()
    assert q1 == ["https://l2.example.com/hub"]
    assert q2 == ["https://l2.other.com/hub"]
    assert s1.get_and_clear_remine_queue() == []


def test_bind_session_switches_remine_namespace():
    client = fakeredis.FakeRedis(decode_responses=True)
    keys = RedisKeySpace(prefix="ma4cd", env=f"bind-{uuid.uuid4().hex[:6]}")
    state = RedisInspectorState(client, keys, session_id="old-session")
    state.add_to_remine_queue("https://l2.example.com/one")
    state.bind_session("new-session")
    state.add_to_remine_queue("https://l2.example.com/two")

    state.bind_session("old-session")
    old_q = state.get_and_clear_remine_queue()
    state.bind_session("new-session")
    new_q = state.get_and_clear_remine_queue()
    assert "https://l2.example.com/one" in old_q
    assert "https://l2.example.com/two" in new_q


def test_factory_redis_mode():
    os.environ["MA4CD_MEMORY_BACKEND"] = "redis"
    import agents.miner.memory.backends.factory as mf
    mf._redis_bundle = None
    from agents.inspector.backends.factory import get_inspector_state

    bundle_client = create_redis_backend_from_client(
        fakeredis.FakeRedis(decode_responses=True),
        prefix="ma4cd",
        env="factory-test",
    )
    mf._redis_bundle = bundle_client

    st = get_inspector_state("factory-sess-1")
    st.add_to_remine_queue("https://rcsb.org")
    assert st.get_summary()["PENDING_L2_MINES"] == 1


def run_all():
    test_inspector_reports_global_and_remine_isolated_by_session()
    test_bind_session_switches_remine_namespace()
    test_factory_redis_mode()
    print("inspector redis backend tests: all passed")


if __name__ == "__main__":
    run_all()
