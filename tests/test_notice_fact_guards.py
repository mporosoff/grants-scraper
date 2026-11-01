"""Retained official quotations correct only proved obligation/rate errors."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts import extract_document_evidence as extractor
from scripts import notice_fact_guards as guard


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/parsing/document-fact-guards.json').read_bytes())


class NoticeFactGuardTests(unittest.TestCase):
    def test_retained_official_quote_errors_are_withheld_without_touching_other_facts(self):
        for case in FIXTURE['cases']:
            with self.subTest(opportunity_id=case['opportunity_id'], fact=case['fact']['label']):
                original = deepcopy(case['fact'])
                unrelated = {**deepcopy(original), 'id': 'unrelated', 'type': 'project_duration', 'value': 3}
                before = [unrelated, original]
                facts, changes = guard.repair_facts(before, case['document'])
                self.assertEqual(facts, [unrelated])
                self.assertEqual(changes, [{'fact_id': original['id'], 'reason': case['reason']}])
                self.assertEqual(before, [unrelated, case['fact']])

    def test_fresh_extraction_does_not_reintroduce_the_retained_quote_errors(self):
        for case in FIXTURE['cases']:
            old = case['fact']; citation = old['citation']
            with self.subTest(opportunity_id=case['opportunity_id'], fact=old['label']):
                found = extractor.extract_document_facts({'opportunity_id': case['opportunity_id']},
                    [{'text': citation['quote'], 'page': citation.get('page'), 'section': citation.get('section')}],
                    case['document'], citation['extracted_at'], families={extractor.FACT_FAMILIES[old['type']]})
                if old['type'] == 'program_funding':
                    self.assertFalse(any(f['type'] == 'program_funding' and f['value'] == old['value'] for f in found))
                else:
                    self.assertFalse(any(f['type'] == 'application_component' and f.get('subject') == old['subject']
                                         and f.get('obligation') == 'required' for f in found))

    def test_only_complete_unqualified_named_negation_proves_not_required(self):
        for text in ('Letters of support/commitment are not required.',
                     'You are not required to submit letters of support.',
                     'Letters of support or collaboration are encouraged from partners but are not required.'):
            with self.subTest(text=text):
                self.assertTrue(guard.component_not_required(text, 'Letters of support'))
        for text in ('Letters of support are required. Cost sharing is not required.',
                     'If invited, letters of support are not required.',
                     'Letters of support are not required for preliminary applications.',
                     'Letters of support are not required to be signed.',
                     'Letters of support are not required for a Compl…'):
            with self.subTest(text=text):
                self.assertFalse(guard.component_not_required(text, 'Letters of support'))

    def test_positive_prohibited_conditional_and_page_limit_semantics_remain_distinct(self):
        examples = [('Letters of support are required.', 'required'),
                    ('Do not include letters of support.', 'prohibited'),
                    ('Letters of support are required if a partner contributes resources.', 'conditional'),
                    ('Letters of support are optional.', 'optional'),
                    ('Applications may include letters of support.', 'optional'),
                    ('Letters of support are not required.', 'not_required')]
        document = FIXTURE['cases'][0]['document']
        for text, obligation in examples:
            with self.subTest(text=text):
                facts = extractor.extract_document_facts({'opportunity_id': 'fixture'},
                    [{'text': text, 'page': 1}], document, '2026-10-30T00:00:00Z', families={'components'})
                self.assertEqual([f['obligation'] for f in facts if f['type'] == 'application_component'], [obligation])
        text = 'Letters of support are not required to be signed.'
        facts = extractor.extract_document_facts({'opportunity_id': 'fixture'}, [{'text': text, 'page': 1}],
            document, '2026-10-30T00:00:00Z', families={'components'})
        self.assertFalse(any(f.get('obligation') == 'required' for f in facts))

    def test_rates_do_not_suppress_independently_owned_program_or_award_amounts(self):
        document = FIXTURE['cases'][0]['document']
        text = ('Employee Name Labor Category Direct Hourly Rate Hours Total Direct Labor Program Manager $55.00. '
                'Total program funding is $2 million. Each award has a maximum of $55,000.')
        facts = extractor.extract_document_facts({'opportunity_id': 'fixture'}, [{'text': text, 'page': 1}],
            document, '2026-10-30T00:00:00Z', families={'amounts'})
        self.assertEqual([f['value'] for f in facts if f['type'] == 'program_funding'], [2000000])
        self.assertEqual([f['value']['maximum'] for f in facts if f['type'] == 'award_range'], [55000])

    def test_wrong_document_binding_and_ambiguous_scope_keep_existing_evidence_exact(self):
        case = FIXTURE['cases'][0]
        for key in ('url', 'sha256'):
            document = {**case['document'], key: 'different'}
            self.assertEqual(guard.repair_facts([case['fact']], document), ([case['fact']], []))
        old = deepcopy(next(c['fact'] for c in FIXTURE['cases'] if c['opportunity_id'] == '363378'))
        for quote in ('Letters of support are not required for prelimina…',
                      'Letters of support are not required to be signed.'):
            old['citation']['quote'] = quote
            self.assertEqual(guard.repair_facts([old], next(c['document'] for c in FIXTURE['cases']
                             if c['opportunity_id'] == '363378')), ([old], []))

    def test_actual_role_stage_and_clipped_quotes_do_not_become_unqualified_negative_facts(self):
        for case in FIXTURE['scope_controls']:
            fact = case['fact']; citation = fact['citation']
            with self.subTest(opportunity_id=case['opportunity_id']):
                self.assertEqual(guard.repair_facts([fact], case['document']), ([fact], []))
                found = extractor.extract_document_facts({'opportunity_id': case['opportunity_id']},
                    [{'text': citation['quote'], 'page': citation.get('page'), 'section': citation.get('section')}],
                    case['document'], citation['extracted_at'], families={'components'})
                self.assertFalse(any(f.get('subject') == fact['subject'] and f.get('obligation') == 'not_required'
                                     for f in found))

    def test_entry_and_ordinary_projection_preserve_clocks_and_are_idempotent(self):
        case = next(c for c in FIXTURE['cases'] if c['opportunity_id'] == '363378')
        entry = {'status': 'current', 'document': deepcopy(case['document']), 'checked_at': case['source_checked_at'],
                 'facts': [deepcopy(case['fact'])], 'review_queue': [], 'version_history': [{'version': 1}],
                 'parser_dependencies': extractor.parser_dependencies()}
        original = deepcopy(entry)
        output = extractor.merge_document_entry({'opportunity_id': case['opportunity_id']}, entry)
        self.assertEqual(entry['facts'], [])
        self.assertEqual(output['document_evidence']['facts'], [])
        self.assertEqual({k: v for k, v in entry.items() if k not in ('facts', 'fact_guard')},
                         {k: v for k, v in original.items() if k != 'facts'})
        self.assertEqual(entry['fact_guard']['version'], guard.VERSION)
        self.assertFalse(entry['fact_guard']['source_retrieved'])
        repaired = deepcopy(entry)
        self.assertEqual(guard.repair_entry(entry), [])
        self.assertEqual(entry, repaired)
        self.assertEqual(extractor.merge_document_entry({'opportunity_id': case['opportunity_id']}, entry), output)


if __name__ == '__main__':
    unittest.main()
