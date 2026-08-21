import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class P9ScoringFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.children = json.loads(
            (ROOT / "evaluation" / "p9_scoring_children.json").read_text(
                encoding="utf-8"
            )
        )
        cls.results = json.loads(
            (ROOT / "evaluation" / "p9_scoring_results.json").read_text(
                encoding="utf-8"
            )
        )

    def test_source_group_counts_pin_the_bounded_scoring_frame(self):
        self.assertEqual(self.children["record_count"], 306)
        self.assertEqual(
            self.children["source_group_counts"],
            {
                "arl_82": 82,
                "genesis_21_plus_98": 119,
                "hgeo_4_5_3": 12,
                "office_science_69_upper_bound": 69,
                "roses_10": 10,
                "tdac_14": 14,
            },
        )

    def test_fixture_identity_type_hashes_and_terms_are_bounded(self):
        records = self.children["records"]
        identities = [record["subtopic_id"] for record in records]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertTrue(all(record["child_type"] == "subject" for record in records))
        self.assertTrue(all(len(record["source_document_hash"]) == 64 for record in records))
        self.assertTrue(all(len(record["subtopic_terms"]) <= 400 for record in records))

    def test_genesis_hierarchy_is_explicit(self):
        genesis = [
            record for record in self.children["records"]
            if record["source_group"] == "genesis_21_plus_98"
        ]
        groups = [record for record in genesis if "parent_subtopic_id" not in record]
        focus = [record for record in genesis if "parent_subtopic_id" in record]
        self.assertEqual((len(groups), len(focus)), (21, 98))
        group_ids = {record["subtopic_id"] for record in groups}
        self.assertTrue(all(record["parent_subtopic_id"] in group_ids for record in focus))

    def test_scoring_gate_is_cardinality_invariant_and_fully_reviewed(self):
        self.assertTrue(self.results["anti_flooding"]["passed"])
        self.assertTrue(self.results["review_gate"]["passed"])
        self.assertEqual(self.results["totals"]["top_10_churn"], 10)
        self.assertEqual(self.results["totals"]["human_reviewed_top_10_movements"], 10)
        self.assertEqual(self.results["totals"]["unaccepted_top_10_movements"], 0)
        self.assertTrue(all(
            check["one_copy_rollup"] == check["one_hundred_copy_rollup"]
            for check in self.results["anti_flooding"]["checks"]
        ))

    def test_required_targeted_paths_are_present(self):
        kinds = {
            case["kind"] for case in self.results["cases"]
            if case["id"].startswith("p9")
        }
        self.assertEqual(
            kinds,
            {
                "many_children_office_science",
                "genesis_hierarchy",
                "tdac",
                "roses_native",
                "hgeo",
                "arl_many_children",
                "parent_without_children",
                "exact_opportunity_number",
                "broad_single_term",
                "multiword_technical",
                "acronym",
                "no_result",
                "profile",
            },
        )


if __name__ == "__main__":
    unittest.main()
