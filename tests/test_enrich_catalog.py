from datetime import datetime, timezone
import unittest

from scripts.enrich_catalog import (
    compact_detail,
    empty_cache,
    enrich_catalog,
    merge_detail,
    select_primary_document,
)


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


if __name__ == "__main__":
    unittest.main()
