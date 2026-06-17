import os
import unittest

from utils.runtime_profile import apply_env_defaults_non_overriding
from utils.skill_loader import set_active_skill
from utils.scout_skill import get_scout_prompt_append
from utils.curator_skill import (
    build_curator_gap_seed_urls,
    get_curator_max_rounds,
    get_curator_prompt_append,
)
from utils.miner_signals import negative_kw_re
from utils.miner_prompts import append_to_prompt, get_miner_prompt_append
from utils.rejection_buckets import bucket_rejection_reason, summarize_rejections
from utils.inspector_fallback_audit import compute_fallback_score, get_fallback_audit_config
from utils.search_discovery import authoritative_sites, build_l3_site_queries, default_search_type
from utils.curator_supplement import build_curator_supplement_task as skill_build_task, rank_priority_urls
from utils.search_discovery import build_authoritative_l2_queries
from utils.report_taxonomy import (
    build_taxonomy_codebook_text,
    enforce_host_hints_on_results,
    match_host_hints,
)


class TestNewSkillPacks(unittest.TestCase):
    def setUp(self):
        set_active_skill("protein-research")
        for k in (
            "MA4CD_INSPECTOR_STRICT",
            "MA4CD_INSPECTOR_MIN_SCORE",
            "MA4CD_MINER_CONCURRENCY",
            "MA4CD_LLM_BUDGET_MODE",
            "MA4CD_CURATOR_SCOUT_LOOP",
        ):
            os.environ.pop(k, None)

    def tearDown(self):
        set_active_skill(None)

    def test_scout_prompt_append_present(self):
        txt = get_scout_prompt_append()
        self.assertTrue(txt)
        self.assertIn("Protein Research", txt)

    def test_curator_prompt_append_present(self):
        txt = get_curator_prompt_append()
        self.assertTrue(txt)
        self.assertIn("蛋白质", txt)

    def test_runtime_profile_applies_non_overriding(self):
        applied = apply_env_defaults_non_overriding()
        self.assertIn("MA4CD_INSPECTOR_STRICT", applied)
        # won't override when already set
        os.environ["MA4CD_INSPECTOR_STRICT"] = "1"
        applied2 = apply_env_defaults_non_overriding()
        self.assertNotIn("MA4CD_INSPECTOR_STRICT", applied2)

    def test_miner_negative_kw_regex(self):
        r = negative_kw_re()
        self.assertTrue(r.search("https://example.com/careers/jobs"))

    def test_curator_fuse_max_rounds(self):
        self.assertEqual(get_curator_max_rounds(), 3)

    def test_curator_gap_seed_urls_from_gaps(self):
        gaps = [
            "缺乏蛋白质序列与注释数据库入口（如UniProt/Ensembl/InterPro/Pfam）",
            "缺乏蛋白质三维结构与预测资源（如PDB/AlphaFold/EMDB）",
        ]
        seeds = build_curator_gap_seed_urls(gaps, "UniProt download PDB FTP", set())
        self.assertTrue(any("uniprot.org" in u for u in seeds))
        self.assertTrue(any("rcsb.org" in u or "alphafold" in u for u in seeds))

    def test_runtime_profile_enables_curator_loop(self):
        applied = apply_env_defaults_non_overriding()
        self.assertEqual(applied.get("MA4CD_CURATOR_SCOUT_LOOP"), "1")

    def test_rejection_summarize_buckets(self):
        items = [
            {"url": "https://a", "reason": "规则拦截: noise", "title": "A"},
            {"url": "https://b", "reason": "规则拦截: gate", "title": "B"},
            {"url": "https://c", "reason": "分数低于阈值", "title": "C"},
        ]
        summary = summarize_rejections(items)
        self.assertEqual(summary["total_rejected"], 3)
        self.assertIn("rule_gate", summary["buckets"])
        self.assertEqual(summary["buckets"]["rule_gate"], 2)
        self.assertIn("规则/质量闸门", summary.get("bucket_labels", {}).values())

    def test_protein_fallback_audit_signals(self):
        cfg = get_fallback_audit_config()
        self.assertIn("uniprot", cfg.get("positive_signals", []))
        score, pos, mission, neg = compute_fallback_score(
            haystack="https://www.uniprot.org/downloads protein database",
            tokens=set(["uniprot", "downloads", "protein", "database"]),
            mission_text="寻找蛋白质研究数据",
            topology_score=0.8,
            is_binary=False,
        )
        self.assertGreater(score, 0.5)
        self.assertGreater(pos, 0)

    def test_miner_structure_prompt_append(self):
        txt = append_to_prompt("BASE", "structure_append")
        self.assertTrue(txt.startswith("BASE"))
        self.assertIn("Protein Research", get_miner_prompt_append("structure_append"))

    def test_search_discovery_protein_sites(self):
        sites = authoritative_sites()
        self.assertIn("uniprot.org", sites)
        self.assertEqual(default_search_type(), "authoritative")
        queries = build_l3_site_queries("protein", "uniprot.org")
        self.assertTrue(any("uniprot.org" in q for q in queries))

    def test_search_discovery_neutral_without_skill(self):
        set_active_skill(None)
        from utils.search_discovery import reset_search_discovery_cache
        reset_search_discovery_cache()
        self.assertEqual(authoritative_sites(), [])
        self.assertEqual(default_search_type(), "general")

    def test_genomics_skill_loads(self):
        set_active_skill("genomics-research")
        from utils.search_discovery import reset_search_discovery_cache
        from utils.skill_loader import load_commander_task, load_miner_signals
        reset_search_discovery_cache()
        self.assertIn("genome", load_miner_signals().get("domain_keywords", []))
        self.assertIn("ncbi.nlm.nih.gov", authoritative_sites())
        self.assertIn("基因组", load_commander_task().get("core_intent_template", ""))

    def test_report_taxonomy_host_hints(self):
        codebook = build_taxonomy_codebook_text()
        self.assertIn("生物信息学与蛋白质组学", codebook)
        hint = match_host_hints("https://www.rcsb.org/downloads")
        self.assertIsNotNone(hint)
        self.assertEqual(hint.get("domain_dim"), "科学与智能")

    def test_report_enforce_host_hints(self):
        rows = enforce_host_hints_on_results([
            {"url": "https://www.uniprot.org/downloads", "domain_dim": "未知", "source_dim": "未知"},
        ])
        self.assertEqual(rows[0]["domain_dim"], "生物信息学与蛋白质组学")
        self.assertEqual(rows[0]["source_dim"], "研究机构")

    def test_curator_supplement_task_seeds(self):
        text = skill_build_task("寻找蛋白质数据", ["缺乏 UniProt 下载"], "补搜")
        self.assertIn("site:uniprot.org", text)
        ranked = rank_priority_urls([
            "https://example.com/x",
            "https://www.rcsb.org/downloads",
        ])
        self.assertTrue(ranked[0].startswith("https://www.rcsb.org"))

    def test_l2_authoritative_queries(self):
        qs = build_authoritative_l2_queries(["protein"], "example.com")
        self.assertTrue(any("uniprot.org" in q or "rcsb.org" in q for q in qs))


if __name__ == "__main__":
    unittest.main()

