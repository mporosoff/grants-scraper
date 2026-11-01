"""A complete owned funding table can disambiguate a duplicated program total."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts import extract_document_evidence as evidence, notice_awards


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/parsing/notice-program-total-awards.json').read_bytes())


class NoticeAwardReconciliationTests(unittest.TestCase):
    def setUp(self):
        case = deepcopy(FIXTURE['cases'][0])
        self.record, self.entry = case['record'], case['entry']

    def merge(self):
        return evidence.merge_document_entry(deepcopy(self.record), deepcopy(self.entry))

    def test_scaled_budget_stays_total_and_largest_individual_award_drives_filter(self):
        output = self.merge()
        self.assertEqual(output['award_ceiling'], 25_000_000)
        self.assertEqual(output['total_program_funding'], 237_000_000)
        self.assertEqual(output['award_floor'], 1)
        proof = output['document_evidence']['award_reconciliation']
        self.assertEqual(proof['structured_value'], 237_000_000)
        self.assertEqual(proof['tracks']['Topic Area 1']['maximum'], 15_000_000)
        self.assertEqual(proof['tracks']['Topic Area 2']['maximum'], 25_000_000)
        self.assertEqual(output['document_evidence']['source_fields']['award_ceiling'],
                         {'present': True, 'value': 237_000_000})
        self.assertEqual(self.record['award_ceiling'], 237_000_000)

    def test_repeated_projection_and_evidence_withdrawal_restore_exact_source(self):
        output = self.merge()
        self.assertEqual(evidence.merge_document_entry(output, deepcopy(self.entry)), output)
        for entry in (None, self.entry | {'status': 'source_changed'}):
            restored = evidence.merge_document_entry(output, deepcopy(entry))
            for key in ('award_ceiling', 'award_source', 'total_program_funding'):
                self.assertEqual(restored[key], self.record[key])

    def test_ordinary_genesis_estimated_range_does_not_override_structured_award(self):
        case = deepcopy(FIXTURE['cases'][1])
        output = evidence.merge_document_entry(case['record'], case['entry'])
        self.assertEqual(output['award_ceiling'], 20_000_000)
        self.assertNotIn('award_reconciliation', output['document_evidence'])

    def test_partial_or_conflicting_topic_table_cannot_claim_overall_maximum(self):
        for mutation in ('missing_range', 'missing_budget', 'different_total', 'different_page',
                         'conditional', 'per_year', 'mixed_document', 'conflicting_range'):
            with self.subTest(mutation=mutation):
                entry = deepcopy(self.entry)
                award = next(f for f in entry['facts'] if f['type'] == 'award_range')
                budget = next(f for f in entry['facts'] if f['type'] == 'program_funding' and f.get('track'))
                if mutation == 'missing_range': entry['facts'].remove(award)
                elif mutation == 'missing_budget': entry['facts'].remove(budget)
                elif mutation == 'different_total': budget['value'] -= 1
                elif mutation == 'different_page': award['citation']['page'] += 1
                elif mutation == 'conditional': award['applicant_condition'] = 'Only certain applicants'
                elif mutation == 'per_year': award['basis'] = 'annual'
                elif mutation == 'mixed_document': award['citation']['sha256'] = 'a' * 64
                elif mutation == 'conflicting_range': entry['facts'].append(deepcopy(award) | {'value': {'minimum': 1, 'maximum': 100}})
                self.assertIsNone(notice_awards.reconcile_program_total(self.record, entry))

    def test_other_source_document_or_valid_source_ceiling_is_not_overridden(self):
        for delta in ({'source': 'Other'}, {'award_ceiling': 20_000_000},
                      {'expected_number_of_awards': 1}, {'primary_document_url': 'https://example.org/wrong.pdf'}):
            with self.subTest(delta=delta):
                self.assertIsNone(notice_awards.reconcile_program_total(self.record | delta, self.entry))


if __name__ == '__main__':
    unittest.main()
