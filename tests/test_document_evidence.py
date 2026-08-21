from datetime import datetime, timedelta, timezone
import io
import unittest
from unittest import mock

from pypdf import PdfWriter

from scripts.extract_document_evidence import (
    build_document_entry,
    empty_cache,
    enrich_document_evidence,
    extract_containers,
    extract_document_facts,
    merge_document_entry,
    parse_args,
    refresh_subtopics_without_source,
    source_for_record,
    source_signature,
    subtopic_only_candidates,
    validate_refresh_health,
)


NOTICE_HTML = b"""<!doctype html>
<html><body>
  <h1>Example Notice of Funding Opportunity</h1>
  <h2 id="key-dates">Key dates</h2>
  <p>A letter of intent must be submitted by August 1, 2026 at
  5:00 p.m. Eastern Time. Full applications are due September 30, 2026.</p>
  <h2 id="funding">Funding and period of performance</h2>
  <p>The individual award amount range is between $500,000 and $1 million.
  The agency expects to make approximately 5 awards. The project period is
  up to 36 months. Cost sharing is not required.</p>
  <h2 id="application">Application package</h2>
  <p>The project narrative is limited to 20 pages. Include a budget narrative,
  data management plan, evaluation plan, and letters of support.</p>
  <h2 id="eligibility">Eligibility</h2>
  <p>Eligible applicants include public and private institutions of higher
  education.</p>
  <h2 id="review">Review criteria</h2>
  <p>Reviewers will consider significance, approach, and team capacity.</p>
  <h2 id="limits">Institutional limit</h2>
  <p>Applications are limited to one submission per institution.</p>
</body></html>"""


def base_record():
    return {
        "opportunity_id": "360001",
        "opportunity_number": "TEST-FOA-26-001",
        "title": "Citation-aware funding opportunity",
        "agency": "Test Agency",
        "status": "posted",
        "primary_document_url": "https://agency.example/notice.html",
        "primary_document_name": "notice.html",
        "funding_opportunity_url": None,
        "close_date": "2026-09-30",
        "last_updated": "2026-07-24",
        "api_revision": 2,
        "award_floor": None,
        "award_ceiling": None,
        "status_verification_required": False,
        "has_preliminary_stage": False,
        "limited_submission": False,
        "deadlines": [
            {
                "kind": "application",
                "date": "2026-09-30",
                "source": "Grants.gov XML extract",
                "confidence": "official_structured",
            }
        ],
        "description": "A test program for university researchers.",
        "topic_areas": [],
        "disciplines": [],
        "funding_categories": [],
        "funding_instruments": ["Grant"],
        "applicant_types": ["Institutions of higher education"],
    }


def response(content=NOTICE_HTML, etag='"notice-v1"'):
    return {
        "status_code": 200,
        "content": content,
        "url": "https://agency.example/notice.html",
        "content_type": "text/html; charset=utf-8",
        "etag": etag,
        "last_modified": "Sun, 26 Jul 2026 12:00:00 GMT",
    }


class DocumentEvidenceTests(unittest.TestCase):
    def test_reads_pdf_pages_without_retaining_the_source_file(self):
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        buffer = io.BytesIO()
        writer.write(buffer)

        containers, extraction = extract_containers(
            buffer.getvalue(),
            "application/pdf",
            "notice.pdf",
            "https://agency.example/notice.pdf",
        )

        self.assertEqual(extraction["content_kind"], "pdf")
        self.assertEqual(extraction["page_count"], 1)
        self.assertEqual(extraction["pages_with_text"], 0)
        self.assertEqual(containers, [])

    def test_extracts_high_value_facts_with_section_citations(self):
        record = base_record()
        containers, extraction = extract_containers(
            NOTICE_HTML,
            "text/html",
            "notice.html",
            record["primary_document_url"],
        )
        document = {
            "url": record["primary_document_url"],
            "name": "notice.html",
            "sha256": "abc123",
        }

        facts = extract_document_facts(
            record,
            containers,
            document,
            "2026-07-26T12:00:00Z",
        )
        by_type = {}
        for fact in facts:
            by_type.setdefault(fact["type"], []).append(fact)

        self.assertGreater(extraction["text_characters"], 300)
        deadlines = by_type["deadline"]
        self.assertEqual(
            {(fact["deadline_kind"], fact["date"]) for fact in deadlines},
            {
                ("letter_of_intent", "2026-08-01"),
                ("application", "2026-09-30"),
            },
        )
        self.assertEqual(
            by_type["award_range"][0]["value"],
            {"minimum": 500_000, "maximum": 1_000_000},
        )
        self.assertEqual(by_type["expected_awards"][0]["value"], 5)
        self.assertEqual(
            by_type["project_duration"][0]["value"],
            {"amount": 36, "unit": "months"},
        )
        self.assertEqual(by_type["page_limit"][0]["value"], 20)
        self.assertFalse(by_type["cost_share"][0]["value"])
        self.assertIn("limited_submission", by_type)
        self.assertTrue(
            all(
                fact["citation"]["citation_url"].startswith(
                    "https://agency.example/notice.html#"
                )
                for fact in facts
            )
        )
        self.assertTrue(
            all(fact["citation"]["quote"] for fact in facts)
        )

    def test_merges_cited_deadlines_without_replacing_structured_facts(self):
        record = base_record()
        now = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)
        entry, extracted = build_document_entry(
            record,
            {
                "url": record["primary_document_url"],
                "name": "notice.html",
                "kind": "primary_notice",
            },
            response(),
            None,
            now,
        )

        merged = merge_document_entry(record, entry)

        self.assertTrue(extracted)
        self.assertEqual(merged["document_evidence_status"], "current")
        self.assertEqual(len(merged["deadlines"]), 2)
        structured = next(
            deadline
            for deadline in merged["deadlines"]
            if deadline["kind"] == "application"
        )
        self.assertEqual(structured["date"], "2026-09-30")
        self.assertIn("citation", structured)
        self.assertTrue(merged["has_preliminary_stage"])
        self.assertTrue(merged["limited_submission"])
        self.assertEqual(
            merged["limited_submission_review"]["status"],
            "needs_review",
        )
        self.assertIn("project narrative", merged["document_search_text"].lower())

    def test_incremental_pipeline_reuses_and_versions_documents(self):
        record = base_record()
        catalog = {
            "schema_version": 3,
            "generated_at": "2026-07-26T12:00:00Z",
            "record_count": 1,
            "source": {"name": "Grants.gov"},
            "diagnostics": {},
            "opportunities": [record],
        }
        cache = empty_cache()
        calls = []

        def first_fetcher(url, headers):
            calls.append((url, headers))
            return response()

        first, cache = enrich_document_evidence(
            catalog,
            cache,
            max_documents=5,
            request_delay=0,
            recheck_days=14,
            fetcher=first_fetcher,
            now=datetime(2026, 7, 26, 12, tzinfo=timezone.utc),
        )
        within_window, cache = enrich_document_evidence(
            catalog,
            cache,
            max_documents=5,
            request_delay=0,
            recheck_days=14,
            fetcher=first_fetcher,
            now=datetime(2026, 7, 27, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            first["diagnostics"]["document_evidence"][
                "document_current_count"
            ],
            1,
        )
        self.assertEqual(
            within_window["diagnostics"]["document_evidence"][
                "refreshed_count"
            ],
            0,
        )

        revised_html = NOTICE_HTML.replace(
            b"September 30, 2026",
            b"October 15, 2026",
        )

        def revised_fetcher(url, headers):
            calls.append((url, headers))
            self.assertEqual(headers["If-None-Match"], '"notice-v1"')
            return response(revised_html, '"notice-v2"')

        revised, cache = enrich_document_evidence(
            catalog,
            cache,
            max_documents=5,
            request_delay=0,
            recheck_days=14,
            fetcher=revised_fetcher,
            now=datetime(2026, 7, 26, 12, tzinfo=timezone.utc)
            + timedelta(days=15),
        )

        evidence = revised["opportunities"][0]["document_evidence"]
        self.assertEqual(evidence["document"]["version"], 2)
        self.assertTrue(evidence["document"]["changed_since_previous"])
        self.assertTrue(
            any(
                item["type"] == "amendment"
                for item in evidence["review_queue"]
            )
        )
        self.assertTrue(
            any(
                item["type"] == "deadline_conflict"
                for item in evidence["review_queue"]
            )
        )
        self.assertEqual(
            revised["search_index"]["document_count"],
            revised["record_count"],
        )

    def test_prunes_cached_records_absent_from_the_current_catalog(self):
        cache = empty_cache()
        cache["records"]["old"] = {
            "status": "current",
            "checked_at": "2026-07-01T00:00:00Z",
            "document": {"sha256": "old"},
        }
        catalog = {
            "schema_version": 3,
            "generated_at": "2026-07-26T12:00:00Z",
            "record_count": 0,
            "source": {},
            "diagnostics": {},
            "opportunities": [],
        }

        _, cache = enrich_document_evidence(
            catalog,
            cache,
            max_documents=0,
            request_delay=0,
            now=datetime(2026, 7, 26, 12, tzinfo=timezone.utc),
        )

        self.assertNotIn("old", cache["records"])

    def test_never_processed_agency_pages_are_not_starved_by_rechecks(self):
        primary = base_record()
        agency = {
            **base_record(),
            "opportunity_id": "360002",
            "opportunity_number": "TEST-FOA-26-002",
            "primary_document_url": None,
            "primary_document_name": None,
            "funding_opportunity_url": "https://agency.example/program",
            "close_date": None,
            "deadlines": [],
            "status_verification_required": True,
        }
        catalog = {
            "schema_version": 3,
            "generated_at": "2026-07-26T12:00:00Z",
            "record_count": 2,
            "source": {},
            "diagnostics": {},
            "opportunities": [primary, agency],
        }
        cache = empty_cache()
        primary_source = source_for_record(primary)
        cache["records"]["360001"] = {
            "source_signature": source_signature(primary, primary_source),
            "checked_at": "2026-06-01T12:00:00Z",
            "status": "current",
            "last_error": None,
            "document": {
                "url": primary_source["url"],
                "name": primary_source["name"],
                "source_kind": "primary_notice",
                "sha256": "old",
                "version": 1,
            },
            "facts": [],
            "review_queue": [],
            "version_history": [],
        }
        calls = []

        def fetcher(url, headers):
            calls.append(url)
            return response()

        enrich_document_evidence(
            catalog,
            cache,
            max_documents=1,
            request_delay=0,
            recheck_days=14,
            fetcher=fetcher,
            now=datetime(2026, 7, 26, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(calls, ["https://agency.example/program"])

    def test_refresh_health_fails_on_a_systemic_document_outage(self):
        with self.assertRaisesRegex(RuntimeError, "health check"):
            validate_refresh_health(
                {
                    "refreshed_count": 1,
                    "not_modified_count": 0,
                    "failed_request_count": 9,
                }
            )
        validate_refresh_health(
            {
                "refreshed_count": 8,
                "not_modified_count": 0,
                "failed_request_count": 2,
            }
        )


class SubtopicOnlyCandidateTests(unittest.TestCase):
    """§18.1 Cov1, and §0.5 -- the flag-off path must not notice this exists."""

    def declined_record(self):
        # No primary document and no gap-fill needed, so source_for_record()
        # returns None: the shape of 685 catalog records.
        record = base_record()
        record["primary_document_url"] = None
        record["primary_document_name"] = None
        record["funding_opportunity_url"] = "https://agency.example/program"
        record["award_floor"] = 100000
        record["close_date"] = "2026-09-30"
        return record

    def test_a_declined_record_is_a_subtopic_only_candidate(self):
        record = self.declined_record()
        self.assertIsNone(source_for_record(record))
        self.assertEqual(
            [oid for oid, _ in subtopic_only_candidates([record], enabled=True)],
            ["360001"],
        )

    def test_the_flag_off_produces_no_candidates_and_no_cache_key(self):
        record = self.declined_record()
        self.assertEqual(subtopic_only_candidates([record], enabled=False), [])
        store, metrics = refresh_subtopics_without_source(
            [record],
            max_documents=5,
            fetcher=lambda url, headers: response(),
            now=datetime(2026, 7, 26, 12, tzinfo=timezone.utc),
            enabled=False,
        )
        self.assertEqual(store, {})
        self.assertEqual(metrics["attempted"], 0)

    def test_a_reachable_record_is_never_a_subtopic_only_candidate(self):
        # base_record() has a primary document, so the administrative path
        # already fetches it and this path must not fetch it twice.
        self.assertEqual(
            subtopic_only_candidates([base_record()], enabled=True), []
        )

    def test_the_flag_off_refresh_adds_no_subtopic_only_key(self):
        record = self.declined_record()
        catalog = {
            "schema_version": 3,
            "record_count": 1,
            "source": {"name": "Grants.gov"},
            "diagnostics": {},
            "opportunities": [record],
        }
        _output, cache = enrich_document_evidence(
            catalog,
            empty_cache(),
            max_documents=5,
            request_delay=0,
            recheck_days=14,
            fetcher=lambda url, headers: response(),
            now=datetime(2026, 7, 26, 12, tzinfo=timezone.utc),
        )
        self.assertNotIn("subtopic_only", cache)


class DocumentBudgetTests(unittest.TestCase):
    def declined_records(self, count):
        records = []
        for index in range(count):
            record = base_record()
            record["opportunity_id"] = f"declined-{index}"
            record["opportunity_number"] = f"DECLINED-{index}"
            record["primary_document_url"] = None
            record["primary_document_name"] = None
            record["funding_opportunity_url"] = (
                f"https://agency.example/program/{index}"
            )
            record["award_floor"] = 100000
            records.append(record)
        return records

    def test_default_budgets_preserve_both_established_pass_limits(self):
        args = parse_args([])
        self.assertEqual(args.max_documents, 45)
        self.assertEqual(args.max_subtopic_documents, 45)

    def test_explicit_budgets_are_independent(self):
        args = parse_args([
            "--max-documents", "3",
            "--max-subtopic-documents", "7",
        ])
        self.assertEqual(args.max_documents, 3)
        self.assertEqual(args.max_subtopic_documents, 7)

    def test_zero_subtopic_budget_attempts_nothing_and_reports_all_remaining(self):
        calls = []
        records = self.declined_records(3)
        with mock.patch(
            "scripts.extract_document_evidence.subtopic_fields",
            return_value={"subtopics": []},
        ):
            store, metrics = refresh_subtopics_without_source(
                records,
                max_documents=0,
                fetcher=lambda url, headers: calls.append(url),
                now=datetime(2026, 7, 26, 12, tzinfo=timezone.utc),
                enabled=True,
            )
        self.assertEqual(store, {})
        self.assertEqual(calls, [])
        self.assertEqual(metrics["attempted"], 0)
        self.assertEqual(metrics["remaining_update_count"], 3)

    def test_small_subtopic_budget_is_honored_and_accounted_separately(self):
        calls = []
        records = self.declined_records(3)

        def fetcher(url, _headers):
            calls.append(url)
            return response()

        with mock.patch(
            "scripts.extract_document_evidence.subtopic_fields",
            return_value={"subtopics": []},
        ):
            store, metrics = refresh_subtopics_without_source(
                records,
                max_documents=2,
                fetcher=fetcher,
                now=datetime(2026, 7, 26, 12, tzinfo=timezone.utc),
                enabled=True,
            )
        self.assertEqual(len(store), 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(metrics["attempted"], 2)
        self.assertEqual(metrics["remaining_update_count"], 1)


if __name__ == "__main__":
    unittest.main()
