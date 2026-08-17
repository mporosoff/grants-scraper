"""Provenance, confidence and Cov4 bypass for `native` ROSES records (§5.1).

These exist because §5.1's `native` rung was reachable but unexercised: nothing
passed the override, so "native records bypass the classifier" was a claim in a
document rather than a property of the code.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import subtopic_records as records  # noqa: E402
from scripts.sources.adapters import nasa_roses  # noqa: E402
from scripts.sources.adapters.nasa_roses import NasaRosesAdapter  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "roses"


def adapter():
    instance = NasaRosesAdapter.__new__(NasaRosesAdapter)
    from scripts.sources.base import SourceAdapter
    SourceAdapter.__init__(instance)
    instance._client = None
    return instance


def roses_rows():
    return adapter().rows(
        {"table3_html": (FIXTURES / "table3.html").read_text(encoding="utf-8")}
    )


class Result:
    """The minimum SegmentationResult surface build_records reads."""

    def __init__(self, subtopics=(), confidence="high", method="outline",
                 family="topic_area"):
        self.subtopics = tuple(subtopics)
        self.confidence = confidence
        self.method = method
        self.family = family
        self.diagnostics = {}


class NativeOverrideTests(unittest.TestCase):
    def test_the_override_path_is_exercised_not_merely_reachable(self):
        self.assertEqual(
            records.classify_provenance(None, override="native"), "native"
        )
        self.assertEqual(
            records.classify_provenance(None, override="referenced"), "referenced"
        )

    def test_the_pipeline_default_is_still_inferred(self):
        """A ROSES override must not quietly change everything else."""
        self.assertEqual(records.classify_provenance(Result()), "inferred")

    def test_an_unknown_rung_is_rejected(self):
        with self.assertRaises(ValueError):
            records.classify_provenance(None, override="authoritative")


class NativeConfidenceTests(unittest.TestCase):
    def test_a_valid_native_record_reaches_its_intended_confidence(self):
        self.assertEqual(records.cap_confidence("high", "native"), "high")

    def test_provenance_is_a_ceiling_not_an_assignment(self):
        """The whole point: a high rung does not promote a weak result."""
        self.assertEqual(records.cap_confidence("low", "native"), "low")
        self.assertEqual(records.cap_confidence("medium", "native"), "medium")
        self.assertEqual(records.cap_confidence("low", "referenced"), "low")

    def test_a_degraded_parse_cannot_be_high_just_because_it_is_native(self):
        """A native source with a broken parse is a failed parse (§5.1).

        The adapter's health check is what decides this, and an unhealthy parse
        must not be handed a `high` to cap.
        """
        instance = adapter()
        health = instance.check_health(
            {"table3_html": "<html><body><p>200 OK, no rows</p></body></html>",
             "table2_html": None}
        )
        self.assertFalse(health["healthy"])
        earned = "high" if health["healthy"] else "low"
        self.assertEqual(records.cap_confidence(earned, "native"), "low")

    def test_inferred_is_still_capped_at_medium(self):
        self.assertEqual(records.cap_confidence("high", "inferred"), "medium")


class NativeBypassesCov4Tests(unittest.TestCase):
    """Bypass proven in code, not asserted in a document."""

    def setUp(self):
        self.rows = roses_rows()
        _overview, elements = adapter().split_rows(self.rows)
        self.elements = elements
        # Pretend the first two elements matched catalog records.
        self.parents = {
            self.elements[0]["identity"]: "363224",
            self.elements[1]["identity"]: "363240",
        }

    def test_children_carry_native_provenance(self):
        children = adapter().subtopic_children(
            self.rows, parent_matches=self.parents, as_of="2026-08-17")
        self.assertEqual(len(children), 2)
        for child in children:
            self.assertEqual(child["subtopic_source"], "native")

    def test_no_family_and_no_segmentation_method_are_recorded(self):
        """Nothing inferred them, so neither field may claim a mechanism."""
        children = adapter().subtopic_children(
            self.rows, parent_matches=self.parents)
        for child in children:
            self.assertIsNone(child["pattern_family"])
            self.assertIsNone(child["segmentation_method"])

    def test_native_status_is_nasas_and_currentness_is_marked_derived(self):
        children = adapter().subtopic_children(
            self.rows, parent_matches=self.parents)
        native_values = {
            nasa_roses.NATIVE_DATED, nasa_roses.NATIVE_NOT_SOLICITED,
            nasa_roses.NATIVE_TBD, nasa_roses.NATIVE_NO_DUE_DATE,
            nasa_roses.NATIVE_FOLLOW_LINK, nasa_roses.NATIVE_NONE,
        }
        for child in children:
            self.assertIn(child["native_status"], native_values)
            self.assertIn(child["derived_currentness"],
                          {nasa_roses.DERIVED_OPEN, nasa_roses.DERIVED_CLOSED,
                           nasa_roses.DERIVED_UNDATED})
            # "closed" is derived and must never appear as a NASA status.
            self.assertNotEqual(child["native_status"], "closed")

    def test_the_segmenter_is_never_invoked_for_roses(self):
        """If ROSES ever routed through segmentation, this would fail."""
        import scripts.subtopic_segmentation as seg

        calls = []
        original = seg.segment_document
        seg.segment_document = lambda *a, **k: calls.append(a) or original(*a, **k)
        try:
            adapter().subtopic_children(self.rows, parent_matches=self.parents)
            adapter().standalone_inventory(self.rows)
            adapter().check_health(
                {"table3_html": (FIXTURES / "table3.html").read_text(
                    encoding="utf-8"), "table2_html": None})
        finally:
            seg.segment_document = original
        self.assertEqual(calls, [])


class InventoryStaysOutOfProductionTests(unittest.TestCase):
    def test_unmatched_elements_never_become_catalog_records(self):
        rows = roses_rows()
        instance = adapter()
        _overview, elements = instance.split_rows(rows)
        parents = {elements[0]["identity"]: "363224"}
        inventory = instance.standalone_inventory(
            rows, catalog_matches=set(parents))
        # The inventory is large and real...
        self.assertGreater(len(inventory), 50)
        # ...and still nothing reaches the catalog path.
        instance.fetch = lambda: {
            "table3_html": (FIXTURES / "table3.html").read_text(encoding="utf-8"),
            "table2_html": None, "year": 2025, "amendment": 69,
        }
        self.assertEqual(instance.collect(), [])
        self.assertEqual(list(instance.parse(instance.fetch())), [])

    def test_children_are_only_produced_for_matched_parents(self):
        rows = roses_rows()
        self.assertEqual(
            adapter().subtopic_children(rows, parent_matches={}), []
        )


if __name__ == "__main__":
    unittest.main()
