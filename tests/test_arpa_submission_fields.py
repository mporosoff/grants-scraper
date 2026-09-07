"""Current source structures: preliminary stages and topic-owned package dates."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts import extract_document_evidence as e
from scripts.submission_schedule import next_submission
from scripts.sources.adapters.arpa_h import notice_schedule

CASES = json.loads((Path(__file__).parent / 'fixtures/parsing/arpa-submission-fields.json').read_bytes())['cases']
EXPECTED = {
    'arpa-h:stream': [('preapplication', '2026-09-14', '11:59 pm', 'ET', None, None)],
    'arpa-h:tigar': [('preapplication', '2026-06-08', None, None, True, None),
                     ('application', '2026-09-17', '5:00PM', 'ET', None, None)],
    'arpa-h:rest': [('preapplication', '2026-08-12', None, None, True, None)],
    'arpa-h:fastpass': [('preapplication', '2026-09-21', '4:00PM', 'ET', True, None),
                        ('application', '2026-11-10', '4:00PM', 'ET', None, None)],
    'arpa-h:sbir': [('preapplication', '2026-07-17', '11:59AM', 'ET', None, None),
                    ('application', '2026-09-11', '12:00PM', 'ET', None, 'Topics 1, 2, 3, 4, 6, and 7'),
                    ('application', '2026-10-01', '12:00PM', 'ET', None, 'Topic 5')],
    '363390': [('application', '2026-09-28', '11:59 PM', 'CET', None, None)],
}


def values(facts):
    return sorted({tuple(f.get(k) for k in ('deadline_kind', 'date', 'time', 'timezone', 'required', 'track'))
                   for f in facts if f['type'] == 'deadline'}, key=lambda row: (row[1], row[0]))


class ArpaSubmissionTests(unittest.TestCase):
    def test_source_fields_fresh_and_legacy_revalidation(self):
        for case in CASES:
            key = case['opportunity_id']
            with self.subTest(opportunity=key):
                expected = sorted(EXPECTED[key], key=lambda row: (row[1], row[0]))
                facts = e.extract_deadlines(key, deepcopy(case['containers']), case['source'], case['source_checked_at'])
                self.assertEqual(values(facts), expected)
                old = {'status': 'current', 'document': case['source'], 'checked_at': case['source_checked_at'],
                       'facts': deepcopy(case['legacy_facts']), 'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'},
                       'review_queue': []}
                e.quarantine_legacy_facts({'opportunity_id': key}, {}, old, None)
                self.assertEqual(values(old['facts']), expected)
                self.assertEqual(old['checked_at'], case['source_checked_at'])
                self.assertEqual(old['document'], case['source'])
                if key == 'arpa-h:rest':
                    unknown = next(f for f in facts if f['type'] == 'submission_requirement' and f['deadline_kind'] == 'application')
                    self.assertIsNone(unknown['date'])
                    self.assertTrue(unknown['invitation_required'])

    def test_listing_refinement_does_not_recreate_an_application_or_change_structured_authority(self):
        case = next(c for c in CASES if c['opportunity_id'] == 'arpa-h:stream')
        facts = e.extract_deadlines('fixture', deepcopy(case['containers']), case['source'], case['source_checked_at'])
        entry = {'status': 'current', 'document': case['source'], 'facts': facts, 'checked_at': case['source_checked_at'],
                 'deadline_extractor_identity': e.DEADLINE_EXTRACTOR_IDENTITY}
        record = {'opportunity_id': 'fixture', 'close_date': '2026-09-14', 'deadlines': [
            {'date': '2026-09-14', 'kind': 'application', 'confidence': 'source_listed',
             'source_field': 'source listing', 'source_url': case['source']['url']}]}
        result = e.merge_document_entry(record, entry)
        selected = next_submission(result, '2026-09-07')
        self.assertEqual(selected['event']['kind'], 'preapplication')
        self.assertEqual(result['close_date'], record['close_date'])
        self.assertEqual(len(result['deadlines']), 1)
        self.assertEqual(e.merge_document_entry(result, entry), result)
        # A retrieval failure removes only the evidence refinement, recovering
        # the actual maintained listing default without a new check timestamp.
        failed = e.merge_document_entry(result, {'status': 'failed'})
        self.assertEqual(failed['deadlines'], record['deadlines'])
        record['deadlines'][0]['confidence'] = 'official_structured'
        authoritative = e.merge_document_entry(record, entry)
        self.assertEqual(authoritative['deadlines'][0]['kind'], 'application')
        record['deadlines'][0]['confidence'] = 'source_listed'
        record['deadlines'][0]['source_url'] = 'https://other.gov/notice'
        self.assertEqual(e.merge_document_entry(record, entry)['deadlines'][0]['kind'], 'application')

    def test_adapter_uses_the_same_owned_fields_and_closed_video_qualifies_entry(self):
        case = next(c for c in CASES if c['opportunity_id'] == 'arpa-h:tigar')
        html = ''.join('<p>' + c['text'] + '</p>' for c in case['containers'])
        deadlines = notice_schedule(html, case['source']['url'])
        self.assertEqual([(d['kind'], d['date'], d['required']) for d in deadlines],
                         [('preapplication', '2026-06-08', True), ('application', '2026-09-17', None)])
        selected = next_submission({'deadlines': deadlines}, '2026-09-07')
        self.assertEqual((selected['date'], selected['access']), ('2026-09-17', 'prerequisite_closed'))
        from tests.test_arpa_h_adapter import adapter, payload
        fixture = payload()
        for case in CASES:
            if case['opportunity_id'] in {'arpa-h:stream', 'arpa-h:tigar', 'arpa-h:rest'}:
                route = case['source']['url'].removeprefix('https://arpa-h.gov')
                fixture['detail_pages'][route] = ''.join('<p>' + c['text'] + '</p>' for c in case['containers'])
        records = {r.external_id: r.to_record(slug='arpa-h', source='ARPA-H', source_type='Federal')
                   for r in adapter().parse(fixture)}
        self.assertEqual(records['stream']['close_date'], '2026-09-14')
        self.assertEqual(next_submission(records['stream'], '2026-09-07')['event']['kind'], 'preapplication')
        self.assertEqual(next_submission(records['tigar'], '2026-09-07')['access'], 'prerequisite_closed')
        self.assertFalse(any(d['kind'] == 'application' and d['date'] for d in records['rest']['deadlines']))

    def test_owned_noon_annotation_must_agree_with_clock(self):
        for clock, expected in [('12:00PM ET (noon)', True), ('12 PM ET (noon)', True),
                                ('12:00AM ET (noon)', False), ('1 PM ET (noon)', False)]:
            with self.subTest(clock=clock):
                found = e.TIME_RE.search(clock)
                self.assertIs(e._clock_extent(clock, found)[1], expected)

    def test_unnamed_or_unrelated_actions_cannot_own_generic_submissions(self):
        url = 'https://arpa-h.gov/explore-funding/programs/example'
        for middle in ('Sign-in required to access a budget. ', 'Eligibility is decided separately. '):
            text = 'Solution Summary information. ' + middle + 'Submissions must be submitted by September 14, 2026.'
            self.assertEqual(notice_schedule('<p>' + text + '</p>', url), [])
        text = 'Solution Summary Due: August 12, 2026. Full Proposal Due: October 1, 2026. A summary is required to submit a full proposal.'
        facts = notice_schedule('<p>' + text + '</p>', url)
        self.assertIsNone(next(f for f in facts if f['kind'] == 'preapplication')['required'])


if __name__ == '__main__':
    unittest.main()
