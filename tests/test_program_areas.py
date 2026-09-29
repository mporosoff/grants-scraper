"""Tests for evidence-backed FOA program-area discoverability.

Covers the controlled vocabulary, the notice-text extractor, and the merge that
folds found program areas into a record's indexed search text + Topic facet
(without leaking raw notice text into the browser catalog).
"""

from copy import deepcopy
from datetime import datetime, timezone
import unittest

from scripts import program_areas
from scripts.extract_document_evidence import (
    EXTRACTOR_IDENTITY,
    extract_program_areas,
    merge_document_entry,
    revalidate_program_areas_only,
    validated_program_area_hits,
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


class ProgramAreaContextTests(unittest.TestCase):
    def test_recipient_and_application_policies_are_not_research_topics(self):
        cases = [
            ('cybersecurity', 'Recipients shall develop plans and procedures, modeled after the NIST Cybersecurity framework, to protect HHS systems and data.'),
            ('cybersecurity', 'Describe any plan to address cybersecurity and confidentiality of participants.'),
            ('cybersecurity', 'Cybersecurity plan. How you will protect personally identifiable information.'),
            ('cybersecurity', 'Complete research security training certifications covering cybersecurity and international travel.'),
            ('artificial intelligence', 'Policy on the Use of Artificial Intelligence for NEH Applications'),
            ('artificial intelligence', 'Guidance on Use of Artificial Intelligence (AI). IES added guidance on the use of AI in preparing grant applications (see Part III.A).'),
            ('artificial intelligence', 'Artificial Intelligence (AI) Application Use ..................................... 10'),
            ('critical minerals', 'Simplifying the Funding of Energy Infrastructure and Critical Mineral and Material Projects, the Department of Energy may share and use within the Government any application information.'),
            ('artificial intelligence', 'Artificial Intelligence Explore All Focus Areas Arctic and Antarctic'),
        ]
        for label, text in cases:
            with self.subTest(label=label, text=text):
                _, fresh = entry_for(text)
                cached = {'program_areas': [{'label': label, 'citation': {'quote': text}}]}
                self.assertNotIn(label, [hit['label'] for hit in fresh])
                self.assertEqual(validated_program_area_hits(cached), [])

    def test_award_administration_heading_rejects_cached_and_fresh_mentions(self):
        text = 'Recipients must address cybersecurity throughout the award.'
        headings = ['Section VI. Award Administration Information', 'Post-Award Monitoring']
        container = {'text': text, 'section': 'Post-Award Monitoring', 'structure': [
            {'span': [0, len(text)], 'kind': 'paragraph', 'heading_path': headings}]}
        self.assertEqual(extract_program_areas([container], DOCUMENT, DOCUMENT['first_seen_at']), [])
        cached = {'program_areas': [{'label': 'cybersecurity', 'citation': {
            'quote': text, 'section': 'Post-Award Monitoring', 'structural_reference': {'heading_path': headings}}}]}
        self.assertEqual(validated_program_area_hits(cached), [])

    def test_skips_policy_occurrence_and_keeps_later_scientific_paragraph(self):
        policy = 'Recipients shall follow the NIST cybersecurity framework to protect HHS data.'
        science = 'The program supports cybersecurity research for medical devices.'
        text = policy + '\n' + science
        container = {'text': text, 'section': 'Program Description', 'structure': [
            {'span': [0, len(policy)], 'kind': 'paragraph', 'block_id': 'policy'},
            {'span': [len(policy) + 1, len(text)], 'kind': 'paragraph', 'block_id': 'science'}]}
        hits = extract_program_areas([container], DOCUMENT, DOCUMENT['first_seen_at'])
        self.assertEqual([hit['label'] for hit in hits], ['cybersecurity'])
        self.assertEqual(hits[0]['citation']['quote'], science)
        self.assertEqual(hits[0]['citation']['structural_reference']['block_id'], 'science')
        self.assertEqual(validated_program_area_hits({'program_areas': hits}), hits)

    def test_pdf_line_keeps_cross_line_recipient_policy_context(self):
        first = 'Cybersecurity plan.'
        text = first + '\nHow you will protect personally identifiable information.'
        container = {'text': text, 'page': 8, 'structure': [
            {'span': [0, len(first)], 'kind': 'line', 'block_id': 'pdf-8-1'},
            {'span': [len(first) + 1, len(text)], 'kind': 'line', 'block_id': 'pdf-8-2'}]}
        self.assertEqual(extract_program_areas([container], DOCUMENT, DOCUMENT['first_seen_at']), [])

    def test_skips_navigation_and_retains_scientific_occurrence(self):
        containers = [
            {'text': 'Artificial Intelligence Explore All Focus Areas', 'section': None},
            {'text': 'The program supports artificial intelligence research in plasma physics.', 'section': 'Synopsis'},
        ]
        hits = extract_program_areas(containers, DOCUMENT, DOCUMENT['first_seen_at'])
        ai = next(hit for hit in hits if hit['label'] == 'artificial intelligence')
        self.assertEqual(ai['citation']['section'], 'Synopsis')

    def test_security_research_and_project_implementation_remain_scientific(self):
        cases = [
            'The program funds cybersecurity research into security plans and the NIST Cybersecurity Framework.',
            'Proposals must describe how the project will implement robust physical and cybersecurity measures, aligned with the research infrastructure project accessibility and trustworthiness aims.',
            'The funded research includes development of artificial intelligence techniques for plasma physics.',
            'Research methods must identify bias in Artificial Intelligence (AI) in Education.',
        ]
        for text in cases:
            with self.subTest(text=text):
                _, fresh = entry_for(text)
                self.assertTrue(fresh)
                self.assertEqual(validated_program_area_hits({'program_areas': fresh}), fresh)

    def test_revalidation_restores_source_topics_and_preserves_source_owned_cyber_topic(self):
        for source_topics in (['Education and workforce', 'Social and behavioral sciences'], ['Cybersecurity']):
            with self.subTest(source_topics=source_topics):
                entry, _ = entry_for('The program supports cybersecurity research.')
                entry['extractor_identity'] = EXTRACTOR_IDENTITY
                record = {'opportunity_id': '359655', 'title': 'Summer research education', 'topic_areas': source_topics}
                published = merge_document_entry(record, entry)
                entry['program_areas'][0]['citation'].update(
                    section='2. Administrative and National Policy Requirements',
                    quote='Recipients shall develop plans modeled after the NIST Cybersecurity framework.')
                catalog = {'opportunities': [published], 'generated_at': DOCUMENT['first_seen_at'],
                           'document_evidence_generated_at': DOCUMENT['first_seen_at'], 'search_index': {}}
                cache = {'records': {'359655': entry}, 'generated_at': DOCUMENT['first_seen_at']}
                before = deepcopy((catalog, cache))
                rebuilt, rebuilt_cache, changed_ids = revalidate_program_areas_only(
                    catalog, cache, now=datetime(2026, 7, 27, tzinfo=timezone.utc))
                corrected = rebuilt['opportunities'][0]
                self.assertEqual(changed_ids, ['359655'])
                self.assertEqual(corrected['topic_areas'], source_topics)
                self.assertNotIn('document_program_areas', corrected)
                self.assertNotIn('cybersecurity', (corrected.get('document_search_text') or '').lower())
                self.assertEqual(corrected['document_evidence'], published['document_evidence'])
                self.assertEqual(rebuilt['generated_at'], before[0]['generated_at'])
                self.assertEqual(rebuilt['document_evidence_generated_at'], before[0]['document_evidence_generated_at'])
                self.assertEqual(rebuilt_cache['generated_at'], before[1]['generated_at'])
                self.assertEqual(rebuilt_cache['records']['359655']['checked_at'], entry['checked_at'])


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
