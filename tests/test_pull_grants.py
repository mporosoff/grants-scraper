from datetime import date, datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.pull_grants import (
    build_feed,
    normalize,
    parse_args,
    prepare_records,
    write_feed,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "grants_gov_opportunities.json"
)


class NormalizeTests(unittest.TestCase):
    def test_curated_api_fixture_normalizes_posted_and_forecast_records(self):
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

        records = [
            normalize(item["stub"], item["detail"])
            for item in fixture["opportunities"]
        ]

        self.assertEqual(
            [record["status"] for record in records],
            ["posted", "forecasted"],
        )
        self.assertTrue(all(record["source"] == "Grants.gov" for record in records))
        self.assertTrue(all(record["title"] for record in records))

    def test_normalizes_live_synopsis_field_names_and_attachment(self):
        stub = {
            "id": "347749",
            "number": "22-605",
            "title": "Chemistry program",
            "agency": "U.S. National Science Foundation",
            "agencyCode": "NSF",
            "openDate": "04/26/2023",
            "closeDate": "09/30/2026",
            "oppStatus": "posted",
            "docType": "synopsis",
            "cfdaList": ["47.049"],
        }
        detail = {
            "id": 347749,
            "opportunityNumber": "22-605",
            "opportunityTitle": "Division of Chemistry",
            "owningAgencyCode": "NSF",
            "docType": "synopsis",
            "synopsis": {
                "version": 9,
                "agencyCode": "NSF",
                "agencyName": "A contact accidentally supplied as agency",
                "agencyDetails": {
                    "agencyName": "U.S. National Science Foundation"
                },
                "synopsisDesc": "Research in chemical catalysis.",
                "responseDate": "Sep 30, 2026 12:00:00 AM EDT",
                "responseDateDesc": "Applications are due by 5:00 p.m. Eastern Time.",
                "postingDate": "Apr 26, 2023 12:00:00 AM EDT",
                "costSharing": False,
                "agencyContactName": "Dr. Program Officer",
                "agencyContactEmail": "program.officer@nsf.gov",
                "agencyContactPhone": "703-555-0100",
                "fundingDescLinkUrl": "https://www.nsf.gov/example",
                "applicantTypes": [{"description": "Higher education"}],
                "fundingActivityCategories": [{"description": "Science"}],
                "fundingInstruments": [{"description": "Grant"}],
            },
            "synopsisAttachmentFolders": [
                {
                    "folderType": "Full Announcement",
                    "folderName": "Current NOFO",
                    "synopsisAttachments": [
                        {
                            "id": 111111,
                            "fileName": "Attachment 01 FAQ Program.pdf",
                            "fileDescription": "Frequently asked questions",
                            "mimeType": "application/pdf",
                            "fileLobSize": 12345,
                        },
                        {
                            "id": 353260,
                            "fileName": "Open BAA.pdf",
                            "fileDescription": "Full announcement",
                            "mimeType": "application/pdf",
                            "fileLobSize": 378652,
                        }
                    ],
                }
            ],
            "synopsisDocumentURLs": [],
            "cfdas": [{"cfdaNumber": "47.049"}],
        }

        record = normalize(stub, detail)

        self.assertEqual(record["agency"], "U.S. National Science Foundation")
        self.assertEqual(record["agency_code"], "NSF")
        self.assertEqual(record["close_date_note"], detail["synopsis"]["responseDateDesc"])
        self.assertEqual(record["deadline_time"].lower(), "5:00 p.m.")
        self.assertEqual(record["deadline_timezone"], "Eastern Time")
        self.assertEqual(record["aln"], ["47.049"])
        self.assertEqual(record["all_attachments"][0]["folder_name"], "Current NOFO")
        self.assertTrue(record["nofo_pdf_url"].endswith("/353260"))
        self.assertEqual(record["primary_document_url"], record["nofo_pdf_url"])
        self.assertEqual(record["contacts"][0]["name"], "Dr. Program Officer")
        self.assertEqual(
            record["contacts"][0]["email"],
            "program.officer@nsf.gov",
        )

    def test_normalizes_forecast_field_family(self):
        stub = {
            "id": "355824",
            "number": "MP-CPI-25-001",
            "title": "Forecasted program",
            "agency": "Office of the Assistant Secretary for Health",
            "agencyCode": "HHS-OPHS",
            "openDate": "08/01/2024",
            "closeDate": "",
            "oppStatus": "forecasted",
            "docType": "forecast",
            "cfdaList": ["93.137"],
        }
        detail = {
            "id": 355824,
            "opportunityNumber": "MP-CPI-25-001",
            "opportunityTitle": "Forecasted program",
            "owningAgencyCode": "HHS-OPHS",
            "docType": "forecast",
            "forecast": {
                "version": 7,
                "postingDate": "Aug 01, 2024 12:00:00 AM EDT",
                "forecastDesc": "A forecast description suitable for matching.",
                "agencyCode": "HHS-OPHS",
                "agencyDetails": {
                    "agencyName": "Office of the Assistant Secretary for Health"
                },
                "estSynopsisPostingDate": "Aug 15, 2026 12:00:00 AM EDT",
                "estApplicationResponseDate": "Oct 15, 2026 12:00:00 AM EDT",
                "estApplicationResponseDateDesc": "Estimated application deadline.",
                "estAwardDate": "Jan 15, 2027 12:00:00 AM EST",
                "estProjectStartDate": "Mar 01, 2027 12:00:00 AM EST",
                "estimatedFunding": "5000000",
                "numberOfAwards": "9",
                "awardCeiling": "600000",
                "awardFloor": "450000",
                "costSharing": False,
            },
            "synopsisAttachmentFolders": [],
            "synopsisDocumentURLs": [],
            "alns": [{"alnNumber": "93.137"}],
        }

        record = normalize(stub, detail)

        self.assertEqual(record["description"], detail["forecast"]["forecastDesc"])
        self.assertEqual(
            record["estimated_posting_date"],
            detail["forecast"]["estSynopsisPostingDate"],
        )
        self.assertEqual(
            record["close_date"],
            detail["forecast"]["estApplicationResponseDate"],
        )
        self.assertEqual(record["estimated_award_date"], detail["forecast"]["estAwardDate"])
        self.assertEqual(
            record["estimated_project_start"],
            detail["forecast"]["estProjectStartDate"],
        )
        self.assertEqual(record["aln"], ["93.137"])

    def test_marks_open_until_superseded_as_rolling(self):
        record = normalize(
            {"id": "1", "oppStatus": "posted", "docType": "synopsis"},
            {
                "id": 1,
                "synopsis": {
                    "responseDateDesc": "Open until superseded",
                    "synopsisDesc": "Standing opportunity.",
                },
            },
        )

        self.assertTrue(record["rolling"])


class ArgumentTests(unittest.TestCase):
    def test_default_output_cannot_overwrite_production_catalog(self):
        args = parse_args([])

        self.assertEqual(args.output, Path("data/api-sample.js"))

    def test_small_live_run_arguments(self):
        args = parse_args(
            [
                "--search-term",
                "catalysis",
                "--max-opportunities",
                "3",
                "--output",
                "data/test-opportunities.js",
                "--min-records",
                "2",
            ]
        )

        self.assertEqual(args.search_terms, ["catalysis"])
        self.assertEqual(args.max_opportunities, 3)
        self.assertEqual(args.output, Path("data/test-opportunities.js"))
        self.assertEqual(args.min_records, 2)


class FeedTests(unittest.TestCase):
    def test_deduplicates_and_removes_expired_posted_opportunities(self):
        base = {
            "opportunity_id": "100",
            "opportunity_number": "DOE-TEST-1",
            "title": "Current opportunity",
            "status": "forecasted",
            "version": 1,
        }
        posted_revision = {
            **base,
            "opportunity_id": "101",
            "status": "posted",
            "version": 2,
            "close_date": "Dec 31, 2026 12:00:00 AM EST",
        }
        expired = {
            "opportunity_id": "200",
            "opportunity_number": "NSF-EXPIRED",
            "title": "Expired opportunity",
            "status": "posted",
            "close_date": "06/30/2026",
        }
        rolling = {
            **expired,
            "opportunity_id": "300",
            "opportunity_number": "DOD-ROLLING",
            "title": "Rolling opportunity",
            "rolling": True,
        }

        records, diagnostics = prepare_records(
            [base, posted_revision, expired, rolling],
            as_of=date(2026, 7, 25),
        )

        self.assertEqual(
            [record["opportunity_number"] for record in records],
            ["DOE-TEST-1", "DOD-ROLLING"],
        )
        self.assertEqual(records[0]["status"], "posted")
        self.assertEqual(diagnostics["deduplicated_count"], 1)
        self.assertEqual(diagnostics["closed_removed_count"], 1)

    def test_writes_versioned_javascript_feed(self):
        generated_at = datetime(2026, 7, 25, 14, 0, tzinfo=timezone.utc)
        records = [
            {
                "opportunity_id": "1",
                "opportunity_number": "TEST-1",
                "title": "Test &amp; <strong>opportunity</strong>",
                "status": "posted",
            }
        ]
        feed = build_feed(
            records,
            generated_at,
            ["catalysis"],
            {"closed_removed_count": 0},
        )

        with TemporaryDirectory() as directory:
            output = Path(directory) / "opportunities.js"
            write_feed(feed, output)
            javascript = output.read_text(encoding="utf-8")

        self.assertIn("globalThis.GRANT_MATCH_FEED =", javascript)
        self.assertIn('"schema_version": 1', javascript)
        self.assertIn('"generated_at": "2026-07-25T14:00:00Z"', javascript)
        self.assertIn('"record_count": 1', javascript)
        self.assertEqual(
            feed["opportunities"][0]["title"],
            "Test & opportunity",
        )


if __name__ == "__main__":
    unittest.main()
