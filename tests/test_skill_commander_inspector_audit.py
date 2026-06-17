import os
import unittest

from agents.inspector.prompts.inspector_prompt import InspectorPrompt
from agents.inspector.tools.quality_gates import (
    has_container_signal,
    post_llm_gate,
    prefilter_item,
    reset_quality_gates_cache,
)
from utils.commander_skill import apply_commander_skill_defaults, get_planning_guidance_block
from utils.inspector_audit import (
    get_audit_protocol_append,
    is_l3_trusted_host,
    reset_inspector_audit_cache,
    resolve_inspector_min_score,
    resolve_inspector_strict,
)
from utils.skill_loader import load_commander_task, load_inspector_audit, set_active_skill


class TestCommanderInspectorSkillRules(unittest.TestCase):
    def setUp(self):
        set_active_skill("protein-research")
        reset_quality_gates_cache()
        reset_inspector_audit_cache()
        for key in ("MA4CD_INSPECTOR_STRICT", "MA4CD_INSPECTOR_MIN_SCORE"):
            os.environ.pop(key, None)

    def tearDown(self):
        set_active_skill(None)
        reset_quality_gates_cache()
        reset_inspector_audit_cache()
        for key in ("MA4CD_INSPECTOR_STRICT", "MA4CD_INSPECTOR_MIN_SCORE"):
            os.environ.pop(key, None)

    def test_load_commander_task(self):
        rules = load_commander_task()
        self.assertIn("scout_config", rules)
        self.assertIn("seed_query_examples", rules)
        self.assertGreaterEqual(len(rules.get("seed_query_examples", [])), 3)

    def test_load_inspector_audit(self):
        rules = load_inspector_audit()
        self.assertIn("gate_thresholds", rules)
        self.assertIn("audit_protocol_append", rules)
        self.assertIn("uniprot", rules.get("audit_protocol_append", "").lower())

    def test_planning_guidance_block_nonempty(self):
        block = get_planning_guidance_block()
        self.assertIn("蛋白质", block)
        self.assertIn("UniProt", block)

    def test_apply_commander_skill_defaults_fills_sparse_plan(self):
        sparse = {"core_intent": "", "search_queries": [], "scout_config": {}, "scoring_rubric": {}}
        merged = apply_commander_skill_defaults(sparse, user_request="寻找蛋白质研究数据")
        self.assertTrue(merged.get("core_intent"))
        self.assertGreaterEqual(len(merged.get("search_queries", [])), 3)
        self.assertEqual(merged["scout_config"].get("task_type"), "database_and_archive")

    def test_inspector_skill_gate_defaults(self):
        self.assertFalse(resolve_inspector_strict())
        self.assertEqual(resolve_inspector_min_score(), 0.55)

    def test_trusted_download_path_passes_prefilter(self):
        ok, reason = prefilter_item(
            {"url": "https://www.uniprot.org/help/download", "title": "Downloads"},
            user_query="寻找蛋白质研究数据",
        )
        self.assertTrue(ok, reason)

    def test_l3_trusted_host_uniprot_download(self):
        self.assertTrue(is_l3_trusted_host("https://ftp.uniprot.org/pub/databases/uniprot"))
        self.assertTrue(has_container_signal("https://www.uniprot.org/help/download", "Downloads"))

    def test_post_llm_gate_relaxed_for_trusted_l3(self):
        ok, reason = post_llm_gate(
            {"url": "https://www.uniprot.org/help/download", "title": "Downloads"},
            suggested_level="L3",
            total_score=0.58,
            status="PASS",
            raw_report={
                "action": "KEEP",
                "is_valid": True,
                "evidence_signals": {"is_database_entry_link": False},
            },
            user_query="寻找蛋白质研究数据",
            min_confidence=0.6,
        )
        self.assertTrue(ok, reason)

    def test_audit_prompt_includes_skill_append(self):
        prompt = InspectorPrompt.get_audit_prompt(
            "https://www.uniprot.org/help/download",
            "Downloads",
            "bulk data",
            user_query="寻找蛋白质研究数据",
        )
        append = get_audit_protocol_append()
        self.assertIn(append, prompt)
        self.assertIn("PROTEIN RESEARCH DATA", prompt)


if __name__ == "__main__":
    unittest.main()
