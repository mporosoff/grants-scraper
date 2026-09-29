"""Retained program-area correction lifecycle; no providers or browser suites."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml

from tests import test_release_candidate as fixtures
from tools import release_candidate as c


class ProgramAreaCandidateTests(unittest.TestCase):
    def setUp(self):
        # Reuse only the isolated repository builder, never inherit/run its
        # unrelated lifecycle or manual-browser test methods.
        self.fixture = fixtures.CandidateLifecycleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.policy = deepcopy(self.fixture.policy)
        self.policy['generation_contract'].update(python='3.13', node='22')
        self.policy['dependency_groups'] = {
            'source': {'patterns': ['scripts/parser.py', 'config/source.json'], 'excluded': []},
            'teams': {'patterns': ['scripts/teams.py'], 'excluded': []},
            'semantic': {'patterns': ['tools/vectors.mjs'], 'excluded': []},
            'runtime': {'patterns': self.policy['runtime'], 'excluded': []},
            'validation': {'patterns': self.policy['validation'] + [c.POLICY], 'excluded': []},
        }
        c.write_json(self.root / c.POLICY, self.policy)
        (self.root / '.github/workflows/refresh-opportunities.yml').write_text(
            'jobs:\n  generate:\n    steps:\n'
            '      - run: python -m scripts.parser\n'
            '      - run: node tools/build_search_v2_voyage_vectors.mjs --production --write\n', encoding='utf8')
        self.fixture.commit()
        self.fixture.source_sha = c.git(self.root, 'rev-parse', 'HEAD')
        self.parent = self.fixture.create()
        self.receipt = Path(self.fixture.temp.name) / 'receipt.json'
        self.receipt_value = {'version': 'program-area-revalidation-fixture',
                              'parent_candidate_id': self.parent['candidate_id'], 'source_collection_requests': 0}
        c.write_json(self.receipt, self.receipt_value)
        self.retained = {'config/opportunity_team_model.json': self.parent['generation_files']['config/opportunity_team_model.json']}

    def update_source(self):
        (self.root / 'scripts/parser.py').write_text('VERSION = 2\n', encoding='utf8')
        (self.root / 'data/opportunities.js').write_text('corrected-retained-catalog', encoding='utf8')
        c.write_json(self.root / 'data/search-v2-voyage-manifest.json',
                     {'model': 'test', 'model_space_fingerprint': 'space', 'corpus_sha256': 'corrected-corpus'})
        c.write_json(self.root / 'data/search-v2-release.json', {'current_corpus_sha256': 'corrected-corpus'})
        self.fixture.commit()
        return c.git(self.root, 'rev-parse', 'HEAD')

    def verified_inputs(self, root, original, receipt):
        self.assertEqual(Path(root), self.root)
        self.assertEqual(original, self.parent)
        self.assertEqual(Path(receipt), self.receipt)
        if c.read_json(receipt) != self.receipt_value:
            raise ValueError('Exact correction receipt required')
        return self.retained

    def corrected(self, name='corrected'):
        bundle = Path(self.fixture.temp.name) / name
        with patch('tools.program_area_revalidation.verify_inputs', side_effect=self.verified_inputs) as verify:
            value = c.create(self.root, bundle, parent=self.fixture.bundle,
                             program_area_revalidation=self.receipt, run_id='456', attempt='2')
        verify.assert_called_once()
        return bundle, value

    def test_correction_retains_original_owner_and_teams_but_binds_current_source_and_vectors(self):
        new_sha = self.update_source()
        bundle, value = self.corrected()
        for key in ('generation_sha', 'generation_run_id', 'generation_run_attempt', 'generation_timestamp', 'team_identity'):
            self.assertEqual(value[key], self.parent[key], key)
        self.assertEqual(value['derived_from_candidate'], self.parent['candidate_id'])
        self.assertEqual(value['assembly_sha'], new_sha)
        self.assertEqual(value['generation_dependencies'], c.generation_dependencies(self.root))
        self.assertNotEqual(value['generation_dependencies'], self.parent['generation_dependencies'])
        self.assertNotEqual(value['dependency_groups']['source'], self.parent['dependency_groups']['source'])
        self.assertEqual(value['dependency_groups']['teams'], self.parent['dependency_groups']['teams'])
        self.assertEqual(value['dependency_groups']['semantic'], self.parent['dependency_groups']['semantic'])
        self.assertEqual(value['semantic_identity']['corpus_sha256'], 'corrected-corpus')
        self.assertEqual(value['release_identity']['current_corpus_sha256'], 'corrected-corpus')
        self.assertEqual(value['generation_files']['data/opportunities.js'], c.digest(b'corrected-retained-catalog'))
        lineage = value['program_area_revalidation']
        self.assertEqual(lineage['parent_candidate_id'], self.parent['candidate_id'])
        self.assertEqual(lineage['retained_output_hashes'], self.retained)
        self.assertEqual(lineage['affected_generation']['generation_sha'], new_sha)
        self.assertEqual(lineage['affected_generation']['generation_run_id'], '456')
        self.assertEqual(lineage['affected_generation']['generation_run_attempt'], '2')
        self.assertEqual(set(lineage['affected_output_hashes']),
                         {'data/opportunities.js', 'data/search-v2-voyage-manifest.json'})
        self.assertEqual(value['original_generation']['generation_files'], self.parent['generation_files'])
        self.assertEqual(value['original_generation']['generation_dependencies'], self.parent['generation_dependencies'])
        self.assertEqual(c.load(bundle, value['candidate_id']), value)
        c.verify_dependencies(self.root, value)

    def test_runtime_child_keeps_the_typed_correction_and_original_generation(self):
        self.update_source()
        parent_bundle, corrected = self.corrected()
        (self.root / 'assets/app.css').write_text('main { color: blue; }', encoding='utf8')
        self.fixture.commit()
        child = c.create(self.root, Path(self.fixture.temp.name) / 'runtime-child',
                         parent=parent_bundle, run_id='789', attempt='1')
        self.assertEqual(child['derived_from_candidate'], corrected['candidate_id'])
        for key in ('program_area_revalidation', 'original_generation', 'generation_files', 'generation_dependencies',
                    'generation_sha', 'generation_run_id', 'generation_run_attempt', 'generation_timestamp',
                    'team_identity', 'semantic_identity'):
            self.assertEqual(child[key], corrected[key], key)
        self.assertNotEqual(child['files']['assets/app.css'], corrected['files']['assets/app.css'])
        c.verify_dependencies(self.root, child)

    def test_constructor_rejects_missing_parent_and_mixed_generation_modes(self):
        for index, options in enumerate(({}, {'parent': self.fixture.bundle, 'team_update': True},
                                        {'parent': self.fixture.bundle, 'source_correction': {}})):
            with self.subTest(options=options), patch('tools.program_area_revalidation.verify_inputs') as verify:
                with self.assertRaisesRegex(ValueError, 'requires its exact parent'):
                    c.create(self.root, Path(self.fixture.temp.name) / f'invalid-{index}',
                             program_area_revalidation=self.receipt, **options)
                verify.assert_not_called()

    def test_invalid_receipt_and_changed_retained_team_bytes_cannot_construct_candidate(self):
        self.update_source()
        c.write_json(self.receipt, self.receipt_value | {'parent_candidate_id': '0' * 64})
        with self.assertRaisesRegex(ValueError, 'Exact correction receipt required'):
            self.corrected('wrong-receipt')
        c.write_json(self.receipt, self.receipt_value)
        c.write_json(self.root / 'config/opportunity_team_model.json', {'generation_id': 'altered'})
        with self.assertRaisesRegex(ValueError, 'Candidate bytes differ'):
            self.corrected('changed-teams')

    def test_ordinary_reuse_cannot_cross_source_or_generated_data_changes(self):
        (self.root / 'scripts/parser.py').write_text('VERSION = 2\n', encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'dependency mismatch'):
            c.create(self.root, Path(self.fixture.temp.name) / 'ordinary-source', parent=self.fixture.bundle)
        (self.root / 'scripts/parser.py').write_text('VERSION = 1\n', encoding='utf8')
        (self.root / 'data/opportunities.js').write_text('unapproved-output', encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'Generation data input changed'):
            c.create(self.root, Path(self.fixture.temp.name) / 'ordinary-data', parent=self.fixture.bundle)


class ProgramAreaWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load((c.ROOT / '.github/workflows/refresh-opportunities.yml').read_text(encoding='utf8'))
        cls.jobs = cls.workflow['jobs']
        cls.job = cls.jobs['program-area-revalidation']
        cls.steps = cls.job['steps']
        cls.by_id = {step['id']: step for step in cls.steps if step.get('id')}

    def test_correction_exposes_only_the_vector_credential_and_keeps_teams_disabled(self):
        settings = c.read_json(c.ROOT / 'config/offline_ai.json')
        self.assertIs(settings['production_services']['teams']['enabled'], False)
        self.assertNotIn('API_KEY', json.dumps(self.job.get('env', {})))
        secret_steps = [step.get('id') for step in self.steps if 'secrets.' in json.dumps(step)]
        self.assertEqual(secret_steps, ['vectors'])
        self.assertEqual(self.by_id['vectors']['env'], {'VOYAGE_API_KEY': '${{ secrets.VOYAGE_API_KEY }}'})
        commands = '\n'.join(step.get('run', '') for step in self.steps)
        for command in ('scripts.build_catalog', 'scripts.enrich_catalog', 'scripts.sources merge',
                        'tools.run_budgeted_documents', 'scripts.build_opportunity_teams', 'pnpm test:e2e', 'playwright'):
            self.assertNotIn(command, commands)
        self.assertEqual(self.by_id['vectors']['run'], 'node tools/build_search_v2_voyage_vectors.mjs --write --production')

    def test_reservation_is_durable_before_vectors_and_complete_vector_checkpoint_precedes_candidate(self):
        ids = ['restore', 'prepare', 'vectors-restore', 'reserve', 'reservation-upload',
               'vectors', 'checkpoint', 'checkpoint-upload', 'persist']
        positions = [self.steps.index(self.by_id[name]) for name in ids]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("steps.reservation-upload.outcome == 'success'", self.by_id['vectors']['if'])
        for name in ('reserve', 'reservation-upload', 'vectors', 'checkpoint', 'checkpoint-upload'):
            step = self.by_id[name]
            self.assertIn("steps.restore.outputs.candidate_id == ''", step['if'])
            self.assertIn("steps.vectors-restore.outputs.restored != 'true'", step['if'])
            self.assertNotIn('continue-on-error', step)
            self.assertNotIn('always()', step['if'])
        for name in ('reservation-upload', 'checkpoint-upload'):
            self.assertEqual(self.by_id[name]['uses'], 'actions/upload-artifact@v4')
            self.assertEqual(self.by_id[name]['with']['if-no-files-found'], 'error')
            self.assertIsNot(self.by_id[name]['with'].get('overwrite'), True)
        package = next(step for step in self.steps if 'node tools/build_search_release_package.mjs' in step.get('run', ''))
        self.assertLess(self.steps.index(self.by_id['checkpoint-upload']), self.steps.index(package))
        self.assertLess(self.steps.index(package), self.steps.index(self.by_id['persist']))
        self.assertNotIn('continue-on-error', package)
        self.assertNotIn('continue-on-error', self.by_id['persist'])

    def test_completed_candidate_skips_all_mutation_and_enters_ordinary_protected_gates(self):
        restore_index = self.steps.index(self.by_id['restore'])
        for step in self.steps[restore_index + 1:]:
            self.assertIn("steps.restore.outputs.candidate_id == ''", step['if'])
        self.assertIn('steps.restore.outputs.candidate_id || steps.persist.outputs.candidate_id', self.job['outputs']['candidate_id'])
        candidate = self.jobs['candidate']
        self.assertIn('program-area-revalidation', candidate['needs'])
        self.assertIn("needs.program-area-revalidation.result == 'success'", candidate['if'])
        self.assertIn("needs.program-area-revalidation.result == 'skipped'", candidate['if'])
        select = next(step for step in candidate['steps'] if step.get('id') == 'select')
        self.assertIn('needs.program-area-revalidation.outputs.candidate_id', select['env']['GENERATED_ID'])
        self.assertEqual(self.jobs['validate']['needs'], ['plan', 'candidate'])
        self.assertIn('validate', self.jobs['publish']['needs'])
        self.assertIn("needs.validate.result == 'success'", self.jobs['publish']['if'])
        self.assertIn('program-area-revalidation', self.jobs['closeout']['needs'])
        final_integration = next(step for step in self.jobs['validate']['steps']
                                 if '--final-integration ' in step.get('run', ''))
        self.assertEqual(final_integration['if'], "github.event_name == 'workflow_dispatch' && inputs.final_integration")
        events = self.workflow.get('on') or self.workflow[True]
        self.assertIs(events['workflow_dispatch']['inputs']['final_integration']['default'], False)


class ProgramAreaPlanTests(unittest.TestCase):
    def setUp(self):
        from tools import program_area_release as bridge
        self.bridge = bridge
        self.environment = {
            'GITHUB_REPOSITORY': 'mporosoff/grants-scraper', 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_WORKFLOW_REF': 'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main',
            'CANDIDATE_RUN': str(bridge.recovery.PARENT_RUN), 'CANDIDATE_ID': bridge.recovery.PARENT_CANDIDATE,
            'REQUESTED_STAGE': 'program-area-revalidation', 'QUALIFICATION_PILOT': 'false',
        }

    def test_plan_uses_only_the_exact_manual_parent_without_team_or_document_providers(self):
        with patch.object(c, 'git', return_value='a' * 40):
            plan = self.bridge.plan(Path('.'), self.environment)
        self.assertEqual(plan['stage'], 'program-area-revalidation')
        self.assertEqual(plan['candidate_id'], self.bridge.recovery.PARENT_CANDIDATE)
        self.assertEqual(plan['candidate_run'], str(self.bridge.recovery.PARENT_RUN))
        self.assertEqual(plan['release_sha'], 'a' * 40)
        self.assertEqual(plan['team_mode'], 'maintenance')
        self.assertEqual((plan['openai'], plan['anthropic']), ('false', 'false'))

    def test_plan_rejects_implicit_foreign_or_mixed_selectors_before_git(self):
        changes = [('GITHUB_EVENT_NAME', 'schedule'), ('GITHUB_EVENT_NAME', 'push'),
                   ('GITHUB_REF', 'refs/heads/feature'), ('GITHUB_REPOSITORY', 'foreign/repo'),
                   ('GITHUB_WORKFLOW_REF', 'mporosoff/grants-scraper/.github/workflows/other.yml@refs/heads/main'),
                   ('CANDIDATE_RUN', ''), ('CANDIDATE_RUN', '999'), ('CANDIDATE_ID', ''),
                   ('CANDIDATE_ID', '0' * 64), ('QUALIFICATION_PILOT', 'true'),
                   ('RECEIPT_RUN', '1'), ('PUBLICATION_RUN', '1'), ('PUBLICATION_ATTEMPT', '1')]
        for key, value in changes:
            with self.subTest(key=key, value=value), patch.object(c, 'git') as git:
                with self.assertRaises(ValueError):
                    self.bridge.plan(Path('.'), self.environment | {key: value})
                git.assert_not_called()

    def test_only_the_old_source_fingerprint_holds_automatic_paid_work(self):
        manifest = {'candidate_id': 'b' * 64}
        fingerprints = [(self.bridge.recovery.PARENT_EXTRACTOR_SHA256, True),
                        ('68fa1d7149eae53c27d75ffcc8e168398500cbf663542a5f4faf104ba9788d68', True),
                        ('fixed-source', False), (None, False)]
        for fingerprint, held in fingerprints:
            files = {'scripts/extract_document_evidence.py': fingerprint} if fingerprint else {}
            with self.subTest(fingerprint=fingerprint), patch.object(c, 'read_json', return_value=manifest), \
                    patch('tools.release_dependencies.candidate_groups', return_value={'source': {'files': files}}):
                self.assertIs(self.bridge.correction_pending(Path('.')), held)

    def test_existing_bridge_applies_the_hold_and_routes_explicit_correction(self):
        from tools import catalog_correction_release as existing
        for held in (False, True):
            with self.subTest(held=held), patch.dict(os.environ, {'REQUESTED_STAGE': 'auto'}, clear=True), \
                    patch.object(existing, 'correction_complete', return_value=True), \
                    patch.object(self.bridge, 'correction_pending', return_value=held), \
                    patch('tools.plan_release.main', return_value='planned') as ordinary:
                self.assertEqual(existing.plan(), 'planned')
                ordinary.assert_called_once_with(automatic_paid_hold=held)
        with patch.dict(os.environ, self.environment | {'RUNNER_TEMP': '.'}, clear=True), \
                patch.object(self.bridge, 'plan', return_value={'stage': 'program-area-revalidation'}) as explicit, \
                patch.object(existing, 'atomic_json') as write, patch.object(existing, 'output'), \
                patch('tools.plan_release.main') as ordinary:
            existing.plan()
            explicit.assert_called_once_with(existing.ROOT, self.environment | {'RUNNER_TEMP': '.'})
            write.assert_called_once()
            ordinary.assert_not_called()


if __name__ == '__main__':
    unittest.main()
