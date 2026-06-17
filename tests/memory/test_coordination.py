"""Coordination 与 Session 归档单元测试（无需真实 Redis）。"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from agents.miner.memory.backends.session_archiver import archive_session
from agents.miner.memory.storage.session_memory import SessionMemoryStorage
from agents.miner.state.miner_state import MinerState


class _MockCoordination:
    def __init__(self):
        self.visited: set[str] = set()
        self.processing: set[str] = set()
        self.domain_fails: dict[str, int] = {}
        self.url_retries: dict[str, int] = {}
        self.reset_calls: list[str] = []

    @staticmethod
    def _norm(url: str) -> str:
        return url.split("#")[0].rstrip("/")

    def is_visited(self, session_id: str, url: str) -> bool:
        return self._norm(url) in self.visited

    def try_acquire_processing(self, session_id: str, url: str, ttl_seconds: int = 600) -> bool:
        norm = self._norm(url)
        if norm in self.visited or norm in self.processing:
            return False
        self.processing.add(norm)
        return True

    def release_processing(self, session_id: str, url: str) -> None:
        self.processing.discard(self._norm(url))

    def mark_visited(self, session_id: str, url: str) -> bool:
        norm = self._norm(url)
        if norm in self.visited:
            return False
        self.visited.add(norm)
        return True

    def incr_domain_fail(self, session_id: str, domain: str) -> int:
        self.domain_fails[domain] = self.domain_fails.get(domain, 0) + 1
        return self.domain_fails[domain]

    def get_domain_fail(self, session_id: str, domain: str) -> int:
        return self.domain_fails.get(domain, 0)

    def incr_url_retry(self, session_id: str, url: str) -> int:
        norm = self._norm(url)
        self.url_retries[norm] = self.url_retries.get(norm, 0) + 1
        return self.url_retries[norm]

    def get_url_retry(self, session_id: str, url: str) -> int:
        return self.url_retries.get(self._norm(url), 0)

    def reset_batch(self, session_id: str) -> None:
        self.reset_calls.append(session_id)
        self.visited.clear()
        self.processing.clear()
        self.domain_fails.clear()
        self.url_retries.clear()


def test_miner_state_coordination_dedup_across_workers():
    coord = _MockCoordination()
    state_a = MinerState(coordination=coord, session_id="sess-1")
    state_b = MinerState(coordination=coord, session_id="sess-1")
    url = "https://example.com/data"

    assert state_a.acquire_processing_lock(url) is True
    assert state_b.acquire_processing_lock(url) is False

    state_a.release_processing_lock(url, success=True)
    assert state_a.acquire_processing_lock(url) is False


def test_miner_state_domain_fail_via_coordination():
    coord = _MockCoordination()
    state = MinerState(coordination=coord, session_id="sess-1", MAX_DOMAIN_FAILS=2)

    state.record_domain_failure("example.com")
    assert state.is_domain_banned("example.com") is False
    state.record_domain_failure("example.com")
    assert state.is_domain_banned("example.com") is True


def test_session_export_and_archive_to_sqlite():
    with tempfile.TemporaryDirectory() as tmp:
        storage = SessionMemoryStorage(storage_dir=str(Path(tmp) / "sessions"))
        session_id = "test-session-001"
        storage.create_session(session_id, {"task_intent": "unit test"})
        storage.record_extraction(
            session_id,
            domain="example.com",
            url="https://example.com",
            site_profile={},
            strategy_used={},
            success=True,
            l3_candidates=[{"url": "https://example.com/db", "title": "DB"}],
            execution_time=1.2,
        )

        exported = storage.export_session(session_id)
        assert exported is not None
        assert exported["total_extractions"] == 1
        assert len(exported["learning_events"]) == 1

        persistent = MagicMock()
        persistent.save_session_snapshot.return_value = True

        ok = archive_session(session_id, storage, persistent, bundle=None)
        assert ok is True
        persistent.save_session_snapshot.assert_called_once()
        args = persistent.save_session_snapshot.call_args[0]
        assert args[0] == session_id
        assert args[1] == "__session__"
        payload = args[2]
        assert payload["session_id"] == session_id
        assert payload["backend"] == "file"
