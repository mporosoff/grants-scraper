"""Source amendments, outages and recovery must not freeze unrelated updates."""
from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.build_changes import diff_catalogs
from scripts.sources import sam_reviewed
from scripts.sources.adapters.sam_gov import SamGovAdapter
from scripts.sources.base import CanonicalOpportunity, SourceAdapter
from scripts.sources.merge import integrate, load_catalog, save_catalog
from scripts.sources.sam_api import SamError
from tools.require_sam_refresh import require_complete_refresh

FIXTURE = Path(__file__).parent / 'fixtures/sam_release_amendments_20261024.json'


class Peer(SourceAdapter):
    enabled = True
    slug = 'test-peer'
    display_name = 'Verified peer'
    source_type = 'Federal'
    def __init__(self, identifiers):
        super().__init__()
        self.identifiers = identifiers
    def collect(self):
        return [CanonicalOpportunity(title='Research program ' + ident, external_id=ident,
                    agency='Test agency', url='https://example.gov/' + ident, close_date='2026-12-31').to_record(
                    slug=self.slug, source=self.display_name, source_type=self.source_type)
                for ident in self.identifiers]


class SamSourceIsolationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.catalog = self.root / 'catalog.js'
        self.previous = self.root / 'previous.js'
        self.cache = self.root / 'cache.json'
        self.config_path = self.root / 'sam.json'
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf8'))
        self.config = deepcopy(self.fixture['config'])
        self.original = {a['notice_id']: a['reviewed_snapshot'] for a in self.config['approved_notices']}
        save_catalog({'generated_at': '2026-10-20T12:00:00Z', 'opportunities': []}, self.catalog)
        self.refresh(self.original, date(2026, 10, 20), peer=['old'])

    def refresh(self, snapshots, as_of, *, failures=(), peer=('old',)):
        prior = load_catalog(self.catalog)
        save_catalog(prior, self.previous)
        prior['generated_at'] = as_of.isoformat() + 'T12:00:00Z'
        save_catalog(prior, self.catalog)
        self.config_path.write_text(json.dumps(self.config), encoding='utf8')
        def client(identifier):
            if identifier in failures:
                raise SamError('unavailable', {'request_count': 2, 'http_status': 503,
                                              'failure_class': 'transient_transport'})
            return deepcopy(snapshots[identifier]), {'request_count': 2}
        with patch.dict('os.environ', {'VPR_ENRICH_LINKS': 'false', 'SAM_PREFLIGHT_RECEIPT': ''}), \
                patch('scripts.sources.merge.utc_now', return_value=datetime.combine(as_of, datetime.min.time(), timezone.utc)):
            summary = integrate(catalog_path=self.catalog, cache_path=self.cache, previous_catalog_path=self.previous,
                                adapters=[SamGovAdapter(self.config_path, reviewed_client=client), Peer(peer)],
                                as_of=as_of, write=True)
        require_complete_refresh(self.config, summary)
        return prior, load_catalog(self.catalog), summary

    def test_real_three_amendments_allow_healthy_additions_and_confirmed_removals(self):
        case = self.fixture['cases'][-1]
        previous, current, summary = self.refresh(case['snapshots'], date(2026, 10, 24), peer=['new'])
        ids = {r['opportunity_id'] for r in current['opportunities']}
        affected = {'sam-gov:' + value for value in case['expected_review_ids']}
        self.assertFalse(ids & affected)
        self.assertIn('test-peer:new', ids)
        self.assertNotIn('test-peer:old', ids)
        sam = next(s for s in summary['sources'] if s['slug'] == 'sam-gov')
        self.assertEqual(sam['status'], 'partial_refresh')
        self.assertFalse(sam['healthy'])
        self.assertEqual(len(sam['unresolved_records']), 3)
        self.assertEqual(sam['published'], 1)
        events = diff_catalogs(previous, current, as_of=date(2026, 10, 24))
        self.assertIn(('new', 'test-peer:new'), {(e['type'], e['opportunity_id']) for e in events})
        self.assertIn(('closed_or_removed', 'test-peer:old'), {(e['type'], e['opportunity_id']) for e in events})
        self.assertFalse(any(e['opportunity_id'] in affected and e['type'] == 'closed_or_removed' for e in events))

    def test_transport_retains_exact_dated_facts_only_until_the_existing_review_bound(self):
        failed = self.config['approved_notices'][0]['notice_id']
        original = next(r for r in load_catalog(self.catalog)['opportunities'] if r['opportunity_id'] == 'sam-gov:' + failed)
        _, current, summary = self.refresh(self.original, date(2026, 10, 24), failures=[failed])
        retained = next(r for r in current['opportunities'] if r['opportunity_id'] == original['opportunity_id'])
        self.assertEqual(retained, {**original, 'source_observation': 'retained_after_transport_failure'})
        sam = next(s for s in summary['sources'] if s['slug'] == 'sam-gov')
        self.assertEqual(sam['retained_data_age_days'], 4)
        self.assertEqual(sam['retained_transport_ids'], [original['opportunity_id']])
        _, expired, _ = self.refresh(self.original, date(2026, 10, 28), failures=[failed])
        self.assertNotIn(original['opportunity_id'], {r['opportunity_id'] for r in expired['opportunities']})

    def test_quarantine_survives_later_outage_and_old_deadline_without_false_closure(self):
        case = self.fixture['cases'][-1]
        self.refresh(case['snapshots'], date(2026, 10, 24))
        previous, current, summary = self.refresh(case['snapshots'], date(2026, 10, 25), failures=case['expected_review_ids'])
        sam = next(s for s in summary['sources'] if s['slug'] == 'sam-gov')
        self.assertEqual(sam['retained_transport_ids'], [])
        self.assertTrue(all(r['disposition'] == 'review_required' for r in sam['unresolved_records']))
        self.assertEqual(len(current['opportunities']), 2)
        # The last published snapshot may contain a now-passed old entry date.
        # Known changed terms still cannot be turned into a closure notification.
        last_accepted, _ = sam_reviewed.collect(self.config, date(2026, 10, 20), {},
            client=lambda ident: (self.original[ident], {'request_count': 0}))
        prior = {'opportunities': last_accepted}
        events = diff_catalogs(prior, current, as_of=date(2026, 10, 29))
        self.assertFalse(any(e['type'] == 'closed_or_removed' and e['opportunity_id'].startswith('sam-gov:') for e in events))

    def test_reviewed_amendment_recovers_its_identity_after_quarantine_without_new_alert(self):
        case = self.fixture['cases'][-1]
        self.refresh(case['snapshots'], date(2026, 10, 24))
        old_id = case['expected_review_ids'][0]
        item = next(a for a in self.config['approved_notices'] if a['notice_id'] == old_id)
        old_notice = case['snapshots'][old_id]
        new_notice = case['snapshots'][old_notice['latest_notice_id']]
        item.update(notice_id=new_notice['notice_id'], review_sha256=new_notice['review_sha256'],
                    reviewed_snapshot=deepcopy(new_notice), verified_on='2026-10-25', review_after='2026-11-12')
        previous, current, _ = self.refresh(case['snapshots'], date(2026, 10, 25))
        recovered = next(r for r in current['opportunities'] if r['opportunity_id'] == 'sam-gov:' + new_notice['notice_id'])
        self.assertIn('sam-gov:' + old_id, {a['opportunity_id'] for a in recovered['source_aliases']})
        self.assertEqual(recovered['source_observation'], 'reverified_existing_call')
        self.assertEqual(recovered['source_first_seen_date'], '2026-10-20')
        self.assertFalse(any(e['type'] == 'new' and e['opportunity_id'] == recovered['opportunity_id']
                             for e in diff_catalogs(previous, current, as_of=date(2026, 10, 25))))

    def reviewed_amendments(self):
        current = json.loads((FIXTURE.parents[2] / 'config/sam_gov.json').read_text(encoding='utf8'))
        approvals = {item['solicitation_number']: item for item in current['approved_notices']}
        snapshots = deepcopy(self.original)
        snapshots.update(json.loads((FIXTURE.parent / 'sam_amendments_reviewed_20261024.json')
                                    .read_text(encoding='utf8')))
        self.config['approved_notices'] = [deepcopy(approvals[item['solicitation_number']])
                                           for item in self.config['approved_notices']]
        return snapshots

    def test_reviewed_successors_replace_all_three_cached_predecessors_without_interim_quarantine(self):
        history = {
            '693KA8-27-T-00003': ('e3d96ffd4a0a48b080e09dd5af732cc8', '2026-10-12'),
            'HM047627XXXX': ('4984511e4bbc4d01a21df55b30a88f02', '2026-10-17'),
            '693JJ626R000001': ('45850d5326944be1b187cece69fe7790', '2026-10-12'),
        }
        previous = load_catalog(self.catalog)
        cache = json.loads(self.cache.read_text(encoding='utf8'))
        for record in previous['opportunities'] + cache['sources']['sam-gov']['records']:
            if record.get('opportunity_number') in history:
                record['source_first_seen_date'] = history[record['opportunity_number']][1]
        save_catalog(previous, self.catalog)
        self.cache.write_text(json.dumps(cache), encoding='utf8')
        snapshots = self.reviewed_amendments()
        previous, current, summary = self.refresh(snapshots, date(2026, 10, 24))
        sam = next(s for s in summary['sources'] if s['slug'] == 'sam-gov')
        self.assertEqual(sam['published'], 4)
        self.assertTrue(sam['healthy'])
        events = diff_catalogs(previous, current, as_of=date(2026, 10, 24))
        amended = {}
        for number, (old_id, first_seen) in history.items():
            with self.subTest(number=number):
                matches = [r for r in current['opportunities'] if r.get('opportunity_number') == number]
                self.assertEqual(len(matches), 1)
                record = amended[number] = matches[0]
                self.assertEqual(record['status'], 'posted')
                self.assertNotEqual(record['opportunity_id'], 'sam-gov:' + old_id)
                self.assertIn('sam-gov:' + old_id, {a['opportunity_id'] for a in record['source_aliases']})
                self.assertEqual(record['source_first_seen_date'], first_seen)
                self.assertEqual(record['source_last_seen_date'], '2026-10-24')
                self.assertEqual(record['sam_review_reconciliation']['reviewed_on'], '2026-10-24')
                ids = {'sam-gov:' + old_id, record['opportunity_id']}
                self.assertFalse(any(e['opportunity_id'] in ids and e['type'] in {'new', 'closed_or_removed'}
                                     for e in events))
        faa = amended['693KA8-27-T-00003']
        self.assertEqual((faa['deadlines'][0]['kind'], faa['deadlines'][0]['date']),
                         ('concept_paper', '2026-11-02'))
        self.assertTrue(faa['deadlines'][1]['invitation_required'])
        self.assertIn('no required cost sharing', faa['description'])
        nga = amended['HM047627XXXX']
        self.assertEqual([event['date'] for event in nga['deadlines']], ['2026-10-28', '2026-12-21'])
        self.assertTrue(nga['deadlines'][0]['required'])
        self.assertFalse(nga['deadlines'][1]['invitation_required'])
        self.assertIn('conflicting budget figure', nga['description'])
        fra = amended['693JJ626R000001']
        self.assertEqual((fra['deadlines'][0]['kind'], fra['deadlines'][0]['date']),
                         ('concept_paper', '2027-09-30'))
        self.assertTrue(fra['deadlines'][1]['invitation_required'])
        for topic in ('003', '004', '005', '006', '007', '009'):
            self.assertIn('FRA-TR-' + topic, fra['deadlines'][0]['note'])
        self.assertIn('these six topics are excluded', fra['description'])

    def test_reviewed_successor_never_suppresses_a_different_sponsor_organization_or_solicitation(self):
        cached = next(r for r in json.loads(self.cache.read_text(encoding='utf8'))['sources']['sam-gov']['records']
                      if r['opportunity_number'] == '693KA8-27-T-00003')
        snapshots = self.reviewed_amendments()
        for changed in ({'agency': 'A different funding agency'}, {'sam_organization_id': '99999'},
                        {'sam_organization_id': None}, {'opportunity_number': 'ANOTHER-CALL'}):
            with self.subTest(changed=changed):
                prior = dict(cached, **changed)
                rows, _ = sam_reviewed.collect(self.config, date(2026, 10, 24), {'sam-gov': [prior]},
                    client=lambda ident: (deepcopy(snapshots[ident]), {'request_count': 0}))
                retained = next(r for r in rows if r['opportunity_id'] == cached['opportunity_id'])
                self.assertEqual(retained['status'], 'unverified')

    def test_unapproved_changed_expired_or_unavailable_successor_keeps_predecessor_invalidated(self):
        cached = next(r for r in json.loads(self.cache.read_text(encoding='utf8'))['sources']['sam-gov']['records']
                      if r['opportunity_number'] == '693KA8-27-T-00003')
        snapshots = self.reviewed_amendments()
        successor = '897e1427461540d792897c599373758b'
        for outcome in ('removed_approval', 'changed_terms', 'expired_approval', 'unavailable'):
            with self.subTest(outcome=outcome):
                config, notices = deepcopy(self.config), deepcopy(snapshots)
                if outcome == 'removed_approval':
                    config['approved_notices'] = [a for a in config['approved_notices'] if a['notice_id'] != successor]
                elif outcome == 'changed_terms':
                    notices[successor]['description_sha256'] = '0' * 64
                    notices[successor]['review_sha256'] = sam_reviewed.digest(
                        {k: v for k, v in notices[successor].items() if k != 'review_sha256'})
                elif outcome == 'expired_approval':
                    approval = next(a for a in config['approved_notices'] if a['notice_id'] == successor)
                    approval.pop('reviewed_snapshot')
                    approval.update(verified_on='2026-10-01', review_after='2026-10-23')
                def client(ident):
                    if outcome == 'unavailable' and ident == successor:
                        raise SamError('unavailable', {'request_count': 0, 'http_status': 503,
                                                      'failure_class': 'transient_transport'})
                    return deepcopy(notices[ident]), {'request_count': 0}
                rows, _ = sam_reviewed.collect(config, date(2026, 10, 24), {'sam-gov': [cached]}, client=client)
                retained = next(r for r in rows if r['opportunity_id'] == cached['opportunity_id'])
                self.assertEqual(retained['status'], 'unverified')


if __name__ == '__main__':
    unittest.main()
