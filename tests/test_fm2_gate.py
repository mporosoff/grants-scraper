"""Narrow tests for P7.4a's measurement-only F1 instrument."""

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import run_fm2_gate as gate  # noqa: E402


def containers(lines):
    return [{"page": 1, "section": None, "anchor": None,
             "text": "\n".join(lines)}]


class GrammarTests(unittest.TestCase):

    def test_only_the_four_frozen_bare_markers_match(self):
        lines = [
            "1. Alpha", "1) Beta", "1.) Gamma", "1 – Delta",
            "1.2 Decimal section", "Topic 1: Labelled", "A. Lettered",
        ]
        _flat, rows = gate.raw_candidates(containers(lines))
        self.assertEqual([row.title for row in rows],
                         ["Alpha", "Beta", "Gamma", "Delta"])

    def test_restarts_are_three_groups_not_one_failed_sequence(self):
        lines = []
        for size, label in ((15, "Center"), (3, "Institute"), (6, "Department")):
            for ordinal in range(1, size + 1):
                lines.extend([
                    f"{ordinal}. {label} {ordinal}",
                    "A substantive research description long enough to make the "
                    "span pass the existing production minimum. " * 5,
                ])
        _flat, rows = gate.raw_candidates(containers(lines))
        groups = gate.candidate_groups(rows)
        self.assertEqual([len(group) for _marker, group in groups], [15, 3, 6])

    def test_355150_explanatory_clause_is_not_part_of_the_title(self):
        self.assertEqual(
            gate.clean_title(
                "Autonomous platforms – The Army is particularly interested in research"
            ),
            "Autonomous platforms",
        )
        self.assertEqual(
            gate.clean_title("Artificial Intelligence (AI/ML) - The Army seeks work"),
            "Artificial Intelligence (AI/ML)",
        )

    def test_a_two_item_mechanism_still_fails_the_existing_floor(self):
        lines = [
            "1. Critical Conservation Area Funding Pool",
            "Description " * 80,
            "2. State and Multi-State Funding Pool",
            "Description " * 80,
        ]
        _flat, _rows, groups = gate.scan_f1(containers(lines))
        self.assertEqual(len(groups), 1)
        self.assertIn("min_candidates", groups[0]["failures"])
        self.assertFalse(groups[0]["admitted"])


class FrozenFrameTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.frame = json.loads(
            (ROOT / "evaluation" / "fm2_gate_frame.json").read_text(encoding="utf-8")
        )

    def test_the_named_negative_set_has_exactly_33_unique_documents(self):
        ids = self.frame["populations"]["category_a_negative_ids"]
        self.assertEqual(len(ids), 33)
        self.assertEqual(len(set(ids)), 33)
        self.assertEqual(self.frame["populations"]["eda_hazard_id"], "347414")

    def test_the_five_current_residual_records_are_not_substituted(self):
        self.assertEqual(
            self.frame["populations"]["residual_f1_ids"],
            ["332894", "345938", "328902", "355150", "362910"],
        )

    def test_330175_and_all_three_b0_notices_are_present(self):
        self.assertIn("330175", self.frame["populations"]["f1_validation_ids"])
        self.assertEqual(
            self.frame["populations"]["b0_administrative_ids"],
            ["356605", "362681", "356623"],
        )

    def test_human_truth_is_frozen_before_model_output(self):
        self.assertTrue(self.frame["frozen_before_outcomes"])
        self.assertEqual(
            sum(len(row.get("fundable_subjects", []))
                for row in self.frame["truth"].values()),
            58,
        )
        self.assertFalse(
            self.frame["stronger_770_precheck"]["reproducible_without_reconstruction"]
        )

    def test_the_measurement_tool_is_not_wired_into_production(self):
        for path in (
            ROOT / "scripts" / "subtopic_patterns.py",
            ROOT / "scripts" / "subtopic_segmentation.py",
            ROOT / "scripts" / "extract_document_evidence.py",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("fm2_measurement_only", source)
            self.assertNotIn("run_fm2_gate", source)


if __name__ == "__main__":
    unittest.main()
