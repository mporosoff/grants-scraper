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


if __name__ == '__main__':
    unittest.main()
