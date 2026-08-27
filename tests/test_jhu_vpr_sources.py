"""Regression coverage for the JHU and UR funding-email source adapters."""

from io import BytesIO
from datetime import date
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from threading import Thread
import unittest
from unittest.mock import patch

import openpyxl

from scripts.sources.adapters.jhu_fellowships import (
    JHUFellowshipsAdapter,
    MIN_ROWS_PER_AUDIENCE,
    PINNED_WORKBOOK_MAX_AGE_DAYS,
    SHEETS,
)
from scripts.sources.adapters.vpr_email import VPREmailAdapter
from scripts.sources.registry import collect


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def jhu_workbook_bytes(
    prefix: str,
    rows: int = MIN_ROWS_PER_AUDIENCE,
    deadline="2030-12-31",
) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append([
        "Sponsor",
        "Program",
        "Description",
        "Eligibility",
        "Keywords",
        "Amount",
        "Annual Deadline",
    ])
    for index in range(rows):
        row_deadline = deadline(index) if callable(deadline) else deadline
        sheet.append([
            f"{prefix} Foundation {index}",
            f"{prefix} Research Fellowship {index}",
            "Supports environmental and engineering research.",
            "Researchers at eligible universities.",
            "water; materials",
            "$100,000",
            row_deadline,
        ])
        sheet.cell(index + 2, 2).hyperlink = f"https://example.org/{prefix.lower()}/{index}"
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


class JHUFellowshipsTests(unittest.TestCase):
    def test_upstream_challenge_keeps_jhu_out_of_default_publication(self):
        adapter = JHUFellowshipsAdapter()
        self.assertFalse(adapter.enabled)
        self.assertIn("interactive Cloudflare challenge", adapter.disabled_reason)
        records, results = collect([adapter])
        self.assertEqual(records, [])
        self.assertEqual(results, [])

    def test_fetch_uses_official_fallbacks_and_requires_every_audience(self):
        adapter = JHUFellowshipsAdapter(as_of=date(2026, 8, 27))

        def fake_get(url, **_kwargs):
            if "/funding-opportunities/" in url:
                raise RuntimeError("page host blocked")
            return b"PK\x03\x04sanitized workbook"

        with patch.object(adapter, "_get", side_effect=fake_get):
            payload = adapter.fetch()

        self.assertEqual(
            [item["audience"] for item in payload],
            ["grad", "postdoc", "faculty"],
        )
        self.assertEqual(
            adapter.diagnostics["downloaded_audiences"],
            ["grad", "postdoc", "faculty"],
        )

    def test_fetch_fails_instead_of_accepting_a_partial_snapshot(self):
        adapter = JHUFellowshipsAdapter()

        def fake_get(url, **_kwargs):
            if "/funding-opportunities/" in url or "Postdoc" in url:
                raise RuntimeError("blocked")
            return b"PK\x03\x04sanitized workbook"

        with patch.object(adapter, "_get", side_effect=fake_get):
            with self.assertRaisesRegex(RuntimeError, "Incomplete JHU workbook refresh"):
                adapter.fetch()
        self.assertIn("postdoc", adapter.diagnostics["download_failures"][0])

    def test_under_construction_pages_use_bounded_official_direct_workbooks(self):
        page = (FIXTURES / "jhu_funding_page_under_construction.html").read_bytes()
        adapter = JHUFellowshipsAdapter(as_of=date(2026, 8, 27))

        def fake_get(url, **_kwargs):
            if "/funding-opportunities/" in url:
                return page
            if "/wp-content/uploads/" in url:
                return b"PK\x03\x04sanitized workbook"
            raise AssertionError(f"unexpected short-link request: {url}")

        with patch.object(adapter, "_get", side_effect=fake_get):
            payload = adapter.fetch()

        self.assertEqual(len(payload), 3)
        self.assertEqual(
            adapter.diagnostics["page_states"],
            {
                "grad": "under_construction_no_workbook_link",
                "postdoc": "under_construction_no_workbook_link",
                "faculty": "under_construction_no_workbook_link",
            },
        )
        self.assertEqual(
            adapter.diagnostics["download_sources_by_audience"],
            {
                "grad": "official_direct",
                "postdoc": "official_direct",
                "faculty": "official_direct",
            },
        )
        self.assertEqual(
            adapter.diagnostics["source_state"],
            "bounded_official_snapshot",
        )
        self.assertEqual(adapter.diagnostics["source_snapshot_at"], "2026-07-01")
        self.assertEqual(adapter.diagnostics["source_snapshot_age_days"], 57)
        self.assertEqual(
            adapter.diagnostics["source_snapshot_max_age_days"],
            PINNED_WORKBOOK_MAX_AGE_DAYS,
        )

    def test_pinned_workbooks_fail_closed_after_the_snapshot_age_bound(self):
        page = (FIXTURES / "jhu_funding_page_under_construction.html").read_bytes()
        adapter = JHUFellowshipsAdapter(as_of=date(2026, 9, 2))

        def fake_get(url, **_kwargs):
            if "/funding-opportunities/" in url:
                return page
            if "/wp-content/uploads/" in url:
                return b"PK\x03\x04sanitized workbook"
            raise AssertionError(f"unexpected short-link request: {url}")

        with patch.object(adapter, "_get", side_effect=fake_get):
            with self.assertRaisesRegex(
                RuntimeError,
                "official fallback snapshot is 63 days old",
            ):
                adapter.fetch()

        self.assertEqual(adapter.diagnostics["source_snapshot_age_days"], 63)
        self.assertEqual(
            adapter.diagnostics["failure_class"],
            "upstream_response_change",
        )
        self.assertEqual(
            adapter.diagnostics["failure_reason"],
            "pinned_workbook_expired",
        )

    def test_merge_context_date_controls_snapshot_freshness_in_both_directions(self):
        page = (FIXTURES / "jhu_funding_page_under_construction.html").read_bytes()

        def fake_get(url, **_kwargs):
            if "/funding-opportunities/" in url:
                return page
            if "/wp-content/uploads/" in url:
                return b"PK\x03\x04sanitized workbook"
            raise AssertionError(f"unexpected short-link request: {url}")

        historical = JHUFellowshipsAdapter(as_of=date(2026, 9, 2))
        with (
            patch.object(historical, "_get", side_effect=fake_get),
            patch.object(historical, "parse", return_value=[]),
        ):
            _records, results = collect(
                [historical], include_disabled=True,
                context={"catalog_records": [], "as_of": date(2026, 8, 27)}
            )
        self.assertTrue(results[0].ok)
        self.assertEqual(historical.as_of, date(2026, 8, 27))
        self.assertEqual(historical.diagnostics["source_snapshot_age_days"], 57)

        future = JHUFellowshipsAdapter(as_of=date(2026, 8, 27))
        with (
            patch.object(future, "_get", side_effect=fake_get),
            patch.object(future, "parse", return_value=[]),
        ):
            _records, results = collect(
                [future], include_disabled=True,
                context={"catalog_records": [], "as_of": date(2026, 9, 2)}
            )
        self.assertFalse(results[0].ok)
        self.assertEqual(future.as_of, date(2026, 9, 2))
        self.assertEqual(future.diagnostics["source_snapshot_age_days"], 63)
        self.assertEqual(future.diagnostics["failure_reason"], "pinned_workbook_expired")

        predating = JHUFellowshipsAdapter(as_of=date(2026, 8, 27))
        with (
            patch.object(predating, "_get", side_effect=fake_get),
            patch.object(predating, "parse", return_value=[]),
        ):
            _records, results = collect(
                [predating], include_disabled=True,
                context={"catalog_records": [], "as_of": date(2026, 6, 30)}
            )
        self.assertFalse(results[0].ok)
        self.assertEqual(predating.as_of, date(2026, 6, 30))
        self.assertEqual(predating.diagnostics["source_snapshot_age_days"], -1)
        self.assertEqual(
            predating.diagnostics["failure_reason"],
            "pinned_workbook_newer_than_catalog",
        )

    def test_new_page_discovered_workbooks_are_not_treated_as_pinned_snapshots(self):
        current_sheet = "https://research.jhu.edu/current/current-funding.xlsx"
        page = f'<a href="{current_sheet}">Current workbook</a>'.encode()
        adapter = JHUFellowshipsAdapter(as_of=date(2027, 1, 1))

        def fake_get(url, **_kwargs):
            if "/funding-opportunities/" in url:
                return page
            if url == current_sheet:
                return b"PK\x03\x04sanitized workbook"
            raise AssertionError(f"unexpected fallback request: {url}")

        with patch.object(adapter, "_get", side_effect=fake_get):
            payload = adapter.fetch()

        self.assertEqual(len(payload), 3)
        self.assertEqual(adapter.diagnostics["source_state"], "live_page_workbooks")
        self.assertEqual(adapter.diagnostics["snapshot_dates_by_audience"], {})

    def test_public_page_cookie_is_reused_for_official_workbook_requests(self):
        page = (FIXTURES / "jhu_funding_page_under_construction.html").read_bytes()
        workbook = b"PK\x03\x04sanitized workbook"
        workbook_cookies = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/page/"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Set-Cookie", "__cf_bm=allowed; Path=/; HttpOnly")
                    self.send_header("Content-Length", str(len(page)))
                    self.end_headers()
                    self.wfile.write(page)
                    return
                if self.path.startswith("/sheet/"):
                    cookie = self.headers.get("Cookie") or ""
                    workbook_cookies.append(cookie)
                    if "__cf_bm=allowed" not in cookie:
                        self.send_response(403)
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                    self.send_header("Content-Length", str(len(workbook)))
                    self.end_headers()
                    self.wfile.write(workbook)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        sheets = [
            {
                "audience": audience,
                "page": f"{origin}/page/{audience}",
                "direct_sheet": f"{origin}/sheet/{audience}.xlsx",
                "fallback_sheet": None,
                "snapshot_date": None,
                "applicant_types": [audience],
                "drop_federal": False,
            }
            for audience in ("grad", "postdoc", "faculty")
        ]
        try:
            with patch("scripts.sources.adapters.jhu_fellowships.SHEETS", sheets):
                payload = JHUFellowshipsAdapter().fetch()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(len(payload), 3)
        self.assertEqual(len(workbook_cookies), 3)
        self.assertTrue(all("__cf_bm=allowed" in cookie for cookie in workbook_cookies))

    def test_repeated_cloudflare_403_is_classified_and_fails_closed(self):
        adapter = JHUFellowshipsAdapter()

        def blocked(_url, **_kwargs):
            raise RuntimeError("HTTP Error 403: Forbidden; cf-mitigated=challenge")

        with patch.object(adapter, "_get", side_effect=blocked):
            with self.assertRaisesRegex(RuntimeError, "Incomplete JHU workbook refresh"):
                adapter.fetch()

        self.assertEqual(adapter.diagnostics["downloaded_audiences"], [])
        self.assertEqual(adapter.diagnostics["failure_class"], "request_network")
        self.assertEqual(
            adapter.diagnostics["failure_reason"],
            "http_403_access_challenge",
        )

    def test_parse_requires_and_reports_all_three_audiences(self):
        adapter = JHUFellowshipsAdapter(as_of=date(2026, 8, 10))
        payload = [
            {**config, "data": jhu_workbook_bytes(config["audience"])}
            for config in SHEETS
        ]
        records = list(adapter.parse(payload))
        self.assertEqual(len(records), MIN_ROWS_PER_AUDIENCE * 3)
        self.assertEqual(
            adapter.diagnostics["raw_rows_by_audience"],
            {
                "grad": MIN_ROWS_PER_AUDIENCE,
                "postdoc": MIN_ROWS_PER_AUDIENCE,
                "faculty": MIN_ROWS_PER_AUDIENCE,
            },
        )
        self.assertEqual(
            adapter.diagnostics["current_rows_by_audience"],
            {
                "grad": MIN_ROWS_PER_AUDIENCE,
                "postdoc": MIN_ROWS_PER_AUDIENCE,
                "faculty": MIN_ROWS_PER_AUDIENCE,
            },
        )
        self.assertTrue(all(record.close_date == "2030-12-31" for record in records))

    def test_expired_and_unverified_rows_are_removed_but_zero_is_valid(self):
        adapter = JHUFellowshipsAdapter(as_of=date(2026, 8, 10))
        payload = [
            {
                **config,
                "data": jhu_workbook_bytes(
                    config["audience"],
                    deadline=lambda index: "2020-01-01" if index % 2 else "TBD",
                ),
            }
            for config in SHEETS
        ]

        records = list(adapter.parse(payload))

        self.assertEqual(records, [])
        self.assertEqual(adapter.min_records, 0)
        self.assertEqual(adapter.diagnostics["parsed_records"], 0)
        for audience in ("grad", "postdoc", "faculty"):
            dropped = adapter.diagnostics["dropped_deadlines_by_audience"][audience]
            self.assertEqual(dropped["expired"] + dropped["unverified"], 50)

    def test_explicit_rolling_rows_remain_only_while_present_in_fresh_files(self):
        adapter = JHUFellowshipsAdapter(as_of=date(2026, 8, 10))
        payload = [
            {
                **config,
                "data": jhu_workbook_bytes(
                    config["audience"],
                    deadline=lambda index: "Rolling applications" if index == 0 else "2020-01-01",
                ),
            }
            for config in SHEETS
        ]

        records = list(adapter.parse(payload))

        self.assertEqual(len(records), 3)
        self.assertTrue(all(record.close_date is None for record in records))
        self.assertTrue(all("Rolling" in record.deadline_note for record in records))

    def test_exact_deadline_expires_on_the_following_day(self):
        payload = [
            {
                **config,
                "data": jhu_workbook_bytes(
                    config["audience"], deadline="2026-08-10"
                ),
            }
            for config in SHEETS
        ]

        on_deadline = list(
            JHUFellowshipsAdapter(as_of=date(2026, 8, 10)).parse(payload)
        )
        after_deadline = list(
            JHUFellowshipsAdapter(as_of=date(2026, 8, 11)).parse(payload)
        )

        self.assertEqual(len(on_deadline), MIN_ROWS_PER_AUDIENCE * 3)
        self.assertEqual(after_deadline, [])

    def test_same_program_across_audiences_is_merged_once(self):
        adapter = JHUFellowshipsAdapter(as_of=date(2026, 8, 10))
        payload = [
            {**config, "data": jhu_workbook_bytes("Shared")}
            for config in SHEETS
        ]

        records = list(adapter.parse(payload))

        self.assertEqual(len(records), MIN_ROWS_PER_AUDIENCE)
        self.assertEqual(adapter.diagnostics["deduplicated_current_rows"], 100)
        self.assertEqual(
            set(records[0].applicant_types),
            {"Graduate students", "Postdoctoral researchers", "Early-career faculty"},
        )


class VPREmailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cindy_digest = (FIXTURES / "vpr_digest_sample.html").read_text(
            encoding="utf-8"
        )
        cls.vpr_single = (FIXTURES / "vpr_single_sample.txt").read_text(
            encoding="utf-8"
        )

    def test_sanitized_cindy_and_vpr_formats_parse_independently(self):
        adapter = VPREmailAdapter()
        cindy = adapter.parse_payload(self.cindy_digest)
        vpr = adapter.parse_payload(self.vpr_single)
        self.assertEqual(len(cindy), 1)
        self.assertIn("Water Research Award", cindy[0].title)
        self.assertEqual(cindy[0].close_date, "2026-09-30")
        self.assertEqual(len(vpr), 1)
        self.assertIn("Instrumentation Award", vpr[0].title)
        self.assertEqual(vpr[0].close_date, "2026-10-15")

    def test_free_form_email_fields_do_not_become_one_off_discipline_facets(self):
        sample = """
        Sloan Research Fellowships
        Deadline: September 15, 2026
        Topic/Discipline: chemistry, computer science, earth systems science,
        economics, mathematics, neuroscience, physics, or a related field
        Sponsor website: https://example.org/sloan
        """

        opportunity = VPREmailAdapter().parse_payload(sample)[0]
        record = opportunity.to_record(
            slug="vpr-email",
            source="VPR funding digest (limited submissions & foundations)",
            source_type="Internal",
        )

        self.assertNotIn("chemistry, computer science", " | ".join(record["disciplines"]))
        self.assertIn("Engineering and Physical Sciences", record["disciplines"])
        self.assertIn("Environmental and Life Sciences", record["disciplines"])

    def test_private_funder_page_fills_missing_card_details_when_enabled(self):
        digest = """
        <p><b><u>External Funding</u></b></p>
        <p><b>ACS Petroleum Research Fund New Directions</b></p>
        <p><a href="https://www.acs.org/funding/grants/petroleum-research-fund/programs/new-directions-grants.html">Sponsor website</a></p>
        <p><b>Deadline:</b> October 23, 2026</p>
        """
        page = """
        <html><head><meta name="description" content="The New Directions program supports innovative petroleum-relevant research that enables investigators to pursue a new scientific direction."></head>
        <body>
          <p>Eligibility: Tenured or tenure-track faculty at eligible nonprofit institutions may apply.</p>
          <p>Maximum award amount: up to $125,000 for a two-year project.</p>
        </body></html>
        """

        class Response:
            url = "https://www.acs.org/funding/grants/petroleum-research-fund/programs/new-directions-grants.html"
            headers = {"content-type": "text/html; charset=utf-8"}
            content = page.encode()
            text = page

            @staticmethod
            def raise_for_status():
                return None

        adapter = VPREmailAdapter()
        with patch.dict(os.environ, {"VPR_ENRICH_LINKS": "true"}), patch(
            "scripts.sources.adapters.vpr_email.requests.get",
            return_value=Response(),
        ) as fetched:
            opportunity = list(adapter.parse([{"stream": "vpr", "body": digest}]))[0]

        self.assertIn("innovative petroleum-relevant research", opportunity.description)
        self.assertIn("Tenured or tenure-track faculty", opportunity.eligibility_text)
        self.assertEqual(opportunity.award_ceiling, "125000")
        self.assertEqual(
            opportunity.agency,
            "American Chemical Society Petroleum Research Fund",
        )
        self.assertEqual(adapter.diagnostics["private_link_enrichment"]["succeeded"], 1)
        record = opportunity.to_record(
            slug="vpr-email",
            source="VPR funding digest (limited submissions & foundations)",
            source_type="Internal",
        )
        provenance = record["page_field_provenance"]
        self.assertEqual(
            set(provenance),
            {"description", "eligibility_text", "award_ceiling"},
        )
        for field in provenance.values():
            self.assertEqual(
                set(field),
                {
                    "source_url",
                    "fetched_at",
                    "source_excerpt",
                    "extraction_method",
                    "confidence",
                    "status",
                },
            )
            self.assertEqual(field["status"], "page_extracted")
            self.assertTrue(field["source_excerpt"])
        fetched.assert_called_once()

    def test_private_page_uses_only_explicit_submission_deadline(self):
        digest = """
        <p><b><u>External Funding</u></b></p>
        <p><b>Sloan Research Fellowship</b></p>
        <p><a href="https://sloan.org/fellowships">Sponsor website</a></p>
        <p><b>Synopsis:</b> Early-career research fellowship.</p>
        """
        page = """
        <html><head><meta name="description" content="The Sloan fellowship supports early-career researchers pursuing original scientific research across several disciplines."></head>
        <body>
          <p>Applications open January 5, 2027 and applications are due March 15, 2027.</p>
          <p>Preliminary nomination event: February 1, 2027.</p>
        </body></html>
        """

        class Response:
            url = "https://sloan.org/fellowships"
            headers = {"content-type": "text/html; charset=utf-8"}
            content = page.encode()
            text = page

            @staticmethod
            def raise_for_status():
                return None

        with patch.dict(os.environ, {"VPR_ENRICH_LINKS": "true"}), patch(
            "scripts.sources.adapters.vpr_email.requests.get",
            return_value=Response(),
        ):
            opportunity = list(
                VPREmailAdapter().parse([{"stream": "vpr", "body": digest}])
            )[0]

        self.assertEqual(opportunity.close_date, "2027-03-15")
        close_provenance = opportunity.extra["page_field_provenance"]["close_date"]
        self.assertIn("applications are due", close_provenance["source_excerpt"])

    def test_private_page_does_not_promote_opening_or_preliminary_date(self):
        digest = """
        <p><b><u>External Funding</u></b></p>
        <p><b>Sloan Research Fellowship</b></p>
        <p><a href="https://sloan.org/fellowships">Sponsor website</a></p>
        <p><b>Synopsis:</b> Early-career research fellowship.</p>
        """
        page = """
        <html><body>
          <p>Nominations open September 1, 2026.</p>
          <p>Letter of intent deadline: October 1, 2026.</p>
        </body></html>
        """

        class Response:
            url = "https://sloan.org/fellowships"
            headers = {"content-type": "text/html; charset=utf-8"}
            content = page.encode()
            text = page

            @staticmethod
            def raise_for_status():
                return None

        with patch.dict(os.environ, {"VPR_ENRICH_LINKS": "true"}), patch(
            "scripts.sources.adapters.vpr_email.requests.get",
            return_value=Response(),
        ):
            opportunity = list(
                VPREmailAdapter().parse([{"stream": "vpr", "body": digest}])
            )[0]

        self.assertIsNone(opportunity.close_date)
        self.assertNotIn(
            "close_date",
            opportunity.extra.get("page_field_provenance", {}),
        )

    def test_blocked_private_page_keeps_the_sponsor_and_email_fields(self):
        digest = """
        <p><b><u>External Funding</u></b></p>
        <p><b>ACS Petroleum Research Fund Doctoral New Investigator</b></p>
        <p><a href="https://www.acs.org/funding/grants/petroleum-research-fund/programs/doctoral-new-investigator-grants.html">Sponsor website</a></p>
        <p><b>Deadline:</b> October 23, 2026</p>
        <p><b>Amount:</b> up to $110,000</p>
        """

        adapter = VPREmailAdapter()
        with patch.dict(os.environ, {"VPR_ENRICH_LINKS": "true"}), patch(
            "scripts.sources.adapters.vpr_email.requests.get",
            side_effect=ValueError("sponsor blocks automated retrieval"),
        ):
            opportunity = list(adapter.parse([{"stream": "vpr", "body": digest}]))[0]

        self.assertEqual(
            opportunity.agency,
            "American Chemical Society Petroleum Research Fund",
        )
        self.assertEqual(opportunity.close_date, "2026-10-23")
        self.assertEqual(opportunity.award_ceiling, "110000")
        self.assertEqual(adapter.diagnostics["private_link_enrichment"]["failed"], 1)

    def _message(self, sender, subject, body, subtype="plain"):
        message = EmailMessage()
        message["From"] = sender
        message["To"] = "funding-mailbox@example.org"
        message["Subject"] = subject
        message.set_content(body, subtype=subtype)
        return message.as_bytes()

    def test_mailbox_fetch_requires_and_classifies_both_streams(self):
        raw_messages = {
            b"1": self._message(
                "VPR_Funding_Opps@lists.rochester.edu",
                "Weekly funding opportunity",
                self.vpr_single,
            ),
            b"2": self._message(
                "Cindy Gary <cindy.gary@rochester.edu>",
                "Updates, Events, Funding opportunities",
                self.cindy_digest,
                subtype="html",
            ),
        }

        class FakeMailbox:
            def __init__(self, _host):
                pass

            def login(self, _user, _password):
                return "OK", []

            def select(self, _folder, readonly=True):
                return "OK", []

            def search(self, *_args):
                return "OK", [b"1 2"]

            def fetch(self, message_id, _query):
                return "OK", [(b"RFC822", raw_messages[message_id])]

            def logout(self):
                return "BYE", []

        adapter = VPREmailAdapter()
        environment = {
            "VPR_IMAP_USER": "funding-mailbox@example.org",
            "VPR_IMAP_PASS": "test-only",
            "VPR_REQUIRED_STREAMS": "vpr,cindy",
        }
        with patch.dict(os.environ, environment, clear=False), patch(
            "imaplib.IMAP4_SSL", FakeMailbox
        ):
            payload = adapter.fetch()

        self.assertEqual([item["stream"] for item in payload], ["vpr", "cindy"])
        self.assertEqual(adapter.diagnostics["missing_streams"], [])
        self.assertEqual(
            adapter.diagnostics["streams"]["vpr"]["accepted_messages"], 1)
        self.assertEqual(
            adapter.diagnostics["streams"]["cindy"]["accepted_messages"], 1)

    def test_combined_adapter_records_per_stream_diagnostics(self):
        adapter = VPREmailAdapter()
        adapter.diagnostics = {
            "required_streams": ["vpr", "cindy"],
            "streams": {
                "vpr": {"sender_messages": 1, "accepted_messages": 1,
                        "parsed_records": 0, "empty_messages": 0},
                "cindy": {"sender_messages": 1, "accepted_messages": 1,
                          "parsed_records": 0, "empty_messages": 0},
            },
        }
        records = list(adapter.parse([
            {"stream": "vpr", "body": self.vpr_single},
            {"stream": "cindy", "body": self.cindy_digest},
        ]))
        self.assertEqual(len(records), 2)
        self.assertEqual(adapter.diagnostics["streams"]["vpr"]["parsed_records"], 1)
        self.assertEqual(adapter.diagnostics["streams"]["cindy"]["parsed_records"], 1)
        self.assertEqual(adapter.diagnostics["parse_failed_streams"], [])

    def test_accepted_stream_that_stops_parsing_fails_closed(self):
        adapter = VPREmailAdapter()
        adapter.diagnostics = {
            "required_streams": ["vpr", "cindy"],
            "streams": {
                "vpr": {"sender_messages": 1, "accepted_messages": 1,
                        "parsed_records": 0, "empty_messages": 0},
                "cindy": {"sender_messages": 1, "accepted_messages": 1,
                          "parsed_records": 0, "empty_messages": 0},
            },
        }
        with self.assertRaisesRegex(ValueError, "cindy"):
            list(adapter.parse([
                {"stream": "vpr", "body": self.vpr_single},
                {"stream": "cindy", "body": "Funding newsletter with a new layout"},
            ]))
        self.assertEqual(adapter.diagnostics["parse_failed_streams"], ["cindy"])

    def test_registry_preserves_safe_stream_diagnostics(self):
        class DiagnosticAdapter(VPREmailAdapter):
            def fetch(self):
                self.diagnostics = {"streams": {"vpr": {"accepted_messages": 1}}}
                return []

            def parse(self, payload):
                return []

        _, results = collect(adapters=[DiagnosticAdapter()])
        self.assertTrue(results[0].ok)
        self.assertEqual(
            results[0].diagnostics["streams"]["vpr"]["accepted_messages"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
