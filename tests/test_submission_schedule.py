import json
from pathlib import Path
from datetime import date
from copy import deepcopy
import unittest

from scripts.submission_schedule import events, next_submission, project, project_invitation_access, project_two_step_prerequisite
from scripts.build_changes import diff_catalogs
from scripts.build_feeds import summarize
from scripts.currentness import record_is_current
from tests.test_build_changes import rec, catalog

FIXTURE = Path(__file__).parent / 'fixtures/submission-schedule.json'


class SubmissionScheduleTests(unittest.TestCase):
    def test_abstract_schedule_retains_both_source_stages_and_proposal_window(self):
        record = next(case['record'] for case in json.loads(FIXTURE.read_text(encoding='utf8'))
                      if case['name'] == 'DARPA unknown Abstract before its deadline')
        before = deepcopy(record)
        self.assertEqual(events(record), record['deadlines'])
        self.assertEqual([(event['kind'], event['date']) for event in events(record)],
                         [('abstract', '2026-11-03'), ('application', '2026-12-14')])
        for day in (date(2026, 11, 3), date(2026, 11, 4), date(2026, 12, 14)):
            self.assertTrue(record_is_current(record, day)[0])
        self.assertFalse(record_is_current(record, date(2026, 12, 15))[0])
        selected = next_submission(record, '2026-11-04')
        self.assertIsNone(selected['prerequisites'][0]['required'])
        self.assertEqual(selected['prerequisites'][0]['obligation'], 'unknown')
        self.assertIn('Abstract 2026-11-03', summarize(record, date(2026, 10, 16)))
        self.assertIn('verify prerequisite', summarize(record, date(2026, 11, 4)))
        self.assertEqual(record, before)

    def test_abstract_uncertainty_blocks_later_proposal_closing_reminders(self):
        template = next(case['record'] for case in json.loads(FIXTURE.read_text(encoding='utf8'))
                        if case['name'] == 'DARPA unknown Abstract before its deadline')
        for required in (None, True, False):
            with self.subTest(required=required):
                record = deepcopy(template)
                record['deadlines'][0]['required'] = required
                record['deadlines'][0]['obligation'] = 'required' if required is True else 'optional' if required is False else 'unknown'
                record['preliminary_required'] = required
                changed = diff_catalogs(catalog([record]), catalog([record]), as_of=date(2026, 11, 14))
                reminders = [event for event in changed if event['type'] == 'closing_soon']
                self.assertEqual(len(reminders), 1 if required is False else 0)
        changed = diff_catalogs(catalog([]), catalog([template]), as_of=date(2026, 10, 20))
        reminders = [event for event in changed if event['type'] == 'closing_soon']
        self.assertEqual(len(reminders), 1)
        self.assertIn('2026-11-03', reminders[0]['detail'])

    def test_source_contracts_preserve_dates_and_qualify_access(self):
        for case in json.loads(FIXTURE.read_text(encoding='utf8')):
            with self.subTest(case=case['name']):
                original = deepcopy(case['record'])
                result = next_submission(case['record'], case['as_of'])
                actual = {'date': result['date'], 'access': result['access'], 'kind': (result['event'] or {}).get('kind')}
                self.assertEqual(actual, case['expected'])
                self.assertEqual(original, case['record'])

    def test_source_access_projection_matches_shared_typed_records_without_mutation(self):
        for case in json.loads(FIXTURE.read_text(encoding='utf8')):
            if 'source_record' not in case:
                continue
            with self.subTest(case=case['name']):
                original = deepcopy(case['source_record'])
                scheduled = project(original, case['as_of'])
                result = {key: value for key, value in scheduled.items() if key != 'next_submission'}
                self.assertEqual(result, case['record'])
                self.assertEqual(scheduled, result | {'next_submission': next_submission(result, case['as_of'])})
                self.assertEqual(project(scheduled, case['as_of']), scheduled)
                self.assertEqual(original, case['source_record'])
                for field in ('title', 'description', 'eligibility_text', 'close_date', 'status'):
                    self.assertEqual(result.get(field), original.get(field))

    def test_single_source_requires_its_explicit_notice_clause_and_preserves_forecast(self):
        cases = [case for case in json.loads(FIXTURE.read_text(encoding='utf8'))
                 if case['name'].startswith('Explicit single-source invitation ')]
        self.assertEqual(len(cases), 7)
        self.assertEqual(sum(case['source_record']['status'] == 'forecasted' for case in cases), 5)
        for case in cases:
            source = deepcopy(case['source_record'])
            projected = project(source, case['as_of'])
            self.assertEqual(projected['status'], source['status'])
            self.assertEqual(projected['deadlines'][0]['estimated'], source['deadlines'][0]['estimated'])
            for mutation in ('ordinary_title', 'generic_invitation', 'named_recipient_only'):
                with self.subTest(case=case['name'], mutation=mutation):
                    changed = deepcopy(source)
                    if mutation == 'ordinary_title':
                        changed['title'] = 'Research program open competition'
                    else:
                        changed['description'] = ('All eligible organizations are invited to apply.'
                            if mutation == 'generic_invitation' else 'Only the named current recipient is eligible.')
                        changed['eligibility_text'] = 'The current recipient is eligible to apply.'
                    self.assertEqual(project_invitation_access(changed), changed)

    def test_title_invitation_preserves_fallback_date_and_exact_bounded_source_evidence(self):
        title = 'DOJ Invited to Apply - ' + 'Research program ' * 40
        record = rec('fallback', title=title, close_date='2026-10-13', deadlines=None)
        result = project(record, '2026-10-08')
        self.assertEqual((result['next_submission']['date'], result['next_submission']['access']),
                         ('2026-10-13', 'invitation_required'))
        self.assertEqual(result['deadlines'][0]['kind'], 'application')
        self.assertEqual(result['deadlines'][0]['invitation_evidence'],
            {'source_field': 'title', 'quote': title[:500], 'source_url': record['detail_page']})
        self.assertEqual(result['title'], title)
        self.assertIsNone(record['deadlines'])
        self.assertEqual(project(result, '2026-10-08'), result)

    def test_notice_title_qualification_preserves_preliminary_stages_and_scope_identity(self):
        record = rec('stages', title='Invited to Apply - Research Program', deadlines=[
            {'kind': 'concept_paper', 'date': '2026-10-20', 'required': True, 'cycle': 'FY2027', 'track': 'A'},
            {'kind': 'application', 'date': '2027-02-01', 'cycle': 'FY2027', 'track': 'A'},
            {'kind': 'estimated_application', 'date': '2027-03-01', 'estimated': True, 'cycle': 'FY2028', 'track': 'B'}],
            submission_requirements=[{'kind': 'white_paper', 'date': None, 'required': False, 'track': 'B'}])
        result = project(record, '2026-10-08')
        self.assertEqual(result['next_submission']['access'], 'open')
        self.assertEqual(result['deadlines'][0], record['deadlines'][0])
        self.assertEqual(result['submission_requirements'], record['submission_requirements'])
        for before, after in zip(record['deadlines'][1:], result['deadlines'][1:]):
            self.assertTrue(after['invitation_required'])
            self.assertEqual({k: after[k] for k in before}, before)
        self.assertEqual(next_submission(result, '2026-11-01')['access'], 'invitation_required')

    def test_invited_notice_remains_current_but_never_emits_open_closing_reminder(self):
        case = next(c for c in json.loads(FIXTURE.read_text(encoding='utf8'))
                    if (c.get('source_record') or {}).get('opportunity_id') == '362990')
        record = project(case['source_record'], '2026-10-08')
        self.assertTrue(record_is_current(record, date(2026, 10, 8))[0])
        self.assertEqual(record['close_date'], '2026-10-13')
        changes = diff_catalogs(catalog([]), catalog([record]), as_of=date(2026, 10, 8))
        self.assertEqual([event['type'] for event in changes], ['new'])
        self.assertIn('invitation required', summarize(record, date(2026, 10, 8)))

    def test_two_step_projection_requires_one_explicit_owned_pair_and_matching_full_date(self):
        source = next(case['source_record'] for case in json.loads(FIXTURE.read_text(encoding='utf8'))
                      if (case.get('source_record') or {}).get('opportunity_id') == '363734')
        for fault in ('no_obligation', 'optional_stage', 'duplicate_pair', 'extra_step_date', 'invalid_date',
                      'reversed_order', 'different_close', 'different_full_event', 'competing_cycle', 'conflicting_preliminary'):
            with self.subTest(fault=fault):
                record = deepcopy(source)
                if fault == 'no_obligation':
                    record['description'] = record['description'].replace('only proposers that submit', 'proposers may submit')
                elif fault == 'optional_stage':
                    record['description'] = record['description'].replace('will be eligible to submit', 'are encouraged to submit')
                elif fault == 'duplicate_pair':
                    record['description'] += ' Step-1 proposals are due September 29, 2026, and Step-2 proposals are due December 4, 2026.'
                elif fault == 'extra_step_date':
                    record['description'] += ' Step-1 proposals are due October 1, 2026.'
                elif fault == 'invalid_date':
                    record['description'] = record['description'].replace('September 29, 2026', 'September 31, 2026')
                elif fault == 'reversed_order':
                    record['description'] = record['description'].replace('September 29, 2026', 'December 5, 2026')
                elif fault == 'different_close':
                    record['close_date'] = '2026-12-05'
                elif fault == 'different_full_event':
                    record['deadlines'][0]['date'] = '2026-12-05'
                elif fault == 'competing_cycle':
                    record['deadlines'].append({'kind': 'application', 'date': '2027-12-04', 'cycle': 'FY2027'})
                else:
                    record['deadlines'].append({'kind': 'preproposal', 'date': '2026-09-20', 'required': False})
                before = deepcopy(record)
                self.assertEqual(project_two_step_prerequisite(record), before)
                self.assertEqual(record, before)

    def test_two_step_source_evidence_does_not_relabel_failed_document_or_move_full_deadline(self):
        case = next(case for case in json.loads(FIXTURE.read_text(encoding='utf8'))
                    if case['name'].startswith('NASA SSERVI missed'))
        source = case['source_record']
        result = project(source, '2026-10-08')
        self.assertEqual(result['deadlines'][0], source['deadlines'][0])
        self.assertEqual(result['document_evidence_status'], 'failed')
        self.assertEqual(result.get('document_evidence'), source.get('document_evidence'))
        prerequisite = result['next_submission']['prerequisites'][0]
        self.assertTrue(prerequisite['required'])
        for field in ('citation', 'requirement_citation'):
            self.assertIn(prerequisite[field]['quote'], source['description'])
            self.assertEqual(prerequisite[field]['source_url'], source['detail_page'])
        self.assertEqual(result['next_submission']['date'], source['close_date'])
        self.assertEqual(result['next_submission']['access'], 'prerequisite_closed')
        self.assertEqual(project(result, '2026-10-08'), result)
        changes = diff_catalogs(catalog([]), catalog([result]), as_of=date(2026, 11, 15))
        self.assertNotIn('closing_soon', [event['type'] for event in changes])

    def test_invalid_calendar_values_are_never_selected(self):
        for day in ['2027-02-30', '2027-13-01', '02/01/2027']:
            self.assertIsNone(next_submission({'deadlines': [{'kind': 'application', 'date': day}]}, '2026-09-07')['date'])

    def test_parser_correction_is_not_a_sponsor_amendment(self):
        before = rec('one', close_date='2026-12-01', document_evidence={'document': {'sha256': 'same'}})
        after = {**before, 'deadlines': [{'kind': 'concept_paper', 'date': '2026-10-09', 'required': True, 'evidence_id': 'document-field'},
                                       {'kind': 'application', 'date': '2026-12-01'}]}
        after['next_submission'] = next_submission(after, '2026-09-07')
        changes = diff_catalogs(catalog([before]), catalog([after]), as_of=date(2026, 9, 7))
        self.assertEqual([event['type'] for event in changes], ['source_correction'])
        after['document_evidence'] = {'document': {'sha256': 'material-amendment'}}
        changes = diff_catalogs(catalog([before]), catalog([after]), as_of=date(2026, 9, 7))
        self.assertEqual({event['type'] for event in changes}, {'deadline_changed', 'amended'})

    def test_listing_deadline_changes_are_not_suppressed_without_revision_metadata(self):
        before = rec('source:one', source='Official listing', close_date='2026-12-01',
                     last_updated=None, version=None)
        for document in [None, {'document': {'sha256': 'unchanged-attachment'}}]:
            with self.subTest(document=document):
                old = {**before, 'document_evidence': document}
                after = {**old, 'close_date': '2026-12-15'}
                after['next_submission'] = next_submission(after, '2026-09-07')
                changed = diff_catalogs(catalog([old]), catalog([after]), as_of=date(2026, 9, 7))
                self.assertEqual([event['type'] for event in changed], ['deadline_changed'])
        # A source-listed stage can change independently of the headline date.
        old = {**before, 'deadlines': [{'kind': 'concept_paper', 'date': '2026-10-01', 'required': True}],
               'document_evidence': {'document': {'sha256': 'same'}}}
        after = deepcopy(old)
        after['deadlines'][0]['date'] = '2026-10-09'
        after['next_submission'] = next_submission(after, '2026-09-07')
        changed = diff_catalogs(catalog([old]), catalog([after]), as_of=date(2026, 9, 7))
        self.assertEqual([event['type'] for event in changed], ['deadline_changed'])

    def test_same_document_with_new_listing_text_is_not_proven_parser_only(self):
        before = rec('one', close_date='2026-12-01', document_evidence={'document': {'sha256': 'same'}})
        after = {**before, 'description': 'The agency added a concept paper requirement.',
                 'deadlines': [{'kind': 'concept_paper', 'date': '2026-10-09', 'evidence_id': 'doc-new-field'}]}
        after['next_submission'] = next_submission(after, '2026-09-07')
        changed = diff_catalogs(catalog([before]), catalog([after]), as_of=date(2026, 9, 7))
        self.assertEqual([event['type'] for event in changed], ['deadline_changed'])

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
