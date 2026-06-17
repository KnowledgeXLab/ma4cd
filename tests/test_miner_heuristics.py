import unittest

from agents.miner.nodes.extract_node import ExtractNode
from utils.miner_heuristics import (
    get_evolve_gates,
    get_invalid_path_suffixes,
    get_link_noise_re,
    reset_miner_heuristics_cache,
)
from utils.skill_loader import set_active_skill


class TestMinerHeuristics(unittest.TestCase):
    def setUp(self):
        set_active_skill(None)
        reset_miner_heuristics_cache()

    def tearDown(self):
        set_active_skill(None)
        reset_miner_heuristics_cache()

    def test_builtin_invalid_suffixes(self):
        suffixes = get_invalid_path_suffixes()
        self.assertIn("/about", suffixes)
        self.assertIn("/login", suffixes)

    def test_protein_skill_filters_youtube_links(self):
        set_active_skill("protein-research")
        reset_miner_heuristics_cache()
        node = ExtractNode()
        links = [
            {"url": "https://www.youtube.com/watch?v=abc", "text": "video"},
            {"url": "https://www.uniprot.org/help/uniprotkb", "text": "help"},
        ]
        out = node._dynamic_heuristic_filter(links, {})
        urls = [x["url"] for x in out]
        self.assertNotIn("https://www.youtube.com/watch?v=abc", urls)
        self.assertIn("https://www.uniprot.org/help/uniprotkb", urls)

    def test_protein_skill_evolve_gates(self):
        set_active_skill("protein-research")
        reset_miner_heuristics_cache()
        gates = get_evolve_gates()
        self.assertEqual(gates["positive_evolve_min_assets"], 12)
        self.assertEqual(gates["min_recall_score_to_activate"], 0.42)

    def test_protein_skill_extra_invalid_suffixes(self):
        set_active_skill("protein-research")
        reset_miner_heuristics_cache()
        suffixes = get_invalid_path_suffixes()
        self.assertIn("/news", suffixes)
        self.assertIn("/press", suffixes)

    def test_link_noise_re_matches_news_path(self):
        set_active_skill("protein-research")
        reset_miner_heuristics_cache()
        pat = get_link_noise_re()
        self.assertTrue(pat.search("https://www.rutgers.edu/news/protein-data-bank"))


if __name__ == "__main__":
    unittest.main()
