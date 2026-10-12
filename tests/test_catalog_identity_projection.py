from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.build_catalog import catalog_javascript_bytes
from scripts.build_changes import diff_catalogs
from tools import catalog_identity_projection as a, release_candidate as c


class IdentityProjectionTests(unittest.TestCase):
    def setUp(self):
        self.stamp = '2026-10-12T16:08:24.355794Z'
        self.audit = '2026-10-12T18:00:00Z'
        self.old_id = 'nasa-roses:25-B.8-c9ad18a888'
        def row(ident):
            return {'opportunity_id': ident, 'title': 'Public science call ' + ident,
                    'source': 'Grants.gov', 'source_type': 'Federal', 'agency': 'NASA Headquarters',
                    'status': 'posted', 'posted_date': '2026-10-08', 'close_date': '2027-02-05',
                    'opportunity_number': 'NNH25ZDA001N-SSF' if ident == '364039' else ident,
                    'description': 'Exact retained scientific content.', 'topic_areas': ['science'],
                    'detail_page': 'https://www.grants.gov/search-results-detail/' + ident}
        self.before = {'schema_version': 1, 'generated_at': self.stamp, 'record_count': 3,
                       'detail_enrichment_generated_at': self.stamp,
                       'diagnostics': {'additional_sources': {'merged_at': self.stamp}},
                       'opportunities': [row('364039'), row('363829'), row('unrelated')]}
        aliases = {'364039': [{'opportunity_id': self.old_id, 'opportunity_number': 'NNH25ZDA001N-SSF',
                              'source': 'NASA ROSES', 'detail_page': 'https://solicitation.nasaprs.com/NNH25ZDA001N-SSF',
                              'funding_opportunity_url': 'https://solicitation.nasaprs.com/NNH25ZDA001N-SSF'}],
                   '363829': [{'opportunity_id': 'vpr-email:vpr-a3ddeff815d159a4', 'source': 'VPR digest',
                              'official_identity': {'version': 1, 'target_url': 'https://www.grants.gov/search-results-detail/363829'}}]}
        self.history = {'schema_version': 1, 'generated_at': '2026-10-12T16:13:11Z', 'retention_days': 90,
                        'events': [
                            {'id': '7278311ccd6ffc55323b', 'type': 'new', 'opportunity_id': '364039',
                             'changed_at': self.stamp, 'record': self.before['opportunities'][0]},
                            {'id': '889ae59b100100c3b09b', 'type': 'closed_or_removed', 'opportunity_id': self.old_id,
                             'changed_at': self.stamp, 'record': {'title': 'Original NASA science'}},
                            {'id': 'original-arrival', 'type': 'new', 'opportunity_id': self.old_id,
                             'changed_at': '2026-10-08T19:03:50.931739Z', 'record': {'title': 'Original NASA science'}},
                            {'id': 'unrelated-event', 'type': 'amended', 'opportunity_id': 'unrelated',
                             'changed_at': self.stamp, 'record': self.before['opportunities'][-1]}]}
        kept = self.history['events'][2:]
        self.evidence = {'schema_version': 1, 'candidate_id': a.PARENT_ID, 'previous_candidate_id': a.PREVIOUS_ID,
                         'previous_record_hashes': {i: 'a' * 64 for i in a.PREVIOUS_RECORDS},
                         'record_count': 3, 'original_generated_at': self.stamp,
                         'corrections': [{'opportunity_id': r['opportunity_id'],
                             'previous_opportunity_id': self.old_id if r['opportunity_id'] == '364039' else '363829',
                             'record_sha256': a.value_hash(r), 'source_aliases': aliases[r['opportunity_id']],
                             'expected_record_sha256': a.value_hash(r | {'source_aliases': aliases[r['opportunity_id']]})}
                            for r in self.before['opportunities'][:2]],
                         'removed_event_hashes': {e['id']: a.value_hash(e) for e in self.history['events'][:2]},
                         'retained_event_count': len(kept), 'retained_events_sha256': a.value_hash(kept)}

    def test_aliases_only_and_all_original_clocks_and_science_retained(self):
        original = deepcopy(self.before)
        after, proof = a.corrected_catalog(self.before, self.evidence, self.audit)
        self.assertEqual(self.before, original)
        self.assertEqual(set(proof), a.CHANGED)
        for old, new in zip(self.before['opportunities'], after['opportunities']):
            self.assertEqual({k: v for k, v in new.items() if k != 'source_aliases'}, old)
        self.assertEqual({k: v for k, v in after.items() if k != 'opportunities'},
                         {k: v for k, v in original.items() if k != 'opportunities'})
        previous = deepcopy(self.before)
        previous['opportunities'][0]['opportunity_id'] = self.old_id
        previous['opportunities'][0]['source'] = 'NASA ROSES'
        self.assertEqual(diff_catalogs(previous, after, as_of=date(2026, 10, 12)), [])

    def test_record_policy_and_expected_alias_tampering_fail_closed(self):
        for mutate, reason in [
            (lambda b, e: b['opportunities'][0].update(description='Changed science'), 'exact_record'),
            (lambda b, e: e['corrections'].pop(), 'fixed_policy'),
            (lambda b, e: e['corrections'][0]['source_aliases'][0].update(detail_page='https://wrong.example'), 'expected_record'),
            (lambda b, e: e['corrections'][0]['source_aliases'][0].update(opportunity_id='wrong'), 'unique_alias_owner')]:
            before, evidence = deepcopy(self.before), deepcopy(self.evidence)
            mutate(before, evidence)
            with self.assertRaisesRegex(ValueError, reason):
                a.corrected_catalog(before, evidence, self.audit)

    def test_colliding_alias_owner_and_duplicate_current_ids_fail_closed(self):
        for kind in ('direct', 'alias', 'duplicate'):
            before = deepcopy(self.before)
            if kind == 'direct': before['opportunities'][-1]['opportunity_id'] = self.old_id
            elif kind == 'alias': before['opportunities'][-1]['source_aliases'] = [{'opportunity_id': self.old_id}]
            else: before['opportunities'][-1]['opportunity_id'] = '364039'
            with self.assertRaisesRegex(ValueError, 'unique_alias_owner|parent_membership'):
                a.corrected_catalog(before, self.evidence, self.audit)

    def test_bad_audit_or_generation_clocks_fail_closed(self):
        for stamp in ('2026-10-11T12:00:00Z', '2026-10-12T18:00:00'):
            with self.assertRaisesRegex(ValueError, 'audit_clock'):
                a.corrected_catalog(self.before, self.evidence, stamp)
        before = deepcopy(self.before); before['generated_at'] = '2026-10-12T16:09:00Z'
        with self.assertRaisesRegex(ValueError, 'generation_clock'):
            a.corrected_catalog(before, self.evidence, self.audit)

    def test_only_two_false_events_removed_without_fabricated_observation(self):
        original = deepcopy(self.history)
        result, proof = a.corrected_changes(self.history, self.before, self.evidence)
        self.assertEqual(self.history, original)
        self.assertEqual(result['events'], original['events'][2:])
        self.assertEqual(result['generated_at'], original['generated_at'])
        self.assertEqual(set(proof), a.REMOVED_EVENTS)
        self.assertEqual({k: v for k, v in result.items() if k != 'events'},
                         {k: v for k, v in original.items() if k != 'events'})

    def test_event_content_date_inventory_and_retained_history_are_authenticated(self):
        for kind, reason in [('removed', 'exact_removed_events'), ('retained', 'exact_retained_history'),
                             ('duplicate', 'unique_event_ids'), ('date', 'current_false_event')]:
            history, evidence = deepcopy(self.history), deepcopy(self.evidence)
            if kind == 'removed': history['events'][0]['record']['title'] = 'Forged event'
            elif kind == 'retained': history['events'][2]['record']['title'] = 'Rewritten history'
            elif kind == 'duplicate': history['events'].append(deepcopy(history['events'][0]))
            else:
                history['events'][0]['changed_at'] = '2026-10-08T19:03:50Z'
                evidence['removed_event_hashes'][history['events'][0]['id']] = a.value_hash(history['events'][0])
            with self.assertRaisesRegex(ValueError, reason):
                a.corrected_changes(history, self.before, evidence)

    def fixture(self, directory):
        parent = Path(directory) / 'files'
        c.write_json(parent.parent / 'candidate.json', {'candidate_id': a.PARENT_ID})
        (parent / 'data').mkdir(parents=True)
        (parent / 'data/opportunities.js').write_bytes(catalog_javascript_bytes(self.before))
        c.write_json(parent / 'data/source_records.json', {'sources': {'nasa-roses': {'records': []}}})
        c.write_json(parent / 'feeds/changes.json', self.history)
        evidence = deepcopy(self.evidence)
        evidence['candidate_manifest_sha256'] = c.digest((parent.parent / 'candidate.json').read_bytes())
        evidence['input_hashes'] = {name: c.digest((parent / name).read_bytes()) for name in
                                   ('data/opportunities.js', 'data/source_records.json', 'feeds/changes.json')}
        return parent, evidence

    def test_projection_is_repeatable_and_preserves_all_parent_and_source_cache_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            parent, evidence = self.fixture(directory)
            saved = {p.relative_to(parent).as_posix(): p.read_bytes() for p in parent.rglob('*') if p.is_file()}
            with patch.object(a, 'policy', return_value=evidence):
                first = a.projection(parent, self.audit)
                self.assertEqual(first, a.projection(parent, self.audit))
            output, proof = first
            self.assertNotIn('data/source_records.json', output)
            self.assertIn('feeds/topic/science.xml', output)
            self.assertEqual(json.loads(output['feeds/changes.json'])['events'], self.history['events'][2:])
            self.assertEqual(proof['source_requests'], 0)
            self.assertEqual(proof['provider_requests'], 0)
            self.assertEqual(saved, {p.relative_to(parent).as_posix(): p.read_bytes() for p in parent.rglob('*') if p.is_file()})

    def test_projection_rejects_parent_or_any_pinned_input_drift(self):
        for target, reason in [('candidate.json', 'exact_parent'), ('files/data/opportunities.js', 'exact_inputs'),
                               ('files/data/source_records.json', 'exact_inputs'), ('files/feeds/changes.json', 'exact_inputs')]:
            with tempfile.TemporaryDirectory() as directory:
                parent, evidence = self.fixture(directory)
                path = Path(directory) / target
                path.write_bytes(path.read_bytes() + b' ')
                with patch.object(a, 'policy', return_value=evidence):
                    with self.assertRaisesRegex(ValueError, reason):
                        a.projection(parent, self.audit)


if __name__ == '__main__':
    unittest.main()
