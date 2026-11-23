import unittest
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import ssl
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import requests

from scripts.build_catalog import safe_http_url
from scripts import check_links
from scripts.source_http import GrantsIntermediateAdapter
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
    def test_real_checker_selects_strict_grants_profile_on_direct_and_redirected_hops(self):
        grants = "https://www.grants.gov/search-results-detail/363660"
        for start in (grants, "https://agency.example/notice"):
            visited = []
            closed_sessions = []
            real_close = requests.Session.close
            def close(session):
                closed_sessions.append(session)
                real_close(session)
            def send(session, request, **kwargs):
                adapter = session.get_adapter(request.url)
                visited.append((request, kwargs, session, adapter))
                result = requests.Response()
                result._content = b""
                result._content_consumed = True
                result.url = request.url
                if request.url != grants:
                    result.status_code = 302
                    result.headers["location"] = grants
                    session.cookies.set("test-cookie", "must-not-follow", domain="www.grants.gov")
                    session.headers["Authorization"] = "must-not-follow"
                    session.headers["Cookie"] = "must-not-follow"
                    session.auth = ("must-not-follow", "secret")
                else:
                    result.status_code = 200
                    result.headers["content-type"] = "text/html"
                return result
            with patch.object(requests.Session, "send", send), patch.object(requests.Session, "close", close), \
                    patch.object(check_links, "public_target", return_value=(True, None)) as guard:
                result = check_url(start)
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], 200)
            self.assertEqual(result["redirected"], start != grants)
            self.assertEqual(guard.call_count, len(visited))
            self.assertEqual(len(closed_sessions), 1)
            self.assertEqual(len({id(item[2]) for item in visited}), 1)
            self.assertIsInstance(visited[-1][3], GrantsIntermediateAdapter)
            for request, kwargs, session, adapter in visited:
                self.assertFalse(session.trust_env)
                self.assertIs(kwargs["verify"], True)
                self.assertFalse(kwargs["allow_redirects"])
                self.assertNotIn("Authorization", request.headers)
                self.assertNotIn("Cookie", request.headers)
                if request.url == grants:
                    context = adapter.poolmanager.connection_pool_kw["ssl_context"]
                    self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                    self.assertTrue(context.check_hostname)
                    self.assertEqual(context.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN, 0)
                else:
                    self.assertNotIsInstance(adapter, GrantsIntermediateAdapter)

    def test_head_fallback_uses_bounded_range_get_and_keeps_access_denials(self):
        for final_status, expected in ((200, True), (403, None), (404, False)):
            session = Mock()
            head = Mock(status_code=405)
            get = Mock(status_code=final_status, headers={})
            session.request.side_effect = [head, get]
            with patch.object(check_links, "public_target", return_value=(True, None)):
                result = check_links._check_url("https://grants.gov/notice", 12.0, session)
            self.assertIs(result["ok"], expected)
            self.assertEqual(result["status"], final_status)
            head.close.assert_called_once()
            get.close.assert_called_once()
            self.assertEqual([call.args[0] for call in session.request.call_args_list], ["HEAD", "GET"])
            self.assertEqual(session.request.call_args_list[1].kwargs["headers"]["Range"], "bytes=0-1023")
            self.assertTrue(session.request.call_args_list[1].kwargs["stream"])
            self.assertEqual(session.cookies.clear.call_count, 2)

    def test_every_redirect_is_checked_before_request_and_transport_failure_stays_unconfirmed(self):
        session = Mock()
        response = Mock(status_code=302, headers={"location": "http://127.0.0.1/private"})
        session.request.return_value = response
        with patch.object(check_links, "public_target", side_effect=[(True, None), (False, "non-public IP")]) as guard:
            result = check_links._check_url("https://grants.gov/notice", 12.0, session)
        self.assertEqual(guard.call_count, 2)
        self.assertFalse(result["ok"])
        self.assertIn("unsafe", result["error"])
        self.assertEqual(session.request.call_count, 1)
        response.close.assert_called_once()
        session = Mock()
        session.request.side_effect = requests.exceptions.SSLError("certificate rejected")
        with patch.object(check_links, "public_target", return_value=(True, None)):
            result = check_links._check_url("https://grants.gov/notice", 12.0, session)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["status"])
        self.assertIn("SSLError", result["error"])
        self.assertEqual(annotate_catalog_link_health(
            {"opportunities": [{"detail_page": "https://grants.gov/notice"}]},
            {"records": {"https://grants.gov/notice": result}}), 0)

    def test_credentialed_urls_are_rejected_before_request(self):
        for url in ("https://user:secret@grants.gov/notice", "https://user@agency.example/notice"):
            with patch.object(requests.Session, "request") as request:
                result = check_url(url)
            self.assertFalse(result["ok"])
            request.assert_not_called()

    def test_systemic_failure_threshold_is_still_enforced_at_thirty_five_percent(self):
        for broken, expected in ((7, 0), (8, 2)):
            state = {"url_count": 20, "checked_this_run": 20, "healthy_this_run": 20 - broken,
                     "broken_this_run": broken, "restricted_this_run": 0, "redirected_this_run": 0,
                     "records": {}}
            with TemporaryDirectory() as directory, \
                    patch.object(check_links, "load_catalog", return_value={"opportunities": []}), \
                    patch.object(check_links, "update_link_state", return_value=(state, [])), \
                    patch.object(check_links, "write_catalog"), redirect_stdout(StringIO()):
                result = check_links.main(["--state", str(Path(directory) / "links.json")])
            self.assertEqual(result, expected)

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
