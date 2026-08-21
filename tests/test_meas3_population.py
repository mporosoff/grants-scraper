"""DEBT-9's closure test: the MEAS-3 population is frozen and reproducible.

Offline. These read the committed artifact; none of them fetches anything, which is
itself one of the properties being asserted — classification must be re-runnable
without the network, or the population is not frozen in any useful sense.

**What this does not claim.** It does not repair the loss of §11's 114-span
population, which was never committed and cannot be reconstructed (Cov5 changed
extraction after the fact). It prevents the *recurrence* of that loss.
"""

import json
import pathlib
import unittest

POPULATION = pathlib.Path(__file__).parent.parent / "evaluation" / "meas3_population.json"


class ArtifactShapeTests(unittest.TestCase):
    def setUp(self):
        self.raw = POPULATION.read_bytes()
        self.payload = json.loads(self.raw.decode("utf-8"))
        self.candidates = self.payload["candidates"]

    def test_the_artifact_is_committed_and_parses(self):
        self.assertTrue(POPULATION.exists())
        self.assertEqual(self.payload["schema_version"], 1)
        self.assertEqual(self.payload["candidate_count"], len(self.candidates))

    def test_every_candidate_carries_the_semantic_input_not_just_an_id(self):
        """Classification must not need the source document again."""
        for candidate in self.candidates:
            with self.subTest(candidate=candidate["candidate_id"]):
                self.assertTrue(candidate["title"])
                self.assertIsNotNone(candidate["excerpt"])
                self.assertTrue(candidate["parent_opportunity_id"])
                self.assertTrue(candidate["source_document_sha256"])

    def test_required_fields_are_present_on_every_candidate(self):
        required = {
            "candidate_id", "arm", "parent_opportunity_id",
            "parent_opportunity_number", "parent_title", "source_document_url",
            "source_document_name", "source_document_sha256", "subtopic_code",
            "title", "excerpt", "segmentation_method", "pattern_family",
            "provenance", "confidence_before_cov4", "truth_label", "truth_source",
        }
        for candidate in self.candidates:
            self.assertTrue(required <= set(candidate), required - set(candidate))

    def test_candidate_ids_are_unique_and_stable_in_shape(self):
        ids = [candidate["candidate_id"] for candidate in self.candidates]
        self.assertEqual(len(ids), len(set(ids)))
        for candidate in self.candidates:
            self.assertTrue(
                candidate["candidate_id"].startswith(
                    candidate["parent_opportunity_id"] + ":"
                )
            )

    def test_ordering_is_deterministic(self):
        keys = [
            (c["arm"], c["parent_opportunity_id"], c["candidate_id"])
            for c in self.candidates
        ]
        self.assertEqual(keys, sorted(keys))

    def test_serialization_is_stable_under_a_reload(self):
        """Byte-identical round trip: the artifact is canonical, not incidental."""
        again = json.dumps(self.payload, ensure_ascii=False, indent=2,
                           sort_keys=False) + "\n"
        self.assertEqual(again.encode("utf-8"), self.raw)

    def test_every_candidate_is_inferred_provenance(self):
        """Cov4's population is generic inference only, by construction."""
        for candidate in self.candidates:
            self.assertEqual(candidate["provenance"], "inferred")

    def test_arms_are_separately_identifiable(self):
        arms = {candidate["arm"] for candidate in self.candidates}
        self.assertTrue(arms <= {"A", "B"})
        self.assertIn("A", arms)

    def test_the_document_provenance_block_explains_every_parent(self):
        documented = {row["record_id"] for row in self.payload["documents"]}
        parents = {c["parent_opportunity_id"] for c in self.candidates}
        self.assertTrue(parents <= documented)
        for row in self.payload["documents"]:
            self.assertTrue(row["document_sha256"])
            self.assertIn(row["arm"], {"A", "B"})

    def test_the_artifact_records_that_it_is_not_comparable_to_section_11(self):
        """The honesty property, asserted so it cannot be quietly dropped."""
        self.assertIn("not_comparable_to", self.payload)
        self.assertIn("114", self.payload["not_comparable_to"])

    def test_arm_b_emptiness_is_recorded_rather_than_hidden(self):
        """Arm B's stress documents are declared even when they yield nothing.

        Measured: production accepts no spans from any of them today, so Cov4
        cannot be exercised on F1/F4 shapes until some mechanism produces
        candidates for them. That is a finding, and it must stay visible.
        """
        declared = set(self.payload["arm_b_records"])
        self.assertEqual(declared, {"363594", "330175", "362233"})
        documented = {
            row["record_id"]: row for row in self.payload["documents"]
            if row["arm"] == "B"
        }
        self.assertEqual(set(documented), declared)
        for record_id, row in documented.items():
            self.assertEqual(row["accepted_spans"], 0, record_id)
            self.assertEqual(row["reason"], "no_layer_accepted")


class GeneratorContractTests(unittest.TestCase):
    """The generator's determinism guarantees, without running it."""

    def test_the_generator_verifies_the_committed_digest(self):
        source = (pathlib.Path(__file__).parent.parent / "tools"
                  / "build_meas3_population.py").read_text(encoding="utf-8")
        self.assertIn("digest mismatch", source)
        self.assertIn("hashlib.sha256(content).hexdigest()", source)

    def test_the_generator_uses_the_production_segmentation_path(self):
        source = (pathlib.Path(__file__).parent.parent / "tools"
                  / "build_meas3_population.py").read_text(encoding="utf-8")
        self.assertIn("from scripts.subtopic_segmentation import", source)
        self.assertIn("segment_document(", source)
        self.assertIn("extract_containers(", source)

    def test_the_runner_freezes_its_configuration(self):
        source = (pathlib.Path(__file__).parent.parent / "tools"
                  / "run_meas3.py").read_text(encoding="utf-8")
        self.assertIn('MODEL = "claude-sonnet-5"', source)
        # `thinking` must be omitted, not disabled: that is the 88%-vs-54% setting.
        self.assertNotIn('"thinking"', source.split("PROMPT =")[0].replace(
            "# `thinking` deliberately omitted", ""
        ))
        self.assertIn("thinking_tokens", source)

    def test_the_runner_never_embeds_a_credential(self):
        source = (pathlib.Path(__file__).parent.parent / "tools"
                  / "run_meas3.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("ANTHROPIC_API_KEY")', source)
        self.assertNotIn("sk-ant", source)


if __name__ == "__main__":
    unittest.main()
