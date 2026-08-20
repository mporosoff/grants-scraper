import json
from pathlib import Path
import unittest

from scripts.subtopic_segmentation import SegmentationResult
from tools.run_p7_closeout import segmentation_summary


ROOT = Path(__file__).resolve().parents[1]
FRAME = ROOT / "evaluation" / "fm2_gate_frame.json"
RUNNER = ROOT / "tools" / "run_p7_closeout.py"
RESULT = ROOT / "evaluation" / "p7_closeout.json"


EXPECTED_NEGATIVES = [
    "345241", "355867", "356605", "357305", "360261", "362005",
    "362711", "363489", "334971", "339728", "348923", "349976",
    "356927", "359236", "359816", "362036", "362070", "362839",
    "362848", "363038", "363180", "363247", "363259", "363370",
    "363388", "363396", "363446", "363537", "363538", "363541",
    "363586", "45810", "351923",
]


class P7CloseoutRunnerTests(unittest.TestCase):
    def test_uses_the_exact_frozen_33_document_negative_set(self):
        frame = json.loads(FRAME.read_text(encoding="utf-8"))
        self.assertEqual(
            frame["populations"]["category_a_negative_ids"],
            EXPECTED_NEGATIVES,
        )
        self.assertEqual(len(set(EXPECTED_NEGATIVES)), 33)

    def test_runner_is_production_only(self):
        source = RUNNER.read_text(encoding="utf-8")
        for required in (
            "subtopic_segmentation", "segment_document", "build_records",
            "apply_gate", "publication_eligibility",
        ):
            self.assertIn(required, source)
        for forbidden in (
            "run_fm2_gate", "F1_LINE", "scan_f1", "fm2_measurement_only",
        ):
            self.assertNotIn(forbidden, source)

    def test_runner_writes_only_an_evaluation_artifact(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn('OUT = ROOT / "evaluation" / "p7_closeout.json"', source)
        self.assertNotIn('ROOT / "data" / "subtopic', source)

    def test_empty_result_reads_layers_from_diagnostics(self):
        result = SegmentationResult.empty(
            "no_layer_accepted", layers_attempted=("toc", "numbered")
        )
        self.assertEqual(
            segmentation_summary(result)["layers_attempted"],
            ["toc", "numbered"],
        )


class P7CloseoutOutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = json.loads(RESULT.read_text(encoding="utf-8"))
        cls.summary = cls.result["summary"]

    def test_all_33_sources_were_attempted_without_processing_errors(self):
        self.assertEqual(self.summary["documents_attempted"], 33)
        self.assertEqual(self.summary["documents_hash_verified"], 26)
        self.assertEqual(self.summary["source_hash_drift"], 7)
        self.assertEqual(self.summary["source_errors"], 0)
        self.assertEqual(self.summary["processing_errors"], 0)

    def test_final_production_emits_no_false_positive_children(self):
        self.assertEqual(self.summary["structural_candidate_sets"], 0)
        self.assertEqual(self.summary["structural_false_positive_children"], 0)
        self.assertEqual(self.summary["cov4_false_positive_children"], 0)
        self.assertEqual(self.summary["review_children"], 0)
        self.assertEqual(self.summary["publishable_children"], 0)
        self.assertEqual(self.summary["publishable_titles"], [])

    def test_hash_drift_is_preserved_as_drift_not_relabelled(self):
        self.assertEqual(
            self.summary["drift_ids"],
            ["355867", "357305", "349976", "356927", "359816", "45810", "351923"],
        )

    def test_no_classifier_was_needed_for_the_production_zeros(self):
        self.assertEqual(self.summary["classifier_calls"], 0)
        self.assertEqual(self.summary["classifier_errors"], 0)


if __name__ == "__main__":
    unittest.main()
