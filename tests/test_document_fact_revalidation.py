"""A retained correction removes proved errors without rewriting other work."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from scripts import extract_document_evidence as evidence
from scripts.build_catalog import build_search_index
from tools import document_fact_revalidation as replay


class DocumentFactProjection(unittest.TestCase):
    def inputs(self):
        document = {'url': 'https://apply07.grants.gov/grantsws/rest/opportunity/att/download/354244',
            'sha256': 'a' * 64, 'name': 'DURIP.pdf', 'content_type': 'application/pdf',
            'first_seen_at': '2026-10-29T18:00:00Z', 'last_seen_at': '2026-10-30T16:48:34Z'}
        citation = {'document_url': document['url'], 'sha256': document['sha256'], 'page': 8,
            'quote': 'Letters of support/commitment are not required.',
            'extracted_at': '2026-10-30T16:48:34Z'}
        bad = {'id': 'evidence-363379-letters', 'type': 'application_component',
            'label': 'Letters of support', 'subject': 'Letters of support', 'value': 'Letters of support',
            'display_value': 'Letters of support (required)', 'obligation': 'required', 'stage': 'application',
            'citation': citation}
        good = {'id': 'evidence-363379-cover', 'type': 'application_component',
            'label': 'Cover sheet', 'subject': 'Cover sheet', 'value': 'Cover sheet',
            'display_value': 'Cover sheet (required)', 'obligation': 'required', 'stage': 'application',
            'citation': citation | {'quote': 'A cover sheet is required.'}}
        entry = {'source_signature': 'original-source', 'source_url': document['url'],
            'status': 'current', 'document': document, 'checked_at': '2026-10-30T16:48:34Z',
            'facts': [bad, good], 'review_queue': [], 'extraction': {},
            'parser_dependencies': {'components': 'retained-version'}, 'version_history': []}
        row = evidence.merge_document_entry({'opportunity_id': '363379', 'title': 'DURIP',
            'source': 'Grants.gov', 'source_id': 'grants-gov', 'deadlines': [],
            'close_date': '2026-11-06', 'total_program_funding': 50000000}, deepcopy(entry))
        # Model the exact old public projection, before the new merge guard.
        row['document_evidence']['facts'] = deepcopy(entry['facts'])
        row['document_search_text'] = replay.search_text(row)
        other = {'opportunity_id': 'unaffected', 'title': 'Unrelated retained source',
            'source': 'Another sponsor', 'deadlines': [], 'document_evidence': None}
        catalog = {'schema_version': 3, 'generated_at': '2026-10-30T16:47:06Z',
            'document_evidence_generated_at': '2026-10-30T16:54:47Z',
            'opportunities': [row, other], 'record_count': 2, 'diagnostics': {'retained': True}}
        catalog['search_index'] = build_search_index(catalog['opportunities'])
        cache = {'schema_version': 1, 'generated_at': '2026-10-30T16:54:47Z',
            'records': {'363379': entry, 'unaffected': {'facts': [], 'checked_at': 'original-clock'}}}
        return catalog, cache

    def test_repairs_cache_and_public_projection_without_recollecting_or_rewriting_source(self):
        catalog, cache = self.inputs(); original = deepcopy((catalog, cache))
        after, updated, receipt = replay.project_catalog(catalog, cache)
        self.assertEqual((catalog, cache), original)
        self.assertEqual(receipt['affected_catalog_ids'], ['363379'])
        self.assertEqual(receipt['affected_evidence_ids'], ['363379'])
        self.assertEqual(updated['records']['363379']['facts'], cache['records']['363379']['facts'][1:])
        self.assertEqual(after['opportunities'][0]['document_evidence']['facts'],
                         catalog['opportunities'][0]['document_evidence']['facts'][1:])
        self.assertNotIn('Letters of support (required)', after['opportunities'][0]['document_search_text'])
        self.assertEqual(after['opportunities'][1], catalog['opportunities'][1])
        self.assertEqual(updated['records']['unaffected'], cache['records']['unaffected'])
        self.assertEqual(after['generated_at'], catalog['generated_at'])
        self.assertEqual(updated['generated_at'], cache['generated_at'])
        self.assertEqual(updated['records']['363379']['checked_at'], cache['records']['363379']['checked_at'])
        self.assertEqual(after['search_index'], build_search_index(after['opportunities']))
        self.assertEqual(after['opportunities'][0]['total_program_funding'], 50000000)
        self.assertIs(updated['records']['363379']['fact_guard']['source_retrieved'], False)

    def test_second_projection_has_no_changes_and_keeps_receipt(self):
        catalog, cache = self.inputs()
        first, retained, _ = replay.project_catalog(catalog, cache)
        second, again, receipt = replay.project_catalog(first, retained)
        self.assertEqual(second, first)
        self.assertEqual(again, retained)
        self.assertEqual(receipt['affected_catalog_ids'], [])
        self.assertEqual(receipt['affected_evidence_ids'], [])

    def test_scalar_source_deadline_and_document_clock_changes_are_rejected(self):
        catalog, _ = self.inputs(); row = catalog['opportunities'][0]
        for field, value in [('source', 'Other'), ('close_date', '2027-01-01'),
                             ('total_program_funding', 55), ('document_evidence_checked_at', 'new')]:
            changed = deepcopy(row); changed[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'unchanged_source'):
                replay.record_firewall(row, changed)

    def test_good_fact_edits_additions_and_reordering_are_rejected(self):
        catalog, _ = self.inputs(); row = catalog['opportunities'][0]
        facts = row['document_evidence']['facts']
        edited = deepcopy(facts[1:]); edited[0]['citation']['quote'] = 'Altered source'
        for replacement in (edited, facts[1:] + facts[1:], list(reversed(facts)), []):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                replay.fact_firewall(facts, replacement, row['document_evidence']['document'])

    def test_noncanonical_old_search_text_fails_instead_of_leaving_false_search_evidence(self):
        catalog, cache = self.inputs()
        catalog['opportunities'][0]['document_search_text'] = 'Different historical formatter'
        with self.assertRaisesRegex(ValueError, 'canonical_public_fact_text'):
            replay.project_catalog(catalog, cache)

    def test_public_fact_without_matching_cache_correction_is_not_silently_rewritten(self):
        catalog, cache = self.inputs()
        cache['records']['363379']['facts'] = cache['records']['363379']['facts'][1:]
        with self.assertRaisesRegex(ValueError, 'matching_current_cache_correction'):
            replay.project_catalog(catalog, cache)

    def test_unrelated_cache_mutation_fails_even_if_helper_reports_a_removal(self):
        catalog, cache = self.inputs()
        original = replay.guards.repair_entry
        def unexpected(entry):
            result = original(entry)
            if result:
                entry['checked_at'] = 'new-source-check'
            return result
        with patch.object(replay.guards, 'repair_entry', side_effect=unexpected):
            with self.assertRaisesRegex(ValueError, 'unchanged_cache_document_and_clocks'):
                replay.project_catalog(catalog, cache)


if __name__ == '__main__':
    unittest.main()
