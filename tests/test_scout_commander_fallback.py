"""Scout PlanningNode 失败时回退 Commander search_queries。"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils.prompt_contracts import scout_plan_from_commander_queries


def test_scout_plan_from_commander_queries_dedupes_and_limits():
    cfg = {
        "search_queries": [
            {"search_query": "protein structure database", "tier": "L3_Database"},
            {"query": "protein structure database"},
            "PDB download",
            "",
        ]
    }
    plan = scout_plan_from_commander_queries(cfg, max_queries=2)
    assert plan == ["protein structure database", "PDB download"]


def test_scout_agent_falls_back_when_planning_returns_empty():
    from agents.scout.agent import ScoutAgent

    commander_cfg = {
        "scout_config": {"results_per_query": 3},
        "search_queries": [
            {"search_query": "RCSB PDB protein", "tier": "L3_Database"},
            {"search_query": "UniProt proteomics", "tier": "L3_Database"},
        ],
    }
    captured: dict = {}

    def fake_search(plan, config=None):
        captured["plan"] = list(plan)
        return []

    scout = ScoutAgent()
    with patch.object(scout.planning_node, "run", return_value=[]):
        with patch.object(scout.search_node, "run_with_config", side_effect=fake_search):
            urls = scout.run("寻找蛋白质研究数据", config=commander_cfg)

    assert captured["plan"] == ["RCSB PDB protein", "UniProt proteomics"]
    assert urls == []


def test_scout_agent_skips_planning_when_llm_unavailable():
    from agents.scout.agent import ScoutAgent

    commander_cfg = {
        "search_queries": [{"search_query": "fallback only query"}],
    }
    captured: dict = {}

    scout = ScoutAgent()
    scout.llm = None
    with patch.object(scout.planning_node, "run") as mock_plan:
        with patch.object(scout.search_node, "run_with_config", side_effect=lambda p, **kw: captured.setdefault("plan", p) or []):
            scout.run("task", config=commander_cfg)
    mock_plan.assert_not_called()
    assert captured["plan"] == ["fallback only query"]


def run_all():
    test_scout_plan_from_commander_queries_dedupes_and_limits()
    test_scout_agent_falls_back_when_planning_returns_empty()
    test_scout_agent_skips_planning_when_llm_unavailable()
    print("scout commander fallback tests: all passed")


if __name__ == "__main__":
    run_all()
