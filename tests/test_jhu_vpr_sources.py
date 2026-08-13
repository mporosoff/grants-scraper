"""Regression coverage for the JHU and UR funding-email source adapters."""

from io import BytesIO
from datetime import date
from email.message import EmailMessage
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import openpyxl

from scripts.sources.adapters.jhu_fellowships import (
    JHUFellowshipsAdapter,
    MIN_ROWS_PER_AUDIENCE,
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
    def test_fetch_uses_official_fallbacks_and_requires_every_audience(self):
        adapter = JHUFellowshipsAdapter()

        def fake_get(url):
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

        def fake_get(url):
            if "/funding-opportunities/" in url or "Postdoc" in url:
                raise RuntimeError("blocked")
            return b"PK\x03\x04sanitized workbook"

        with patch.object(adapter, "_get", side_effect=fake_get):
            with self.assertRaisesRegex(RuntimeError, "Incomplete JHU workbook refresh"):
                adapter.fetch()
        self.assertIn("postdoc", adapter.diagnostics["download_failures"][0])

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
            source="UR VPR funding digest (limited submissions & foundations)",
            source_type="Internal",
        )

        self.assertNotIn("chemistry, computer science", " | ".join(record["disciplines"]))
        self.assertIn("Engineering and Physical Sciences", record["disciplines"])
        self.assertIn("Environmental and Life Sciences", record["disciplines"])

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
