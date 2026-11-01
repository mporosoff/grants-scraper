"""Explicit native clocks survive field precedence without cross-scope guesses."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import extract_document_evidence as e, notice_schedule as schedule


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/parsing/doe-submission-clocks.json').read_bytes())


def extract(texts, review=None):
    return schedule.extract_native(e, 'fixture', [{'text': text, 'page': index + 1}
        for index, text in enumerate(texts)], {'url': 'https://example.gov/notice.pdf', 'sha256': 'fixture'},
        'retained-source-clock', review)


def clocks(facts):
    return {(f['deadline_kind'], f['date']): schedule.clock_key(f.get('time'), f.get('timezone')) for f in facts}


class SubmissionClockFieldTests(unittest.TestCase):
    def test_exact_scaled_and_genesis_native_cover_table_precedence(self):
        for case in FIXTURE['cases']:
            with self.subTest(opportunity_id=case['opportunity_id']):
                found = e.extract_deadlines(case['opportunity_id'], deepcopy(case['containers']),
                    case['document'], case['checked_at'], [])
                actual = clocks(found)
                if case['opportunity_id'] == '364174':
                    self.assertEqual(actual[('concept_paper', '2026-11-20')], ('5:00pm', 'et'))
                    self.assertEqual(actual[('application', '2027-02-08')], ('5:00pm', 'et'))
                    full = next(f for f in found if f['deadline_kind'] == 'application')
                    self.assertEqual(full['citation']['page'], 5)
                    self.assertTrue(full.get('clock_citation'))
                else:
                    self.assertEqual(actual[('letter_of_intent', '2026-11-09')], ('5:00pm', 'et'))
                    self.assertEqual(actual[('application', '2027-01-12')], ('11:59pm', 'et'))

    def test_scoped_key_dates_default_and_explicit_override(self):
        text = ('KEY DATES\nAll deadlines are 5:00 p.m. ET unless indicated otherwise\n'
                'Concept Paper Deadline: May 1, 2027\nApplication Deadline: June 1, 2027, 11:59 PM ET\n'
                'Anticipated Award Date: July 1, 2027')
        self.assertEqual(clocks(extract([text])), {('concept_paper', '2027-05-01'): ('5:00pm', 'et'),
                                                  ('application', '2027-06-01'): ('11:59pm', 'et')})
        self.assertEqual(clocks(extract([text.replace('KEY DATES', 'General guidance')]))[('concept_paper', '2027-05-01')], ('', ''))
        other_page = extract([text, 'Application Deadline: August 1, 2027'])
        self.assertEqual(clocks(other_page)[('application', '2027-08-01')], ('', ''))
        other_section = text + '\nII. Other Dates\nApplication Deadline: August 1, 2027'
        self.assertEqual(clocks(extract([other_section]))[('application', '2027-08-01')], ('', ''))

    def test_dotted_zone_and_concept_due_do_not_need_default_inference(self):
        found = extract(['Concept Paper Due: May 1, 2027, 5:00 PM E.T.\n'
                         'Application Due: June 1, 2027, 5:00 PM E.T.'])
        self.assertEqual(clocks(found), {('concept_paper', '2027-05-01'): ('5:00pm', 'et'),
                                       ('application', '2027-06-01'): ('5:00pm', 'et')})
        unknown = extract(['Application Due: June 1, 2027, 5:00 PM X.Y.'])
        self.assertIsNone(unknown[0].get('timezone'))

    def test_conflicting_explicit_clocks_withhold_only_clock(self):
        for reverse in (False, True):
            sources = ['Application Deadline: May 1, 2027 at 5 PM ET',
                       'Application Due: May 1, 2027 at 6 PM ET']
            review = []
            found = extract(list(reversed(sources)) if reverse else sources, review)
            self.assertEqual(clocks(found), {('application', '2027-05-01'): ('', '')})
            self.assertTrue(review)

    def test_unclassified_cover_cannot_enrich_coincident_new_resubmission_groups(self):
        original = deepcopy(FIXTURE['cases'][0]['facts'][0])
        rows = [{**deepcopy(original), 'date': '2027-05-01', 'value': '2027-05-01',
                 'application_class': group, 'time': None, 'timezone': None} for group in ('new', 'resubmission')]
        with patch.object(schedule, '_table_fields', return_value=rows):
            found = extract(['Application Due: May 1, 2027 at 5 PM ET'])
        self.assertEqual(len(found), 2)
        self.assertEqual({f['application_class'] for f in found}, {'new', 'resubmission'})
        self.assertTrue(all(f['time'] is None for f in found))

    def entry(self, case):
        return {'status': 'current', 'document': deepcopy(case['document']), 'checked_at': case['checked_at'],
                'facts': deepcopy(case['facts']), 'review_queue': [], 'version_history': [{'version': 1}]}

    def test_retained_quote_repair_is_precise_and_idempotent(self):
        for case in FIXTURE['cases']:
            with self.subTest(opportunity_id=case['opportunity_id']):
                entry = self.entry(case); before = deepcopy(entry)
                self.assertTrue(schedule.repair_cached_submission_clocks(e, case['record'], entry))
                actual = clocks(entry['facts'])
                if case['opportunity_id'] == '364174':
                    self.assertEqual(set(actual.values()), {('5:00pm', 'et')})
                else:
                    self.assertEqual(actual[('application', '2027-01-12')], ('11:59pm', 'et'))
                self.assertEqual({k: v for k, v in entry.items() if k not in ('facts', 'submission_clock_repair')},
                                 {k: v for k, v in before.items() if k != 'facts'})
                for old, new in zip(before['facts'], entry['facts']):
                    allowed = {'time', 'timezone', 'display_value', 'clock_citation', 'clock_fields_version'}
                    self.assertEqual({k: v for k, v in old.items() if k not in allowed},
                                     {k: v for k, v in new.items() if k not in allowed})
                self.assertFalse(entry['submission_clock_repair']['source_retrieved'])
                repaired = deepcopy(entry)
                self.assertFalse(schedule.repair_cached_submission_clocks(e, case['record'], entry))
                self.assertEqual(entry, repaired)

    def test_cached_conflicting_known_time_or_zone_is_never_overwritten(self):
        case = FIXTURE['cases'][0]
        for value in ({'time': '6 PM', 'timezone': None}, {'time': None, 'timezone': 'PT'},
                      {'time': None, 'timezone': 'EST'}):
            entry = self.entry(case); entry['facts'] = [entry['facts'][1]]
            entry['facts'][0].update(value)
            before = deepcopy(entry)
            self.assertFalse(schedule.repair_cached_submission_clocks(e, case['record'], entry))
            self.assertEqual(entry, before)

    def test_unbound_clipped_or_non_doe_cache_cannot_supply_new_clock(self):
        case = FIXTURE['cases'][0]
        for mode in ('wrong_hash', 'wrong_url', 'clipped', 'non_doe'):
            entry = self.entry(case); record = deepcopy(case['record'])
            if mode == 'non_doe':
                record['opportunity_number'] = 'OTHER-CALL'
            else:
                for fact in entry['facts']:
                    if mode == 'wrong_hash': fact['citation']['sha256'] = 'other'
                    elif mode == 'wrong_url': fact['citation']['document_url'] = 'https://other.gov/notice'
                    else: fact['citation']['quote'] = 'Application Deadline: February 8, 2027, 5:00 PM E…'
            before = deepcopy(entry)
            self.assertFalse(schedule.repair_cached_submission_clocks(e, record, entry))
            self.assertEqual(entry, before)


if __name__ == '__main__':
    unittest.main()
