import unittest

from agents.inspector.tools.quality_gates import (
    has_container_signal,
    mission_keywords,
    post_llm_gate,
    prefilter_item,
    task_alignment_score,
)


class TestQualityGates(unittest.TestCase):
    def test_rejects_github_topics(self):
        ok, _ = prefilter_item(
            {"url": "https://github.com/topics/electronic-warfare", "title": "topics"},
            user_query="搜索现代战争中电子战的研究数据",
        )
        self.assertFalse(ok)

    def test_rejects_poobbc(self):
        ok, _ = prefilter_item(
            {"url": "http://poobbc-efir.ru/home.php", "title": "home"},
            user_query="搜索现代战争中电子战的研究数据",
        )
        self.assertFalse(ok)

    def test_allows_dtic_with_mission(self):
        ok, _ = prefilter_item(
            {
                "url": "https://discover.dtic.mil/results?q=ADA310921",
                "title": "DTIC search",
            },
            user_query="搜索现代战争中电子战的研究数据",
        )
        self.assertTrue(ok)

    def test_post_llm_rejects_low_score(self):
        ok, reason = post_llm_gate(
            {"url": "https://atdi.com/videos", "title": "videos"},
            suggested_level="L3",
            total_score=0.45,
            status="PASS",
            raw_report={"is_valid": True, "action": "KEEP", "evidence_signals": {}},
            user_query="electronic warfare dataset",
            min_confidence=0.6,
        )
        self.assertFalse(ok)
        self.assertIn("分数", reason)

    def test_mission_keywords_ew(self):
        kws = mission_keywords("搜索现代战争中电子战的研究数据")
        self.assertIn("electronic", kws)
        self.assertGreater(task_alignment_score(
            "https://discover.dtic.mil/", "EW database", kws
        ), 0.5)

    def test_container_signal_archive_details(self):
        self.assertTrue(
            has_container_signal("https://archive.org/details/FM_34_36", "manual")
        )


if __name__ == "__main__":
    unittest.main()
