import unittest
import json
from unittest.mock import patch

from scripts.build_catalog import safe_http_url
from scripts.check_links import (
    annotate_catalog_link_health,
    catalog_urls,
    check_url,
    public_target,
    serialize_state,
    select_urls,
    update_link_state,
)


class LinkHealthTests(unittest.TestCase):
    def test_annotates_only_confirmed_missing_primary_links(self):
        catalog = {"opportunities": [{
            "opportunity_id": "1",
            "primary_document_url": "https://agency.example/missing.pdf",
            "funding_opportunity_url": "https://agency.example/timeout",
            "detail_page": "https://grants.gov/1",
        }]}
        state = {"records": {
            "https://agency.example/missing.pdf": {"ok": False, "status": 404},
            "https://agency.example/timeout": {"ok": False, "status": None},
            "https://grants.gov/1": {"ok": True, "status": 200},
        }}

        self.assertEqual(annotate_catalog_link_health(catalog, state), 1)
        self.assertEqual(
            catalog["opportunities"][0]["link_health_broken_urls"],
            ["https://agency.example/missing.pdf"],
        )

    def test_serialized_state_round_trips_with_one_line_per_url(self):
        state = {
            "schema_version": 1,
            "url_count": 2,
            "records": {
                "https://a.example": {"ok": True, "record_ids": ["1"]},
                "https://b.example": {"ok": None, "record_ids": ["2"]},
            },
        }
        serialized = serialize_state(state)
        self.assertEqual(json.loads(serialized), state)
        self.assertEqual(len(serialized.splitlines()), 8)

    def test_known_hosts_upgrade_to_https(self):
        self.assertEqual(
            safe_http_url("http://grants.nih.gov/example"),
            "https://grants.nih.gov/example",
        )
        self.assertEqual(
            safe_http_url("http://example.org/path"),
            "http://example.org/path",
        )
        self.assertEqual(
            safe_http_url("http://nspires.nasaprs.com"),
            "https://nspires.nasaprs.com",
        )

    def test_catalog_urls_deduplicates_and_tracks_records(self):
        catalog = {
            "opportunities": [
                {
                    "opportunity_id": "1",
                    "detail_page": "https://www.grants.gov/x/1",
                    "primary_document_url": "https://agency.example/nofo.pdf",
                },
                {
                    "opportunity_id": "2",
                    "detail_page": "https://www.grants.gov/x/1",
                },
            ]
        }
        urls = catalog_urls(catalog)
        self.assertEqual(
            urls["https://www.grants.gov/x/1"],
            ["1", "2"],
        )

    def test_selects_unseen_before_oldest_prior(self):
        urls = {"https://a": [], "https://b": [], "https://c": []}
        prior = {
            "https://a": {"checked_at": "2026-07-01T00:00:00Z"},
            "https://b": {"checked_at": "2026-07-20T00:00:00Z"},
        }
        self.assertEqual(
            select_urls(urls, prior, 2),
            ["https://c", "https://a"],
        )

    def test_rejects_local_targets_before_request(self):
        self.assertFalse(public_target("http://127.0.0.1/internal")[0])
        result = check_url("http://localhost/internal")
        self.assertFalse(result["ok"])
        self.assertIn("unsafe", result["error"].lower())

    @patch("scripts.check_links.check_url")
    def test_update_retains_prior_and_records_redirect(self, checker):
        checker.return_value = {
            "ok": True,
            "status": 200,
            "final_url": "https://agency.example/new",
            "content_type": "text/html",
            "redirected": True,
            "checked_at": "2026-07-30T12:00:00Z",
            "error": None,
        }
        catalog = {
            "opportunities": [
                {
                    "opportunity_id": "1",
                    "detail_page": "https://agency.example/old",
                }
            ]
        }
        state, results = update_link_state(catalog, {}, max_checks=1, workers=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(state["redirected_this_run"], 1)
        self.assertEqual(
            state["records"]["https://agency.example/old"]["final_url"],
            "https://agency.example/new",
        )


if __name__ == "__main__":
    unittest.main()
