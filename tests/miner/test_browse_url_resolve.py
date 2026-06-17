import unittest

from agents.miner.tools.browse_url_resolve import (
    dtic_403_fallback_urls,
    merge_access_denied_signal,
    normalize_browse_url,
    should_attempt_dtic_fallback,
)


class TestBrowseUrlResolve(unittest.TestCase):
    def test_dsiac_host_maps_to_dsiac_org(self):
        url = "https://dsiac.dtic.mil/tag/electronic-warfare-ew/"
        resolved, remapped = normalize_browse_url(url)
        self.assertTrue(remapped)
        self.assertTrue(resolved.startswith("https://www.dsiac.org/tag/electronic-warfare-ew"))

    def test_non_dsiac_url_unchanged(self):
        url = "https://www.ncbi.nlm.nih.gov/genbank/"
        resolved, remapped = normalize_browse_url(url)
        self.assertFalse(remapped)
        self.assertEqual(resolved, url)

    def test_dtic_citation_fallbacks(self):
        url = "https://apps.dtic.mil/sti/citations/ADA310921"
        fallbacks = dtic_403_fallback_urls(url)
        self.assertIn("https://discover.dtic.mil/results?q=ADA310921", fallbacks)
        self.assertEqual(fallbacks[-1], "https://discover.dtic.mil/")

    def test_should_attempt_dtic_fallback_on_403(self):
        self.assertTrue(
            should_attempt_dtic_fallback({"success": False, "error": "HTTP_SOFT_ERROR_403"})
        )
        self.assertFalse(
            should_attempt_dtic_fallback({"success": False, "error": "ERR_NAME_NOT_RESOLVED"})
        )

    def test_merge_access_denied_flag(self):
        self.assertTrue(merge_access_denied_signal({"access_denied": True, "success": False}))
        self.assertTrue(
            merge_access_denied_signal({"success": False, "error": "HTTP_SOFT_ERROR_403"})
        )


if __name__ == "__main__":
    unittest.main()
