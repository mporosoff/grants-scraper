import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


class P10EvaluationTests(unittest.TestCase):
    def test_meas5_frame_is_additive_broad_and_frozen_before_results(self):
        frame_path = ROOT / "evaluation/meas5_query_set.json"
        frame_bytes = frame_path.read_bytes()
        frame = json.loads(frame_bytes)
        results = load("evaluation/meas5_results.json")
        disciplines = {item["discipline"] for item in frame["queries"]}

        self.assertEqual(len(frame["queries"]), 48)
        self.assertEqual(len(disciplines), 11)
        self.assertTrue(all(
            any(item["discipline"] == discipline and item["kind"] == "profile"
                for item in frame["queries"])
            for discipline in disciplines
        ))
        self.assertIn("before", frame["freeze_rule"])
        self.assertEqual(results["query_count"], len(frame["queries"]))
        self.assertEqual(results["discipline_count"], len(disciplines))
        self.assertEqual(
            results["frame_sha256"], hashlib.sha256(frame_bytes).hexdigest()
        )
        self.assertEqual(
            {item["id"] for item in results["results"]},
            {item["id"] for item in frame["queries"]},
        )
        review = load("evaluation/meas5_movement_review.json")
        self.assertEqual(len(review["reviews"]), 13)
        self.assertEqual(sum(review["classifications"].values()), 13)
        self.assertEqual(review["classifications"]["regression"], 0)

    def test_meas9_uses_real_crossref_path_and_preserves_query_admission(self):
        results = load("evaluation/meas9_results.json")
        route = results["real_orcid_route"]
        self.assertEqual(route["provider"], "Crossref")
        self.assertRegex(route["orcid"], r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
        self.assertGreater(route["imported_work_count"], 0)
        self.assertIn("assets/orcid.js fetchProfile", route["endpoint_contract"])

        self.assertEqual(len(results["arms"]), 8)
        for arm in results["arms"][:6]:
            self.assertEqual(arm["candidate_expansion_vs_query_only"], 0)
            self.assertTrue(all(
                not value for value in arm["false_positives_admitted"].values()
            ))
            self.assertTrue(all(
                anchor["admitted"]
                for anchor in arm["known_recall_anchors"].values()
            ))
        validation = results["explanation_validation"]
        self.assertGreater(validation["sample_count"], 0)
        self.assertEqual(validation["unsupported"], 0)
        self.assertEqual(validation["misleading"], 0)
        self.assertEqual(validation["disabled_source_mentions"], 0)
        self.assertEqual(validation["noncontributing_child_mentions"], 0)

    def test_meas10_records_the_human_dependency_without_fabricated_labels(self):
        status = load("evaluation/meas10_status.json")
        self.assertEqual(status["status"], "open_human_dependency")
        self.assertFalse(status["labels_available"])
        self.assertTrue(
            status["engineering_readiness"]["normal_product_rating_surface_absent"]
        )
        self.assertTrue(
            status["engineering_readiness"]["evaluation_rating_controls_available"]
        )
        self.assertIn("3-5 real researchers", status["exact_blocker"])
        self.assertIn("DEC-17", status["p11_gate"])


if __name__ == "__main__":
    unittest.main()
