"""Stored-fact projection preserves identity, citations, clocks and raw cache."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from tests.test_administrative_close_contract import retained_record
from scripts import extract_document_evidence as evidence
from scripts.build_catalog import build_search_index
from tools import administrative_submission_revalidation as replay


class AdministrativeSubmissionReplay(unittest.TestCase):
    def inputs(self):
        row = retained_record()
        row['document_evidence_checked_at'] = '2026-10-19T17:05:45Z'
        row['document_search_text'] = evidence.clean_text(' '.join(str(value)
            for fact in row['document_evidence']['facts'] for value in
            (fact['label'], fact['display_value'], fact['citation']['quote'])))
        other = {'opportunity_id': 'unaffected', 'title': 'Unchanged science', 'source': 'Another source',
            'next_submission': {'date': '2026-11-01', 'as_of': '2026-10-19'}}
        catalog = {'generated_at': '2026-10-19T17:02:00Z',
            'document_evidence_generated_at': '2026-10-19T17:12:00Z',
            'opportunities': [row, other], 'record_count': 2,
            'facets': {'topic': 'retained'}, 'diagnostics': {'unchanged': True}}
        catalog['search_index'] = build_search_index(catalog['opportunities'])
        cache = {'generated_at': '2026-10-19T17:12:00Z',
            'records': {'362893': {'checked_at': '2026-10-19T17:05:45Z',
                'facts': deepcopy(row['document_evidence']['facts']), 'source_signature': 'retained'}}}
        return catalog, cache

    def test_pure_refinement_changes_only_qualified_projection_and_derived_lexical_index(self):
        catalog, cache = self.inputs(); original = deepcopy((catalog, cache))
        after, retained, ids = replay.project_catalog(catalog, cache)
        self.assertEqual((catalog, cache), original)
        self.assertEqual(retained, cache)
        self.assertEqual(ids, ['362893'])
        self.assertEqual(after['opportunities'][1], catalog['opportunities'][1])
        row = after['opportunities'][0]
        self.assertIsNone(row['next_submission']['date'])
        self.assertEqual(row['next_submission']['access'], 'closed')
        self.assertEqual(row['close_date'], '2026-12-16')
        self.assertEqual(row['document_evidence_checked_at'], '2026-10-19T17:05:45Z')
        self.assertEqual(after['search_index'], build_search_index(after['opportunities']))
        self.assertNotEqual(row['document_search_text'], catalog['opportunities'][0]['document_search_text'])
        for old, new in zip(catalog['opportunities'][0]['document_evidence']['facts'], row['document_evidence']['facts']):
            self.assertEqual(old['citation'], new['citation'])
            self.assertEqual(old['value'], new['value'])

    def test_second_projection_is_identical_without_migrating_raw_cached_facts(self):
        catalog, cache = self.inputs()
        first, retained, _ = replay.project_catalog(catalog, cache)
        second, again, ids = replay.project_catalog(first, retained)
        self.assertEqual(second, first)
        self.assertEqual(again, cache)
        self.assertEqual(ids, [])

    def test_noncanonical_document_search_text_is_preserved(self):
        catalog, cache = self.inputs()
        catalog['opportunities'][0]['document_search_text'] = 'Retained text from a different historical formatter'
        after, _, _ = replay.project_catalog(catalog, cache)
        self.assertEqual(after['opportunities'][0]['document_search_text'],
            catalog['opportunities'][0]['document_search_text'])

    def test_record_and_fact_firewalls_refuse_unrelated_source_or_citation_changes(self):
        catalog, _ = self.inputs(); before = catalog['opportunities'][0]
        for change in ('source', 'clock', 'date', 'citation', 'source-receipt'):
            after = deepcopy(before)
            if change == 'source': after['source'] = 'Different sponsor'
            elif change == 'clock': after['document_evidence_checked_at'] = '2026-10-20T00:00:00Z'
            elif change == 'date': after['document_evidence']['facts'][0]['date'] = '2026-10-15'
            elif change == 'citation': after['document_evidence']['facts'][0]['citation']['quote'] = 'Changed proof'
            else:
                before = deepcopy(before)
                before['deadlines'][0]['document_source_fields'] = {'kind': {'present': True, 'value': 'application'}}
                after = deepcopy(before)
                after['deadlines'][0]['document_source_fields']['kind']['value'] = 'submission'
            with self.subTest(change=change), self.assertRaises(ValueError):
                replay.record_firewall(before, after)

    def test_unreported_mutation_and_non_scientific_text_injection_fail_closed(self):
        catalog, cache = self.inputs()
        def mutate(row):
            row['title'] = 'Unreported change'
            return False
        with patch.object(evidence, 'refine_administrative_close', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'unaffected_row'):
                replay.project_catalog(catalog, cache)
        before = catalog['opportunities'][0]; after = deepcopy(before)
        after['document_search_text'] = 'Injected text beyond the retained public fact recipe'
        with self.assertRaisesRegex(ValueError, 'derived_public_fact_text'):
            replay.record_firewall(before, after)

    def test_non_deadline_document_fact_and_source_receipt_are_exact(self):
        catalog, _ = self.inputs(); before = catalog['opportunities'][0]
        before['document_evidence']['facts'].append({'id': 'eligibility', 'type': 'eligibility', 'label': 'Eligibility'})
        after = deepcopy(before); after['document_evidence']['facts'][-1]['label'] = 'Changed eligibility'
        with self.assertRaisesRegex(ValueError, 'unchanged_non_deadline_document_fact'):
            replay.record_firewall(before, after)
        after = deepcopy(before)
        after['deadlines'][0]['document_source_fields'] = {'stage': {'present': True, 'value': 'wrong'}}
        with self.assertRaisesRegex(ValueError, 'reversible_source_fields'):
            replay.record_firewall(before, after)


if __name__ == '__main__':
    unittest.main()
