import json
from pathlib import Path
import unittest

from scripts.evaluate_phase2 import evaluate_exports, evaluate_paths, format_report


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "phase2_evaluation_export.json"
)


class Phase2EvaluationTests(unittest.TestCase):
    def test_separates_retrieval_and_reranking_metrics(self):
        summary = evaluate_paths([FIXTURE])

        self.assertEqual(summary["reviewed"], 6)
        self.assertEqual(summary["labels"]["useful"], 3)
        self.assertEqual(
            summary["retrieval"]["candidate_recall_at_32"],
            2 / 3,
        )
        self.assertEqual(summary["reranking"]["reviewed_in_ai_top_12"], 4)
        self.assertEqual(summary["reranking"]["precision_at_12"], 0.5)
        self.assertEqual(summary["reranking"]["mean_rank_improvement"], 2.25)
        self.assertEqual(summary["quality_errors"]["eligibility"], 1)
        self.assertEqual(summary["quality_errors"]["expired_or_closed"], 1)

    def test_aggregates_multiple_exports(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        summary = evaluate_exports([payload, payload])

        self.assertEqual(summary["exports"], 2)
        self.assertEqual(summary["reviewed"], 12)
        self.assertEqual(summary["labels"]["useful"], 6)
        self.assertEqual(
            summary["prompt_versions"]["phase2-profile-v1"],
            12,
        )

    def test_formats_missing_metrics_without_division_errors(self):
        summary = evaluate_exports([{
            "schema_version": 1,
            "prompt_version": "phase2-profile-v1",
            "feedback": [],
        }])
        report = format_report(summary)

        self.assertIn("Reviewed pairs: 0", report)
        self.assertIn("not available", report)


if __name__ == "__main__":
    unittest.main()
