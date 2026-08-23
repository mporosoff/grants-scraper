"""Tests for evidence-backed FOA program-area discoverability.

Covers the controlled vocabulary, the notice-text extractor, and the merge that
folds found program areas into a record's indexed search text + Topic facet
(without leaking raw notice text into the browser catalog).
"""

import unittest

from scripts import program_areas
from scripts.extract_document_evidence import (
    extract_program_areas,
    merge_document_entry,
    revalidate_program_areas_only,
)

DOCUMENT = {
    "url": "https://example.gov/de-foa-0003600.pdf",
    "name": "de-foa-0003600.pdf",
    "source_kind": "pdf",
    "content_type": "application/pdf",
    "sha256": "deadbeef",
    "version": 1,
    "first_seen_at": "2026-07-27T00:00:00Z",
    "last_seen_at": "2026-07-27T00:00:00Z",
}

UMBRELLA_TEXT = (
    "The Office of Science Financial Assistance Program supports Basic Energy "
    "Sciences including heterogeneous catalysis, condensed matter and materials "
    "science, and quantum information science, as well as advanced scientific "
    "computing and carbon capture."
)
UNRELATED_TEXT = "This notice concerns rural community development block grants."


def entry_for(text, page=7):
    containers = [{"text": text, "page": page, "section": None}]
    hits = extract_program_areas(containers, DOCUMENT, "2026-07-27T00:00:00Z")
    return {
        "status": "current",
        "checked_at": "2026-07-27T00:00:00Z",
        "document": DOCUMENT,
        "extraction": {},
        "facts": [],
        "program_areas": hits,
        "review_queue": [],
    }, hits


class VocabularyTests(unittest.TestCase):
    def test_topics_for_maps_labels_to_facet_tags(self):
        self.assertIn("Catalysis and reaction engineering", program_areas.topics_for(["catalysis"]))
        self.assertEqual(program_areas.topics_for(["nuclear physics"]), [])  # searchable, no clean topic

    def test_entries_have_compiled_patterns(self):
        labels = {label for label, _, _ in program_areas.ENTRIES}
        self.assertIn("catalysis", labels)
        self.assertTrue(all(hasattr(p, "search") for _, _, p in program_areas.ENTRIES))


class ExtractTests(unittest.TestCase):
    def test_finds_terms_present_in_notice_with_citation(self):
        _, hits = entry_for(UMBRELLA_TEXT)
        labels = {hit["label"] for hit in hits}
        self.assertIn("catalysis", labels)
        self.assertIn("materials science", labels)
        self.assertIn("quantum science", labels)
        self.assertTrue(all(hit["citation"]["page"] == 7 for hit in hits))

    def test_ignores_terms_not_present(self):
        _, hits = entry_for(UNRELATED_TEXT)
        self.assertEqual(hits, [])

    def test_information_exchange_is_not_ion_exchange(self):
        _, hits = entry_for(
            "Regular briefings and information exchange maintain visibility."
        )
        self.assertNotIn("hydrometallurgy", {hit["label"] for hit in hits})

    def test_standalone_ion_exchange_remains_hydrometallurgy_evidence(self):
        _, hits = entry_for(
            "The funded research includes ion exchange for selective recovery."
        )
        self.assertIn("hydrometallurgy", {hit["label"] for hit in hits})


class MergeTests(unittest.TestCase):
    def test_folds_into_search_text_and_topics(self):
        entry, _ = entry_for(UMBRELLA_TEXT)
        record = {"opportunity_id": "1", "title": "Office of Science", "topic_areas": ["Energy"]}
        merged = merge_document_entry(record, entry)
        self.assertIn("catalysis", merged["document_search_text"])
        self.assertIn("Catalysis and reaction engineering", merged["topic_areas"])
        self.assertIn("Quantum science", merged["topic_areas"])
        self.assertIn("Energy", merged["topic_areas"])  # existing topic preserved
        self.assertIn("catalysis", merged["document_program_areas"])

    def test_does_not_leak_raw_notice_text(self):
        entry, _ = entry_for(UMBRELLA_TEXT)
        record = {"opportunity_id": "1", "title": "Office of Science", "topic_areas": []}
        merged = merge_document_entry(record, entry)
        # only compact canonical labels enter the index, not the surrounding prose
        self.assertNotIn("heterogeneous", merged["document_search_text"])
        self.assertNotIn("supports", merged["document_search_text"])

    def test_unrelated_notice_adds_nothing(self):
        entry, _ = entry_for(UNRELATED_TEXT)
        record = {"opportunity_id": "2", "title": "Rural grants", "topic_areas": ["Community development"]}
        merged = merge_document_entry(record, entry)
        self.assertNotIn("document_program_areas", {k: v for k, v in merged.items() if v})
        self.assertEqual(merged["topic_areas"], ["Community development"])

    def test_stale_cached_metaphorical_hit_is_not_merged(self):
        entry, _ = entry_for(UMBRELLA_TEXT)
        entry["program_areas"] = [{
            "label": "catalysis",
            "topics": ["Catalysis and reaction engineering"],
            "citation": {
                **DOCUMENT,
                "quote": "The award will serve as catalytic capital for community investment.",
            },
        }]
        record = {"opportunity_id": "3", "title": "Housing fund", "topic_areas": []}
        merged = merge_document_entry(record, entry)
        self.assertNotIn(
            "Catalysis and reaction engineering",
            merged["topic_areas"],
        )
        self.assertNotIn("catalysis", merged.get("document_search_text") or "")

    def test_stale_cached_compound_suffix_is_removed_from_existing_record(self):
        entry, _ = entry_for(UMBRELLA_TEXT)
        entry["program_areas"] = [{
            "label": "hydrometallurgy",
            "topics": ["Separations and membranes", "Materials science"],
            "citation": {
                **DOCUMENT,
                "quote": "Regular briefings and information exchange maintain visibility.",
            },
        }]
        record = {
            "opportunity_id": "4",
            "title": "Governance program",
            "topic_areas": ["Separations and membranes", "Materials science"],
            "document_program_areas": ["hydrometallurgy"],
        }
        merged = merge_document_entry(record, entry)
        self.assertNotIn("document_program_areas", merged)
        self.assertNotIn("Separations and membranes", merged["topic_areas"])
        self.assertNotIn("Materials science", merged["topic_areas"])

    def test_program_area_only_revalidation_does_not_remerge_unrelated_fields(self):
        entry, _ = entry_for(UMBRELLA_TEXT)
        entry["program_areas"] = [{
            "label": "hydrometallurgy",
            "topics": ["Separations and membranes", "Materials science"],
            "citation": {
                **DOCUMENT,
                "quote": "Regular briefings and information exchange maintain visibility.",
            },
        }]
        record = {
            "opportunity_id": "4",
            "title": "Governance program",
            "topic_areas": ["Separations and membranes", "Materials science"],
            "document_program_areas": ["hydrometallurgy"],
            "deadlines": [{"date": "2027-01-01", "kind": "application"}],
        }
        catalog = {"opportunities": [record], "search_index": {}}
        cache = {"records": {"4": entry}}
        rebuilt, rebuilt_cache, changed_ids = revalidate_program_areas_only(
            catalog,
            cache,
        )
        self.assertEqual(changed_ids, ["4"])
        self.assertEqual(rebuilt["opportunities"][0]["deadlines"], record["deadlines"])
        self.assertNotIn("document_program_areas", rebuilt["opportunities"][0])
        self.assertEqual(rebuilt_cache["records"]["4"]["program_areas"], [])


if __name__ == "__main__":
    unittest.main()
