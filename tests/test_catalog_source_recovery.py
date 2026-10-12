"""Offline contracts for the fixed rejected-candidate recovery and quarantine."""
from contextlib import ExitStack
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
import warnings
import zipfile

import yaml
from tools import catalog_source_recovery as recovery
from tools import release_candidate as candidate
from tools import release_dependencies as dependencies
from tools import validate_release_candidate as validation
from tools import publish_release_candidate as publication
from tools.offline_spend import ConfigurationFailure


def archive(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as writer, warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        for name, raw in entries:
            writer.writestr(name, raw)
    return output.getvalue()


def groups():
    return {name: {'files': {}, 'fingerprint': candidate.digest(candidate.encoded({}))}
        for name in ('source', 'teams', 'semantic', 'runtime', 'validation')}


def changed_group(original, group, filename):
    changed = deepcopy(original)
    changed[group]['files'][filename] = 'e' * 64
    changed[group]['fingerprint'] = candidate.digest(candidate.encoded(changed[group]['files']))
    return changed


class AuthenticationFixture:
    """Real ZIP/digest/manifest authentication with synthetic immutable pins."""
    def __init__(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='source-recovery-contract-')))
        self.bundle = self.root/'parent'
        self.payloads = {
            'data/opportunities.js': b'original public catalog',
            'config/opportunity_team_model.json': b'original team evidence',
            'data/search-v2-voyage-canaries.json': b'original canaries',
            'evaluation/search_v2_hybrid_vector_build.json': candidate.encoded({
                'API_request_count': 6, 'usage_total_tokens': 298906,
                'estimated_cost_at_published_paid_pricing_usd': .005978}),
        }
        hashes = {name: candidate.digest(raw) for name, raw in self.payloads.items()}
        self.manifest = {'schema_version': 1, 'candidate_format': candidate.VERSION,
            'files': hashes, 'generation_files': hashes,
            'generation_sha': recovery.GENERATION_SHA, 'generation_run_id': str(recovery.RUN),
            'generation_run_attempt': str(recovery.ATTEMPT), 'dependency_groups': groups(),
            'runtime_baseline': {}}
        self.manifest['candidate_id'] = candidate.digest(candidate.encoded(self.manifest))
        self.raw_manifest = candidate.encoded(self.manifest)
        for name, raw in self.payloads.items():
            path = self.bundle/'files'/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        (self.bundle/'candidate.json').write_bytes(self.raw_manifest)
        ledger = {'logical_id': 'offline-' + str(recovery.RUN), 'limit_microusd': 2_000_000,
            'max_requests': 300, 'requests': [{'charged_microusd': 0} for _ in range(65)] + [{'charged_microusd': 441023}]}
        self.state = {'ledger.json': candidate.encoded(ledger), 'team-progress.json': b'{"unchanged":true}\n'}
        reservation = {'attempt': '4', 'maximum_logical_spend_usd': 2, 'mode': 'maintenance',
            'prior_ledger_hash': 'eac564e5caed08887a815aaa64ae19e0e0e01c430b77ef7abde684a5bea8370e',
            'run_id': str(recovery.RUN)}
        self.entries = {'candidate': [('candidate.json', self.raw_manifest)] + [('files/' + n, b) for n, b in self.payloads.items()],
            'state': list(self.state.items()), 'reservation': [('spend-reservation.json', candidate.encoded(reservation))]}
        self.run = {'id': recovery.RUN, 'run_attempt': recovery.ATTEMPT, 'head_sha': recovery.EVENT_SHA,
            'head_branch': 'main', 'path': recovery.auth.REFRESH, 'event': 'schedule',
            'status': 'completed', 'conclusion': 'cancelled'}
        self.pins = {role: (number, 'synthetic-' + role, '') for number, role in enumerate(self.entries, 301)}
        self.refresh_archives()
        for name, value in [('PARENT', self.manifest['candidate_id']), ('MANIFEST_SHA', candidate.digest(self.raw_manifest)),
            ('LEDGER_SHA', candidate.digest(self.state['ledger.json'])), ('ARTIFACTS', self.pins)]:
            self.stack.enter_context(patch.object(recovery, name, value))
        self.stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')))
        self.api = Mock(side_effect=self.read_api)

    def refresh_archives(self):
        self.archives = {role: archive(entries) for role, entries in self.entries.items()}
        self.metadata = {}
        for role, (identifier, name, _) in list(self.pins.items()):
            sha = candidate.digest(self.archives[role]); self.pins[role] = (identifier, name, sha)
            self.metadata[role] = {'id': identifier, 'name': name, 'expired': False, 'digest': 'sha256:' + sha,
                'workflow_run': {'id': recovery.RUN, 'head_sha': recovery.EVENT_SHA}}

    def read_api(self, path):
        if path == f'actions/runs/{recovery.RUN}/attempts/{recovery.ATTEMPT}':
            return candidate.encoded(self.run)
        for role, (identifier, _, _) in self.pins.items():
            if path == f'actions/artifacts/{identifier}': return candidate.encoded(self.metadata[role])
            if path == f'actions/artifacts/{identifier}/zip': return self.archives[role]
        raise AssertionError('Unexpected authentication route: ' + path)

    def authenticate(self):
        return recovery.authenticate(self.bundle, api=self.api)

    def close(self):
        self.stack.close()


class AuthenticationContracts(unittest.TestCase):
    def setUp(self):
        self.fixture = AuthenticationFixture(); self.addCleanup(self.fixture.close)

    def test_exact_archives_authenticate_without_rewriting_spend_or_original_payloads(self):
        fixture = self.fixture
        archived = deepcopy(fixture.archives)
        manifest, spending = fixture.authenticate()
        self.assertEqual(manifest, fixture.manifest)
        self.assertEqual(spending['requests_used'], 66)
        self.assertEqual(spending['charged_microusd'], 441023)
        self.assertEqual(spending['prior_vector_requests'], 6)
        self.assertEqual(spending['prior_vector_tokens'], 298906)
        self.assertEqual([spending[name] for name in ('new_document_ai_requests', 'new_vector_requests', 'new_team_requests')], [0, 0, 0])
        self.assertEqual(spending['state_hashes'], {n: candidate.digest(raw) for n, raw in fixture.state.items()})
        self.assertEqual(fixture.archives, archived)
        self.assertEqual((fixture.bundle/'candidate.json').read_bytes(), fixture.raw_manifest)
        self.assertEqual(fixture.api.call_count, 7)

    def test_run_attempt_branch_event_sha_and_terminal_state_are_bound(self):
        fixture = self.fixture
        for key, invalid in [('run_attempt', 3), ('head_sha', '0' * 40), ('head_branch', 'feature'),
            ('event', 'workflow_dispatch'), ('status', 'in_progress'), ('conclusion', 'success')]:
            with self.subTest(key=key):
                before = fixture.run[key]; fixture.run[key] = invalid
                with self.assertRaisesRegex(ValueError, 'original_run'): fixture.authenticate()
                fixture.run[key] = before

    def test_artifact_owner_digest_and_expiry_cannot_be_substituted(self):
        fixture = self.fixture
        for mutate in [lambda meta: meta.update(expired=True), lambda meta: meta.update(digest='sha256:' + '0' * 64),
            lambda meta: meta['workflow_run'].update(id=recovery.RUN + 1),
            lambda meta: meta['workflow_run'].update(head_sha='0' * 40)]:
            with self.subTest(mutation=mutate):
                before = deepcopy(fixture.metadata['state']); mutate(fixture.metadata['state'])
                with self.assertRaisesRegex(ConfigurationFailure, 'artifact_metadata'): fixture.authenticate()
                fixture.metadata['state'] = before
        fixture.archives['state'] += b'changed'
        with self.assertRaisesRegex(ConfigurationFailure, 'raw_artifact_digest'): fixture.authenticate()

    def test_local_parent_tamper_and_extra_authenticated_archive_payload_fail(self):
        fixture = self.fixture
        path = fixture.bundle/'files/config/opportunity_team_model.json'; original = path.read_bytes()
        path.write_bytes(b'altered team')
        with self.assertRaisesRegex(ValueError, 'Candidate bytes differ'): fixture.authenticate()
        path.write_bytes(original)
        fixture.entries['candidate'].append(('files/extra.json', b'{}'))
        fixture.refresh_archives()
        with self.assertRaisesRegex(ValueError, 'complete_parent'): fixture.authenticate()

    def test_ledger_and_reservation_are_independently_pinned_after_archive_authentication(self):
        fixture = self.fixture
        fixture.entries['state'][0] = ('ledger.json', fixture.state['ledger.json'] + b' ')
        fixture.refresh_archives()
        with self.assertRaisesRegex(ValueError, 'original_ledger'): fixture.authenticate()
        fixture.entries['state'] = list(fixture.state.items())
        reservation = json.loads(fixture.entries['reservation'][0][1]); reservation['maximum_logical_spend_usd'] = 3
        fixture.entries['reservation'] = [('spend-reservation.json', candidate.encoded(reservation))]
        fixture.refresh_archives()
        with self.assertRaisesRegex(ValueError, 'original_reservation'): fixture.authenticate()


class SelectorAndLifecycleContracts(unittest.TestCase):
    def environment(self):
        return {'GITHUB_REPOSITORY': 'mporosoff/grants-scraper', 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_WORKFLOW_REF': 'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main',
            'CANDIDATE_ID': recovery.PARENT, 'CANDIDATE_RUN': str(recovery.RUN), 'REQUESTED_STAGE': recovery.STAGE}

    def test_only_exact_protected_manual_selector_can_enter_provider_free_stage(self):
        with patch.object(candidate, 'git', return_value='c' * 40):
            result = recovery.plan(Path('.'), self.environment())
            self.assertEqual((result['stage'], result['openai'], result['anthropic'], result['team_mode']),
                (recovery.STAGE, 'false', 'false', 'maintenance'))
            for key in self.environment():
                if key == 'REQUESTED_STAGE': continue
                for invalid in ('', 'other'):
                    with self.subTest(key=key, invalid=invalid):
                        env = self.environment(); env[key] = invalid
                        with self.assertRaisesRegex(ValueError, 'exact_protected_manual_selector'): recovery.plan(Path('.'), env)
            for key in ('RECEIPT_RUN', 'PUBLICATION_RUN', 'PUBLICATION_ATTEMPT', 'QUALIFICATION_PILOT'):
                with self.subTest(key=key):
                    env = self.environment(); env[key] = 'true' if key == 'QUALIFICATION_PILOT' else '17'
                    with self.assertRaisesRegex(ValueError, 'no_other_generation_or_recovery'): recovery.plan(Path('.'), env)

    def test_workflow_stage_has_no_provider_secret_or_generation_allowance(self):
        workflow = yaml.safe_load((candidate.ROOT/'.github/workflows/refresh-opportunities.yml').read_text(encoding='utf8'))
        job = workflow['jobs'][recovery.STAGE]
        self.assertEqual(job['needs'], 'plan')
        self.assertEqual(job['if'], "needs.plan.outputs.stage == 'catalog-source-recovery'")
        environments = [workflow.get('env', {}), job.get('env', {})] + [s.get('env', {}) for s in job['steps']]
        text = json.dumps(environments) + json.dumps(job['steps'])
        self.assertNotRegex(text, r'(?i)OPENAI_API_KEY|ANTHROPIC_API_KEY|VOYAGE_API_KEY|secrets\.|max(?:imum)?_.*spend|run_budgeted_documents|build_search_v2_voyage_vectors|build_opportunity_teams|offline_ai\.reserve')
        self.assertIn('python -m tools.catalog_source_recovery', text)
        candidate_job = workflow['jobs']['candidate']
        self.assertIn(recovery.STAGE, candidate_job['needs'])
        self.assertIn("needs.catalog-source-recovery.result == 'success'", candidate_job['if'])

    def test_planner_dispatch_uses_the_exact_recovery_selector_without_ordinary_generation(self):
        from tools import catalog_correction_release as router
        with patch.dict(os.environ, self.environment() | {'RUNNER_TEMP': 'unused-plan-fixture'}, clear=True), \
            patch.object(candidate, 'git', return_value='d' * 40), patch.object(router, 'atomic_json') as save, \
            patch.object(router, 'output') as output, patch('tools.plan_release.main', side_effect=AssertionError('No ordinary generation')):
            router.plan()
        self.assertEqual(output.call_args.args[0]['stage'], recovery.STAGE)
        self.assertEqual(output.call_args.args[0]['candidate_id'], recovery.PARENT)
        self.assertEqual(save.call_args.args[1], output.call_args.args[0])

    def test_quarantined_parent_is_rejected_before_validation_materialization_and_publication(self):
        manifest = {'candidate_id': recovery.PARENT}
        with patch.object(candidate, 'load', return_value=manifest), \
            patch.object(candidate, 'read_json', return_value={}), \
            patch.object(candidate, 'write_json', side_effect=AssertionError('No success receipt')) as write, \
            patch.object(publication, 'run', side_effect=AssertionError('No remote/Git mutation')) as publish, \
            patch.object(candidate, 'git', side_effect=AssertionError('No dependency bypass')):
            for operation in [lambda: candidate.verify_dependencies(Path('.'), manifest),
                lambda: candidate.materialize(Path('.'), Path('bundle')),
                lambda: validation.validate(Path('.'), Path('bundle'), Path('reports')),
                lambda: publication.prepare(Path('bundle'), Path('receipt'), Path('reports'), '123')]:
                with self.assertRaisesRegex(ValueError, 'rejected_candidate_requires_exact_source_recovery'): operation()
            write.assert_not_called(); publish.assert_not_called()

    def test_dependency_scope_rejects_unrelated_source_team_semantic_and_runtime_changes(self):
        with tempfile.TemporaryDirectory(prefix='source-scope-') as temporary:
            root = Path(temporary); (root/'index.html').write_bytes(b'original runtime')
            original = {'dependency_groups': groups(), 'runtime_baseline': {'index.html': candidate.digest(b'original runtime')}}
            allowed = changed_group(original['dependency_groups'], 'source', 'scripts/sources/merge.py')
            with patch.object(dependencies, 'snapshot', return_value=allowed), patch.object(candidate, 'git', return_value=''):
                recovery.dependency_scope(root, original)
            for group, path in [('source', 'scripts/subtopic_segmentation.py'), ('source', '@document_spend_config'),
                ('teams', 'config/offline_ai.json'), ('semantic', 'assets/search-hybrid.js')]:
                with self.subTest(group=group), patch.object(dependencies, 'snapshot', return_value=changed_group(original['dependency_groups'], group, path)):
                    with self.assertRaisesRegex(ValueError, 'bounded_dependency_changes'): recovery.dependency_scope(root, original)
            (root/'index.html').write_bytes(b'changed runtime')
            with patch.object(dependencies, 'snapshot', return_value=allowed), patch.object(candidate, 'git', return_value=''):
                with self.assertRaisesRegex(ValueError, 'Candidate bytes differ'): recovery.dependency_scope(root, original)

    def test_archive_decoder_rejects_duplicate_paths_escape_and_symlink(self):
        link = zipfile.ZipInfo('link'); link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for entries in [[('../escape', b'x')], [('duplicate', b'a'), ('duplicate', b'b')], [(link, b'/outside')]]:
            with self.subTest(entries=entries):
                with self.assertRaisesRegex(ConfigurationFailure, 'unsafe_public_archive'): recovery.archive_files(archive(entries))


class ProjectionIntegrationContracts(unittest.TestCase):
    def test_vector_proof_is_outside_materialized_root_and_historical_bytes_are_retained(self):
        from tools import catalog_record_withdrawal as withdrawal
        from scripts import update_catalog_docs as docs
        with tempfile.TemporaryDirectory(prefix='source-derive-') as temporary:
            bundle = Path(temporary)/'parent'; files = bundle/'files'; files.mkdir(parents=True)
            original = {'README.md': b'Readme', 'PROJECT.md': b'Project', 'match_explorer.html': b'match', 'team_match.html': b'team',
                'evaluation/search_v2_hybrid_vector_build.json': b'historical six requests',
                'data/search-v2-voyage-canaries.json': b'original canaries'}
            for name, raw in original.items():
                target = files/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
            projected = {'data/opportunities.js': b'corrected catalog'}
            proof = {'new_provider_requests': 0, 'retained_passage_count': 1463}
            def vector_command(command, **kwargs):
                root = Path(command[command.index('--root') + 1]); receipt = Path(command[command.index('--receipt') + 1])
                self.assertFalse(receipt.is_relative_to(root), 'vector proof must not become an unmanifested candidate payload')
                for name in recovery.VECTOR_OUTPUTS:
                    path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(('projected ' + name).encode())
                for name in ('evaluation/search_v2_hybrid_vector_build.json', 'data/search-v2-voyage-canaries.json'):
                    self.assertEqual((root/name).read_bytes(), original[name])
                candidate.write_json(receipt, proof)
            with patch.object(withdrawal, 'projection', return_value=(projected, {'removed': 6})), \
                patch.object(docs, 'load_catalog', return_value={}), patch.object(docs, 'catalog_stats', return_value={}), \
                patch.object(docs, 'render_docs', return_value=('New readme', 'New project')), \
                patch.object(docs, 'update_catalog_asset_reference', side_effect=lambda text, catalog: text + '-new'), \
                patch.object(recovery.subprocess, 'run', side_effect=vector_command) as command:
                outputs, result = recovery.derive(bundle, '2026-10-08T23:00:00+00:00')
            self.assertEqual(command.call_count, 1)
            self.assertEqual(result['vector_projection'], proof)
            self.assertEqual(set(outputs), set(projected) | set(recovery.VECTOR_OUTPUTS) | {'README.md', 'PROJECT.md', 'match_explorer.html', 'team_match.html'})
            self.assertNotIn('evaluation/search_v2_hybrid_vector_build.json', outputs)
            self.assertNotIn('data/search-v2-voyage-canaries.json', outputs)

    def test_constructor_replays_exact_receipt_and_checks_all_retained_payloads(self):
        fixture = AuthenticationFixture(); self.addCleanup(fixture.close)
        root = fixture.root/'corrected'; root.mkdir(); receipt_path = fixture.root/'receipt.json'
        outputs = {'data/opportunities.js': b'corrected catalog'}; spending = {'new_vector_requests': 0}
        proof = {'new_provider_requests': 0}; clock = '2026-10-08T23:00:00+00:00'
        receipt = recovery.receipt_for(fixture.manifest, spending, outputs, proof, clock)
        for name, raw in fixture.payloads.items():
            target = root/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(outputs.get(name, raw))
        candidate.write_json(receipt_path, receipt)
        with patch.object(recovery, 'authenticate', return_value=(fixture.manifest, spending)), \
            patch.object(recovery, 'derive', return_value=(outputs, proof)), \
            patch.object(dependencies, 'snapshot', return_value=fixture.manifest['dependency_groups']):
            retained = recovery.verify_inputs(root, fixture.manifest, fixture.bundle, receipt_path)
            self.assertEqual(set(retained), set(fixture.payloads) - set(outputs))
            changed = deepcopy(receipt); changed['spending']['new_vector_requests'] = 1
            candidate.write_json(receipt_path, changed)
            with self.assertRaisesRegex(ValueError, 'deterministic_replay'): recovery.verify_inputs(root, fixture.manifest, fixture.bundle, receipt_path)
            candidate.write_json(receipt_path, receipt)
            (root/'config/opportunity_team_model.json').write_bytes(b'new team data')
            with self.assertRaisesRegex(ValueError, 'Candidate bytes differ'): recovery.verify_inputs(root, fixture.manifest, fixture.bundle, receipt_path)
            (root/'config/opportunity_team_model.json').write_bytes(fixture.payloads['config/opportunity_team_model.json'])
            extra = root/'feeds/topic/unexpected.xml'; extra.parent.mkdir(parents=True); extra.write_bytes(b'extra')
            with self.assertRaisesRegex(ValueError, 'complete_facet_inventory'): recovery.verify_inputs(root, fixture.manifest, fixture.bundle, receipt_path)


if __name__ == '__main__':
    unittest.main()
