"""Bounded DARPA recovery keeps the parent budget and all unrelated work."""
from copy import deepcopy
from datetime import datetime, timezone
import os
import unittest
from unittest.mock import patch

from scripts.sources.base import CanonicalOpportunity
from scripts.sources.merge import load_catalog, save_catalog
from tests import test_catalog_reconcile as fixtures
from tools import catalog_reconcile as repair
from tools import release_candidate as c


class DarpaReconciliation(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ReconcileContracts(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.root, self.parent, self.state = f.root, f.parent, f.state
        # Public identities of the two calls lost by the 2026-10-29 workshop
        # notice parser failure. Scientific text is a bounded test projection.
        self.rows = []
        for number, title, notice, closed in (
            ('DARPA-PA-25-07-05', 'Liquid Surge', '33a06aa2901440c29518b95f8e099cfa', '2026-12-14'),
            ('DARPA-PA-26-02-01', 'QBI Topic: Independent Verification and Validation',
             '3fc74819705a4a81b205327ba4537973', '2026-12-30'),
        ):
            self.rows.append(CanonicalOpportunity(title=title,
                external_id='darpa-' + number.lower().replace('-', ''),
                opportunity_number=number, agency='Defense Advanced Research Projects Agency (DARPA)',
                url=f'https://sam.gov/workspace/contract/opp/{notice}/view',
                description='Official research solicitation inviting proposals.',
                posted_date='2026-10-14', close_date=closed).to_record(
                    slug=repair.DARPA_SLUG, source='DARPA / IARPA research solicitations', source_type='Federal'))
        f.sam = self.rows[0]
        f.result.slug = repair.DARPA_SLUG
        f.result.display_name = 'DARPA / IARPA research solicitations'
        f.result.records = self.rows
        f.result.record_count = len(self.rows)
        f.result.min_records, f.result.max_records = 0, 200
        f.result.retain_on_failure = False
        f.result.diagnostics = {'partitions': [
            {'id_prefix': repair.DARPA_SLUG + ':' + sponsor + '-', 'healthy': True, 'status': 'refreshed'}
            for sponsor in ('darpa', 'iarpa')]}
        context = c.read_json(self.state / 'reconciliation.json')
        context['source_slug'] = repair.DARPA_SLUG
        c.write_json(self.state / 'reconciliation.json', context)
        f.cache['sources'][repair.DARPA_SLUG] = {'records': []}
        self.write_parent('data/source_records.json', f.cache)
        # An old, unrelated DARPA decision must remain intact, as in the real
        # retained parent; it must not block recovery of these distinct calls.
        self.write_parent('config/opportunity_team_model.json', {
            'opportunities': [{'id': 'darpa-iarpa:darpa-darpapa250704', 'teams': [{'id': 'retained'}]}]})
        self.write_parent('data/document_evidence.json', {
            'generated_at': '2026-10-17T13:49:40Z', 'records': {'nsf-test:external-1': {'status': 'failed'}},
            'subtopic_only': {'nsf-test:external-1': {'subtopics': []}}})
        selected = patch.dict(os.environ, {'CATALOG_RECONCILE_SOURCE': repair.DARPA_SLUG})
        selected.start(); self.addCleanup(selected.stop)

    def write_parent(self, name, value):
        target = self.parent / 'files' / name
        c.write_json(target, value)
        self.fixture.manifest['generation_files'][name] = c.digest(target.read_bytes())
        c.write_json(self.parent / 'candidate.json', self.fixture.manifest)

    def run_sources(self):
        return self.fixture.run_sources(now=datetime(2026, 10, 29, tzinfo=timezone.utc))

    def receipt(self):
        value = self.fixture.receipt()
        value.update(source_slug=repair.DARPA_SLUG,
                     active_source_ids=sorted(row['opportunity_id'] for row in self.rows))
        value.pop('active_sam_ids')
        return value

    def verify(self, value=None):
        with patch.object(repair, 'operation_contract', return_value={}), \
                patch.object(repair, 'verify_source_delta'):
            return repair.verify_inputs(self.root, self.fixture.manifest, self.parent, value or self.receipt())

    def test_two_calls_recover_once_with_exact_other_records_documents_and_team_decisions(self):
        self.assertEqual(self.run_sources(), 1)
        catalog = load_catalog(self.root / 'data/opportunities.js')
        self.assertEqual([r for r in catalog['opportunities'] if not repair.source_record(r, repair.DARPA_SLUG)],
                         [self.fixture.other])
        self.assertEqual({r['opportunity_id'] for r in catalog['opportunities'] if repair.source_record(r, repair.DARPA_SLUG)},
                         {r['opportunity_id'] for r in self.rows})
        for name in ('data/document_evidence.json', 'config/opportunity_team_model.json'):
            self.assertEqual((self.root / name).read_bytes(), (self.parent / 'files' / name).read_bytes())
        self.verify()
        before = c.file_hashes(self.root, ['data/opportunities.js', 'data/source_records.json', 'data/document_evidence.json'])
        self.assertEqual(self.run_sources(), 0)
        self.assertEqual(c.file_hashes(self.root, before), before)
        self.assertEqual(catalog['generated_at'], self.fixture.catalog['generated_at'])
        self.assertEqual(c.read_json(self.root / 'data/source_records.json')['sources']['sam-gov'],
                         self.fixture.cache['sources']['sam-gov'])

    def test_partial_inventory_is_not_a_successful_repair(self):
        self.fixture.result.diagnostics['partitions'][0].update(healthy=False, status='failed')
        with self.assertRaisesRegex(ValueError, 'darpa_partitions_incomplete'):
            self.run_sources()
        self.assertFalse((self.state / ('source-' + 'c' * 64) / 'summary.json').exists())

    def test_authenticated_published_identity_preserves_first_seen_without_old_content_or_freshness(self):
        prior = deepcopy(self.rows)
        for record in prior:
            record.update(source_first_seen_date='2026-10-16', description='Old published scientific text',
                          source_last_seen_date='2026-10-16', close_date='2026-11-01')
        self.fixture.run_sources(prior, now=datetime(2026, 10, 29, tzinfo=timezone.utc))
        catalog = load_catalog(self.root / 'data/opportunities.js')
        target = [row for row in catalog['opportunities'] if repair.source_record(row, repair.DARPA_SLUG)]
        cached = c.read_json(self.root / 'data/source_records.json')['sources'][repair.DARPA_SLUG]
        for rows in (target, cached['records']):
            self.assertEqual({row['source_first_seen_date'] for row in rows}, {'2026-10-16'})
            self.assertTrue(all(row['description'] != 'Old published scientific text' for row in rows))
            self.assertTrue(all(row.get('source_last_seen_date') != '2026-10-16' for row in rows))
            self.assertEqual({row['close_date'] for row in rows}, {'2026-12-14', '2026-12-30'})
        self.assertNotEqual(cached['fetched_at'][:10], '2026-10-16')
        before = (self.root / 'data/opportunities.js').read_bytes()
        self.assertEqual(self.run_sources(), 0)
        self.assertEqual((self.root / 'data/opportunities.js').read_bytes(), before)

    def test_first_seen_cannot_cross_changed_sponsor_or_solicitation_identity(self):
        for changed in ({'agency': 'National Science Foundation'}, {'opportunity_number': 'DARPA-PA-25-07-99'}):
            with self.subTest(changed=changed):
                current = deepcopy(self.rows[0]) | {'source_first_seen_date': '2026-10-29'}
                previous = deepcopy(current) | changed | {'source_first_seen_date': '2026-10-16'}
                cache = {'sources': {repair.DARPA_SLUG: {'records': [deepcopy(current)]}}}
                repair.preserve_darpa_first_seen([current], cache, [previous])
                self.assertEqual(current['source_first_seen_date'], '2026-10-29')
                self.assertEqual(cache['sources'][repair.DARPA_SLUG]['records'][0]['source_first_seen_date'], '2026-10-29')

    def test_cross_source_duplicate_cannot_silently_drop_new_call_or_change_owner(self):
        owner = deepcopy(self.rows[0])
        owner.update(opportunity_id='sam-gov:' + 'd' * 32, source='SAM.gov')
        with self.assertRaisesRegex(ValueError, 'darpa_cross_source_identity|darpa_active_records'):
            repair.merge_darpa_projection([owner], [self.rows[0]], [])

    def test_existing_paid_decision_for_changed_call_blocks_without_regeneration(self):
        self.write_parent('config/opportunity_team_model.json', {
            'opportunities': [{'id': self.rows[0]['opportunity_id'], 'teams': [{'id': 'accepted'}]}]})
        with self.assertRaisesRegex(ValueError, 'changed_source_scope_has_existing_team_decision'):
            self.run_sources()

    def test_receipt_selector_is_independent_of_ambient_workflow_default(self):
        self.run_sources()
        with patch.dict(os.environ, {'CATALOG_RECONCILE_SOURCE': 'sam-gov'}):
            self.verify()
        with self.assertRaisesRegex(ValueError, 'unsupported_source'):
            self.verify(self.receipt() | {'source_slug': 'nsf-funding'})

    def test_receipt_rejects_unrelated_source_or_any_document_cache_mutation(self):
        self.run_sources()
        original = (self.root / 'data/document_evidence.json').read_bytes()
        (self.root / 'data/document_evidence.json').write_bytes(original + b'\n')
        with self.assertRaisesRegex(ValueError, 'derived_darpa_document_cache'):
            self.verify()
        (self.root / 'data/document_evidence.json').write_bytes(original)
        catalog = load_catalog(self.root / 'data/opportunities.js')
        catalog['opportunities'][0]['title'] = 'Unrelated mutation'
        save_catalog(catalog, self.root / 'data/opportunities.js')
        with self.assertRaisesRegex(ValueError, 'derived_non_target_records'):
            self.verify()

    def test_receipt_rejects_duplicate_active_cache_rows(self):
        self.run_sources()
        cache = c.read_json(self.root / 'data/source_records.json')
        cache['sources'][repair.DARPA_SLUG]['records'].append(
            deepcopy(cache['sources'][repair.DARPA_SLUG]['records'][0]))
        c.write_json(self.root / 'data/source_records.json', cache)
        with self.assertRaisesRegex(ValueError, 'active_darpa_identity_cache'):
            self.verify()

    def test_darpa_dependency_allowance_does_not_authorize_sam_or_document_changes(self):
        original = {'generation_dependencies': {'contract': {}, 'files': {}}}
        for name, accepted in ((next(iter(repair.DARPA_INPUTS)), True),
                               ('config/sam_gov.json', False), ('scripts/sources/merge.py', False),
                               ('scripts/extract_document_evidence.py', False)):
            with self.subTest(name=name), patch.object(c, 'generation_dependencies',
                    return_value={'contract': {}, 'files': {name: 'new'}}):
                if accepted:
                    repair.verify_source_delta(self.root, original, repair.DARPA_SLUG)
                else:
                    with self.assertRaisesRegex(ValueError, 'unrelated_generation_input'):
                        repair.verify_source_delta(self.root, original, repair.DARPA_SLUG)

    def test_source_switch_cannot_restore_an_older_allowance(self):
        with self.fixture.completed_restore() as fixture:
            with self.assertRaisesRegex(ValueError, 'repair_checkpoint_source_mismatch'):
                repair.restore(self.root, self.parent, self.state, fixture['output'])
            self.assertEqual(c.read_json(self.state / 'ledger.json'), fixture['ledger'])
            fixture['imported'].assert_not_called()
            self.assertFalse(fixture['output'].exists())

    def test_completed_darpa_child_reuses_exact_bytes_and_original_ledger(self):
        with self.fixture.completed_restore() as fixture:
            fixture['context']['source_slug'] = repair.DARPA_SLUG
            fixture['child']['source_reconciliation']['source_slug'] = repair.DARPA_SLUG
            fixture['context']['operation_sha256'] = repair.identity({k: v for k, v in fixture['context'].items()
                if k not in ('operation_sha256', 'completed_candidate_id')})
            self.assertTrue(repair.restore(self.root, self.parent, self.state, fixture['output']))
            self.assertEqual(c.read_json(self.state / 'ledger.json'), fixture['ledger'])
            self.assertEqual(c.read_json(fixture['output'] / 'candidate.json'), fixture['child'])
            fixture['imported'].assert_not_called()

    def test_child_receipt_keeps_source_parent_budget_and_zero_document_team_work(self):
        self.run_sources()
        context = c.read_json(self.state / 'reconciliation.json')
        context.update(version=repair.VERSION, parent_candidate_id=self.fixture.manifest['candidate_id'],
                       operation_contract={})
        c.write_json(self.state / 'reconciliation.json', context)
        ledger = {'logical_id': 'offline-10', 'limit_microusd': 2_000_000, 'max_requests': 300,
                  'requests': [{'id': 'original-completed-request', 'charged_microusd': 179337}]}
        c.write_json(self.state / 'ledger.json', ledger)
        c.write_json(self.state / 'consumed-checkpoints.json', [])
        child = {'candidate_id': 'd' * 64}
        output, receipt = self.root / 'child', self.state / 'receipt.json'

        def create(_root, destination, **_):
            c.write_json(destination / 'candidate.json', child)
            return child

        with patch.object(c, 'load', side_effect=lambda path, *_:
                self.fixture.manifest if path == self.parent else child), \
                patch.object(c, 'create', side_effect=create), \
                patch.object(repair, 'operation_contract', return_value={}), \
                patch.dict(os.environ, {'GITHUB_RUN_ID': '20', 'GITHUB_OUTPUT': ''}):
            repair.finish(self.root, self.parent, self.state, output, receipt)
        value = c.read_json(receipt)
        self.assertEqual(value['source_slug'], repair.DARPA_SLUG)
        self.assertEqual(value['parent_candidate_id'], self.fixture.manifest['candidate_id'])
        self.assertEqual(value['active_source_ids'], sorted(row['opportunity_id'] for row in self.rows))
        self.assertNotIn('active_sam_ids', value)
        self.assertEqual((value['new_document_requests'], value['new_team_requests']), (0, 0))
        self.assertEqual(value['ledger_sha256'], repair.identity(ledger))
        self.assertEqual(c.read_json(self.state / 'ledger.json'), ledger)
        self.assertEqual(value['published_predecessor'], self.fixture.published_metadata)

    def test_selection_defaults_to_legacy_sam_and_rejects_arbitrary_adapters(self):
        self.assertEqual(repair.requested_source({}), 'sam-gov')
        self.assertEqual(repair.source_slug({}), 'sam-gov')
        self.assertEqual(repair.requested_source({'CATALOG_RECONCILE_SOURCE': repair.DARPA_SLUG}), repair.DARPA_SLUG)
        with self.assertRaisesRegex(ValueError, 'unsupported_source'):
            repair.requested_source({'CATALOG_RECONCILE_SOURCE': 'nsf-funding'})


if __name__ == '__main__':
    unittest.main()
