import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRAME = ROOT / "evaluation" / "fm2_gate_frame.json"
RUNNER = ROOT / "tools" / "run_p7_closeout.py"


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


if __name__ == "__main__":
    unittest.main()
