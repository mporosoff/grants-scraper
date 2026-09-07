import json
from pathlib import Path
from datetime import date
from copy import deepcopy
import unittest

from scripts.submission_schedule import next_submission
from scripts.build_changes import diff_catalogs
from tests.test_build_changes import rec, catalog

FIXTURE = Path(__file__).parent / 'fixtures/submission-schedule.json'


class SubmissionScheduleTests(unittest.TestCase):
    def test_source_contracts_preserve_dates_and_qualify_access(self):
        for case in json.loads(FIXTURE.read_text()):
            with self.subTest(case=case['name']):
                original = deepcopy(case['record'])
                result = next_submission(case['record'], case['as_of'])
                actual = {'date': result['date'], 'access': result['access'], 'kind': (result['event'] or {}).get('kind')}
                self.assertEqual(actual, case['expected'])
                self.assertEqual(original, case['record'])

    def test_invalid_calendar_values_are_never_selected(self):
        for day in ['2027-02-30', '2027-13-01', '02/01/2027']:
            self.assertIsNone(next_submission({'deadlines': [{'kind': 'application', 'date': day}]}, '2026-09-07')['date'])

    def test_parser_correction_is_not_a_sponsor_amendment(self):
        before = rec('one', close_date='2026-12-01', document_evidence={'document': {'sha256': 'same'}})
        after = {**before, 'deadlines': [{'kind': 'concept_paper', 'date': '2026-10-09', 'required': True},
                                       {'kind': 'application', 'date': '2026-12-01'}]}
        after['next_submission'] = next_submission(after, '2026-09-07')
        changes = diff_catalogs(catalog([before]), catalog([after]), as_of=date(2026, 9, 7))
        self.assertEqual([event['type'] for event in changes], ['source_correction'])
        after['document_evidence'] = {'document': {'sha256': 'material-amendment'}}
        changes = diff_catalogs(catalog([before]), catalog([after]), as_of=date(2026, 9, 7))
        self.assertEqual({event['type'] for event in changes}, {'deadline_changed', 'amended'})

    def test_alias_transition_does_not_emit_new_or_closure_alerts(self):
        before = rec('exchange:one')
        after = {**before, 'opportunity_id': '123', 'source_aliases': [{'opportunity_id': 'exchange:one'}]}
        changes = diff_catalogs(catalog([before]), catalog([after]), as_of=date(2026, 9, 7))
        self.assertEqual(changes, [])

    def test_closed_preliminary_does_not_emit_open_closing_reminder(self):
        before = rec('one', close_date='2026-10-01', deadlines=[
            {'kind': 'preproposal', 'date': '2026-07-01', 'required': True},
            {'kind': 'application', 'date': '2026-10-01'}])
        changes = diff_catalogs(catalog([before]), catalog([before]), as_of=date(2026, 9, 7))
        self.assertEqual(changes, [])


if __name__ == '__main__':
    unittest.main()
