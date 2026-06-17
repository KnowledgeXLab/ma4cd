"""飞轮细粒度续挖/续审单元测试。"""
from __future__ import annotations

import asyncio
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils.pipeline_checkpoint import (
    CHECKPOINT_VERSION,
    ROUND_STEP_INSPECTOR,
    ROUND_STEP_MINER,
    new_checkpoint_payload,
)


class _FakeCoord:
    def __init__(self):
        self.visited = set()

    def reset_batch(self, _sid):
        self.visited.clear()

    def is_visited(self, _sid, url):
        return url in self.visited

    def mark_visited(self, _sid, url):
        self.visited.add(url)
        return True

    def try_acquire_processing(self, _sid, url, ttl_seconds=600):
        return True

    def release_processing(self, _sid, url):
        pass

    def incr_domain_fail(self, _sid, domain):
        return 0

    def get_domain_fail(self, _sid, domain):
        return 0

    def incr_url_retry(self, _sid, url):
        return 0

    def get_url_retry(self, _sid, url):
        return 0


async def test_miner_resume_skips_completed_urls():
    from agents.miner.agent import UniversalMinerAgent

    miner = UniversalMinerAgent.__new__(UniversalMinerAgent)
    miner.memory_manager = type("M", (), {"coordination": _FakeCoord()})()
    miner._active_batch_session_id = "sess-1"
    miner.shared_visited_urls = set()
    miner.shared_processing_urls = set()
    miner.shared_domain_fail_counts = {}
    miner.shared_url_retry_counts = {}
    miner.working_memory = None
    miner.batch_stats = {}
    miner._evolve_last_ts_global = 0.0
    miner._evolve_last_ts_by_domain = {}
    miner._evolve_count_batch = 0
    miner._evolve_count_by_domain = {}
    miner.config = {}
    miner.runtime_instruction = ""
    miner._owns_session_lifecycle = False
    miner.evolution_engine = type("E", (), {"current_config": {}})()
    miner.report_node = type("R", (), {"generate": lambda *a, **k: "r.md"})()

    calls = []

    async def _fake_pipeline(url):
        calls.append(url)
        return [{"url": url, "title": "t"}]

    miner._run_single_url_pipeline = _fake_pipeline
    miner._bind_batch_session = lambda sid: None

    coord = miner.memory_manager.coordination
    coord.mark_visited("sess-1", "https://done.example.com")

    progress = []

    async def on_url(url, assets):
        progress.append(url)

    result = await miner.mine_urls(
        ["https://done.example.com", "https://pending.example.com"],
        session_id="sess-1",
        resume_batch=True,
        on_url_complete=on_url,
    )

    assert calls == ["https://pending.example.com"]
    assert len(result) == 1
    assert progress == ["https://pending.example.com"]


async def test_inspector_resume_skips_done_urls():
    from agents.inspector.agent import InspectorAgent

    agent = InspectorAgent.__new__(InspectorAgent)
    agent.state = None
    agent.global_deduplicator = None
    agent.memory = type("M", (), {"consult_past_experience": lambda self, u: None, "memorize_audit_result": lambda *a, **k: None})()
    agent.evolution_engine = type("E", (), {
        "get_runtime_config": lambda self, ctx: {"batch_size": 50},
        "evolve": lambda *a, **k: {},
        "generation": 1,
    })()
    agent.dna_config = {}
    agent._build_miner_supervision_payload = lambda **k: []
    agent._flatten_artifacts = lambda items: items
    agent._clean_invalid_paths = lambda u: u

    invoked_batches = []

    class _FakeApp:
        async def ainvoke(self, state):
            invoked_batches.append(len(state["miner_output"]["l3_candidates"]))
            item = state["miner_output"]["l3_candidates"][0]
            return {
                "audited_results": [item],
                "rejected_items": [],
                "statistics": state["statistics"],
            }

    agent.app = _FakeApp()

    artifacts = [
        {"url": "https://a.example.com"},
        {"url": "https://b.example.com"},
    ]
    progress_calls = []

    async def on_progress(done, passed, rejected):
        progress_calls.append(list(done))

    result = await agent.process(
        artifacts,
        user_query={"human_request": "test"},
        session_id="s1",
        resume_state={
            "done_urls": ["https://a.example.com"],
            "passed": [{"url": "https://a.example.com", "status": "PASS"}],
            "rejected": [],
        },
        on_progress=on_progress,
    )

    assert len(result) == 2
    assert invoked_batches == [1]
    assert "https://b.example.com" in progress_calls[-1]


def test_checkpoint_v2_round_step_fields():
    payload = new_checkpoint_payload(
        "task", "sid", "rid", phase="flywheel", round_counter=1,
        artifacts={
            "round_step": ROUND_STEP_MINER,
            "round_urls": ["https://x.com"],
            "round_miner_done_urls": ["https://x.com"],
        },
    )
    assert payload["version"] == CHECKPOINT_VERSION
    assert payload["artifacts"]["round_step"] == ROUND_STEP_MINER


def run_all():
    asyncio.run(test_miner_resume_skips_completed_urls())
    asyncio.run(test_inspector_resume_skips_done_urls())
    test_checkpoint_v2_round_step_fields()
    print("flywheel granular resume tests: all passed")


if __name__ == "__main__":
    run_all()
