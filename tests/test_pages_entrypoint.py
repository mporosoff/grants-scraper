from datetime import date
import json
from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class GitHubPagesEntrypointTests(unittest.TestCase):
    def test_root_page_opens_match_explorer(self):
        index_html = (REPOSITORY_ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('content="0; url=./match_explorer.html"', index_html)
        self.assertIn('window.location.replace(target)', index_html)
        self.assertIn('name="viewport"', index_html)

    def test_match_explorer_supports_public_search_and_optional_ai(self):
        explorer_html = (
            REPOSITORY_ROOT / "match_explorer.html"
        ).read_text(encoding="utf-8")
        application_js = (
            REPOSITORY_ROOT / "assets" / "app.js"
        ).read_text(encoding="utf-8")

        self.assertIn('id="query"', explorer_html)
        self.assertIn('id="facet-discipline"', explorer_html)
        self.assertIn('id="facet-agency"', explorer_html)
        self.assertIn('id="sort"', explorer_html)
        self.assertIn('id="export-csv"', explorer_html)
        self.assertIn('id="k-provider"', explorer_html)
        self.assertIn('id="k-key"', explorer_html)
        self.assertIn('id="research-profile"', explorer_html)
        self.assertIn('id="ai-refine"', explorer_html)
        self.assertIn('id="chat-form"', explorer_html)
        self.assertIn("Export CSV", explorer_html)
        self.assertIn(
            '<script src="./data/opportunities.js"></script>',
            explorer_html,
        )
        self.assertIn(
            '<script src="./assets/app.js"></script>',
            explorer_html,
        )
        self.assertIn("globalThis.GRANT_CATALOG", application_js)
        self.assertIn("MAX_AI_CANDIDATES = 32", application_js)
        self.assertIn("api.openai.com/v1/responses", application_js)
        self.assertIn("api.anthropic.com/v1/messages", application_js)
        self.assertNotIn("localStorage", application_js)
        self.assertNotIn("sessionStorage", application_js)
        self.assertNotIn("GRANT_MATCH_FEED", explorer_html + application_js)
        self.assertNotIn("CALIBRATION_GRANTS", explorer_html)
        self.assertNotIn('id="sel-faculty"', explorer_html)
        self.assertNotIn('id="load-faculty"', explorer_html)
        self.assertNotIn('id="load-grants"', explorer_html)
        self.assertNotIn('type="file"', explorer_html)
        self.assertNotIn('id="k-openai"', explorer_html)
        self.assertNotIn('id="k-anthropic"', explorer_html)

    def test_project_docs_define_one_public_browser_product(self):
        project = (REPOSITORY_ROOT / "PROJECT.md").read_text(encoding="utf-8")
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        hosting = (REPOSITORY_ROOT / "docs" / "HOSTING.md").read_text(
            encoding="utf-8"
        )
        docs = "\n".join((project, readme, hosting))

        self.assertIn("GitHub Pages is the only active product surface", project)
        self.assertIn("comprehensive catalog", docs.lower())
        self.assertIn("https://mporosoff.github.io/grants-scraper/", docs)
        self.assertIn("page memory", docs)
        self.assertIn("zero AI calls", docs)
        self.assertNotIn("https://ur-grant-matcher.zing78.chatgpt.site", docs)
        self.assertNotIn("saved searches in the browser", docs)

    def test_generated_opportunity_asset_is_valid(self):
        asset = (
            REPOSITORY_ROOT / "data" / "opportunities.js"
        ).read_text(encoding="utf-8")
        prefix = "globalThis.GRANT_CATALOG="

        self.assertIn(prefix, asset)
        payload = asset.split(prefix, 1)[1].strip().removesuffix(";")
        catalog = json.loads(payload)

        self.assertEqual(catalog["schema_version"], 2)
        self.assertEqual(
            catalog["record_count"], len(catalog["opportunities"])
        )
        self.assertGreaterEqual(catalog["record_count"], 1000)
        self.assertTrue(catalog["generated_at"].endswith("Z"))
        self.assertEqual(
            catalog["search_index"]["document_count"],
            catalog["record_count"],
        )
        self.assertIn("carbon", catalog["search_index"]["postings"])
        self.assertIn("agency", catalog["facets"])
        identities = {
            record.get("opportunity_number") or record.get("opportunity_id")
            for record in catalog["opportunities"]
        }
        self.assertEqual(len(identities), catalog["record_count"])
        self.assertTrue(
            all(record.get("source") == "Grants.gov"
                for record in catalog["opportunities"])
        )
        catalog_date = date.fromisoformat(catalog["generated_at"][:10])
        self.assertTrue(
            all(
                not record.get("close_date")
                or date.fromisoformat(record["close_date"]) >= catalog_date
                or record.get("status") == "forecasted"
                for record in catalog["opportunities"]
            )
        )
        self.assertTrue(
            all(
                record.get("status_verification_required")
                for record in catalog["opportunities"]
                if record.get("status") == "posted"
                and not record.get("close_date")
                and not record.get("archive_date")
                and not record.get("rolling")
            )
        )

    def test_scheduled_refresh_has_health_checks_and_failure_alert(self):
        workflow = (
            REPOSITORY_ROOT
            / ".github"
            / "workflows"
            / "refresh-opportunities.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("schedule:", workflow)
        self.assertIn("python -m scripts.build_catalog", workflow)
        self.assertIn("--min-records 1000", workflow)
        self.assertIn("--max-record-count 5000", workflow)
        self.assertIn("if: failure()", workflow)
        self.assertIn("data/opportunities.js", workflow)


if __name__ == "__main__":
    unittest.main()
