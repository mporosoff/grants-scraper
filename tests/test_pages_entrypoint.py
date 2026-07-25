from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class GitHubPagesEntrypointTests(unittest.TestCase):
    def test_root_page_opens_match_explorer(self):
        index_html = (REPOSITORY_ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('content="0; url=./match_explorer.html"', index_html)
        self.assertIn('window.location.replace(target)', index_html)
        self.assertIn('name="viewport"', index_html)

    def test_match_explorer_uses_one_provider_key(self):
        explorer_html = (
            REPOSITORY_ROOT / "match_explorer.html"
        ).read_text(encoding="utf-8")

        self.assertIn('id="k-provider"', explorer_html)
        self.assertIn('id="k-key"', explorer_html)
        self.assertIn('id="research-profile"', explorer_html)
        self.assertIn('id="btn-save-search"', explorer_html)
        self.assertIn('id="btn-new-search"', explorer_html)
        self.assertIn('id="saved-searches"', explorer_html)
        self.assertIn("Export results.csv", explorer_html)
        self.assertIn("Due date(s)", explorer_html)
        self.assertIn("Grant duration", explorer_html)
        self.assertNotIn('id="sel-faculty"', explorer_html)
        self.assertNotIn('id="load-faculty"', explorer_html)
        self.assertNotIn('id="load-grants"', explorer_html)
        self.assertNotIn('type="file"', explorer_html)
        self.assertNotIn('id="k-openai"', explorer_html)
        self.assertNotIn('id="k-anthropic"', explorer_html)


if __name__ == "__main__":
    unittest.main()
