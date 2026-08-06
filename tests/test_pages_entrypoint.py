from datetime import date
import hashlib
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
        ai_provider_js = (
            REPOSITORY_ROOT / "assets" / "ai-provider.js"
        ).read_text(encoding="utf-8")
        profile_js = (
            REPOSITORY_ROOT / "assets" / "profile.js"
        ).read_text(encoding="utf-8")
        review_js = (
            REPOSITORY_ROOT / "assets" / "review.js"
        ).read_text(encoding="utf-8")
        credentials_js = (
            REPOSITORY_ROOT / "assets" / "credentials.js"
        ).read_text(encoding="utf-8")
        chat_ui_js = (
            REPOSITORY_ROOT / "assets" / "chat-ui.js"
        ).read_text(encoding="utf-8")
        application_css = (
            REPOSITORY_ROOT / "assets" / "app.css"
        ).read_text(encoding="utf-8")

        self.assertIn('id="query"', explorer_html)
        self.assertIn('id="facet-discipline"', explorer_html)
        self.assertIn('id="facet-agency"', explorer_html)
        self.assertIn('id="flag-evidence"', explorer_html)
        self.assertIn('id="sort"', explorer_html)
        self.assertIn('id="export-csv"', explorer_html)
        self.assertIn('id="k-provider"', explorer_html)
        self.assertIn('id="k-key"', explorer_html)
        self.assertIn('id="research-profile"', explorer_html)
        self.assertIn('id="expertise-keywords"', explorer_html)
        self.assertIn('id="cv-file"', explorer_html)
        self.assertIn('id="save-profile"', explorer_html)
        self.assertIn('id="use-profile"', explorer_html)
        self.assertIn('id="find-funding"', explorer_html)
        self.assertIn('id="save-key"', explorer_html)
        self.assertIn('id="key-storage-status"', explorer_html)
        self.assertIn("OpenAI key and project limits", explorer_html)
        self.assertIn("Anthropic key safety and limits", explorer_html)
        self.assertIn('id="feedback-tools"', explorer_html)
        self.assertIn('id="result-assistant"', explorer_html)
        self.assertIn('id="export-evaluation"', explorer_html)
        self.assertIn('id="review-candidates"', explorer_html)
        self.assertIn('id="send-deployment-review"', explorer_html)
        self.assertIn('id="source-review-progress"', explorer_html)
        self.assertIn('id="ai-refine"', explorer_html)
        self.assertIn('id="chat-form"', explorer_html)
        self.assertIn('<section class="chat" id="chat"', explorer_html)
        self.assertIn("Chat with your results", explorer_html)
        self.assertIn('id="chat-thinking"', explorer_html)
        self.assertIn('id="open-results-chat"', explorer_html)
        self.assertIn('id="toggle-chat-size"', explorer_html)
        self.assertIn('role="dialog" aria-modal="true"', explorer_html)
        self.assertNotIn("Open larger chat", explorer_html)
        self.assertIn("Enter to send", explorer_html)
        self.assertIn("Export CSV", explorer_html)
        self.assertIn('id="result-label"', explorer_html)
        self.assertIn(
            '<script src="./data/opportunities.js?v=catalog-',
            explorer_html,
        )
        release_version = "release-2026-08-06-v4"
        self.assertIn(
            f'<link rel="stylesheet" href="./assets/app.css?v={release_version}">',
            explorer_html,
        )
        for asset in (
            "profile.js", "review.js", "ai-provider.js", "credentials.js",
            "chat-ui.js", "saved.js", "preferences.js", "app.js",
        ):
            self.assertIn(
                f'<script src="./assets/{asset}?v={release_version}"></script>',
                explorer_html,
            )
        self.assertIn("globalThis.GRANT_CATALOG", application_js)
        self.assertIn("MAX_AI_CANDIDATES = 32", application_js)
        self.assertIn("MAX_CHAT_RESULTS = 20", application_js)
        self.assertIn("NEW_RELEVANT_MAX_AGE_DAYS = 14", application_js)
        self.assertIn("NEW_RELEVANT_MIN_SCORE_RATIO = .2", application_js)
        self.assertIn("function announcementAgeDays", application_js)
        self.assertIn("function newRelevantBoost", application_js)
        self.assertIn("const boost = newRelevantBoost", application_js)
        self.assertIn("match.newRelevant = boost > 0", application_js)
        self.assertIn("async function askResults", application_js)
        self.assertIn('$("open-results-chat").addEventListener("click", openExpandedChat)', application_js)
        self.assertIn('$("result-assistant").classList.remove("hidden")', application_js)
        self.assertIn('$("result-assistant")?.classList.add("hidden")', application_js)
        self.assertIn("referenced_result_ids", application_js)
        self.assertIn("focus_result_ids", application_js)
        self.assertIn("renderRichText", chat_ui_js)
        self.assertIn("Open official FOA", application_js)
        self.assertIn("Minimum per-award amount", explorer_html)
        self.assertIn("primary_document_url", application_js)
        self.assertIn("deadlineEvidenceLabel", application_js)
        self.assertNotIn(
            "Number(record.total_program_funding || 0),\n    );",
            application_js,
        )
        self.assertIn("globalThis.FUNDING_AI.providerJson", application_js)
        self.assertIn("globalThis.FUNDING_PROFILE", profile_js)
        self.assertIn("funding-finder.profile.v1", profile_js)
        self.assertIn("funding-finder.feedback.v1", profile_js)
        self.assertIn("async function extractCv", profile_js)
        self.assertIn("profileContext({ includeCv: true })", application_js)
        self.assertIn("globalThis.FUNDING_PREFERENCES", application_js)
        self.assertIn("globalThis.FUNDING_SAVED", application_js)
        self.assertIn("function renderPreferenceStatus", application_js)
        self.assertIn("function renderSaved", application_js)
        self.assertIn("function exportEvaluation", application_js)
        self.assertIn("function evidenceRows", application_js)
        self.assertIn("function programContactAction", application_js)
        self.assertIn("Show full description &amp; details", application_js)
        self.assertIn(">Ask AI</button>", application_js)
        self.assertIn(">Program contact</a>", application_js)
        self.assertIn("function amendmentOverview", application_js)
        self.assertIn("function amendmentNotice", application_js)
        self.assertIn("function structuredDescription", application_js)
        self.assertIn("FOA amended", application_js)
        self.assertIn("Summary of changes:", application_js)
        self.assertIn(".amendment-notice", application_css)
        self.assertIn(".result-feedback-toggle", application_css)
        self.assertLess(
            application_js.index('<details class="record-details">'),
            application_js.index('<details class="result-feedback-toggle">'),
        )
        self.assertIn(".full-description p", application_css)
        self.assertIn(".full-description li + li", application_css)
        self.assertNotIn("Prioritized from your ratings", application_js)
        self.assertNotIn("Verify current status", application_js)
        self.assertNotIn("Why this matched", application_js)
        self.assertNotIn("Official notice analyzed", application_js)
        self.assertNotIn(".card-contact", application_css)
        self.assertNotIn(".match-explanation", application_css)
        self.assertNotIn(".evidence-summary", application_css)
        self.assertIn("function sendDeploymentReview", application_js)
        self.assertIn("citation_evidence_ids", application_js)
        self.assertIn("globalThis.FUNDING_REVIEW", review_js)
        self.assertIn("funding-finder.deployment-review.v1", review_js)
        self.assertIn("globalThis.FUNDING_CREDENTIALS", application_js)
        self.assertIn("funding-finder.credentials.v1", credentials_js)
        self.assertIn("localStorage", credentials_js)
        self.assertIn("AI retrieval candidate set", application_js)
        self.assertIn('id="browse-all"', application_js)
        self.assertIn("function browseAllOpportunities", application_js)
        self.assertIn(
            '$("result-label").textContent = display.length === 1',
            application_js,
        )
        self.assertIn("api.openai.com/v1/responses", ai_provider_js)
        self.assertIn("api.anthropic.com/v1/messages", ai_provider_js)
        self.assertRegex(
            application_css,
            r"(?s)\.search-form input\s*\{[^}]*color: var\(--ink\);",
        )
        self.assertIn("/* Unified search workflow */", application_css)
        self.assertRegex(
            application_css,
            r"(?s)\.context-grid\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr",
        )
        self.assertRegex(
            application_css,
            r"(?s)\.filter-panel\s*\{[^}]*grid-area:\s*auto",
        )
        self.assertRegex(
            application_css,
            r"(?s)\.filter-body\s*\{[^}]*overflow:\s*visible",
        )
        self.assertRegex(
            application_css,
            r"(?s)\.results-column\s*\{[^}]*width:\s*100%",
        )
        self.assertIn('<meta name="color-scheme" content="light">', explorer_html)
        self.assertIn('<h1 id="page-title">Find funding in a few clear steps</h1>', explorer_html)
        self.assertNotIn("@media (prefers-color-scheme: dark)", application_css)
        self.assertRegex(application_css, r"(?s):root\s*\{[^}]*color-scheme:\s*light")
        self.assertIn("@media (forced-colors: active)", application_css)
        self.assertNotIn('class="chat hidden"', explorer_html)
        self.assertNotIn("localStorage", application_js)
        self.assertNotIn("sessionStorage", application_js)
        self.assertNotIn("sessionStorage", profile_js)
        self.assertNotIn("sessionStorage", review_js)
        self.assertNotIn("k-key", profile_js)
        self.assertNotIn("api_key", profile_js)
        self.assertNotIn("k-key", review_js)
        self.assertNotIn("api_key", review_js)
        self.assertNotIn("FUNDING_CREDENTIALS", profile_js)
        self.assertNotIn("FUNDING_CREDENTIALS", review_js)
        self.assertNotIn("Phase 3 deployment", explorer_html)
        self.assertNotIn('id="profile-search"', explorer_html)
        self.assertNotIn('id="remember-profile"', explorer_html)
        self.assertNotIn("GRANT_MATCH_FEED", explorer_html + application_js)
        self.assertNotIn("CALIBRATION_GRANTS", explorer_html)
        self.assertNotIn('id="sel-faculty"', explorer_html)
        self.assertNotIn('id="load-faculty"', explorer_html)
        self.assertNotIn('id="load-grants"', explorer_html)
        self.assertIn('type="file"', explorer_html)
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
        self.assertIn("save it on this device", docs)
        self.assertIn("zero AI calls", docs)
        self.assertNotIn("https://ur-grant-matcher.zing78.chatgpt.site", docs)
        self.assertNotIn("saved searches in the browser", docs)

    def test_pages_deployment_uses_current_actions_and_extended_timeout(self):
        workflow = (
            REPOSITORY_ROOT
            / ".github"
            / "workflows"
            / "pages.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("actions/checkout@v6", workflow)
        self.assertIn("actions/configure-pages@v6", workflow)
        self.assertIn("actions/upload-pages-artifact@v5", workflow)
        self.assertIn("actions/deploy-pages@v5", workflow)
        self.assertIn('timeout: "1800000"', workflow)
        self.assertIn("timeout-minutes: 35", workflow)
        self.assertIn("pages: write", workflow)
        self.assertIn("id-token: write", workflow)

    def test_generated_opportunity_asset_is_valid(self):
        asset = (
            REPOSITORY_ROOT / "data" / "opportunities.js"
        ).read_text(encoding="utf-8")
        prefix = "globalThis.GRANT_CATALOG="

        self.assertIn(prefix, asset)
        payload = asset.split(prefix, 1)[1].strip().removesuffix(";")
        catalog = json.loads(payload)

        self.assertEqual(catalog["schema_version"], 3)
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
        self.assertIn("quality", catalog["diagnostics"])
        self.assertIn("document_evidence", catalog["diagnostics"])
        identities = {
            record.get("opportunity_number") or record.get("opportunity_id")
            for record in catalog["opportunities"]
        }
        self.assertEqual(len(identities), catalog["record_count"])
        self.assertTrue(
            all(record.get("source") and record.get("source_type")
                for record in catalog["opportunities"])
        )
        self.assertIn(
            "Grants.gov",
            {record.get("source") for record in catalog["opportunities"]},
        )
        catalog_date = date.fromisoformat(catalog["generated_at"][:10])
        self.assertTrue(
            all(
                not record.get("close_date")
                or date.fromisoformat(record["close_date"]) >= catalog_date
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
        self.assertTrue(
            all(
                isinstance(record.get("deadlines"), list)
                and record.get("award_source")
                and record.get("detail_enrichment_status")
                and record.get("document_evidence_status")
                for record in catalog["opportunities"]
            )
        )
        amended_records = [
            record
            for record in catalog["opportunities"]
            if (
                (record.get("document_evidence") or {})
                .get("document", {})
                .get("changed_since_previous")
                or (record.get("history") or {}).get("modified_field_count", 0)
                or (record.get("history") or {}).get("change_comment_count", 0)
            )
        ]
        self.assertTrue(amended_records)
        self.assertTrue(
            all(
                (record.get("document_evidence") or {})
                .get("document", {})
                .get("last_seen_at")
                or record.get("last_updated")
                or record.get("api_last_updated")
                or record.get("detail_enriched_at")
                or record.get("posted_date")
                for record in amended_records
            )
        )
        self.assertTrue(
            all(
                any(
                    record.get(field)
                    for field in (
                        "primary_document_url",
                        "funding_opportunity_url",
                        "detail_page",
                    )
                )
                for record in catalog["opportunities"]
            )
        )
        self.assertTrue(
            all(
                not record.get(field)
                or record[field].startswith(("http://", "https://"))
                for record in catalog["opportunities"]
                for field in (
                    "primary_document_url",
                    "funding_opportunity_url",
                    "detail_page",
                )
            )
        )

        document_cache = json.loads(
            (
                REPOSITORY_ROOT / "data" / "document_evidence.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(document_cache["schema_version"], 1)
        self.assertIsInstance(document_cache["records"], dict)

    def test_vendored_cv_parsers_match_reviewed_hashes(self):
        expected = {
            "pdf.mjs": (
                "d7f44e075a8fa47ac165362d404de2dabf61f64f3d98c9180162c5f71f54980a"
            ),
            "pdf.worker.mjs": (
                "f9ed6a050771ad74c228a1cbfc8edb3271249f2e2efa29ed4692468ecb001733"
            ),
            "mammoth.browser.min.js": (
                "5d4c0e7c9165d70b78f789c5274a2c7846d9e1c06ec19b69afa6ef45f789a3b9"
            ),
        }
        vendor = REPOSITORY_ROOT / "assets" / "vendor"
        for name, digest in expected.items():
            with self.subTest(name=name):
                payload = (vendor / name).read_bytes().replace(b"\r\n", b"\n")
                self.assertEqual(
                    hashlib.sha256(payload).hexdigest(),
                    digest,
                )
        self.assertTrue((vendor / "pdfjs.LICENSE").is_file())
        self.assertTrue((vendor / "mammoth.LICENSE").is_file())

    def test_scheduled_refresh_has_health_checks_and_failure_alert(self):
        workflow = (
            REPOSITORY_ROOT
            / ".github"
            / "workflows"
            / "refresh-opportunities.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("schedule:", workflow)
        self.assertIn("python -m scripts.build_catalog", workflow)
        self.assertIn("python -m scripts.enrich_catalog", workflow)
        self.assertIn("python -m scripts.extract_document_evidence", workflow)
        self.assertIn("python -m scripts.sources merge", workflow)
        self.assertIn("python -m scripts.build_feeds", workflow)
        self.assertIn("--fail-on-degraded", workflow)
        self.assertIn("continue-on-error: true", workflow)
        self.assertIn("steps.additional-sources.outcome == 'failure'", workflow)
        self.assertIn("External funding source refresh degraded", workflow)
        self.assertIn("--min-records 1000", workflow)
        self.assertIn("--max-record-count 5000", workflow)
        self.assertIn("actions/setup-node@v6", workflow)
        self.assertIn("tests/browser/*.test.mjs", workflow)
        self.assertNotIn("web/tests/", workflow)
        self.assertIn("python -m scripts.update_catalog_docs", workflow)
        self.assertIn("git add README.md PROJECT.md", workflow)
        self.assertIn("if: failure()", workflow)
        self.assertIn("data/opportunities.js", workflow)
        self.assertIn("data/document_evidence.json", workflow)
        self.assertIn("data/source_records.json", workflow)
        self.assertIn("feeds", workflow)


if __name__ == "__main__":
    unittest.main()
