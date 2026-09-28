"""Offline contracts for interrupted notice work and safe recovery artifacts."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import extract_document_evidence as e
from scripts.document_work_budget import WorkTimedOut


class Budget:
    def __init__(self):
        self.stopped = False
        self.units = []

    def expired(self, finalize=False):
        return self.stopped and not finalize

    @contextmanager
    def guard(self, phase, opportunity_id="", **kwargs):
        self.units.append((phase, opportunity_id))
        yield


class DocumentEvidenceBudget(unittest.TestCase):
    now = datetime(2026, 9, 28, tzinfo=timezone.utc)

    def setUp(self):
        self.enterContext(patch.object(e, "build_search_index", return_value={}))
        self.enterContext(patch.object(e, "facet_counts", return_value={}))
        self.enterContext(patch.object(e, "source_for_record", side_effect=self.source))

    @staticmethod
    def record(identifier):
        return {"opportunity_id": identifier, "opportunity_number": identifier,
                "title": "Official notice", "status": "posted", "close_date": "2027-01-01",
                "description": "Research program", "topic_areas": [], "deadlines": [],
                "primary_document_url": "https://example.gov/" + identifier}

    @staticmethod
    def source(record):
        return {"url": record["primary_document_url"], "kind": "primary_notice", "name": "notice.html"}

    def entry(self, record):
        source = self.source(record)
        return {"status": "current", "checked_at": "2026-09-27T00:00:00Z", "facts": [],
                "program_areas": [], "review_queue": [], "document": {"url": source["url"], "sha256": "original"},
                "source_signature": e.source_signature(record, source),
                "parser_dependencies": e.parser_dependencies(), "extractor_identity": e.EXTRACTOR_IDENTITY,
                "deadline_extractor_identity": e.DEADLINE_EXTRACTOR_IDENTITY}

    def build(self, record, source, response, previous, now, **kwargs):
        entry = self.entry(record)
        entry["checked_at"] = e.iso_utc(now)
        return entry, True

    def enrich(self, records, cache=None, **kwargs):
        with patch.object(e, "build_document_entry", side_effect=self.build):
            return e.enrich_document_evidence({"opportunities": records}, cache or {"records": {}},
                now=self.now, request_delay=0, **kwargs)

    def test_live_timeout_escapes_broad_handler_and_next_notice_completes(self):
        records = [self.record("slow"), self.record("good")]
        def fetch(url, headers):
            if url.endswith("slow"):
                raise WorkTimedOut("notice_refresh", "slow")
            return {"status_code": 200}
        output, cache = self.enrich(records, work_budget=Budget(), fetcher=fetch)
        self.assertEqual(cache["records"]["slow"]["status"], "processing_incomplete")
        self.assertNotIn("checked_at", cache["records"]["slow"])
        self.assertEqual(cache["records"]["good"]["status"], "current")
        metrics = output["diagnostics"]["document_evidence"]
        self.assertEqual(metrics["remaining_update_count"], 1)
        self.assertEqual(metrics["processing"]["timed_out_count"], 1)
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            e.validate_refresh_health(metrics)

    def test_cached_reparse_timeout_keeps_original_receipt_and_does_not_fetch(self):
        record = self.record("cached")
        original = self.entry(record)
        original["parser_dependencies"] = {}
        def reparse(record, source, entry, now, structure_cache):
            entry["document"]["sha256"] = "half-mutated"
            raise WorkTimedOut("notice_reparse", "cached")
        with patch.object(e, "reparse_from_structure", side_effect=reparse):
            output, cache = self.enrich([record], {"records": {"cached": original}}, work_budget=Budget(),
                fetcher=lambda *_: self.fail("A timed-out reparse must not fetch"))
        retained = cache["records"]["cached"]
        self.assertEqual(retained["document"]["sha256"], "original")
        self.assertEqual(retained["checked_at"], "2026-09-27T00:00:00Z")
        self.assertIsNone(output["opportunities"][0]["document_evidence"])
        self.assertTrue(e.due_for_check(retained, retained["source_signature"], self.now, 14))

    def test_cached_projection_timeout_strips_owned_fields_and_preserves_structured_fields(self):
        record = self.record("cached")
        record.update(limited_submission=True, document_evidence={"source_fields": {
            "limited_submission": {"present": True, "value": False}}},
            deadlines=[{"date": "2027-01-01", "source": "structured"},
                       {"date": "2026-11-01", "evidence_id": "derived"}])
        original = self.entry(record)
        def quarantine(record, source, entry, structure_cache):
            entry["document"]["sha256"] = "half-mutated"
            raise WorkTimedOut("cached_projection", "cached")
        with patch.object(e, "quarantine_legacy_facts", side_effect=quarantine):
            output, cache = self.enrich([record], {"records": {"cached": original}}, work_budget=Budget(), max_documents=0)
        projected = output["opportunities"][0]
        self.assertFalse(projected["limited_submission"])
        self.assertEqual(projected["deadlines"], [{"date": "2027-01-01", "source": "structured"}])
        self.assertEqual(cache["records"]["cached"]["document"]["sha256"], "original")
        sidecar = {"records": {"cached": {"subtopics": [{"subtopic_id": "unchecked"}]}}}
        e.merge_subtopic_sidecar(sidecar, cache["records"].items(), {"cached"}, as_of="2026-09-28")
        self.assertEqual(sidecar["records"]["cached"]["subtopics"], [])

    def test_budget_expiry_counts_unprocessed_records_and_preserves_completed_work(self):
        records = [self.record(str(index)) for index in range(3)]
        budget = Budget()
        def fetch(*_):
            budget.stopped = True
            return {"status_code": 200}
        checkpoints = []
        output, cache = self.enrich(records, work_budget=budget, fetcher=fetch,
            checkpoint=lambda value: checkpoints.append(deepcopy(value)))
        metrics = output["diagnostics"]["document_evidence"]
        self.assertEqual(metrics["remaining_update_count"], 2)
        self.assertEqual(metrics["processing"]["deferred_count"], 2)
        self.assertEqual(cache["records"]["0"]["status"], "current")
        self.assertTrue(any(value["records"].get("0", {}).get("status") == "current" for value in checkpoints))
        self.assertNotIn("checked_at", cache["records"]["1"])

    def test_fallback_timeout_does_not_refresh_timestamp_and_remains_due(self):
        record = self.record("fallback")
        prior = {"status": "processing_incomplete", "checked_at": "2026-09-27T00:00:00Z", "subtopics": []}
        with patch.object(e, "source_for_record", return_value=None), \
                patch.object(e, "subtopic_fields", side_effect=WorkTimedOut("subtopic_notice", "fallback")), \
                patch("scripts.subtopic_sources.subtopic_only_primary", return_value=None):
            store, metrics = e.refresh_subtopics_without_source([record], max_documents=1, fetcher=lambda *_: {},
                now=self.now, enabled=True, previous_store={"fallback": prior}, work_budget=Budget())
        self.assertEqual(store["fallback"]["checked_at"], prior["checked_at"])
        self.assertEqual(metrics["remaining_update_count"], 1)
        self.assertEqual(metrics["processing"]["status"], "incomplete")

    def test_cached_preparation_timeout_does_not_commit_partial_mutation(self):
        record = self.record("cached")
        original = self.entry(record)
        original["program_areas"] = [{"label": "original"}]
        def prepare(entry):
            entry["program_areas"][0]["label"] = "half-mutated"
            raise WorkTimedOut("cached_preparation", "cached")
        with patch.object(e, "validated_program_area_hits", side_effect=prepare):
            output, cache = self.enrich([record], {"records": {"cached": original}},
                work_budget=Budget(), fetcher=lambda *_: self.fail("Interrupted preparation must not fetch"))
        self.assertEqual(cache["records"]["cached"]["program_areas"], [{"label": "original"}])
        self.assertEqual(output["diagnostics"]["document_evidence"]["remaining_update_count"], 1)

    def test_entrypoint_unblocks_only_after_complete_processing_and_health_validation(self):
        for status in ("complete", "incomplete"):
            with self.subTest(status=status):
                metrics = {"processing": {"status": status}, "document_current_count": 1,
                           "citation_fact_count": 0, "failed_request_count": 0, "remaining_update_count": 0}
                catalog = {"opportunities": [self.record("safe")], "record_count": 1,
                           "diagnostics": {"document_evidence": metrics}}
                args = SimpleNamespace(catalog=Path("unused"), cache=Path("unused-cache"),
                    revalidate_program_areas_only=False, max_documents=1, max_subtopic_documents=1,
                    request_delay=0, recheck_days=14, enable_subtopics=False, now=self.now,
                    structure_cache=Path("unused-structure"))
                snapshots = []
                with patch.object(e, "parse_args", return_value=args), patch.object(e, "read_catalog", return_value=catalog), \
                        patch.object(e, "read_cache", return_value={}), patch.object(e, "write_cache"), \
                        patch.object(e, "enrich_document_evidence", return_value=(catalog, {})), \
                        patch.object(e, "write_catalog", side_effect=lambda value, *_: snapshots.append(deepcopy(value))):
                    if status == "incomplete":
                        with self.assertRaisesRegex(RuntimeError, "incomplete"):
                            e.main(work_budget=Budget())
                    else:
                        e.main(work_budget=Budget())
                self.assertEqual([value["diagnostics"]["document_work"]["publication_safe"] for value in snapshots],
                                 [False, False] if status == "incomplete" else [False, False, True])

    def test_prior_incomplete_notice_outside_cap_keeps_health_closed(self):
        record = self.record("pending")
        prior = e.incomplete_entry(self.entry(record), "prior_timeout")
        output, _ = self.enrich([record], {"records": {"pending": prior}}, work_budget=Budget(), max_documents=0)
        metrics = output["diagnostics"]["document_evidence"]
        self.assertEqual(metrics["remaining_update_count"], 1)
        self.assertEqual(metrics["processing"]["deferred_count"], 1)
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            e.validate_refresh_health(metrics)
        # Ordinary count-limited backfill, without an interrupted prior unit,
        # keeps its established non-failing queue semantics.
        output, _ = self.enrich([record], work_budget=Budget(), max_documents=0)
        e.validate_refresh_health(output["diagnostics"]["document_evidence"])

    def test_prior_incomplete_fallback_outside_cap_remains_incomplete(self):
        record = self.record("fallback")
        prior = e.incomplete_entry({"checked_at": "2026-09-27T00:00:00Z"}, "prior_timeout")
        with patch.object(e, "source_for_record", return_value=None), \
                patch("scripts.subtopic_sources.subtopic_only_primary", return_value=None):
            _, metrics = e.refresh_subtopics_without_source([record], max_documents=0, fetcher=lambda *_: {},
                now=self.now, enabled=True, previous_store={"fallback": prior}, work_budget=Budget())
        self.assertEqual(metrics["remaining_update_count"], 1)
        self.assertEqual(metrics["processing"]["status"], "incomplete")
        self.assertEqual(metrics["processing"]["deferred_count"], 1)

    def test_prior_incomplete_fallback_is_not_lost_when_canonical_route_appears(self):
        record = self.record("new-route")
        prior = e.incomplete_entry({"checked_at": "2026-09-27T00:00:00Z"}, "prior_timeout")
        output, cache = self.enrich([record], {"records": {}, "subtopic_only": {"new-route": prior}},
            work_budget=Budget(), max_documents=0, max_subtopic_documents=0, enable_subtopics=True)
        self.assertEqual(cache["records"]["new-route"]["status"], "processing_incomplete")
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            e.validate_refresh_health(output["diagnostics"]["document_evidence"])

    def test_startup_marker_preserves_data_before_any_ledger_or_parser_setup(self):
        catalog = {"opportunities": [self.record("retained")], "generated_at": "unchanged",
                   "diagnostics": {"existing": {"ok": True}}}
        original = deepcopy(catalog)
        args = SimpleNamespace(catalog=Path("unused"))
        with patch.object(e, "parse_args", return_value=args), patch.object(e, "read_catalog", return_value=catalog), \
                patch.object(e, "write_catalog") as write, patch.object(e, "write_cache") as cache_write:
            e.mark_document_work_incomplete(phase="wrapper_setup")
        self.assertEqual(catalog["opportunities"], original["opportunities"])
        self.assertEqual(catalog["generated_at"], original["generated_at"])
        self.assertEqual(catalog["diagnostics"]["existing"], original["diagnostics"]["existing"])
        self.assertEqual(catalog["diagnostics"]["document_work"],
                         {"publication_safe": False, "phase": "wrapper_setup"})
        cache_write.assert_not_called()
        write.assert_called_once_with(catalog, args.catalog)

    def test_outer_fallback_only_adds_publication_block_and_preserves_all_data(self):
        catalog = {"opportunities": [self.record("retained")], "generated_at": "unchanged",
                   "diagnostics": {"existing": {"ok": True}}}
        expected = deepcopy(catalog)
        args = SimpleNamespace(catalog=Path("unused"))
        with patch.object(e, "parse_args", return_value=args), patch.object(e, "read_catalog", return_value=catalog), \
                patch.object(e, "write_catalog") as write, patch.object(e, "write_cache") as cache_write:
            self.assertEqual(e.safe_timeout_fallback(), 1)
        self.assertEqual(catalog["opportunities"], expected["opportunities"])
        self.assertEqual(catalog["generated_at"], "unchanged")
        self.assertEqual(catalog["diagnostics"]["existing"], {"ok": True})
        self.assertFalse(catalog["diagnostics"]["document_work"]["publication_safe"])
        cache_write.assert_not_called()
        write.assert_called_once_with(catalog, args.catalog)


if __name__ == "__main__":
    unittest.main()
