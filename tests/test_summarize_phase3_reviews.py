import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.summarize_phase3_reviews import (
    aggregate,
    load_exports,
    markdown_report,
    write_outputs,
)


def payload(review_id, exported_at, source_status="accurate"):
    return {
        "schema_version": 1,
        "kind": "funding_finder_phase3_deployment_review",
        "exported_at": exported_at,
        "review": {
            "review_id": review_id,
            "participant_code": "pilot-01",
            "overall_note": "The citation flow was quick.",
            "deployment_checks": {
                "search_worked": "yes",
                "citation_landed_correctly": "no",
            },
            "usage": {
                "searches": 4,
                "official_source_opens": 2,
            },
            "source_reviews": [
                {
                    "opportunity_id": "ABC-123",
                    "opportunity_number": "FOA-123",
                    "title": "Example opportunity",
                    "agency": "Example Agency",
                    "status": source_status,
                    "field": "deadline",
                    "note": "Checked against page 4.",
                    "document_url": "https://example.test/nofo.pdf",
                    "evidence_ids": ["evidence-1"],
                }
            ],
        },
        "match_feedback": [
            {
                "opportunity_id": "ABC-123",
                "label": "useful",
                "reason": "topic_fit",
            }
        ],
        "catalog": {
            "schema_version": 3,
            "record_count": 1465,
        },
        "deployment": {"app_version": "phase3-v1"},
    }


class Phase3ReviewSummaryTests(unittest.TestCase):
    def test_deduplicates_review_ids_using_the_latest_export(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            older = payload("review-1", "2026-07-26T12:00:00Z")
            newer = payload(
                "review-1",
                "2026-07-26T13:00:00Z",
                source_status="incorrect",
            )
            (root / "older.json").write_text(
                json.dumps(older),
                encoding="utf-8",
            )
            (root / "newer.json").write_text(
                json.dumps(newer),
                encoding="utf-8",
            )
            (root / "wrong.json").write_text(
                json.dumps({"schema_version": 1, "kind": "other"}),
                encoding="utf-8",
            )

            exports, failures = load_exports([root])
            summary = aggregate(exports, failures)

            self.assertEqual(len(exports), 1)
            self.assertEqual(summary["review_count"], 1)
            self.assertEqual(
                summary["source_status_counts"],
                {"incorrect": 1},
            )
            self.assertEqual(
                summary["failed_deployment_checks"],
                {"citation_landed_correctly": 1},
            )
            self.assertEqual(summary["usage_totals"]["searches"], 4)
            self.assertEqual(len(summary["invalid_files"]), 1)

    def test_writes_markdown_json_and_csv_reports(self):
        summary = aggregate(
            [payload("review-2", "2026-07-26T14:00:00Z")]
        )
        with TemporaryDirectory() as directory:
            markdown_path, json_path, csv_path = write_outputs(
                summary,
                directory,
            )

            self.assertTrue(markdown_path.is_file())
            self.assertTrue(json_path.is_file())
            self.assertTrue(csv_path.is_file())
            self.assertIn(
                "Verified source-fact accuracy: 100.0%",
                markdown_path.read_text(encoding="utf-8"),
            )
            self.assertIn(
                "ABC-123",
                csv_path.read_text(encoding="utf-8-sig"),
            )
            machine = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertNotIn("source_rows", machine)

    def test_markdown_handles_an_empty_summary(self):
        report = markdown_report(aggregate([]))
        self.assertIn("No source reviews were returned.", report)
        self.assertIn("No check was marked as failed.", report)


if __name__ == "__main__":
    unittest.main()
