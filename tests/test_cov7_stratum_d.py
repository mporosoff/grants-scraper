"""Cov7 -- the stratum-D measurement artifact, pinned.

Offline, and deliberately thin: Cov7 is a **measurement**, so what these tests
protect is the artifact's internal consistency and the discipline it claims,
never a production behaviour. The reads themselves were live and are not
reproducible without the network, exactly like the census, the survey and the
taxonomy before them.
"""

import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "evaluation" / "cov7_stratum_d.json"

NO_LIST = "genuine_no_enumerated_list"
MISS = "list_exists_generic_model_misses"
UNRESOLVED = "ambiguous_unresolved"


class ArtifactShapeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))

    def test_exactly_thirty_records_were_read(self):
        self.assertEqual(len(self.payload["records"]), 30)

    def test_every_record_carries_an_evidence_backed_category(self):
        for record in self.payload["records"]:
            self.assertIn(record["category"],
                          {NO_LIST, MISS, UNRESOLVED,
                           "list_exists_generic_model_recovers",
                           "source_or_evidence_unavailable",
                           "externally_delegated_hierarchy",
                           "implementation_defect"},
                          record["opportunity_id"])
            self.assertGreater(len(record["evidence"]), 40,
                               record["opportunity_id"])

    def test_the_counts_match_the_records(self):
        counted = {}
        for record in self.payload["records"]:
            counted[record["category"]] = counted.get(record["category"], 0) + 1
        self.assertEqual(counted, self.payload["category_counts"])
        self.assertEqual(counted, {NO_LIST: 27, MISS: 2, UNRESOLVED: 1})

    def test_the_draw_is_deterministic_and_documented(self):
        frame = self.payload["frame"]
        self.assertEqual(frame["seed"], 20260827)
        self.assertEqual(frame["cap_per_agency"], 2)
        self.assertEqual(frame["seats"], {"D-other": 28, "D-NIH": 2})
        self.assertEqual(frame["population"]["D"], 482)
        self.assertIn("exclusion_limitation", frame)

    def test_the_sample_is_split_as_the_seats_specify(self):
        split = {}
        for record in self.payload["records"]:
            split[record["sub_stratum"]] = split.get(record["sub_stratum"], 0) + 1
        self.assertEqual(split, {"D-other": 28, "D-NIH": 2})

    def test_no_record_was_drawn_twice(self):
        ids = [r["opportunity_id"] for r in self.payload["records"]]
        self.assertEqual(len(ids), len(set(ids)))


class MeasurementTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        cls.measurement = cls.payload["measurement"]

    def test_the_prior_is_the_committed_one_and_is_cited(self):
        prior = self.measurement["prior_committed"]
        self.assertEqual((prior["read"], prior["hits"]), (12, 1))
        self.assertIn("FAMILY_TAXONOMY", prior["source"])

    def test_the_combined_total_is_the_sum_of_its_parts(self):
        prior = self.measurement["prior_committed"]
        cov7 = self.measurement["cov7_only"]
        combined = self.measurement["combined_pooled"]
        self.assertEqual(combined["read"], prior["read"] + cov7["read"])
        self.assertEqual(combined["hits"], prior["hits"] + cov7["hits"])

    def test_the_hits_in_the_records_match_the_measurement(self):
        hits = [r for r in self.payload["records"] if r["category"] == MISS]
        self.assertEqual(len(hits), self.measurement["cov7_only"]["hits"])
        self.assertEqual({r["opportunity_id"] for r in hits},
                         {"359782", "363381"})

    def test_the_pooled_rate_carries_its_own_caveat(self):
        """Cov7 over-sampled D-other on purpose; the artifact must say so."""
        self.assertIn("over-sampled",
                      self.measurement["combined_pooled"]["caveat"])

    def test_the_sub_stratified_estimate_is_reported_with_its_sources(self):
        sub = self.measurement["sub_stratified"]
        self.assertEqual(sub["D-NIH"]["hits"], 0)
        self.assertEqual(sub["D-NIH"]["read"], 24)
        self.assertEqual(sub["D-other"]["hits"], 3)
        self.assertEqual(sub["D-other"]["read"], 37)
        for key in ("D-NIH", "D-other"):
            self.assertIn("reads_source", sub[key])
        # The sub-populations must add up to the frame.
        self.assertEqual(sub["D-NIH"]["catalog"] + sub["D-other"]["catalog"],
                         self.payload["frame"]["population"]["D"])

    def test_every_interval_is_a_wilson_interval_and_brackets_its_rate(self):
        for block in (self.measurement["combined_pooled"],
                      self.measurement["sub_stratified"]["D-NIH"],
                      self.measurement["sub_stratified"]["D-other"]):
            low, high = block["wilson"]
            self.assertLessEqual(low, high)
            rate = block["hits"] / block["read"]
            self.assertLessEqual(low, rate)
            self.assertGreaterEqual(high, rate)

    def test_the_bookkeeping_discrepancy_is_disclosed(self):
        self.assertIn("12", self.measurement["bookkeeping_discrepancy"])
        self.assertIn("13", self.measurement["bookkeeping_discrepancy"])


class GateSeparationTests(unittest.TestCase):
    """Extraction, review state and publication must stay distinguishable."""

    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))

    def test_no_record_is_recorded_as_a_miss_for_being_review_queued(self):
        """Cov6's rule: review-required is not extraction failure."""
        for record in self.payload["records"]:
            if record["category"] == MISS:
                self.assertEqual(record["pipeline"]["segmentation_spans"], 0,
                                 record["opportunity_id"])

    def test_the_pipeline_stages_are_recorded_separately_for_every_record(self):
        for record in self.payload["records"]:
            pipeline = record["pipeline"]
            for stage in ("source_available", "segmentation_spans",
                          "segmentation_reason", "cov4_invoked",
                          "publication_eligibility"):
                self.assertIn(stage, pipeline, record["opportunity_id"])

    def test_cov4_was_never_invoked_so_it_caused_no_loss(self):
        regressions = self.payload["regressions"]
        self.assertEqual(regressions["cov4_invoked_on"], 0)
        self.assertEqual(regressions["cov4_rejections_of_valid_segmentation"], 0)
        self.assertEqual(regressions["children_lost_rather_than_queued"], 0)
        self.assertIn("cannot exercise either gate", regressions["note"])
        for record in self.payload["records"]:
            self.assertFalse(record["pipeline"]["cov4_invoked"],
                             record["opportunity_id"])

    def test_format_blind_records_still_carry_a_judged_category(self):
        """Production reading nothing is not the same as there being nothing."""
        blind = [r for r in self.payload["records"]
                 if r["production_format_blind"]]
        self.assertGreaterEqual(len(blind), 5)
        for record in blind:
            self.assertNotEqual(record["category"],
                                "source_or_evidence_unavailable",
                                record["opportunity_id"])


if __name__ == "__main__":
    unittest.main()
