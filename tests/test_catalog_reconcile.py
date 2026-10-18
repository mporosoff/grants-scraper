"""Exact-parent reconciliation boundaries; no source/provider requests."""
from copy import deepcopy
from contextlib import contextmanager, ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.sources.base import CanonicalOpportunity
from scripts.sources.merge import save_catalog, load_catalog
from scripts.sources.registry import AdapterResult
from tools import catalog_reconcile as repair
from tools import release_candidate as c


class ReconcileContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'; self.parent = Path(self.temp.name) / 'parent'
        self.state = Path(self.temp.name) / 'state'; self.state.mkdir()
        self.root.mkdir(); (self.parent / 'files/data').mkdir(parents=True)
        (self.parent / 'files/config').mkdir()
        self.other = CanonicalOpportunity(title='Independent research', external_id='external-1',
            url='https://www.nsf.gov/funding/opportunities/example', agency='National Science Foundation',
            description='Independent public research.', close_date='2027-12-01').to_record(
                slug='nsf-test', source='NSF', source_type='Federal')
        self.sam = CanonicalOpportunity(title='Reviewed replacement research', external_id='a' * 32,
            url='https://sam.gov/opp/' + 'a' * 32 + '/view', agency='DARPA',
            description='Public reviewed research.', close_date='2027-12-01').to_record(
                slug='sam-gov', source='SAM.gov', source_type='Federal')
        self.catalog = {'generated_at': '2026-10-17T13:49:40Z', 'opportunities': [self.other],
            'diagnostics': {'additional_sources': {'adapters': [{'slug': 'nsf-test', 'ok': True}],
                                                  'lifecycle': [{'slug': 'nsf-test', 'status': 'retained'}]}}}
        save_catalog(self.catalog, self.parent / 'files/data/opportunities.js')
        self.cache = {'schema_version': 1, 'sources': {'nsf-test': {'records': [self.other]},
            'sam-gov': {'records': []}}}
        (self.parent / 'files/data/source_records.json').write_text(json.dumps(self.cache))
        (self.parent / 'files/config/opportunity_team_model.json').write_text('{"opportunities":[]}')
        (self.parent / 'files/data/document_evidence.json').write_text('{"records":{}}')
        names = ['data/opportunities.js', 'data/source_records.json',
                 'config/opportunity_team_model.json', 'data/document_evidence.json']
        self.manifest = {'candidate_id': 'b' * 64,
                         'generation_files': c.file_hashes(self.parent / 'files', names)}
        (self.parent / 'candidate.json').write_text(json.dumps(self.manifest))
        (self.state / 'reconciliation.json').write_text(json.dumps({'operation_sha256': 'c' * 64}))
        self.result = AdapterResult(slug='sam-gov', display_name='SAM.gov', source_type='Federal',
            ok=True, record_count=1, records=[self.sam], diagnostics={})

    def run_sources(self):
        with patch.object(c, 'load', return_value=self.manifest), \
                patch.object(repair, 'verify_source_delta'), \
                patch('scripts.sources.registry.collect', return_value=([self.sam], [self.result])) as collect, \
                patch('tools.require_sam_refresh.require_complete_refresh'):
            repair.reconcile(self.root, self.parent, self.state)
            return collect.call_count

    def receipt(self):
        retained = {n: h for n, h in self.manifest['generation_files'].items()
                    if n not in repair.DERIVED_FILES}
        return {'version': repair.VERSION, 'source_slug': 'sam-gov',
            'parent_candidate_id': self.manifest['candidate_id'],
            'parent_manifest_sha256': c.digest((self.parent / 'candidate.json').read_bytes()),
            'operation_contract': {}, 'retained_output_hashes': retained}

    def test_only_sam_is_replaced_and_successful_source_checkpoint_never_recollects(self):
        self.assertEqual(self.run_sources(), 1)
        current = load_catalog(self.root / 'data/opportunities.js')
        self.assertEqual([r for r in current['opportunities'] if not repair.sam_record(r)], [self.other])
        self.assertEqual(current['generated_at'], self.catalog['generated_at'])
        self.assertEqual(self.run_sources(), 0)
        self.assertEqual(load_catalog(self.root / 'data/opportunities.js'), current)
        cached = c.read_json(self.root / 'data/source_records.json')
        self.assertEqual(cached['sources']['nsf-test'], self.cache['sources']['nsf-test'])

    def test_derived_verifier_rejects_non_sam_changes_and_changed_paid_outputs(self):
        self.run_sources()
        with patch.object(repair, 'operation_contract', return_value={}), patch.object(repair, 'verify_source_delta'):
            retained = repair.verify_inputs(self.root, self.manifest, self.parent, self.receipt())
            self.assertIn('config/opportunity_team_model.json', retained)
            changed = load_catalog(self.root / 'data/opportunities.js')
            changed['opportunities'][0]['title'] = 'Unrelated mutation'
            save_catalog(changed, self.root / 'data/opportunities.js')
            with self.assertRaisesRegex(ValueError, 'derived_non_sam_records'):
                repair.verify_inputs(self.root, self.manifest, self.parent, self.receipt())
            self.run_sources()
            (self.root / 'data/document_evidence.json').write_text('{"records":{"nsf-test:external-1":{"altered":true}}}')
            with self.assertRaisesRegex(ValueError, 'derived_non_sam_document_cache'):
                repair.verify_inputs(self.root, self.manifest, self.parent, self.receipt())

    def test_new_unrelated_generation_inputs_are_not_covered_by_source_exception(self):
        original = {'generation_dependencies': {'contract': {}, 'files': {'scripts/existing.py': 'a'}}}
        current = {'contract': {}, 'files': {'scripts/existing.py': 'a', 'scripts/unrelated.py': 'b'}}
        with patch.object(c, 'generation_dependencies', return_value=current):
            with self.assertRaisesRegex(ValueError, 'unrelated_generation_input_scripts/unrelated.py'):
                repair.verify_source_delta(self.root, original)
        current['files'].pop('scripts/unrelated.py')
        current['files']['scripts/sources/sam_preflight.py'] = 'c'
        with patch.object(c, 'generation_dependencies', return_value=current):
            repair.verify_source_delta(self.root, original)

    def test_manual_plan_requires_the_exact_protected_parent_and_no_paid_modes(self):
        env = {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_REPOSITORY': 'mporosoff/grants-scraper',
            'GITHUB_WORKFLOW_REF': 'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main',
            'CANDIDATE_RUN': '123', 'CANDIDATE_ID': 'a' * 64}
        with patch.object(c, 'git', return_value='b' * 40):
            result = repair.plan(self.root, env)
            self.assertEqual((result['stage'], result['candidate_run']), ('catalog-reconcile', '123'))
            self.assertEqual((result['openai'], result['anthropic']), ('false', 'false'))
            for delta in [{'GITHUB_EVENT_NAME': 'schedule'}, {'CANDIDATE_ID': ''}, {'QUALIFICATION_PILOT': 'true'}]:
                with self.subTest(delta=delta), self.assertRaises(ValueError):
                    repair.plan(self.root, env | delta)

    def test_constructor_records_affected_producer_without_relabelling_original_generation(self):
        from tests.test_release_candidate import CandidateLifecycleTests
        fixture = CandidateLifecycleTests(methodName='runTest')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        original = fixture.create()
        (fixture.root / 'scripts/parser.py').write_text('VERSION = 2\n')
        c.git(fixture.root, 'add', 'scripts/parser.py')
        c.git(fixture.root, 'commit', '-m', 'Accepted isolated source repair')
        current = c.git(fixture.root, 'rev-parse', 'HEAD')
        receipt = self.state / 'receipt.json'
        receipt.write_text(json.dumps({'version': repair.VERSION, 'parent_candidate_id': original['candidate_id']}))
        with patch.object(repair, 'verify_inputs', return_value=original['generation_files']):
            child = c.create(fixture.root, Path(fixture.temp.name) / 'source-child', parent=fixture.bundle,
                             run_id='456', attempt='2', source_reconciliation=receipt)
        self.assertEqual(child['derived_from_candidate'], original['candidate_id'])
        for key in ('generation_sha', 'generation_run_id', 'generation_run_attempt', 'generation_timestamp'):
            self.assertEqual(child[key], original[key])
        affected = child['source_reconciliation']['affected_generation']
        self.assertEqual((affected['generation_sha'], affected['generation_run_id'], affected['generation_run_attempt']),
                         (current, '456', '2'))
        self.assertEqual(child['team_identity'], original['team_identity'])

    @contextmanager
    def completed_restore(self, *, changed_source=False, current_run='30', incompatible=False):
        """Authenticated transport fixtures; no GitHub/provider operations."""
        self.manifest.update(generation_run_id='10', generation_run_attempt='1', generation_sha='1' * 40)
        (self.parent / 'candidate.json').write_text(json.dumps(self.manifest))
        old = {'config/sam_gov.json': 'a', '.github/workflows/refresh-opportunities.yml': 'old-validator'}
        current = old | {'.github/workflows/refresh-opportunities.yml': 'new-validator'}
        if changed_source:
            current['config/sam_gov.json'] = 'b'
        context = {'version': repair.VERSION, 'parent_candidate_id': self.manifest['candidate_id'],
            'parent_manifest_sha256': c.digest((self.parent / 'candidate.json').read_bytes()),
            'parent_run': '10', 'operation_contract': old, 'original_spend': {'ledger_sha256': 'e' * 64}}
        context['operation_sha256'] = repair.identity(context)
        context['completed_candidate_id'] = 'd' * 64
        child = {'candidate_id': 'd' * 64, 'derived_from_candidate': self.manifest['candidate_id'],
                 'source_reconciliation': {'version': repair.VERSION}}
        row = {'id': 'r1', 'provider': 'voyage', 'model': 'voyage-4-lite', 'stage': 'vectors',
            'key': 'key', 'attempt': 1, 'reserved_microusd': 20, 'charged_microusd': 10, 'status': 'completed'}
        ledger = {'logical_id': 'offline-10', 'limit_microusd': 2_000_000, 'max_requests': 300, 'requests': [row]}
        raw = b'authenticated-private-state'
        common = {'expired': False, 'workflow_run': {'id': 20}}
        reservation = common | {'id': 101, 'name': repair.prefix(self.manifest['candidate_id']) + '-reservation-20-1',
                                'digest': 'sha256:' + 'a' * 64}
        state = common | {'id': 102, 'name': reservation['name'].replace('-reservation-', '-state-'),
                          'digest': 'sha256:' + c.digest(raw)}
        artifact = {'id': 103, 'name': 'candidate-' + child['candidate_id'], 'expired': False,
                    'digest': 'sha256:' + 'b' * 64}
        parent_artifact = {'id': 100, 'name': 'candidate-' + self.manifest['candidate_id'],
                           'expired': False, 'digest': 'sha256:' + 'c' * 64}
        def metadata(_repository, path):
            run = 10 if '/10/' in path else 20
            return json.dumps({'id': run, 'run_attempt': 1, 'head_sha': '1' * 40,
                'head_branch': 'main', 'path': repair.archive.SOURCE_WORKFLOW,
                'event': 'workflow_dispatch'}).encode()
        def unpack(_raw, destination):
            repair.atomic_json(destination / 'reconciliation.json', context)
            repair.atomic_json(destination / 'ledger.json', ledger)
            repair.atomic_json(destination / 'consumed-checkpoints.json', [])
            repair.atomic_json(destination / 'complete-candidates' / child['candidate_id'] / 'candidate.json', child)
        def fetch(_repo, _run, _name, destination):
            repair.atomic_json(destination / 'candidate.json', child)
        with ExitStack() as stack:
            stack.enter_context(patch.dict('os.environ', {'GITHUB_REPOSITORY': 'mporosoff/grants-scraper',
                'CANDIDATE_ID': self.manifest['candidate_id'], 'CANDIDATE_RUN': '10',
                'GITHUB_RUN_ID': current_run, 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_OUTPUT': ''}))
            stack.enter_context(patch.object(c, 'load', side_effect=lambda path, *_:
                                             self.manifest if Path(path) == self.parent else child))
            stack.enter_context(patch.object(repair, 'api', side_effect=metadata))
            stack.enter_context(patch.object(repair, 'run_artifacts', side_effect=lambda run, *_a, **_k:
                                             [parent_artifact] if str(run) == '10' else [artifact]))
            stack.enter_context(patch.object(repair, 'repository_artifacts', return_value=[reservation, state]))
            stack.enter_context(patch.object(repair, 'artifact_bytes', return_value=raw))
            stack.enter_context(patch.object(repair, 'unpack', side_effect=unpack))
            stack.enter_context(patch.object(repair, 'fetch', side_effect=fetch))
            stack.enter_context(patch.object(repair, 'operation_contract', return_value=current))
            stack.enter_context(patch.object(repair, 'verify_source_delta'))
            stack.enter_context(patch.object(c, 'verify_dependencies',
                                             side_effect=ValueError('changed source') if incompatible else None))
            imported = stack.enter_context(patch('tools.catalog_reconcile_spend.import_history'))
            yield {'context': context, 'ledger': ledger, 'child': child, 'imported': imported,
                   'output': self.root / 'restored-candidate', 'current': current}

    def test_completed_checkpoint_reuses_exact_child_after_validator_only_change(self):
        with self.completed_restore() as fixture:
            self.assertTrue(repair.restore(self.root, self.parent, self.state, fixture['output']))
            fixture['imported'].assert_not_called()
            self.assertEqual(c.read_json(fixture['output'] / 'candidate.json'), fixture['child'])
            self.assertEqual(c.read_json(self.state / 'reconciliation.json'), fixture['context'])
            consumed = c.read_json(self.state / 'consumed-checkpoints.json')[0]
            self.assertEqual(consumed['candidate']['candidate_id'], fixture['child']['candidate_id'])
            self.assertEqual(consumed['candidate']['artifact']['id'], 103)
            self.assertEqual(consumed['producer']['run_id'], '20')
            self.assertEqual(consumed['request_identity_prefix_sha256'], repair.request_identity(fixture['ledger']['requests']))

    def test_source_repair_requires_new_dispatch_and_retains_exact_consumed_child_and_budget(self):
        with self.completed_restore(changed_source=True, incompatible=True) as fixture:
            self.assertFalse(repair.restore(self.root, self.parent, self.state, fixture['output']))
            updated = c.read_json(self.state / 'reconciliation.json')
            self.assertNotIn('completed_candidate_id', updated)
            self.assertEqual(updated['operation_contract'], fixture['current'])
            self.assertNotEqual(updated['operation_sha256'], fixture['context']['operation_sha256'])
            self.assertEqual(c.read_json(self.state / 'ledger.json'), fixture['ledger'])
            fixture['imported'].assert_called_once()
            consumed = c.read_json(self.state / 'consumed-checkpoints.json')[0]
            self.assertEqual(consumed['candidate']['manifest_sha256'],
                             c.digest((self.state / 'authenticated-children' / fixture['child']['candidate_id'] /
                                       'candidate.json').read_bytes()))
            self.assertEqual((consumed['reservation']['id'], consumed['state']['id']), (101, 102))

    def test_same_producer_cannot_create_second_candidate_after_source_change(self):
        with self.completed_restore(changed_source=True, current_run='20', incompatible=True) as fixture:
            with self.assertRaisesRegex(ValueError, 'changed_completed_child_requires_new_dispatch'):
                repair.restore(self.root, self.parent, self.state, fixture['output'])
            self.assertEqual(c.read_json(self.state / 'ledger.json'), fixture['ledger'])
            fixture['imported'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
