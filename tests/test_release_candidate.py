"""Executable checkpoint/retry contracts using isolated repositories, no providers."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import release_candidate as c
from tools.validate_release_candidate import validate, final_integration
from tools.verify_notice_publication import verify, bounded_public_value
from tests import test_notice_publication


class CandidateLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        self.bundle = Path(self.temp.name) / 'candidate'
        self.reports = Path(self.temp.name) / 'reports'
        self.policy = {
            'generation': ['scripts/parser.py', 'scripts/teams.py', 'tools/vectors.mjs', 'config/source.json'],
            'generation_excluded': [], 'generation_contract': {'team_max_scopes': 60},
            'generated': ['data/opportunities.js', 'data/search-v2-voyage-manifest.json', 'config/opportunity_team_model.json'],
            'runtime': ['index.html', 'assets/app.css', 'workers/search/src/index.js', '.nojekyll'],
            'package': ['data/search-v2-release.json'], 'worker': ['workers/search/src/index.js'],
            'validation': ['tools/validator.py', '.github/workflows/release.yml'],
        }
        for name, content in {
            c.POLICY: json.dumps(self.policy), 'scripts/parser.py': 'VERSION = 1\n',
            'scripts/teams.py': 'MODEL = "bounded"\n', 'tools/vectors.mjs': 'const model = "v1";\n',
            'config/source.json': '{}', 'data/opportunities.js': 'catalog-original',
            'data/search-v2-voyage-manifest.json': '{"model": "test", "model_space_fingerprint": "space"}',
            'config/opportunity_team_model.json': '{"generation_id": "team"}',
            'data/search-v2-release.json': '{"current_corpus_sha256": "corpus"}',
            'index.html': '<main>current</main>', 'assets/app.css': 'main {}', '.nojekyll': '',
            'workers/search/src/index.js': 'export default {};', 'tools/validator.py': 'VERSION = 1\n',
            '.github/workflows/release.yml': 'version: 1', 'evaluation/frozen.json': '{}',
            'package.json': '{"scripts":{"test:e2e":"playwright test"}}', 'pnpm-lock.yaml': 'lockfileVersion: 9',
            'tools/check.sh': 'true',
        }.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8', newline='\n')
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        c.git(self.root, 'config', 'core.autocrlf', 'false')
        c.git(self.root, 'config', 'user.name', 'Contract')
        c.git(self.root, 'config', 'user.email', 'contract@example.test')
        self.commit()
        self.source_sha = c.git(self.root, 'rev-parse', 'HEAD')
        (self.root / 'data/opportunities.js').write_text('complete-generated-catalog')

    def commit(self):
        c.git(self.root, 'add', '.')
        c.git(self.root, 'commit', '-qm', 'contract checkpoint')

    def create(self):
        return c.create(self.root, self.bundle, generation_sha=self.source_sha, run_id='123', attempt='1')

    def execute(self, commands, fail=None, mutate=None):
        def run(command, **kwargs):
            commands.append(command)
            if mutate:
                (self.root / 'data/opportunities.js').write_text('mutation')
            return subprocess.CompletedProcess(command, int(bool(fail and fail(command))))
        return run

    def test_complete_candidate_is_loadable_after_failure_and_cannot_be_confused(self):
        manifest = self.create()
        before = c.file_hashes(self.bundle / 'files', manifest['files'])
        commands = []
        with self.assertRaisesRegex(ValueError, 'validation failed'):
            validate(self.root, self.bundle, self.reports, execute=self.execute(commands, fail=lambda cmd: 'tools.verify_notice_publication' in cmd))
        self.assertEqual(c.load(self.bundle)['files'], before)
        recovered = Path(self.temp.name) / 'next-job'
        shutil.copytree(self.bundle, recovered)
        self.assertEqual(c.load(recovered, manifest['candidate_id']), manifest)
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            c.load(recovered, '0' * 64)
        self.assertTrue((self.reports / 'validation-report.json').exists())
        self.assertFalse((self.reports / 'validation.json').exists())
        self.assertEqual(len(commands), len(c.GATES))

    def browser_result(self, commands, *, failed=False, mutate=False):
        def run(command, **kwargs):
            commands.append(command)
            if command == ['pnpm', 'test:e2e']:
                c.write_json(self.root / 'test-results/playwright-results.json', {
                    'stats': {'expected': 3, 'unexpected': int(failed), 'skipped': 0}})
                if mutate:
                    (self.root / 'data/opportunities.js').write_text('invalid test mutation')
            return subprocess.CompletedProcess(command, int(failed))
        return run

    def test_manual_browser_integration_reuses_exact_candidate_and_test_receipt(self):
        manifest = self.create()
        validate(self.root, self.bundle, self.reports, execute=self.execute([]))
        commands = []
        first = final_integration(self.root, self.bundle, self.reports,
                                  execute=self.browser_result(commands))
        self.assertTrue(first['passed'])
        self.assertEqual(first['identity']['candidate_hashes'], manifest['files'])
        self.assertEqual(first['new_generation_calls'], 0)
        self.assertEqual(len(commands), 2)
        prior = self.reports / 'final-integration.json'
        repeated = final_integration(self.root, self.bundle, self.reports, prior,
            execute=lambda *args, **kwargs: self.fail('Unchanged E2E must not repeat'))
        self.assertEqual(repeated, first)
        c.verify_files(self.root, manifest['files'])
        test = self.root / 'tests/e2e/current.spec.mjs'
        test.parent.mkdir(parents=True)
        test.write_text('changed browser contract')
        current = final_integration(self.root, self.bundle, self.reports, prior,
                                    execute=self.browser_result(commands))
        self.assertNotEqual(current['identity'], first['identity'])
        self.assertEqual(len(commands), 4)

    def test_browser_failure_retains_candidate_and_ordinary_validation_for_retry(self):
        manifest = self.create()
        validate(self.root, self.bundle, self.reports, execute=self.execute([]))
        ordinary = (self.reports / 'validation.json').read_bytes()
        for mutate in (False, True):
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                final_integration(self.root, self.bundle, self.reports,
                    execute=self.browser_result([], failed=not mutate, mutate=mutate))
            self.assertFalse(c.read_json(self.reports / 'final-integration.json')['passed'])
            retained = c.read_json(self.reports / 'validation.json')
            self.assertEqual({k: v for k, v in retained.items() if k != 'final_integration'}, json.loads(ordinary))
            if mutate:
                c.git(self.root, 'checkout', 'HEAD', '--', 'data/opportunities.js')
                c.materialize(self.root, self.bundle)
            with self.assertRaisesRegex(ValueError, 'final browser integration'):
                c.verify_receipt(self.root, self.bundle, retained, require_final=True)
            self.assertEqual(c.load(self.bundle), manifest)
        # A failed test cannot poison the artifact used by the next validator.
        c.git(self.root, 'checkout', 'HEAD', '--', 'data/opportunities.js')
        c.materialize(self.root, self.bundle)
        self.assertTrue(final_integration(self.root, self.bundle, self.reports,
            self.reports / 'final-integration.json', execute=self.browser_result([]))['passed'])

    def test_changed_candidate_never_reuses_old_browser_receipt(self):
        self.create()
        validate(self.root, self.bundle, self.reports, execute=self.execute([]))
        first = final_integration(self.root, self.bundle, self.reports, execute=self.browser_result([]))
        old = Path(self.temp.name) / 'old-browser.json'
        c.write_json(old, first)
        (self.root / 'data/opportunities.js').write_text('next complete candidate')
        self.bundle = Path(self.temp.name) / 'next-candidate'
        self.create()
        validate(self.root, self.bundle, self.reports, execute=self.execute([]))
        commands = []
        current = final_integration(self.root, self.bundle, self.reports, old,
                                    execute=self.browser_result(commands))
        self.assertNotEqual(first['identity']['candidate_id'], current['identity']['candidate_id'])
        self.assertEqual(len(commands), 2)

    def test_browser_imports_and_their_transitive_dependencies_invalidate_receipt(self):
        for name, content in {
            'tests/e2e/source.spec.mjs': 'import { normalize } from "../../workers/award-api/src/ror.js";',
            'workers/award-api/src/ror.js': 'import { clean } from "./contract.js"; export const normalize = clean;',
            'workers/award-api/src/contract.js': 'export const clean = value => value;',
        }.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        self.create()
        validate(self.root, self.bundle, self.reports, execute=self.execute([]))
        first = final_integration(self.root, self.bundle, self.reports, execute=self.browser_result([]))
        self.assertIn('workers/award-api/src/ror.js', first['identity']['test_inputs'])
        self.assertIn('workers/award-api/src/contract.js', first['identity']['test_inputs'])
        for name in ('ror.js', 'contract.js'):
            path = self.root / 'workers/award-api/src' / name
            path.write_text(path.read_text() + '\n// changed behavior contract', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'final browser integration'):
                c.verify_receipt(self.root, self.bundle, c.read_json(self.reports / 'validation.json'))
            commands = []
            final_integration(self.root, self.bundle, self.reports, self.reports / 'final-integration.json',
                              execute=self.browser_result(commands))
            self.assertEqual(len(commands), 2)

    def test_required_browser_gate_survives_interruption_and_ordinary_checkpoint_reuse(self):
        self.create()
        ordinary = validate(self.root, self.bundle, self.reports, execute=self.execute([]),
                            require_final_integration=True)
        # Interruption between ordinary validation and the browser step cannot
        # leave an artifact that a publication-only retry will accept.
        with self.assertRaisesRegex(ValueError, 'final browser integration'):
            c.verify_receipt(self.root, self.bundle, ordinary)
        prior = self.reports / 'validation.json'
        reused = validate(self.root, self.bundle, self.reports, prior,
                          execute=lambda *a, **k: self.fail('Ordinary gates must not repeat'))
        self.assertEqual(reused, ordinary)
        def interrupted(*args, **kwargs):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            final_integration(self.root, self.bundle, self.reports, execute=interrupted)
        with self.assertRaisesRegex(ValueError, 'final browser integration'):
            c.verify_receipt(self.root, self.bundle, c.read_json(prior))
        final_integration(self.root, self.bundle, self.reports, execute=self.browser_result([]))
        self.assertTrue(c.verify_receipt(self.root, self.bundle, c.read_json(prior)))

    def test_explicit_publish_or_validate_recovers_latest_required_browser_gate(self):
        from tools import plan_release as planner
        manifest = self.create()
        current = c.create(self.root, Path(self.temp.name) / 'other-current-candidate',
                           generation_sha=self.source_sha, run_id='999', attempt='1')
        c.write_json(self.root / 'release/candidate.json', current)
        c.write_json(self.root / 'release/candidate-source.json', {
            'candidate_id': current['candidate_id'], 'artifact_run': '999'})
        validate(self.root, self.bundle, self.reports, execute=self.execute([]), require_final_integration=True)
        latest = c.read_json(self.reports / 'validation.json')
        for stage in ('publish', 'validate'):
            for selected_receipt in ('', '100'):
                env = {'REQUESTED_STAGE': stage, 'CANDIDATE_ID': manifest['candidate_id'], 'CANDIDATE_RUN': '123',
                    'RECEIPT_RUN': selected_receipt, 'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                    'PUBLICATION_RUN': '', 'PUBLICATION_ATTEMPT': '',
                    'RUNNER_TEMP': str(self.root), 'GITHUB_OUTPUT': str(self.root / 'outputs'),
                    'GITHUB_STEP_SUMMARY': str(self.root / 'summary')}
                with self.subTest(stage=stage, receipt=selected_receipt), patch.dict(os.environ, env), \
                        patch.object(c, 'ROOT', self.root), patch.object(planner, 'latest_report', return_value=('200', latest)) as lookup:
                    planner.main()
                planned = c.read_json(self.root / 'release-plan.json')
                self.assertEqual((planned['candidate_id'], planned['candidate_run']), (manifest['candidate_id'], '123'))
                self.assertEqual(planned['receipt_run'], '200')
                self.assertEqual(lookup.call_args.args[1:3], (manifest['candidate_id'], 'validation'))
                # The workflow downloads this selected receipt even when the
                # dispatch omits both optional receipt and browser flags.
                reused = validate(self.root, self.bundle, self.reports, self.reports / 'validation.json',
                    execute=lambda *a, **k: self.fail('A publish retry must reuse completed ordinary checks'))
                with self.assertRaisesRegex(ValueError, 'final browser integration'):
                    c.verify_receipt(self.root, self.bundle, reused)

    def test_failed_ordinary_report_keeps_manual_browser_intent_on_named_retry(self):
        self.create()
        with self.assertRaises(ValueError):
            validate(self.root, self.bundle, self.reports, execute=self.execute([], fail=lambda _: True),
                     require_final_integration=True)
        self.assertFalse((self.reports / 'validation.json').exists())
        repaired = validate(self.root, self.bundle, self.reports, self.reports / 'validation.json',
                            execute=self.execute([]))
        with self.assertRaisesRegex(ValueError, 'final browser integration'):
            c.verify_receipt(self.root, self.bundle, repaired)
        final_integration(self.root, self.bundle, self.reports, execute=self.browser_result([]))
        self.assertTrue(c.verify_receipt(self.root, self.bundle, c.read_json(self.reports / 'validation.json')))

    def test_expired_or_missing_candidate_recovers_only_exact_protected_bytes(self):
        from tools import fetch_release_artifact as artifacts
        manifest = self.create()
        c.materialize(self.root, self.bundle)
        c.write_json(self.root / 'release/candidate.json', manifest)
        c.write_json(self.root / 'release/candidate-source.json', {'candidate_id': manifest['candidate_id'], 'artifact_run': '123'})
        self.commit()
        c.git(self.root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
        meta = {'head_branch': 'main', 'path': '.github/workflows/refresh-opportunities.yml', 'event': 'push'}
        original = subprocess.check_output
        for expired in (False, True):
            name = 'candidate-' + manifest['candidate_id']
            rows = [{'name': name, 'expired': True}] if expired else []
            def call(command, **kwargs):
                if command[0] == 'gh':
                    return json.dumps({'artifacts': rows} if 'artifacts?' in command[-1] else meta).encode()
                return original(command, **kwargs)
            destination = Path(self.temp.name) / ('expired' if expired else 'missing')
            with patch.object(c, 'ROOT', self.root), patch.object(subprocess, 'check_output', side_effect=call):
                artifacts.fetch('owner/repo', '123', name, destination)
                self.assertEqual(c.load(destination, manifest['candidate_id']), manifest)
                with self.assertRaises(artifacts.ArtifactUnavailable):
                    artifacts.reconstruct('owner/repo', '124', name, destination / 'wrong-run')
                with self.assertRaises(artifacts.ArtifactUnavailable):
                    artifacts.reconstruct('owner/repo', '123', 'validation-' + manifest['candidate_id'], destination / 'receipt')

    def test_artifact_authentication_or_corruption_never_triggers_reconstruction(self):
        from tools import fetch_release_artifact as artifacts
        import zipfile
        meta = {'head_branch': 'main', 'path': '.github/workflows/refresh-opportunities.yml', 'event': 'push'}
        name = 'candidate-' + 'a' * 64
        cases = [subprocess.CalledProcessError(1, ['gh', 'api']),
                 [json.dumps(meta).encode(), json.dumps({'artifacts': [{'name': name, 'expired': False, 'id': 1}]}).encode(), b'corrupt']]
        for result in cases:
            with patch.object(subprocess, 'check_output', side_effect=result), patch.object(artifacts, 'reconstruct') as recover:
                with self.assertRaises((subprocess.CalledProcessError, zipfile.BadZipFile)):
                    artifacts.fetch('owner/repo', '123', name, self.bundle)
                recover.assert_not_called()

    def test_automatic_rerun_after_pages_resumes_verification_of_exact_candidate(self):
        from tools import plan_release as planner
        manifest = self.create()
        receipt = validate(self.root, self.bundle, self.reports, execute=self.execute([]))
        publication = {'schema_version': 1, 'candidate_id': manifest['candidate_id'], 'candidate_hashes': manifest['files'],
            'generation_sha': self.source_sha, 'generation_run_id': '123', 'validation_sha': receipt['validation_sha'],
            'validation_receipt_sha256': c.digest(c.encoded(receipt)), 'publication_sha': self.source_sha,
            'release_code_sha': self.source_sha}
        checkpoint = {'receipt': publication, 'validation': receipt, 'run': '123', 'attempt': '1', 'pages_complete': True}
        c.write_json(self.root / 'release/candidate-source.json', {'candidate_id': manifest['candidate_id'], 'artifact_run': '123'})
        environment = {'GITHUB_EVENT_NAME': 'schedule', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2'}
        result = planner.plan(self.root, environment, resumed=manifest, receipt=receipt,
                              live={'verified': False}, publication=checkpoint)
        self.assertEqual(result['stage'], 'verify')
        self.assertEqual(result['candidate_id'], manifest['candidate_id'])
        self.assertEqual((result['candidate_run'], result['publication_run'], result['publication_attempt']), ('123', '123', '1'))
        checkpoint['pages_complete'] = False
        self.assertEqual(planner.plan(self.root, environment, resumed=manifest, publication=checkpoint)['stage'], 'publish')
        checkpoint['pages_complete'] = True
        publication['candidate_id'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Publication receipt'):
            planner.plan(self.root, environment, resumed=manifest, publication=checkpoint)

    def test_validator_correction_revalidates_same_bytes_without_generation(self):
        manifest = self.create()
        commands = []
        with self.assertRaises(ValueError):
            validate(self.root, self.bundle, self.reports, execute=self.execute(commands, fail=lambda _: True))
        (self.root / 'tools/validator.py').write_text('VERSION = 2\n')
        self.commit()
        receipt = validate(self.root, self.bundle, self.reports, execute=self.execute(commands))
        self.assertEqual(receipt['generation_sha'], self.source_sha)
        self.assertNotEqual(receipt['validation_sha'], self.source_sha)
        self.assertEqual(receipt['candidate_id'], manifest['candidate_id'])
        self.assertEqual(c.load(self.bundle), manifest)
        self.assertFalse(any(any(name in str(cmd) for name in ['scripts.build_catalog', 'scripts.sources', 'scripts.enrich_catalog', 'scripts.extract_document_evidence', '--generate', 'build_search_v2_voyage_vectors']) for cmd in commands))

    def test_publication_and_live_retry_reuse_receipt_and_exact_candidate(self):
        manifest = self.create()
        commands = []
        receipt = validate(self.root, self.bundle, self.reports, execute=self.execute(commands))
        commands.clear()
        retried = validate(self.root, self.bundle, self.reports, self.reports / 'validation.json', execute=self.execute(commands))
        self.assertEqual(retried, receipt)
        self.assertEqual(commands, [])
        for _ in range(2):
            c.verify_receipt(self.root, self.bundle, receipt)
            c.materialize(self.root, self.bundle)
            c.verify_files(self.root, manifest['files'])
        self.assertEqual(c.load(self.bundle), manifest)

    def test_mutating_validator_cannot_issue_receipt_or_change_persisted_bytes(self):
        manifest = self.create()
        with self.assertRaisesRegex(ValueError, 'bytes differ'):
            validate(self.root, self.bundle, self.reports, execute=self.execute([], mutate=True))
        self.assertEqual(c.load(self.bundle), manifest)
        self.assertFalse((self.reports / 'validation.json').exists())

    def test_generation_input_changes_invalidate_but_unrelated_advancement_preserves_provenance(self):
        manifest = self.create()
        for name in ['scripts/parser.py', 'scripts/teams.py', 'tools/vectors.mjs', 'config/source.json']:
            with self.subTest(name=name):
                path = self.root / name
                before = path.read_bytes()
                path.write_text('x = 2\n' if name.endswith('.py') else 'changed')
                with self.assertRaisesRegex(ValueError, 'Generation dependencies changed'):
                    c.verify_dependencies(self.root, manifest)
                path.write_bytes(before)
        for name in ['tools/validator.py', '.github/workflows/release.yml', 'assets/app.css', 'AGENTS.md']:
            (self.root / name).write_text('unrelated change')
            c.verify_dependencies(self.root, manifest)
        self.commit()
        self.assertNotEqual(c.git(self.root, 'rev-parse', 'HEAD'), self.source_sha)
        self.assertEqual(c.load(self.bundle)['generation_sha'], self.source_sha)

    def test_source_data_advancement_and_receipt_hash_mismatch_fail_closed(self):
        manifest = self.create()
        receipt = validate(self.root, self.bundle, self.reports, execute=self.execute([]))
        forged = deepcopy(receipt)
        forged['identity']['candidate_hashes']['data/opportunities.js'] = 'f' * 64
        with self.assertRaises(ValueError):
            c.verify_receipt(self.root, self.bundle, forged)
        (self.root / 'data/opportunities.js').write_text('other-generation')
        with self.assertRaisesRegex(ValueError, 'Generation data input changed'):
            c.verify_dependencies(self.root, manifest)

    def test_ui_reassembly_preserves_generated_bytes_and_original_generation(self):
        original = self.create()
        (self.root / 'assets/app.css').write_text('main {color:blue}')
        self.commit()
        with self.assertRaisesRegex(ValueError, 'Release runtime changed'):
            c.materialize(self.root, self.bundle)
        derived_path = Path(self.temp.name) / 'derived'
        derived = c.create(self.root, derived_path, run_id='456', attempt='1', parent=self.bundle)
        self.assertNotEqual(derived['candidate_id'], original['candidate_id'])
        self.assertEqual(derived['generation_files'], original['generation_files'])
        self.assertEqual(derived['generation_sha'], original['generation_sha'])
        self.assertEqual(derived['generation_run_id'], '123')
        self.assertEqual(derived['worker_fingerprint'], original['worker_fingerprint'])

    def test_team_only_derived_candidate_preserves_source_vectors_and_historical_provenance(self):
        self.policy['team_outputs'] = ['config/opportunity_team_model.json']
        self.policy['dependency_groups'] = {key: {'patterns': names, 'excluded': []} for key, names in {
            'source': ['scripts/parser.py', 'config/source.json'], 'teams': ['scripts/teams.py', 'config/offline_ai.json'],
            'semantic': ['tools/vectors.mjs'], 'runtime': self.policy['runtime'], 'validation': self.policy['validation']}.items()}
        c.write_json(self.root / c.POLICY, self.policy)
        c.write_json(self.root / 'config/offline_ai.json', {'model': 'retained'})
        (self.root / '.github/workflows/refresh-opportunities.yml').write_text('jobs:\n  generate:\n    steps: []\n')
        self.commit()
        self.source_sha = c.git(self.root, 'rev-parse', 'HEAD')
        original = self.create()
        (self.root / 'scripts/teams.py').write_text('MODEL = "new-default"\n')
        self.commit()
        with self.assertRaisesRegex(ValueError, 'required action teams'):
            c.verify_dependencies(self.root, original)
        c.write_json(self.root / 'config/opportunity_team_model.json', {'generation_id': 'new-team-output'})
        derived_path = Path(self.temp.name) / 'team-derived'
        derived = c.create(self.root, derived_path, run_id='456', attempt='1', parent=self.bundle, team_update=True)
        self.assertEqual(derived['generation_sha'], original['generation_sha'])
        self.assertEqual(derived['generation_run_id'], '123')
        self.assertEqual(derived['team_generation']['sha'], c.git(self.root, 'rev-parse', 'HEAD'))
        self.assertEqual(derived['team_generation']['run_id'], '456')
        self.assertEqual(derived['worker_fingerprint'], original['worker_fingerprint'])
        for name in ('data/opportunities.js', 'data/search-v2-voyage-manifest.json'):
            self.assertEqual(derived['files'][name], original['files'][name])
        receipt = validate(self.root, derived_path, self.reports, execute=self.execute([]))
        c.verify_receipt(self.root, derived_path, receipt)
        c.materialize(self.root, derived_path)
        c.verify_files(self.root, derived['files'])
        (self.root / 'scripts/parser.py').write_text('VERSION = 2\n')
        with self.assertRaisesRegex(ValueError, 'required action generate'):
            c.verify_dependencies(self.root, derived)

    def test_private_and_unmanifested_bytes_are_rejected(self):
        self.create()
        (self.bundle / 'files/unexpected.txt').write_text('not a candidate file')
        with self.assertRaisesRegex(ValueError, 'Unmanifested'):
            c.load(self.bundle)
        private = self.root / 'private.json'
        private.write_text('{"raw_text":"private notice"}')
        with self.assertRaisesRegex(ValueError, 'Private material'):
            c.privacy_check(private)
        for name in ('../escape', '/escape', '.git/config', 'C:/secret', 'path\\secret'):
            with self.assertRaises(ValueError):
                c.checked_path(self.root, name)

    def test_python_comments_do_not_invalidate_generation(self):
        manifest = self.create()
        with (self.root / 'scripts/parser.py').open('a') as file:
            file.write('# Clarified comment\n')
        c.verify_dependencies(self.root, manifest)

    def test_optional_caches_do_not_change_candidate_identity(self):
        with patch.object(c, 'timestamp', return_value='2026-09-08T00:00:00Z'):
            manifest = self.create()
            cache = self.root / '.cache/provider/private.json'
            cache.parent.mkdir(parents=True)
            cache.write_text('{"raw_text":"never retained"}')
            second = c.create(self.root, Path(self.temp.name) / 'same-output', generation_sha=self.source_sha, run_id='123', attempt='1')
        self.assertEqual(manifest, second)

    def test_generation_command_and_safe_source_configuration_changes_invalidate(self):
        workflow = self.root / '.github/workflows/refresh-opportunities.yml'
        workflow.write_text('jobs:\n  generate:\n    steps:\n      - run: python -m scripts.build_catalog --max-record-count 5000\n')
        manifest = self.create()
        workflow.write_text(workflow.read_text().replace('5000', '4000'))
        with self.assertRaisesRegex(ValueError, 'Generation dependencies changed'):
            c.verify_dependencies(self.root, manifest)

    def test_stale_pr_rebases_unchanged_candidate_only_after_terminal_review(self):
        from tools.publish_release_candidate import reconcile_candidate_branch
        manifest = self.create()
        self.commit()
        old_head = c.git(self.root, 'rev-parse', 'HEAD')
        c.git(self.root, 'checkout', '-qb', 'advanced-main', self.source_sha)
        (self.root / 'operations.md').write_text('unrelated main advancement')
        self.commit()
        advanced = c.git(self.root, 'rev-parse', 'HEAD')
        c.materialize(self.root, self.bundle)
        c.git(self.root, 'add', '.')
        existing = {'headRefOid': old_head, 'headRefName': 'automation/release-test', 'url': 'https://github.com/owner/repo/pull/10'}
        observed = []
        def execute(*args):
            observed.append(args)
            if args[:2] == ('git', 'commit'):
                return c.git(self.root, *args[1:])
            return ''
        def waiting(*args):
            observed.append(('review', *args))
            raise ValueError('still pending')
        with self.assertRaisesRegex(ValueError, 'still pending'):
            reconcile_candidate_branch(self.root, existing, manifest, 'owner/repo', execute=execute, wait=waiting)
        self.assertEqual(c.git(self.root, 'rev-parse', 'HEAD'), advanced)
        self.assertFalse(any(row[0] == 'git' for row in observed))
        observed.clear()
        head, boundary = reconcile_candidate_branch(self.root, existing, manifest, 'owner/repo', execute=execute,
                                                    wait=lambda *args: observed.append(('review', *args)))
        self.assertEqual(observed[0], ('review', 'owner/repo', 10, old_head))
        self.assertEqual(c.git(self.root, 'rev-parse', 'HEAD^'), advanced)
        self.assertNotEqual(head, old_head)
        self.assertIn(f'--force-with-lease=refs/heads/automation/release-test:{old_head}', observed[-1])
        self.assertTrue(boundary)
        c.verify_files(self.root, manifest['files'])
        self.assertEqual(c.load(self.bundle)['generation_sha'], self.source_sha)

    def test_live_identity_rejects_same_candidate_with_stale_publication_or_stamp(self):
        from tools import verify_release_live as live
        manifest = self.create()
        receipt = validate(self.root, self.bundle, self.reports, execute=self.execute([]))
        publication = {'schema_version': 1, 'candidate_id': manifest['candidate_id'], 'candidate_hashes': manifest['files'],
                       'generation_sha': manifest['generation_sha'], 'generation_run_id': manifest['generation_run_id'],
                       'validation_sha': receipt['validation_sha'], 'publication_sha': 'b' * 40, 'release_code_sha': 'c' * 40,
                       'validation_receipt_sha256': c.digest(c.encoded(receipt)), 'timestamp': '2026-09-08T00:00:00Z'}
        c.write_json(self.reports / 'publication.json', publication)
        served = deepcopy(publication)
        stamp = publication['publication_sha'] + '\n'
        requested = []
        def fetch(url):
            name = url.removeprefix(live.SITE).split('?')[0]
            requested.append(name)
            if name == '.nojekyll':
                raise AssertionError('Pages does not HTTP-serve its build-control file')
            if name == 'release/candidate.json':
                return c.encoded(manifest)
            if name == 'release/publication.json':
                return c.encoded(served)
            if name == 'pages-release-sha.txt':
                return stamp.encode()
            return (self.bundle / 'files' / name).read_bytes()
        serving = {'verified': True, 'fingerprint': manifest['worker_fingerprint'], 'version_id': 'serving-version'}
        with patch.object(live, 'fetch', side_effect=fetch), patch.object(live, 'worker_check', return_value={'service': 'available'}), \
             patch.object(live, 'worker_provenance', return_value=serving) as provenance:
            site = self.root / 'staged-pages'
            live.stage_site(self.bundle, self.reports, site)
            self.assertEqual((site / '.nojekyll').read_bytes(), b'')
            c.verify_files(site, {'.nojekyll': manifest['files']['.nojekyll']})
            served['publication_sha'] = 'd' * 40
            with self.assertRaisesRegex(ValueError, 'Live verification failed'):
                live.verify(self.bundle, self.reports, attempts=1)
            served.update(publication)
            stamp = 'e' * 40 + '\n'
            with self.assertRaisesRegex(ValueError, 'Live verification failed'):
                live.verify(self.bundle, self.reports, attempts=1)
            stamp = publication['publication_sha'] + '\n'
            # Supported verify retry: exact Pages and healthy corpus/model are
            # insufficient when authenticated active Worker inputs changed.
            provenance.side_effect = ValueError('Active Search Worker differs from the publication version/input checkpoint')
            with self.assertRaisesRegex(ValueError, 'Live verification failed'):
                live.verify(self.bundle, self.reports, attempts=1)
            self.assertFalse(c.read_json(self.reports / 'live-verification.json')['verified'])
            provenance.side_effect = None
            report = live.verify(self.bundle, self.reports, attempts=1)
            self.assertEqual(report['worker_provenance'], serving)
            # A change during the provider-smoke interval must also fail closed.
            provenance.side_effect = ValueError('Active Search Worker differs from the publication version/input checkpoint')
            with self.assertRaisesRegex(ValueError, 'Complete live verification failed'):
                live.complete_live(self.bundle, self.reports, 'success', 'success')
            self.assertFalse(c.read_json(self.reports / 'live-verification.json')['verified'])
            provenance.side_effect = None
            live.verify(self.bundle, self.reports, attempts=1)
            report = live.complete_live(self.bundle, self.reports, 'success', 'success')
        self.assertTrue(report['verified'])
        self.assertEqual(report['publication_sha'], publication['publication_sha'])
        self.assertEqual(report['publication_receipt_sha256'], c.digest(c.encoded(publication)))
        self.assertEqual(c.load(self.bundle), manifest)
        self.assertNotIn('.nojekyll', requested)
        self.assertIn('data/opportunities.js', requested)
        self.assertIn('assets/app.css', requested)

    def test_live_provenance_reads_authenticated_metadata_and_rejects_stale_success(self):
        from tools import verify_release_live as live
        self.create()
        c.write_json(self.reports / 'worker-live.json', {'verified': True, 'version_id': 'old'})
        # A failed fresh metadata read cannot reuse a successful earlier observation.
        with patch.object(live.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)) as execute:
            with self.assertRaisesRegex(ValueError, 'Worker provenance verification failed'):
                live.worker_provenance(self.bundle, self.reports)
        arguments = execute.call_args.args[0]
        self.assertEqual(arguments[:3], ['node', str(c.ROOT / 'tools/search_worker_checkpoint.mjs'), '--verify-live'])
        self.assertIn(str(self.reports / 'worker-after.json'), arguments)

    def test_publication_noop_requires_committed_bytes_not_materialized_working_copy(self):
        from tools.publish_release_candidate import committed_candidate_matches
        manifest = self.create()
        c.materialize(self.root, self.bundle)
        c.verify_files(self.root, manifest['files'])
        self.assertFalse(committed_candidate_matches(self.root, self.source_sha, manifest))
        self.commit()
        self.assertTrue(committed_candidate_matches(self.root, c.git(self.root, 'rev-parse', 'HEAD'), manifest))


class ExactReviewTests(unittest.TestCase):
    def test_old_approval_reaction_does_not_cover_rebased_head(self):
        from tools import wait_release_review as review
        head = 'b' * 40
        pr = {'head': {'sha': head}, 'base': {'ref': 'main'}, 'created_at': '2026-09-08T00:00:00Z',
              'body': f'Review head: `{"a" * 40}`', 'user': {'login': 'github-actions[bot]'}}
        request = {'user': pr['user'], 'created_at': '2026-09-08T01:00:05Z',
                   'body': f'<!-- funding-finder-review:{head} -->\nReview boundary: 2026-09-08T01:00:00+00:00'}
        reaction = {'user': {'login': review.BOT}, 'content': '+1', 'created_at': '2026-09-08T00:30:00Z'}
        def pages(path):
            if path.endswith('/reactions'):
                return [reaction]
            return [request] if '/issues/' in path and path.endswith('/comments') else []
        with patch.object(review, 'api', return_value=pr), patch.object(review, 'all_pages', side_effect=pages), \
             patch.object(review, 'all_threads', return_value=[]):
            self.assertEqual(review.review_state('owner/repo', 1, head), (False, []))
            reaction['created_at'] = '2026-09-08T01:01:00Z'
            self.assertEqual(review.review_state('owner/repo', 1, head), (True, []))

    def test_terminal_top_level_completion_needs_full_head_and_no_unresolved_findings(self):
        from tools import wait_release_review as review
        head = 'a' * 40
        complete = {'user': {'login': review.BOT}, 'body': f'Codex Review completed. Reviewed commit: {head}'}
        def pages(path):
            return [complete] if path.endswith('/comments') and '/issues/' in path else []
        with patch.object(review, 'api', return_value={'head': {'sha': head}, 'base': {'ref': 'main'}}), \
             patch.object(review, 'all_pages', side_effect=pages), patch.object(review, 'all_threads', return_value=[]):
            self.assertEqual(review.review_state('owner/repo', 1, head, '2026-01-01'), (True, []))
            complete['body'] = 'Codex Review working'
            self.assertEqual(review.review_state('owner/repo', 1, head, '2026-01-01'), (False, []))


class ProjectionDiagnosticsTests(unittest.TestCase):
    def test_exact_record_and_bounded_before_after_are_reported(self):
        catalog, cache = test_notice_publication.NoticePublicationTests().candidate()
        catalog['opportunities'][0]['next_submission'] = {'date': '2099-01-01'}
        report = verify(catalog, cache, candidate_id='candidate-example')
        self.assertEqual(report['candidate_id'], 'candidate-example')
        change = next(row for row in report['changes'] if 'next_submission' in row['fields'])
        self.assertEqual(change['opportunity_id'], 'fixture')
        diff = next(d for d in change['differences'] if d['field'] == 'next_submission')
        self.assertEqual(diff['before'], {'date': '2099-01-01'})
        self.assertNotEqual(diff['before'], diff['after'])
        self.assertEqual(report['source_requests'], 0)
        self.assertTrue(report['validator_version'])
        bounded = bounded_public_value('x' * 5000)
        self.assertTrue(bounded['truncated'])
        self.assertLess(len(bounded['preview']), 3000)
