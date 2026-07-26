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

    def test_graded_labels_are_counted_and_positive_includes_strong(self):
        summary = evaluate_exports([{
            "schema_version": 1,
            "prompt_version": "phase2-profile-v1",
            "session": {"candidate_ids": ["A", "B", "C"]},
            "feedback": [
                {"opportunity_id": "A", "label": "strong",
                 "retrieval_rank": 1, "ai_rank": 1},
                {"opportunity_id": "B", "label": "partial",
                 "retrieval_rank": 2, "ai_rank": 2},
                {"opportunity_id": "C", "label": "not_relevant",
                 "retrieval_rank": 3, "ai_rank": 3},
            ],
        }])
        self.assertEqual(summary["labels"]["strong"], 1)
        self.assertEqual(summary["labels"]["partial"], 1)
        # "strong" counts as a positive (useful-tier) match in the AI top 12.
        self.assertEqual(summary["reranking"]["useful_in_ai_top_12"], 1)
        # mean graded relevance over strong(3), partial(1), not_relevant(0).
        self.assertAlmostEqual(summary["graded"]["mean_relevance"], 4 / 3)

    def test_graded_ndcg_penalises_bad_ordering(self):
        # A not-relevant item ranked above a strong item -> nDCG below 1.
        summary = evaluate_exports([{
            "schema_version": 1,
            "prompt_version": "phase2-profile-v1",
            "feedback": [
                {"opportunity_id": "X", "label": "not_relevant",
                 "retrieval_rank": 1, "ai_rank": 1},
                {"opportunity_id": "Y", "label": "strong",
                 "retrieval_rank": 2, "ai_rank": 2},
            ],
        }])
        self.assertAlmostEqual(
            summary["graded"]["retrieval_ndcg"], 0.6309, places=3)
        self.assertAlmostEqual(
            summary["graded"]["reranking_ndcg"], 0.6309, places=3)

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
