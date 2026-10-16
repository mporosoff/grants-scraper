"""Captured DARPA child stages remain distinct and conservatively actionable."""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.sources.adapters.darpa_iarpa import DarpaIarpaAdapter
from scripts.sources.merge import resolve_live_records
from scripts.sources.registry import collect
from scripts.submission_schedule import next_submission


FIXTURES = Path(__file__).parent / 'fixtures/darpa_iarpa'
PROGRAM = 'https://www.darpa.mil/research/programs/liquid-surge'
NUMBER = 'DARPA-PA-25-07-05'
AS_OF = date(2026, 10, 16)


def payload():
    return {'darpa': json.loads((FIXTURES / 'liquid_surge.json').read_bytes()),
            'iarpa': (FIXTURES / 'iarpa_empty.html').read_text(encoding='utf-8'),
            'pages': {PROGRAM: (FIXTURES / 'liquid_surge.html').read_text(encoding='utf-8')}}


def source(data=None, as_of=AS_OF):
    instance = DarpaIarpaAdapter()
    instance.set_context({'as_of': as_of})
    with patch.object(instance, 'fetch', return_value=payload() if data is None else data):
        return collect([instance])


class DarpaAbstractScheduleContracts(unittest.TestCase):
    def test_captured_pair_retains_typed_dates_exact_child_citations_and_unknown_requirement(self):
        data = payload()
        records, results = source(data)
        self.assertEqual(len(records), 1)
        self.assertTrue(results[0].ok)
        self.assertTrue(all(part['healthy'] for part in results[0].diagnostics['partitions']))
        record = records[0]
        self.assertEqual(record, json.loads((FIXTURES / 'liquid_surge_record.json').read_bytes()))
        self.assertEqual((record['close_date'], record['close_date_kind']),
                         ('2026-12-14', 'submission_window_end'))
        self.assertTrue(record['has_preliminary_stage'])
        self.assertEqual(record['preliminary_stage_type'], 'abstract')
        self.assertIsNone(record['preliminary_required'])
        self.assertEqual([(event['kind'], event['stage'], event['date']) for event in record['deadlines']],
                         [('abstract', 'abstract', '2026-11-03'), ('application', 'application', '2026-12-14')])
        for event, label, raw_date in zip(record['deadlines'], ('Abstract', 'Proposal'), ('Nov. 3, 2026', 'Dec. 14, 2026')):
            self.assertIsNone(event['required'])
            self.assertEqual(event['obligation'], 'unknown')
            self.assertEqual(event['source_url'], PROGRAM)
            citation = event['citation']
            self.assertEqual(citation['document_url'], PROGRAM)
            self.assertEqual(citation['section'], NUMBER)
            self.assertEqual(citation['quote'], label + ': ' + raw_date)
            self.assertEqual(citation['structural_reference'],
                             {'field_label': label, 'solicitation_number': NUMBER})
            self.assertEqual(citation['sha256'], hashlib.sha256(data['pages'][PROGRAM].encode()).hexdigest())

    def test_actual_adapter_record_preserves_the_later_proposal_with_unverified_abstract_access(self):
        record = source()[0][0]
        for as_of, expected in [('2026-10-16', ('2026-11-03', 'abstract', 'open')),
                                ('2026-11-03', ('2026-11-03', 'abstract', 'open')),
                                ('2026-11-04', ('2026-12-14', 'application', 'verify_prerequisite')),
                                ('2026-12-14', ('2026-12-14', 'application', 'verify_prerequisite'))]:
            with self.subTest(as_of=as_of):
                schedule = next_submission(record, as_of)
                self.assertEqual((schedule['date'], schedule['event']['kind'], schedule['access']), expected)
        self.assertEqual(next_submission(record, '2026-12-15')['access'], 'closed')
        self.assertEqual(len(source(as_of=date(2026, 11, 4))[0]), 1)
        self.assertEqual(source(as_of=date(2026, 12, 15))[0], [])

    def test_staged_parser_does_not_change_the_scalar_deadline_contract(self):
        data = payload()
        data['pages'][PROGRAM] = data['pages'][PROGRAM].replace(
            '&nbsp;<br>Abstract: Nov. 3, 2026<br>Proposal: Dec. 14, 2026', ' Dec. 14, 2026')
        records, results = source(data)
        self.assertTrue(results[0].ok)
        record = records[0]
        self.assertEqual(record['close_date'], '2026-12-14')
        self.assertNotIn('close_date_kind', record)
        self.assertFalse(record['has_preliminary_stage'])
        self.assertEqual([(event['kind'], event['date']) for event in record['deadlines']],
                         [('application', '2026-12-14')])

    def test_missing_unknown_conflicting_and_unparsed_stages_hold_the_darpa_partition(self):
        changes = [('Abstract: Nov. 3, 2026<br>', ''),
                   ('Proposal: Dec. 14, 2026', ''),
                   ('Abstract:', 'Concept:'),
                   ('Proposal:', 'Questions:'),
                   ('Nov. 3, 2026', 'TBD'),
                   ('Nov. 3, 2026', 'Nov. 31, 2026'),
                   ('Abstract: Nov. 3, 2026', 'Abstract: Nov. 3, 2026 Abstract: Nov. 4, 2026'),
                   ('Proposal: Dec. 14, 2026', 'Proposal: Dec. 14, 2026 Questions: Dec. 1, 2026'),
                   ('Proposal: Dec. 14, 2026', 'Proposal: Dec. 14, 2026 Dec. 15, 2026')]
        for old, new in changes:
            data = payload()
            data['pages'][PROGRAM] = data['pages'][PROGRAM].replace(old, new)
            with self.subTest(old=old, new=new):
                records, results = source(data)
                self.assertEqual(records, [])
                self.assertFalse(results[0].ok)
                self.assertIn('submission deadline', results[0].error)
                self.assertIn(NUMBER, results[0].error)
                self.assertIn(PROGRAM, results[0].error)

    def test_inverted_implausible_or_prepublication_stages_are_rejected(self):
        for old, new, message in [('Nov. 3, 2026', 'Dec. 15, 2026', 'Inverted'),
                                  ('Dec. 14, 2026', 'Dec. 14, 2099', 'Implausible'),
                                  ('Oct. 14, 2026', 'Nov. 4, 2026', 'Inverted')]:
            data = payload()
            data['pages'][PROGRAM] = data['pages'][PROGRAM].replace(old, new)
            with self.subTest(old=old, new=new):
                records, results = source(data)
                self.assertEqual(records, [])
                self.assertFalse(results[0].ok)
                self.assertIn(message, results[0].error)

    def test_extra_deadline_or_duplicate_exact_child_cannot_override_the_owned_pair(self):
        for extra in ('<p>Deadline: Dec. 20, 2026</p>',
                      '<p>DARPA-PA-25-07-05</p><p>Deadline: Dec. 20, 2026</p>'):
            data = payload()
            html = data['pages'][PROGRAM]
            position = html.rfind('</div>')
            data['pages'][PROGRAM] = html[:position] + extra + html[position:]
            with self.subTest(extra=extra):
                records, results = source(data)
                self.assertEqual(records, [])
                self.assertFalse(results[0].ok)

    def test_future_or_negated_issuing_language_does_not_admit_the_captured_child(self):
        for phrase in ('DSO will be issuing a Disruption Opportunity',
                       'DSO is not issuing a Disruption Opportunity',
                       'DSO previously issued a Disruption Opportunity',
                       'A Disruption Opportunity may be issued'):
            data = payload()
            for row in data['darpa']:
                for field in ('field_body_with_summary', 'field_body_with_summary_1'):
                    row[field] = (row.get(field) or '').replace('DSO is issuing a Disruption Opportunity', phrase)
            with self.subTest(phrase=phrase):
                records, results = source(data)
                self.assertEqual(records, [])
                self.assertFalse(results[0].ok)
                self.assertIn('research submission evidence', results[0].error)

    def test_issuing_a_call_does_not_override_noncall_or_closed_evidence(self):
        for title in ('RFI: Liquid Surge', 'Draft Liquid Surge', 'Proposers\' Day: Liquid Surge',
                      'Future Program: Liquid Surge', 'Closed: Liquid Surge'):
            data = payload()
            for row in data['darpa']:
                row['title'] = title
            with self.subTest(title=title):
                records, results = source(data)
                self.assertEqual(records, [])
                self.assertTrue(results[0].ok)

    def test_sibling_dates_cannot_fill_a_missing_stage_or_change_the_pair(self):
        data = payload()
        html = data['pages'][PROGRAM]
        sibling = ('<p>DARPA-PA-25-07-99</p><ul><li>Published: Jan. 1, 2026</li>'
                   '<li>Deadline: Abstract: Dec. 1, 2026 Proposal: Dec. 20, 2026</li></ul>')
        position = html.rfind('</div>')
        data['pages'][PROGRAM] = html[:position] + sibling + html[position:]
        record = source(data)[0][0]
        self.assertEqual([event['date'] for event in record['deadlines']], ['2026-11-03', '2026-12-14'])
        data['pages'][PROGRAM] = data['pages'][PROGRAM].replace('Abstract: Nov. 3, 2026<br>', '')
        records, results = source(data)
        self.assertEqual(records, [])
        self.assertFalse(results[0].ok)

    def test_failed_pair_keeps_source_health_degraded_and_does_not_republish_a_prior_snapshot(self):
        prior = source()[0]
        data = payload()
        data['pages'][PROGRAM] = data['pages'][PROGRAM].replace('Nov. 3, 2026', 'TBD')
        records, results = source(data)
        self.assertEqual(records, [])
        cache = {'sources': {'darpa-iarpa': {'records': deepcopy(prior), 'fetched_at': '2026-10-15'}}}
        live, updated, summaries = resolve_live_records(results, cache, AS_OF)
        self.assertEqual(live, [])
        self.assertEqual(updated['sources']['darpa-iarpa']['records'], [])
        self.assertEqual(summaries[0]['status'], 'partial_refresh')
        self.assertFalse(summaries[0]['healthy'])
        self.assertEqual(summaries[0]['publication_decision'], 'published_independently_verified_records')


if __name__ == '__main__':
    unittest.main()
