import unittest

from utils.skill_loader import (
    get_miner_evolve_domain_patterns,
    list_skills,
    load_commander_task,
    load_curator_chain_model,
    load_curator_supplement,
    load_inspector_fallback_audit,
    load_miner_prompts,
    load_miner_signals,
    load_rejection_buckets,
    load_report_taxonomy,
    load_runtime_profile,
    load_scout_search,
    load_search_discovery,
    load_inspector_audit,
    load_inspector_quality_gates,
    load_miner_heuristics,
    set_active_skill,
)


class TestSkillLoader(unittest.TestCase):
    def setUp(self):
        set_active_skill(None)

    def tearDown(self):
        set_active_skill(None)

    def test_list_skills_includes_protein(self):
        skills = list_skills()
        self.assertIn("protein-research", skills)
        self.assertIn("genomics-research", skills)
        self.assertNotIn("_template", skills)

    def test_load_protein_inspector_rules(self):
        set_active_skill("protein-research")
        rules = load_inspector_quality_gates()
        self.assertIn("uniprot", rules.get("container_signal_tokens", []))
        self.assertIn("www.uniprot.org", rules.get("trusted_data_domains", []))
        self.assertIn("protein", rules.get("domain_lexicon", {}))

    def test_load_protein_miner_domains(self):
        set_active_skill("protein-research")
        trusted, noise = get_miner_evolve_domain_patterns()
        self.assertTrue(any("uniprot" in p for p in (trusted or [])))
        self.assertTrue(any("youtube" in p for p in (noise or [])))

    def test_load_protein_miner_heuristics(self):
        set_active_skill("protein-research")
        rules = load_miner_heuristics()
        self.assertIn("/news", rules.get("invalid_path_suffixes", []))
        self.assertEqual(rules.get("evolve_gates", {}).get("positive_evolve_min_assets"), 12)

    def test_load_protein_commander_and_audit(self):
        set_active_skill("protein-research")
        cmd = load_commander_task()
        audit = load_inspector_audit()
        self.assertIn("planning_guidance", cmd)
        self.assertIn("gate_thresholds", audit)

    def test_load_protein_new_skill_packs(self):
        set_active_skill("protein-research")
        scout = load_scout_search()
        miner = load_miner_signals()
        curator = load_curator_chain_model()
        runtime = load_runtime_profile()
        self.assertIn("site_preferences", scout)
        self.assertIn("domain_keywords", miner)
        self.assertIn("data_chain_dimensions", curator)
        self.assertIn("env_defaults", runtime)

    def test_load_protein_p0_skill_packs(self):
        set_active_skill("protein-research")
        buckets = load_rejection_buckets()
        fallback = load_inspector_fallback_audit()
        prompts = load_miner_prompts()
        self.assertIn("bucket_rules", buckets)
        self.assertIn("protein", fallback.get("positive_signals", []))
        self.assertIn("structure_append", prompts)

    def test_load_protein_search_and_taxonomy(self):
        set_active_skill("protein-research")
        search = load_search_discovery()
        taxonomy = load_report_taxonomy()
        self.assertIn("uniprot.org", search.get("authoritative_sites", []))
        self.assertIn("dimensions", taxonomy)
        self.assertIn("生物信息学与蛋白质组学", taxonomy.get("dimensions", {}).get("domain", {}).get("options", []))

    def test_load_curator_supplement(self):
        set_active_skill("protein-research")
        sup = load_curator_supplement()
        self.assertIn("uniprot.org", sup.get("priority_sites", []))
        self.assertTrue(sup.get("gap_query_seeds"))

    def test_no_skill_returns_empty_rules(self):
        self.assertEqual(load_inspector_quality_gates(), {})
        trusted, noise = get_miner_evolve_domain_patterns()
        self.assertIsNone(trusted)
        self.assertIsNone(noise)


if __name__ == "__main__":
    unittest.main()
