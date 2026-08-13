from datetime import datetime, timezone
import unittest

from scripts.enrich_catalog import (
    compact_detail,
    description_spacing_issue_count,
    empty_cache,
    enrich_catalog,
    extract_nsf_synopsis,
    merge_detail,
    select_primary_document,
)
from scripts.nsf_funding import parse_nsf_funding_page


def base_record():
    return {
        "opportunity_id": "360001",
        "opportunity_number": "TEST-FOA-26-001",
        "title": "Evidence-aware funding opportunity",
        "agency": "Test Agency",
        "agency_code": "TEST",
        "status": "posted",
        "detail_page": "https://www.grants.gov/search-results-detail/360001",
        "funding_opportunity_url": None,
        "primary_document_url": None,
        "detail_enrichment_status": "pending",
        "last_updated": "2026-07-24",
        "version": "Synopsis 2",
        "close_date": "2026-09-30",
        "archive_date": "2026-10-30",
        "status_verification_required": False,
        "has_preliminary_stage": True,
        "deadlines": [
            {
                "kind": "application",
                "date": "2026-09-30",
                "time": None,
                "timezone": None,
                "estimated": False,
                "source": "Grants.gov XML extract",
                "source_url": (
                    "https://www.grants.gov/search-results-detail/360001"
                ),
                "confidence": "official_structured",
            }
        ],
        "award_floor": None,
        "award_ceiling": None,
        "total_program_funding": 5_000_000,
        "expected_number_of_awards": 5,
        "award_source": "Grants.gov XML extract",
    }


def detail_response(close_date="Sep 30, 2026 12:00:00 AM EDT"):
    return {
        "id": 360001,
        "revision": 3,
        "opportunityNumber": "TEST-FOA-26-001",
        "opportunityTitle": "Evidence-aware funding opportunity",
        "owningAgencyCode": "TEST",
        "docType": "synopsis",
        "synopsis": {
            "version": 3,
            "agencyCode": "TEST",
            "agencyName": "Test Agency",
            "synopsisDesc": (
                "Applicants must submit a letter of intent by "
                "August 1, 2026. Full applications support research."
            ),
            "responseDate": close_date,
            "responseDateDesc": (
                "Applications are due by 5:00 p.m. Eastern Time."
            ),
            "postingDate": "Jul 01, 2026 12:00:00 AM EDT",
            "lastUpdatedDate": "Jul 24, 2026 12:00:00 AM EDT",
            "awardFloor": "500000",
            "awardCeiling": "1000000",
            "estimatedFunding": "5000000",
            "numberOfAwards": "5",
            "costSharing": False,
            "agencyContactName": "Program Officer",
            "agencyContactEmail": "program@example.gov",
            "agencyContactPhone": "202-555-0100",
            "fundingDescLinkUrl": "https://agency.example.test/program",
        },
        "synopsisAttachmentFolders": [
            {
                "folderType": "Full Announcement",
                "folderName": "Current NOFO",
                "synopsisAttachments": [
                    {
                        "id": 9001,
                        "fileName": "Frequently_Asked_Questions.pdf",
                        "fileDescription": "FAQ",
                        "mimeType": "application/pdf",
                        "createdDate": "Jul 20, 2026 12:00:00 AM EDT",
                    },
                    {
                        "id": 9002,
                        "fileName": "Revised_NOFO.pdf",
                        "fileDescription": (
                            "Revised funding opportunity announcement"
                        ),
                        "mimeType": "application/pdf",
                        "createdDate": "Jul 24, 2026 12:00:00 AM EDT",
                    },
                ],
            }
        ],
        "synopsisDocumentURLs": [],
        "alns": [{"alnNumber": "00.001"}],
        "synopsisHistCount": 2,
        "synAttChangeComments": [{"comment": "Revised NOFO posted"}],
    }


class EnrichmentTests(unittest.TestCase):
    def test_extracts_authoritative_nsf_synopsis_without_breaking_inline_text(self):
        html = """
        <main>
          <div class="field field-funding-synopsis">
            <div class="label__above"><h2>Synopsis</h2></div>
            <p>The&nbsp;<strong>Thermal Transport Processes</strong>&nbsp;program
            supports new&nbsp;advances in thermal science.</p>
            <ul><li><strong>T</strong><strong>hermal systems</strong> matter.</li></ul>
          </div>
        </main>
        """

        synopsis = extract_nsf_synopsis(html)

        self.assertIn(
            "The Thermal Transport Processes program supports new advances",
            synopsis,
        )
        self.assertIn("• Thermal systems matter.", synopsis)
        self.assertNotIn("TheThermal", synopsis)
        self.assertNotIn("T hermal", synopsis)

    def test_detects_high_confidence_description_spacing_damage(self):
        damaged = (
            "TheThermal Transport Processesprogram supports research."
            "Projects should be clear;applications must be complete."
        )

        self.assertGreater(description_spacing_issue_count(damaged), 0)
        self.assertEqual(
            description_spacing_issue_count(
                "The Thermal Transport Processes program supports research."
            ),
            0,
        )

    def test_detects_archived_status_on_any_official_nsf_program_page(self):
        html = """
        <main>
          <h1>Decision, Risk and Management Sciences</h1>
          <h2>Status: Archived</h2>
          <h2>Archived funding opportunity</h2>
          <p>This document has been archived.</p>
          <div class="field-funding-synopsis">
            <h2>Synopsis</h2>
            <p>This NSF program supported fundamental research on decisions,
            risk, and management across social and economic systems.</p>
          </div>
          <h2>Program status: Archived</h2>
        </main>
        """

        page = parse_nsf_funding_page(html)

        self.assertEqual(page["status"], "archived")
        self.assertIn("fundamental research", page["text"])

    def test_checks_archive_marker_even_without_structured_synopsis(self):
        html = """
        <main>
          <h1>NSF-wide funding opportunity</h1>
          <p>Refer to the solicitation for the full program description.</p>
        </main>
        """

        page = parse_nsf_funding_page(html, require_synopsis=False)

        self.assertEqual(page["status"], "not_archived")
        self.assertEqual(page["text"], "")

    def test_selects_explicit_revised_nofo_instead_of_supplement(self):
        attachments = [
            {
                "file_name": "Frequently_Asked_Questions.pdf",
                "description": "FAQ",
                "mime_type": "application/pdf",
                "folder_name": "Current NOFO",
                "folder_type": "Full Announcement",
                "download_url": "https://example.test/faq",
            },
            {
                "file_name": "Revised_NOFO.pdf",
                "description": "Revised funding opportunity announcement",
                "mime_type": "application/pdf",
                "folder_name": "Current NOFO",
                "folder_type": "Full Announcement",
                "download_url": "https://example.test/nofo",
            },
        ]

        selected = select_primary_document(attachments)

        self.assertEqual(selected["url"], "https://example.test/nofo")
        self.assertEqual(selected["confidence"], "high")

    def test_compacts_and_merges_official_detail_evidence(self):
        record = base_record()
        now = datetime(2026, 7, 25, 14, tzinfo=timezone.utc)

        entry = compact_detail(record, detail_response(), now)
        merged = merge_detail(record, entry, now.date())

        self.assertEqual(
            merged["primary_document_url"],
            "https://grants.gov/grantsws/rest/opportunity/att/download/9002",
        )
        self.assertEqual(merged["award_floor"], 500_000)
        self.assertEqual(merged["award_ceiling"], 1_000_000)
        self.assertEqual(
            merged["award_source"],
            "Grants.gov XML extract + detail API",
        )
        self.assertEqual(merged["preliminary_deadline"], "2026-08-01")
        self.assertTrue(merged["preliminary_required"])
        self.assertEqual(
            merged["actionability_status"],
            "preliminary_deadline_upcoming",
        )
        self.assertEqual(merged["deadlines"][0]["time"].lower(), "5:00 p.m.")
        self.assertEqual(
            merged["deadlines"][0]["timezone"],
            "Eastern Time",
        )
        self.assertFalse(merged.get("deadline_conflict"))
        self.assertEqual(merged["contacts"][0]["email"], "program@example.gov")

    def test_surfaces_conflicting_structured_deadline(self):
        record = base_record()
        now = datetime(2026, 7, 25, 14, tzinfo=timezone.utc)
        entry = compact_detail(
            record,
            detail_response("Oct 01, 2026 12:00:00 AM EDT"),
            now,
        )

        merged = merge_detail(record, entry, now.date())

        self.assertEqual(
            merged["deadline_conflict"],
            {"xml": "2026-09-30", "api": "2026-10-01"},
        )
        self.assertTrue(merged["status_verification_required"])

    def test_reuses_unchanged_cached_detail_without_an_api_call(self):
        record = base_record()
        catalog = {
            "generated_at": "2026-07-25T14:00:00Z",
            "record_count": 1,
            "source": {"name": "Grants.gov"},
            "diagnostics": {},
            "opportunities": [record],
        }
        cache = empty_cache()
        calls = []

        def fetcher(opportunity_id):
            calls.append(opportunity_id)
            return {"data": detail_response()}

        enriched, cache = enrich_catalog(
            catalog,
            cache,
            max_updates=10,
            request_delay=0,
            fetcher=fetcher,
            now=datetime(2026, 7, 25, 14, tzinfo=timezone.utc),
        )
        enriched_again, cache = enrich_catalog(
            catalog,
            cache,
            max_updates=10,
            request_delay=0,
            fetcher=fetcher,
            now=datetime(2026, 7, 26, 14, tzinfo=timezone.utc),
        )

        self.assertEqual(calls, ["360001"])
        self.assertEqual(
            enriched["diagnostics"]["detail_enrichment"][
                "detail_enriched_count"
            ],
            1,
        )
        self.assertEqual(
            enriched_again["diagnostics"]["detail_enrichment"][
                "refreshed_count"
            ],
            0,
        )

    def test_replaces_damaged_grants_text_with_cached_official_nsf_synopsis(self):
        record = base_record()
        record.update(
            {
                "agency": "U.S. National Science Foundation",
                "agency_code": "NSF",
                "description": (
                    "TheThermal Transport Processesprogram supports "
                    "newadvances in thermal science."
                ),
            }
        )
        catalog = {
            "generated_at": "2026-07-25T14:00:00Z",
            "record_count": 1,
            "source": {"name": "Grants.gov"},
            "diagnostics": {},
            "opportunities": [record],
        }
        detail = detail_response()
        detail["synopsis"]["agencyName"] = (
            "U.S. National Science Foundation"
        )
        detail["synopsis"]["agencyDetails"] = {
            "agencyName": "U.S. National Science Foundation"
        }
        detail["synopsis"]["fundingDescLinkUrl"] = (
            "https://www.nsf.gov/funding/opportunities/thermal-processes"
        )
        detail_calls = []
        agency_calls = []

        def detail_fetcher(opportunity_id):
            detail_calls.append(opportunity_id)
            return {"data": detail}

        def agency_fetcher(url):
            agency_calls.append(url)
            return {
                "text": (
                    "The Thermal Transport Processes program supports new "
                    "advances in thermal science and engineering research."
                ),
                "source_url": (
                    "https://www.nsf.gov/funding/opportunities/"
                    "thermal-processes"
                ),
            }

        enriched, cache = enrich_catalog(
            catalog,
            empty_cache(),
            max_updates=10,
            max_agency_updates=10,
            request_delay=0,
            fetcher=detail_fetcher,
            agency_synopsis_fetcher=agency_fetcher,
            now=datetime(2026, 7, 25, 14, tzinfo=timezone.utc),
        )
        enriched_again, cache = enrich_catalog(
            catalog,
            cache,
            max_updates=10,
            max_agency_updates=10,
            request_delay=0,
            fetcher=detail_fetcher,
            agency_synopsis_fetcher=agency_fetcher,
            now=datetime(2026, 7, 26, 14, tzinfo=timezone.utc),
        )

        opportunity = enriched["opportunities"][0]
        self.assertEqual(detail_calls, ["360001"])
        self.assertEqual(len(agency_calls), 1)
        self.assertIn("The Thermal Transport Processes", opportunity["description"])
        self.assertEqual(
            opportunity["description_source"],
            "Official NSF funding page",
        )
        self.assertIn("thermal", enriched["search_index"]["postings"])
        self.assertEqual(
            enriched_again["opportunities"][0]["description"],
            opportunity["description"],
        )

    def test_backs_off_after_an_official_nsf_page_cannot_be_parsed(self):
        record = base_record()
        record.update(
            {
                "agency": "U.S. National Science Foundation",
                "agency_code": "NSF",
                "description": "TheBroken synopsis has spacing damage.",
            }
        )
        catalog = {
            "generated_at": "2026-07-25T14:00:00Z",
            "record_count": 1,
            "source": {"name": "Grants.gov"},
            "diagnostics": {},
            "opportunities": [record],
        }
        detail = detail_response()
        detail["synopsis"]["fundingDescLinkUrl"] = (
            "https://www.nsf.gov/funding/opportunities/missing-synopsis"
        )
        agency_calls = []

        def agency_fetcher(url):
            agency_calls.append(url)
            raise RuntimeError("no synopsis section")

        first, cache = enrich_catalog(
            catalog,
            empty_cache(),
            max_updates=10,
            max_agency_updates=10,
            request_delay=0,
            fetcher=lambda opportunity_id: {"data": detail},
            agency_synopsis_fetcher=agency_fetcher,
            now=datetime(2026, 7, 25, 14, tzinfo=timezone.utc),
        )
        second, cache = enrich_catalog(
            catalog,
            cache,
            max_updates=10,
            max_agency_updates=10,
            request_delay=0,
            fetcher=lambda opportunity_id: {"data": detail},
            agency_synopsis_fetcher=agency_fetcher,
            now=datetime(2026, 7, 26, 14, tzinfo=timezone.utc),
        )

        self.assertEqual(len(agency_calls), 1)
        self.assertEqual(
            first["diagnostics"]["detail_enrichment"][
                "agency_funding_page_failed_count"
            ],
            1,
        )
        self.assertEqual(
            second["diagnostics"]["detail_enrichment"][
                "agency_funding_page_failed_count"
            ],
            0,
        )

    def test_retains_nsf_archived_program_behind_an_archived_status(self):
        record = base_record()
        record.update(
            {
                "title": "Decision, Risk and Management Sciences",
                "opportunity_number": "PD-XX-0001",
                "agency": "U.S. National Science Foundation",
                "agency_code": "NSF-SBE",
                "description": "A current-looking Grants.gov description.",
                "close_date": None,
                "archive_date": None,
                "status_verification_required": True,
                "deadlines": [],
            }
        )
        catalog = {
            "generated_at": "2026-07-25T14:00:00Z",
            "record_count": 1,
            "source": {"name": "Grants.gov"},
            "diagnostics": {},
            "opportunities": [record],
        }
        detail = detail_response(close_date=None)
        detail["synopsis"]["fundingDescLinkUrl"] = (
            "https://www.nsf.gov/funding/opportunities/"
            "decision-risk-management-sciences"
        )

        enriched, _ = enrich_catalog(
            catalog,
            empty_cache(),
            max_updates=10,
            max_agency_updates=10,
            request_delay=0,
            fetcher=lambda opportunity_id: {"data": detail},
            agency_synopsis_fetcher=lambda url: {
                "text": "",
                "status": "archived",
                "source_url": url,
                "replacement_opportunity_number": None,
            },
            now=datetime(2026, 7, 25, 14, tzinfo=timezone.utc),
        )

        self.assertEqual(enriched["record_count"], 1)
        archived = enriched["opportunities"][0]
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(archived["actionability_status"], "archived_by_agency")
        self.assertEqual(enriched["facets"]["status"]["archived"], 1)
        self.assertIn("decision", enriched["search_index"]["postings"])
        self.assertEqual(
            enriched["diagnostics"]["detail_enrichment"][
                "agency_archived_count"
            ],
            1,
        )


if __name__ == "__main__":
    unittest.main()
