import unittest

from agents.inspector.tools.quality_gates import (
    has_container_signal,
    mission_keywords,
    prefilter_item,
    reset_quality_gates_cache,
)
from utils.skill_loader import set_active_skill


class TestProteinSkillQualityGates(unittest.TestCase):
    def setUp(self):
        set_active_skill("protein-research")
        reset_quality_gates_cache()

    def tearDown(self):
        set_active_skill(None)
        reset_quality_gates_cache()

    def test_rejects_youtube(self):
        ok, reason = prefilter_item(
            {"url": "https://www.youtube.com/watch?v=abc", "title": "video"},
            user_query="寻找蛋白质研究数据",
        )
        self.assertFalse(ok)
        self.assertIn("噪声", reason)

    def test_allows_uniprot_with_mission(self):
        ok, _ = prefilter_item(
            {
                "url": "https://www.uniprot.org/help/uniprotkb",
                "title": "UniProtKB documentation",
            },
            user_query="寻找蛋白质研究数据",
        )
        self.assertTrue(ok)

    def test_mission_keywords_protein(self):
        kws = mission_keywords("寻找蛋白质研究数据")
        self.assertIn("protein", kws)
        self.assertIn("uniprot", kws)

    def test_container_signal_protein_token(self):
        self.assertTrue(
            has_container_signal("https://www.string-db.org/cgi/download", "STRING download")
        )


if __name__ == "__main__":
    unittest.main()
