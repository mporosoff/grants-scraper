"""Native notice stages may explain, but never replace, an XML CloseDate."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts import extract_document_evidence as evidence
from scripts.submission_schedule import next_submission


FIXTURE = Path(__file__).parent / 'fixtures/parsing/stri26_reconciliation.json'


class PreliminaryCloseDateReconciliationTests(unittest.TestCase):
    def setUp(self):
        captured = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.record = captured['source_record']
        self.entry = captured['retained_entry']

    def merge(self):
        return evidence.merge_document_entry(deepcopy(self.record), deepcopy(self.entry))

    def assert_native_application_retained(self):
        output = self.merge()
        self.assertEqual(output['deadlines'][0]['kind'], 'application')
        self.assertNotIn('kind', output['deadlines'][0].get('document_source_fields', {}))
        self.assertEqual(output['close_date'], self.record['close_date'])
        return output

    def test_captured_stri_projects_both_owned_stages_without_fabricated_application(self):
        original_record, original_entry = deepcopy(self.record), deepcopy(self.entry)
        output = self.merge()
        actionable = [event for event in output['deadlines'] if event['kind'] != 'preliminary']
        self.assertEqual([(event['kind'], event['date']) for event in actionable],
                         [('preproposal', '2026-11-03'), ('application', '2027-01-21')])
        self.assertTrue(actionable[0]['required'])
        self.assertEqual(actionable[0]['document_source_fields']['kind'],
                         {'present': True, 'value': 'application'})
        for key, value in self.record['deadlines'][0].items():
            if key != 'kind':
                original = actionable[0].get('document_source_fields', {}).get(key)
                if original:
                    self.assertEqual(original, {'present': True, 'value': value})
                else:
                    self.assertEqual(actionable[0][key], value)
        self.assertEqual(output['close_date'], '2026-11-03')
        self.assertEqual(output['document_evidence_checked_at'], self.entry['checked_at'])
        self.assertEqual(output['document_evidence']['document']['sha256'], self.entry['document']['sha256'])
        self.assertFalse(any(fact.get('reconciliation') for fact in output['document_evidence']['facts']))
        self.assertFalse(any(item['type'] in {'deadline_conflict', 'deadline_source_conflict'}
                             for item in output['document_evidence']['review_queue']))
        for day in ('2026-10-16', '2026-11-03'):
            selected = next_submission(output, day)
            self.assertEqual((selected['event']['kind'], selected['date'], selected['access']),
                             ('preproposal', '2026-11-03', 'open'))
        selected = next_submission(output, '2026-11-04')
        self.assertEqual((selected['event']['kind'], selected['date'], selected['access']),
                         ('application', '2027-01-21', 'prerequisite_closed'))
        self.assertEqual(next_submission(output, '2027-01-22')['access'], 'closed')
        self.assertEqual(self.record, original_record)
        self.assertEqual(self.entry, original_entry)

    def test_projection_is_idempotent_and_withdrawn_evidence_restores_source_receipts(self):
        output = self.merge()
        self.assertEqual(evidence.merge_document_entry(output, deepcopy(self.entry)), output)
        for entry in (None, {'status': 'failed'}):
            with self.subTest(entry=entry):
                withdrawn = evidence.merge_document_entry(output, entry)
                self.assertEqual(withdrawn['deadlines'], self.record['deadlines'])
                self.assertEqual(withdrawn['close_date'], self.record['close_date'])

    def test_different_preliminary_date_does_not_reinterpret_close_date(self):
        self.entry['facts'][0]['date'] = '2026-11-02'
        output = self.assert_native_application_retained()
        self.assertNotIn(('application', '2027-01-21'),
                         [(event['kind'], event['date']) for event in output['deadlines']])
        self.assertTrue(any(item['type'] == 'deadline_conflict'
                            for item in output['document_evidence']['review_queue']))

    def test_same_date_full_field_retains_application_even_when_preliminary_also_matches(self):
        # NARMS-like notices can legitimately have preliminary and full fields
        # on the same day. Their CloseDate must keep its full stage.
        self.entry['facts'][1]['date'] = self.record['close_date']
        self.assert_native_application_retained()

    def test_ambiguous_native_stages_or_full_dates_do_not_reinterpret_close_date(self):
        for variant in ('preliminary_kind', 'full_date', 'same_date_full'):
            with self.subTest(variant=variant):
                self.setUp()
                other = deepcopy(self.entry['facts'][0 if variant == 'preliminary_kind' else 1])
                other['id'] += '-other'
                if variant == 'preliminary_kind':
                    other['deadline_kind'] = 'letter_of_intent'
                else:
                    other['date'] = ('2027-01-22' if variant == 'full_date' else self.record['close_date'])
                self.entry['facts'].append(other)
                self.assert_native_application_retained()

    def test_pair_requires_current_notice_identity_and_native_field_ownership(self):
        for field, value in (('document_url', 'https://other.example/notice'), ('sha256', 'different'),
                             ('field_id', None), ('field_label', None), ('field_authority', None)):
            for index in (0, 1):
                with self.subTest(field=field, index=index):
                    self.setUp()
                    fact = self.entry['facts'][index]
                    if field in {'document_url', 'sha256'}:
                        fact['citation'][field] = value
                    elif field in {'field_id', 'field_label'}:
                        fact['citation']['structural_reference'][field] = value
                    else:
                        fact[field] = value
                    self.assert_native_application_retained()
        self.setUp()
        self.record['funding_opportunity_url'] = 'https://other.example/notice'
        self.assert_native_application_retained()

    def test_native_pair_cannot_cross_application_class_cycle_or_track(self):
        for field, value in (('application_class', 'resubmission'), ('cycle', 'FY2027'), ('track', 'Track B')):
            for index in (0, 1):
                with self.subTest(field=field, index=index):
                    self.setUp()
                    self.entry['facts'][index][field] = value
                    self.assert_native_application_retained()

    def test_explicitly_matching_scope_retains_its_stage_and_source_receipts(self):
        qualifiers = {'application_class': 'new', 'cycle': 'FY2027', 'track': 'Track A'}
        self.record['deadlines'][0].update(qualifiers)
        for fact in self.entry['facts']:
            fact.update(qualifiers)
        output = self.merge()
        self.assertEqual(output['deadlines'][0]['kind'], 'preproposal')
        for key, value in qualifiers.items():
            self.assertEqual(output['deadlines'][0][key], value)
        self.assertEqual(next_submission(output, '2026-11-04')['access'], 'prerequisite_closed')

    def test_only_generic_structured_close_date_is_eligible(self):
        for field, value in (('confidence', 'source_listed'), ('source_field', 'OtherDate'),
                             ('kind', 'full_application')):
            with self.subTest(field=field):
                self.setUp()
                self.record['deadlines'][0][field] = value
                output = self.merge()
                self.assertEqual(output['deadlines'][0]['kind'], self.record['deadlines'][0]['kind'])
                self.assertNotIn('kind', output['deadlines'][0].get('document_source_fields', {}))


if __name__ == '__main__':
    unittest.main()
