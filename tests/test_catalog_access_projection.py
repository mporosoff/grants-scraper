"""Exact retained-source access repair preserves dates, membership and history."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_changes
from scripts.submission_schedule import next_submission
from tools import catalog_access_projection as a, release_candidate as c


class AccessProjectionTests(unittest.TestCase):
    def setUp(self):
        self.stamp = '2026-10-08T19:03:50.931739Z'
        self.audit = '2026-10-12T15:00:00Z'
        self.rows = []
        for ident in sorted(a.CHANGED):
            row = {'opportunity_id': ident, 'title': 'Invited to Apply - ' + ident,
                   'status': 'forecasted' if ident == '362574' else 'posted',
                   'agency': 'Agency', 'source': 'Grants.gov', 'source_type': 'Federal',
                   'description': 'Immutable source text for ' + ident,
                   'eligibility_text': 'The named applicants are eligible.',
                   'topic_areas': ['science'], 'posted_date': '2026-10-08',
                   'close_date': '2026-10-25', 'detail_page': 'https://www.grants.gov/search-results-detail/' + ident,
                   'deadlines': [{'kind': 'application', 'date': '2026-10-25',
                                  'time': None, 'source': 'Grants.gov XML extract', 'detail_checked_at': self.stamp}],
                   'submission_requirements': None}
            if ident == '363734':
                row.update(title='Solar System Exploration Research Virtual Institute Cooperative Agreement Notice-5 (SSERVI CAN-5)',
                           description='A two-step process will be used for proposal submission, in which only proposers that submit a Step-1 proposal will be eligible to submit a Step-2 proposal. Step-1 proposals are due September 29, 2026, and Step-2 proposals are due December 4, 2026.',
                           close_date='2026-12-04', has_preliminary_stage=False,
                           preliminary_required=None, preliminary_stage_type=None)
                row['deadlines'][0]['date'] = '2026-12-04'
            row['next_submission'] = next_submission(row, '2026-10-08')
            self.rows.append(row)
        other = deepcopy(self.rows[0])
        other.update(opportunity_id='unrelated', title='Open research competition')
        self.rows.append(other)
        self.before = {'schema_version': 1, 'generated_at': self.stamp,
                       'record_count': len(self.rows), 'opportunities': self.rows,
                       'status_counts': {'posted': 9, 'forecasted': 1},
                       'detail_enrichment_generated_at': self.stamp,
                       'diagnostics': {'additional_sources': {'merged_at': self.stamp,
                           'lifecycle': [{'healthy': False, 'status': 'retained'}]}}}
        current = next(row for row in self.rows if row['opportunity_id'] == '362990')
        self.prior = {'schema_version': 1, 'generated_at': self.stamp, 'retention_days': 90,
                      'events': [
                          {'id': 'closing', 'type': 'closing_soon', 'changed_at': self.stamp,
                           'opportunity_id': '362990', 'label': 'Closing soon', 'detail': 'Deadline 2026-10-25',
                           'record': build_changes._snapshot(current)},
                          {'id': 'new', 'type': 'new', 'changed_at': self.stamp, 'opportunity_id': '362990',
                           'detail': 'First appeared', 'record': build_changes._snapshot(current)},
                          {'id': 'old-closed', 'type': 'closed_or_removed', 'changed_at': '2026-09-01T00:00:00Z',
                           'opportunity_id': '362990', 'detail': 'Historical observation',
                           'record': {'title': 'Historical title', 'status': 'closed', 'close_date': '2026-08-30'}},
                          {'id': 'old-new', 'type': 'new', 'changed_at': '2026-09-01T00:00:00Z',
                           'opportunity_id': '360458', 'record': build_changes._snapshot(self.rows[0])},
                          {'id': 'unrelated-event', 'type': 'new', 'changed_at': self.stamp,
                           'opportunity_id': 'unrelated', 'record': build_changes._snapshot(other)}]}
        self.evidence = {'schema_version': 1, 'candidate_id': a.PARENT_ID,
                         'record_count': len(self.rows), 'corrections': [
                             {'opportunity_id': row['opportunity_id'], 'record_sha256': a.value_hash(row),
                              'expected_access': 'prerequisite_closed' if row['opportunity_id'] == '363734' else 'invitation_required',
                              'evidence': [{'source_field': 'title', 'quote': row['title']}]} for row in self.rows[:-1]],
                         'affected_event_hashes': {event['id']: a.value_hash(event) for event in self.prior['events']
                                                  if event['opportunity_id'] in a.CHANGED},
                         'event_corrections': [{'event_id': 'closing', 'action': 'suppress_closing_soon'},
                                              {'event_id': 'new', 'action': 'correct_current_new_snapshot'}]}
        nasa = next(item for item in self.evidence['corrections'] if item['opportunity_id'] == '363734')
        url = 'https://www.grants.gov/search-results-detail/363734'
        citation = lambda quote: {'source_field': 'description', 'quote': quote, 'source_url': url}
        nasa['stage_fields'] = dict(a.NASA_STAGE_FIELDS)
        nasa['additional_submission_events'] = {'deadlines': [
            {'kind': 'preproposal', 'stage': 'preproposal', 'date': '2026-09-29', 'required': True,
             'source': 'Grants.gov synopsis', 'source_url': url, 'source_field': 'description',
             'confidence': 'source_listed',
             'citation': citation('Step-1 proposals are due September 29, 2026, and Step-2 proposals are due December 4, 2026'),
             'requirement_citation': citation('only proposers that submit a Step-1 proposal will be eligible to submit a Step-2 proposal')}]}

    def test_access_only_with_original_source_and_generation_clocks(self):
        original = deepcopy(self.before)
        result, proof = a.corrected_catalog(self.before, self.evidence, self.audit)
        self.assertEqual(self.before, original)
        self.assertEqual(result['opportunities'][-1], self.rows[-1])
        self.assertEqual(result['generated_at'], self.stamp)
        self.assertEqual(result['detail_enrichment_generated_at'], self.stamp)
        self.assertEqual(result['diagnostics']['additional_sources'], self.before['diagnostics']['additional_sources'])
        self.assertEqual(result['catalog_audit_generated_at'], self.audit)
        self.assertEqual(set(proof), a.CHANGED)
        for old, new in zip(self.rows[:-1], result['opportunities'][:-1]):
            expected = 'prerequisite_closed' if old['opportunity_id'] == '363734' else 'invitation_required'
            self.assertEqual(new['next_submission']['access'], expected)
            self.assertEqual(new['next_submission']['as_of'], '2026-10-08')
            allowed = a.ACCESS_FIELDS | (a.NASA_STAGE_FIELDS.keys() if old['opportunity_id'] == '363734' else set())
            for key in old.keys() - allowed:
                self.assertEqual(new[key], old[key])
            self.assertTrue(set(proof[old['opportunity_id']]['changed_fields']) <= allowed)

    def test_rejects_changed_source_record_or_partial_correction_list(self):
        changed = deepcopy(self.before)
        changed['opportunities'][0]['description'] = 'A different source response'
        with self.assertRaisesRegex(ValueError, 'exact_record'):
            a.corrected_catalog(changed, self.evidence, self.audit)
        changed = deepcopy(self.evidence)
        changed['corrections'].pop()
        with self.assertRaisesRegex(ValueError, 'fixed_correction_set'):
            a.corrected_catalog(self.before, changed, self.audit)

    def test_rejects_invented_evidence_and_bad_audit_clocks(self):
        changed = deepcopy(self.evidence)
        changed['corrections'][0]['evidence'][0]['quote'] = 'Not in the official source'
        with self.assertRaisesRegex(ValueError, 'evidence_quote'):
            a.corrected_catalog(self.before, changed, self.audit)
        for stamp in ('2026-10-01T00:00:00Z', '2026-10-12T15:00:00'):
            with self.assertRaisesRegex(ValueError, 'audit_clock'):
                a.corrected_catalog(self.before, self.evidence, stamp)

    def test_rejects_interpreter_changes_outside_access_and_source_dates(self):
        from scripts.submission_schedule import project
        for mode, reason in (('description', 'only_access_fields'), ('deadline', 'source_event_values'),
                             ('missing_null', 'source_event_values')):
            def changed(row, as_of):
                result = project(row, as_of)
                if mode == 'description':
                    result['description'] = 'Altered source facts'
                elif mode == 'deadline':
                    result['deadlines'][0]['date'] = '2026-10-24'
                else:
                    result['deadlines'][0].pop('time')
                return result
            with patch('scripts.submission_schedule.project', side_effect=changed):
                with self.assertRaisesRegex(ValueError, reason):
                    a.corrected_catalog(self.before, self.evidence, self.audit)

    def test_history_correction_suppresses_only_wrong_current_closing_event(self):
        before = deepcopy(self.prior)
        catalog, _ = a.corrected_catalog(self.before, self.evidence, self.audit)
        result, proof = a.corrected_changes(self.prior, self.before, catalog, self.evidence, self.audit)
        self.assertEqual(self.prior, before)
        events = {event['id']: event for event in result['events']}
        self.assertNotIn('closing', events)
        for ident in ('old-closed', 'old-new', 'unrelated-event'):
            self.assertEqual(events[ident], next(event for event in before['events'] if event['id'] == ident))
        self.assertEqual(events['new']['changed_at'], self.stamp)
        self.assertEqual(events['new']['record']['next_submission']['access'], 'invitation_required')
        additions = [event for event in result['events'] if event['type'] == 'source_correction']
        self.assertEqual(len(additions), len(a.CHANGED))
        self.assertEqual({event['opportunity_id'] for event in additions}, a.CHANGED)
        self.assertTrue(all(event['changed_at'] == self.audit for event in additions))
        self.assertFalse(any(event['type'] == 'amended' for event in result['events']))
        self.assertEqual(proof['closing']['before_sha256'], self.evidence['affected_event_hashes']['closing'])

    def test_history_hash_and_frame_drift_fail_closed(self):
        after, _ = a.corrected_catalog(self.before, self.evidence, self.audit)
        changed = deepcopy(self.prior)
        changed['events'][0]['detail'] = 'Different event'
        with self.assertRaisesRegex(ValueError, 'exact_affected_events'):
            a.corrected_changes(changed, self.before, after, self.evidence, self.audit)
        changed = deepcopy(self.prior)
        changed['events'][0]['changed_at'] = '2026-09-01T00:00:00Z'
        evidence = deepcopy(self.evidence)
        evidence['affected_event_hashes']['closing'] = a.value_hash(changed['events'][0])
        with self.assertRaisesRegex(ValueError, 'current_event_access'):
            a.corrected_changes(changed, self.before, after, evidence, self.audit)

    def fixture(self, directory):
        parent = Path(directory) / 'files'
        c.write_json(parent.parent / 'candidate.json', {'candidate_id': a.PARENT_ID})
        (parent / 'data').mkdir(parents=True)
        (parent / 'data/opportunities.js').write_text('globalThis.GRANT_CATALOG=' + json.dumps(self.before) + ';', encoding='utf8')
        c.write_json(parent / 'data/source_records.json', {'sources': {}})
        c.write_json(parent / 'feeds/changes.json', self.prior)
        evidence = deepcopy(self.evidence)
        evidence['candidate_manifest_sha256'] = c.digest((parent.parent / 'candidate.json').read_bytes())
        evidence['input_hashes'] = {name: c.digest((parent / name).read_bytes()) for name in
                                   ('data/opportunities.js', 'data/source_records.json', 'feeds/changes.json')}
        return parent, evidence

    def test_projection_is_repeatable_without_touching_parent_or_source_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            parent, evidence = self.fixture(directory)
            original = {p.relative_to(parent).as_posix(): p.read_bytes() for p in parent.rglob('*') if p.is_file()}
            with patch.object(a, 'policy', return_value=evidence):
                first = a.projection(parent, self.audit)
                self.assertEqual(first, a.projection(parent, self.audit))
            outputs, proof = first
            self.assertNotIn('data/source_records.json', outputs)
            self.assertIn('feeds/topic/science.xml', outputs)
            self.assertIn('feeds/source-type/federal.xml', outputs)
            self.assertIn(b'invitation required', outputs['feeds/all.xml'])
            self.assertNotIn(b'Closing soon', outputs['feeds/changes.xml'])
            self.assertEqual(proof['source_requests'], 0)
            self.assertEqual(proof['provider_requests'], 0)
            self.assertEqual(original, {p.relative_to(parent).as_posix(): p.read_bytes() for p in parent.rglob('*') if p.is_file()})

    def test_projection_rejects_parent_or_input_drift(self):
        for target, reason in (('candidate.json', 'exact_parent'), ('files/data/opportunities.js', 'exact_inputs')):
            with tempfile.TemporaryDirectory() as directory:
                parent, evidence = self.fixture(directory)
                path = Path(directory) / target
                path.write_bytes(path.read_bytes() + b' ')
                with patch.object(a, 'policy', return_value=evidence):
                    with self.assertRaisesRegex(ValueError, reason):
                        a.projection(parent, self.audit)

    def test_unexpected_fallback_record_cannot_be_left_unsafe(self):
        with tempfile.TemporaryDirectory() as directory:
            parent, evidence = self.fixture(directory)
            c.write_json(parent / 'data/source_records.json', {'sources': {'unexpected': {'records': [self.rows[0]]}}})
            evidence['input_hashes']['data/source_records.json'] = c.digest((parent / 'data/source_records.json').read_bytes())
            with patch.object(a, 'policy', return_value=evidence):
                with self.assertRaisesRegex(ValueError, 'unexpected_cached_record'):
                    a.projection(parent, self.audit)


if __name__ == '__main__':
    unittest.main()
