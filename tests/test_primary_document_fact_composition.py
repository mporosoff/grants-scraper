"""A primary-notice replay may remove only its explicit retained fact set."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import extract_document_evidence as evidence
from scripts.build_catalog import build_search_index
from tools import document_fact_revalidation as facts
from tools import primary_document_revalidation as recovery


class PrimaryDocumentFactComposition(unittest.TestCase):
    def inputs(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/parsing/conditional-component-roles.json').read_bytes())
        rows, entries, selected = [], {}, {}
        for case in fixture['cases']:
            identifier, document, bad = case['opportunity_id'], case['document'], case['fact']
            good = deepcopy(bad)
            good.update(id=identifier + '-retained-conditional', obligation='conditional',
                        display_value=bad['label'] + ' (conditional)')
            entry = {'source_signature': 'retained-source', 'source_url': document['url'],
                'status': 'current', 'document': deepcopy(document), 'checked_at': '2026-11-01T21:09:01Z',
                'facts': [deepcopy(bad), good], 'review_queue': [], 'extraction': {},
                'parser_dependencies': {'components': 'retained-version'}, 'version_history': []}
            row = evidence.merge_document_entry({'opportunity_id': identifier, 'title': 'Retained notice ' + identifier,
                'source': 'Grants.gov', 'source_id': 'grants-gov', 'close_date': '2027-02-01',
                'deadlines': [], 'total_program_funding': 50000000}, deepcopy(entry))
            # Reconstruct the original public projection, before the new guard.
            row['document_evidence']['facts'] = deepcopy(entry['facts'])
            row['document_search_text'] = facts.search_text(row)
            rows.append(row)
            entries[identifier] = entry
            selected[identifier] = {'document_url': document['url'],
                'document_sha256': document['sha256'], 'fact_ids': [bad['id']]}
        rows.append({'opportunity_id': 'untouched', 'title': 'Unchanged notice', 'source': 'Other sponsor'})
        catalog = {'schema_version': 3, 'generated_at': '2026-11-01T21:07:21Z',
            'document_evidence_generated_at': '2026-11-01T21:09:01Z', 'opportunities': rows,
            'search_index': build_search_index(rows), 'record_count': len(rows)}
        cache = {'schema_version': 1, 'generated_at': '2026-11-01T21:09:01Z', 'records': entries}
        packet = {'records': {'364033': {}, '364174': {}}, 'retained_fact_removals': selected}
        return catalog, cache, packet

    def test_composed_retained_guard_preserves_conditional_facts_and_source_clocks(self):
        catalog, cache, packet = self.inputs()
        original = deepcopy((catalog, cache, packet))
        with patch.object(evidence, 'download_document', side_effect=AssertionError('no source request')), \
                patch.object(evidence, 'build_document_entry', side_effect=AssertionError('no document reparse')):
            after, updated, changes = recovery.project_retained_facts(catalog, cache, packet)
        self.assertEqual((catalog, cache, packet), original)
        self.assertEqual(changes['affected_catalog_ids'], ['334971', '334972', '364188'])
        self.assertEqual(changes['affected_evidence_ids'], changes['affected_catalog_ids'])
        self.assertEqual(after['opportunities'][-1], catalog['opportunities'][-1])
        self.assertEqual(after['generated_at'], catalog['generated_at'])
        self.assertEqual(updated['generated_at'], cache['generated_at'])
        for old, new in zip(catalog['opportunities'][:-1], after['opportunities'][:-1]):
            identifier = old['opportunity_id']
            self.assertEqual(new['document_evidence']['facts'], old['document_evidence']['facts'][1:])
            self.assertEqual(updated['records'][identifier]['facts'], cache['records'][identifier]['facts'][1:])
            self.assertEqual(updated['records'][identifier]['checked_at'], cache['records'][identifier]['checked_at'])
            self.assertEqual(updated['records'][identifier]['document'], cache['records'][identifier]['document'])
            self.assertEqual(new['total_program_funding'], old['total_program_funding'])
            self.assertEqual(new['close_date'], old['close_date'])
            self.assertIs(updated['records'][identifier]['fact_guard']['source_retrieved'], False)

    def test_an_unselected_consequential_guard_hit_fails_closed(self):
        catalog, cache, packet = self.inputs()
        del packet['retained_fact_removals']['334971']
        with self.assertRaisesRegex(ValueError, 'exact_retained_fact_removals'):
            recovery.project_retained_facts(catalog, cache, packet)

    def test_different_document_or_missing_fact_cannot_satisfy_the_packet(self):
        for fault in ('document', 'fact', 'public_fact', 'status'):
            catalog, cache, packet = self.inputs()
            if fault == 'document': packet['retained_fact_removals']['334971']['document_sha256'] = 'a' * 64
            elif fault == 'fact': packet['retained_fact_removals']['334971']['fact_ids'] = ['different-fact']
            elif fault == 'public_fact': catalog['opportunities'][0]['document_evidence']['facts'].pop(0)
            else: cache['records']['334971']['status'] = 'source_changed'
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                recovery.project_retained_facts(catalog, cache, packet)

    def test_quote_only_records_cannot_be_claimed_as_new_primary_acquisitions(self):
        catalog, cache, packet = self.inputs()
        packet['records']['334971'] = {}
        with self.assertRaisesRegex(ValueError, 'bounded_retained_fact_scope'):
            recovery.project_retained_facts(catalog, cache, packet)

    def test_missing_expected_guard_result_fails_closed(self):
        catalog, cache, packet = self.inputs()
        with patch.object(facts, 'project_catalog', return_value=(catalog, cache, {
                'public_fact_changes': {}, 'cached_fact_changes': {}})), \
                self.assertRaisesRegex(ValueError, 'exact_retained_fact_removals'):
            recovery.project_retained_facts(catalog, cache, packet)

    def test_recipe_and_operation_contract_include_composed_guard_dependencies(self):
        from tools import program_area_revalidation as common
        required = {'scripts/notice_fact_guards.py', 'scripts/notice_duration.py',
                    'tools/document_fact_revalidation.py'}
        self.assertTrue(required <= set(recovery.RECIPE_FILES))
        self.assertTrue(required <= set(common.PRIMARY_DOCUMENT_INPUTS))
        packet = recovery.read(recovery.PACKET_PATH)
        self.assertEqual(set(packet['records']), {'364033', '364174'})
        self.assertEqual({identifier: spec['fact_ids'] for identifier, spec in packet['retained_fact_removals'].items()}, {
            '334971': ['evidence-334971-7a6da70a8026'], '334972': ['evidence-334972-9f0b617bf18f'],
            '340828': ['evidence-340828-fd1f3b89df0b'], '364188': ['evidence-364188-c3633b51f026']})


if __name__ == '__main__':
    unittest.main()
