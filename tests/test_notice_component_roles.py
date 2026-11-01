"""Official retained notices cannot lose the applicant condition on a requirement."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts import extract_document_evidence as evidence
from scripts import notice_fact_guards as guards

CASES = json.loads((Path(__file__).parent /
    'fixtures/parsing/conditional-component-roles.json').read_bytes())['cases']


class ComponentRoleTests(unittest.TestCase):
    def test_actual_bound_obligations_are_withheld_in_cache_and_public_projection(self):
        for case in CASES:
            with self.subTest(record=case['opportunity_id']):
                fact, document = case['fact'], case['document']
                supported = deepcopy(fact)
                supported.update(id='retained-conditional', obligation='conditional',
                                 display_value=fact['label'] + ' (conditional)')
                entry = {'status': 'current', 'document': deepcopy(document),
                         'checked_at': '2026-11-01T21:09:01Z', 'facts': [deepcopy(fact), supported],
                         'review_queue': [], 'parser_dependencies': evidence.parser_dependencies()}
                before = deepcopy(entry)
                public = evidence.merge_document_entry({'opportunity_id': case['opportunity_id']}, entry)
                self.assertEqual(entry['facts'], [supported])
                self.assertEqual(public['document_evidence']['facts'], [supported])
                self.assertEqual({k: v for k, v in entry.items() if k not in {'facts', 'fact_guard'}},
                                 {k: v for k, v in before.items() if k != 'facts'})
                self.assertEqual(entry['fact_guard']['withheld'], [{'fact_id': fact['id'],
                                 'reason': 'component_applicant_condition_missing'}])
                retained = deepcopy(entry)
                self.assertEqual(guards.repair_entry(entry), [])
                self.assertEqual(entry, retained)

    def test_fresh_extraction_keeps_actual_role_qualified_requirements_conditional(self):
        for case in CASES:
            fact = case['fact']
            with self.subTest(record=case['opportunity_id']):
                found = evidence.extract_document_facts({'opportunity_id': case['opportunity_id']},
                    [{'text': fact['citation']['quote'], 'page': fact['citation']['page']}],
                    case['document'], fact['citation']['extracted_at'], families={'components'})
                matching = [f for f in found if f['type'] == 'application_component'
                            and f.get('subject') == fact['subject']]
                self.assertTrue(matching)
                self.assertEqual({f['obligation'] for f in matching}, {'conditional'})

    def test_only_complete_same_component_clauses_establish_the_condition(self):
        negative = [
            'Applicants must submit a Data Management Plan.',
            'Applicants that collect data must submit a budget. A Data Management Plan is required.',
            'Applicants that collect data must submit a budget; a Data Management Plan is required.',
            'Applicants that collect data must submit a budget. Proposers must include letters of support.',
            'Applicants that collect data\u2026 must submit a Data Management Plan.',
            'Applicants that collect data... must submit a Data Management Plan.',
            'Applicants that collect data must submit a budget and letters of support.',
        ]
        for quote in negative:
            with self.subTest(quote=quote):
                self.assertFalse(guards.component_role_condition(quote, 'Data management plan'))
        self.assertTrue(guards.component_role_condition(
            'Applicants that plan to collect public health data\n must submit a Data Management Plan.',
            'Data management plan'))

    def test_document_identity_and_existing_explicit_conditions_remain_authoritative(self):
        for case in CASES:
            fact = case['fact']
            for key in ('url', 'sha256'):
                with self.subTest(record=case['opportunity_id'], key=key):
                    self.assertEqual(guards.repair_facts([fact], case['document'] | {key: 'different'}),
                                     ([fact], []))
            scoped = fact | {'applicant_condition': 'Uses the named facility or collects public health data'}
            self.assertEqual(guards.repair_facts([scoped], case['document']), ([scoped], []))


if __name__ == '__main__':
    unittest.main()
