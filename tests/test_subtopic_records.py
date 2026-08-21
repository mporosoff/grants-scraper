"""Subtopic cache tests: the backfill gate, §5.4 diff stability, record shape.

See docs/TOPIC_LAYER_PLAN.md §5.1, §5.3, §5.4, §8.3 and §18.1 item C1.
"""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures.minipdf import build_pdf, containers_from, heading, line  # noqa: E402

from scripts import subtopic_records as records  # noqa: E402
from scripts import subtopic_segmentation as seg  # noqa: E402


PDF = {"content_type": "application/pdf"}
PARENT = {
    "opportunity_id": "360678",
    "opportunity_number": "DE-FOA-0003600",
    "status": "posted",
    "agency": "Office of Science",
}
DOCUMENT = {
    "url": "https://example.gov/notices/foa.pdf",
    "sha256": "a" * 64,
}


def body_for(subject):
    return (
        f"This element supports fundamental studies of {subject}, including "
        f"operando characterization and reactor design relevant to {subject}. "
        f"Awards support single investigators and small teams pursuing "
        f"{subject} at laboratory scale, with catalytic chemistry throughout."
    )


def segmented(headings):
    pages = [[heading("Overview"), line("Program announcement overview.")]]
    for text in headings:
        pages.append([heading(text), line(body_for(text))])
    outline = [(text, index + 1, 0) for index, text in enumerate(headings)]
    return seg.segment_document(
        {}, build_pdf(pages, outline=outline), containers_from(pages), PDF
    )


HEADINGS = [
    "Topic Area 1 Electrocatalysis",
    "Topic Area 2 Membrane Separations",
    "Topic Area 3 Materials Discovery",
]


class NeedsSubtopicExtractionTests(unittest.TestCase):
    VERSION = "1.0.0+test"

    def call(self, entry, enabled=True, version=None):
        return records.needs_subtopic_extraction(
            entry, enabled=enabled, extractor_version=version or self.VERSION
        )

    def test_disabled_never_asks_for_work(self):
        self.assertFalse(self.call({"facts": []}, enabled=False))
        self.assertFalse(self.call(None, enabled=False))

    def test_a_missing_entry_is_not_backfill(self):
        # A full extraction is already happening for this document.
        self.assertFalse(self.call(None))

    def test_an_entry_that_never_attempted_segmentation_needs_it(self):
        self.assertTrue(self.call({"facts": [], "status": "current"}))

    def test_an_entry_from_an_older_extractor_needs_reprocessing(self):
        entry = {"subtopics": [], "subtopic_extractor_version": "0.9.0+old"}
        self.assertTrue(self.call(entry))

    def test_a_current_entry_needs_nothing(self):
        entry = {"subtopics": [], "subtopic_extractor_version": self.VERSION}
        self.assertFalse(self.call(entry))

    def test_an_empty_result_still_counts_as_attempted(self):
        # Zero subtopics is a normal outcome; it must not re-run every night.
        entry = {
            "subtopics": [],
            "subtopic_reason": "no_layer_accepted",
            "subtopic_extractor_version": self.VERSION,
        }
        self.assertFalse(self.call(entry))


class RecordShapeTests(unittest.TestCase):
    def setUp(self):
        self.result = segmented(HEADINGS)
        self.records = records.build_records(
            PARENT, self.result, document=DOCUMENT, as_of="2026-08-20"
        )

    def test_three_records_are_built(self):
        self.assertEqual(len(self.records), 3)

    def test_identity_fields(self):
        first = self.records[0]
        self.assertEqual(first["record_type"], "subtopic")
        self.assertEqual(first["subtopic_id"], "360678:ta-1")
        # The browser derives identity from opportunity_id || opportunity_number.
        self.assertEqual(first["opportunity_id"], first["subtopic_id"])
        self.assertEqual(first["parent_id"], "360678")
        self.assertEqual(first["parent_opportunity_number"], "DE-FOA-0003600")
        self.assertEqual(first["child_type"], "subject")

    def test_status_uses_the_catalog_vocabulary(self):
        # currentness.record_is_current accepts only posted/forecasted; a child
        # emitting anything else is filtered out of every feed as invalid_status.
        for record in self.records:
            self.assertEqual(record["status"], "posted")

    def test_evidence_anchor_and_provenance(self):
        first = self.records[0]
        self.assertEqual(first["evidence_anchor"], "p2")
        self.assertEqual(first["source_document_url"], DOCUMENT["url"])
        self.assertEqual(first["source_document_hash"], DOCUMENT["sha256"])
        self.assertEqual(first["segmentation_method"], "outline")
        self.assertEqual(first["pattern_family"], "topic_area")
        # §5.1: everything the segmentation pipeline produces is `inferred`,
        # because the recogniser did the asserting, not the notice. A Layer A
        # `outline` match at `high` is therefore capped to the rung's ceiling.
        # This assertion previously read "high"; the specification changed.
        self.assertEqual(first["subtopic_source"], "inferred")
        self.assertEqual(first["confidence"], "medium")

    def test_provenance_is_orthogonal_to_segmentation_method(self):
        """§5.1. Provenance says who asserted; the method says how we read it."""
        first = self.records[0]
        self.assertEqual(first["segmentation_method"], "outline")
        self.assertEqual(first["subtopic_source"], "inferred")
        # An adapter declaring `native` keeps its own method value untouched.
        native = records.build_records(
            PARENT, segmented(HEADINGS), document=DOCUMENT,
            as_of="2026-08-20", provenance="native",
        )
        self.assertEqual(native[0]["subtopic_source"], "native")
        self.assertEqual(native[0]["segmentation_method"], "outline")

    def test_provenance_bounds_confidence_and_never_raises_it(self):
        """§5.1: provenance supplies a ceiling, not a value."""
        # `native` may keep a `high` the adapter earned...
        native = records.build_records(
            PARENT, segmented(HEADINGS), document=DOCUMENT,
            as_of="2026-08-20", provenance="native",
        )
        self.assertEqual(native[0]["confidence"], "high")
        # ...but a rung never promotes: a low result stays low on any rung.
        self.assertEqual(records.cap_confidence("low", "native"), "low")
        self.assertEqual(records.cap_confidence("low", "referenced"), "low")
        # `inferred` is the one mechanical cap, and it is absolute.
        self.assertEqual(records.cap_confidence("high", "inferred"), "medium")
        self.assertEqual(records.cap_confidence("medium", "inferred"), "medium")

    def test_unknown_provenance_is_rejected(self):
        with self.assertRaises(ValueError):
            records.build_records(
                PARENT, segmented(HEADINGS), document=DOCUMENT,
                as_of="2026-08-20", provenance="official",
            )

    def test_both_vocabularies_are_populated(self):
        first = self.records[0]
        self.assertIn("Catalysis and reaction engineering", first["topic_areas"])
        self.assertIn("catalysis", first["program_area_labels"])

    def test_term_display_is_bounded_readable_and_display_only(self):
        first = self.records[0]
        self.assertLessEqual(len(first["term_display"]), 60)
        self.assertIn("electrocatalysi", first["term_display"])
        self.assertEqual(
            first["term_display"]["electrocatalysi"], "Electrocatalysis"
        )
        self.assertTrue(set(first["term_display"]).issubset(first["subtopic_terms"]))

    def test_parent_inherited_fields_are_not_duplicated(self):
        # §5.5: agency, award range and the filtering deadline are inherited by
        # the package E merge, never copied here, so they cannot disagree.
        for field in ("agency", "award_ceiling", "close_date", "deadlines"):
            self.assertNotIn(field, self.records[0])

    def test_extractor_version_is_recorded(self):
        self.assertTrue(self.records[0]["extractor_version"].startswith("1.0.0+"))


class DiffStabilityTests(unittest.TestCase):
    def setUp(self):
        self.result = segmented(HEADINGS)
        self.built = records.build_records(
            PARENT, self.result, document=DOCUMENT, as_of="2026-08-20"
        )

    def test_an_unchanged_rerun_does_not_touch_the_cache(self):
        cache = records.empty_cache()
        self.assertTrue(
            records.upsert_parent(cache, "360678", self.built, as_of="2026-08-20",
                                  method="outline")
        )
        later = records.build_records(
            PARENT, self.result, document=DOCUMENT, as_of="2026-09-01"
        )
        self.assertFalse(
            records.upsert_parent(cache, "360678", later, as_of="2026-09-01",
                                  method="outline"),
            "an unchanged rerun reported a change",
        )
        stored = cache["records"]["360678"]["subtopics"][0]
        self.assertEqual(
            stored["last_verified"], "2026-08-20",
            "last_verified moved without any other change (§5.4)",
        )

    def test_a_real_change_updates_last_verified(self):
        cache = records.empty_cache()
        records.upsert_parent(cache, "360678", self.built, as_of="2026-08-20",
                              method="outline")
        changed = segmented(
            [
                "Topic Area 1 Electrocatalysis",
                "Topic Area 2 Membrane Separations",
                "Topic Area 3 Materials Discovery and Synthesis",
            ]
        )
        later = records.build_records(
            PARENT, changed, document=DOCUMENT, as_of="2026-09-01"
        )
        self.assertTrue(
            records.upsert_parent(cache, "360678", later, as_of="2026-09-01",
                                  method="outline")
        )

    def test_identity_and_first_seen_survive_renumbering(self):
        cache = records.empty_cache()
        records.upsert_parent(cache, "360678", self.built, as_of="2026-08-20",
                              method="outline")
        # An amendment inserts a topic; everything below renumbers.
        amended = segmented(
            [
                "Topic Area 1 Electrocatalysis",
                "Topic Area 2 Direct Air Capture",
                "Topic Area 3 Membrane Separations",
                "Topic Area 4 Materials Discovery",
            ]
        )
        later = records.build_records(
            PARENT, amended, document=DOCUMENT, as_of="2026-09-01"
        )
        records.upsert_parent(cache, "360678", later, as_of="2026-09-01",
                              method="outline")

        stored = {r["title"]: r for r in cache["records"]["360678"]["subtopics"]}
        self.assertEqual(len(stored), 4)
        # Membrane Separations moved from ordinal 2 to 3 but keeps its identity
        # and its original first_seen.
        membranes = stored["Membrane Separations"]
        self.assertEqual(membranes["subtopic_id"], "360678:ta-2")
        self.assertEqual(membranes["subtopic_ordinal"], 3)
        self.assertEqual(membranes["first_seen"], "2026-08-20")

    def test_identity_does_not_change_when_the_parent_number_changes(self):
        renamed = dict(PARENT, opportunity_number="DE-FOA-0003600-AMENDMENT")
        later = records.build_records(
            renamed, segmented(HEADINGS), document=DOCUMENT, as_of="2026-09-01"
        )
        self.assertEqual(
            [item["subtopic_id"] for item in later],
            [item["subtopic_id"] for item in self.built],
        )

    def test_records_are_sorted_by_ordinal(self):
        cache = records.empty_cache()
        records.upsert_parent(
            cache, "360678", list(reversed(self.built)), as_of="2026-08-20",
            method="outline",
        )
        ordinals = [
            r["subtopic_ordinal"] for r in cache["records"]["360678"]["subtopics"]
        ]
        self.assertEqual(ordinals, sorted(ordinals))


class CacheIoTests(unittest.TestCase):
    def test_sidecar_trims_readable_terms_to_the_display_record_budget(self):
        cache = records.empty_cache()
        built = records.build_records(
            PARENT, segmented(HEADINGS), document=DOCUMENT, as_of="2026-08-20"
        )
        built[0]["summary"] = "A" * 600
        built[0]["term_display"] = {
            f"stem{index}": f"Readable scientific term {index}"
            for index in range(60)
        }
        built[0]["subtopic_terms"] = {
            f"stem{index}": 60 - index
            for index in range(60)
        }
        records.upsert_parent(
            cache, "360678", built, as_of="2026-08-20", method="outline"
        )

        stored = records.sidecar_payload(cache)["records"]["360678"]["subtopics"][0]
        display = {
            key: value for key, value in stored.items()
            if key in records.DISPLAY_RECORD_FIELDS
        }
        size = len(json.dumps(
            display, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8"))
        self.assertLessEqual(size, records.DISPLAY_RECORD_LIMIT_BYTES)
        self.assertLess(len(stored["term_display"]), 60)
        self.assertIn("stem0", stored["term_display"])
        self.assertNotIn("stem59", stored["term_display"])

    def test_round_trip_and_serialization_style(self):
        cache = records.empty_cache()
        result = segmented(HEADINGS)
        built = records.build_records(
            PARENT, result, document=DOCUMENT, as_of="2026-08-20"
        )
        records.upsert_parent(cache, "360678", built, as_of="2026-08-20",
                              method="outline")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "subtopics.js"
            records.write_cache(cache, path)
            raw = path.read_bytes()

            # §5.4: indented and key-sorted, because a human reads this diff.
            self.assertIn(b"globalThis.SUBTOPIC_CATALOG=", raw)
            self.assertIn(b'\n "records": {', raw)
            # LF on every platform, like write_catalog and write_cache already do.
            self.assertNotIn(b"\r\n", raw)
            self.assertTrue(raw.endswith(b"\n"))

            text = raw.decode("utf-8")
            payload = json.loads(
                text.split(records.SIDECAR_GLOBAL, 1)[1].rstrip(";\n")
            )
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(len(payload["records"]["360678"]["subtopics"]), 3)

            # Keys sorted throughout.
            first = payload["records"]["360678"]["subtopics"][0]
            self.assertEqual(list(first), sorted(first))
            self.assertEqual(first["publication_state"], "review")
            self.assertNotIn("subtopic_terms", first)
            self.assertIn("term_display", first)
            self.assertLessEqual(len(first["term_display"]), 60)
            self.assertEqual(payload["search_index"]["document_count"], 0)

            reread = records.read_cache(path)
            self.assertEqual(reread, payload)

    def test_publishable_terms_live_only_in_the_index_and_rehydrate(self):
        cache = records.empty_cache()
        built = records.build_records(
            PARENT,
            segmented(HEADINGS),
            document=DOCUMENT,
            as_of="2026-08-20",
            provenance=records.REFERENCED,
        )
        records.upsert_parent(
            cache, "360678", built, as_of="2026-08-20", method="referenced"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "subtopics.js"
            records.write_cache(cache, path)
            text = path.read_text(encoding="utf-8")
            payload = json.loads(
                text.split(records.SIDECAR_GLOBAL, 1)[1].rstrip(";\n")
            )
            public = payload["records"]["360678"]["subtopics"]
            self.assertTrue(public)
            self.assertTrue(all("subtopic_terms" not in child for child in public))
            self.assertEqual(payload["search_index"]["document_count"], 3)
            self.assertTrue(payload["search_index"]["postings"])

            reread = records.read_cache(path)
            restored = reread["records"]["360678"]["subtopics"]
            self.assertTrue(all(child["subtopic_terms"] for child in restored))

    def test_writing_twice_is_byte_identical(self):
        cache = records.empty_cache()
        built = records.build_records(
            PARENT, segmented(HEADINGS), document=DOCUMENT, as_of="2026-08-20"
        )
        records.upsert_parent(cache, "360678", built, as_of="2026-08-20",
                              method="outline")
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "a.js"
            second = Path(directory) / "b.js"
            records.write_cache(cache, first)
            records.write_cache(cache, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_a_missing_or_corrupt_cache_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "nope.json"
            self.assertEqual(records.read_cache(missing), records.empty_cache())
            corrupt = Path(directory) / "bad.json"
            corrupt.write_text("{not json", encoding="utf-8")
            self.assertEqual(records.read_cache(corrupt), records.empty_cache())

    def test_parent_membership_is_the_only_child_currentness_axis(self):
        cache = records.empty_cache()
        cache["records"] = {
            "active": {
                "subtopics": [{
                    "subtopic_id": "active:a",
                    "own_deadline": "2000-01-01",
                }]
            },
            "departed": {"subtopics": [{"subtopic_id": "departed:a"}]},
        }
        removed = records.retain_current_parents(cache, {"active"})
        self.assertEqual(removed, ["departed"])
        self.assertEqual(
            cache["records"]["active"]["subtopics"][0]["own_deadline"],
            "2000-01-01",
        )

    def test_rejection_reasons_are_recorded_for_diagnostics(self):
        cache = records.empty_cache()
        self.assertTrue(
            records.upsert_parent(
                cache, "356605", [], as_of="2026-08-20",
                reason="no_layer_accepted",
            )
        )
        metrics = records.cache_metrics(cache)
        self.assertEqual(metrics["subtopic_record_count"], 0)
        self.assertEqual(
            metrics["subtopic_rejection_reasons"], {"no_layer_accepted": 1}
        )

    def test_metrics_count_parents_records_and_confidence(self):
        cache = records.empty_cache()
        built = records.build_records(
            PARENT, segmented(HEADINGS), document=DOCUMENT, as_of="2026-08-20"
        )
        records.upsert_parent(cache, "360678", built, as_of="2026-08-20",
                              method="outline")
        metrics = records.cache_metrics(cache)
        self.assertEqual(metrics["subtopic_parent_count"], 1)
        self.assertEqual(metrics["subtopic_record_count"], 3)
        self.assertEqual(metrics["subtopic_methods"], {"outline": 1})
        # `inferred` caps at medium (§5.1); this read {"high": 3} before the
        # ladder landed.
        self.assertEqual(metrics["subtopic_confidence_counts"], {"medium": 3})


if __name__ == "__main__":
    unittest.main()
