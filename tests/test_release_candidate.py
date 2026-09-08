"""Executable checkpoint/retry contracts using isolated repositories, no providers."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import release_candidate as c
from tools.validate_release_candidate import validate
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
            'runtime': ['index.html', 'assets/app.css', 'workers/search/src/index.js'],
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
            'index.html': '<main>current</main>', 'assets/app.css': 'main {}',
            'workers/search/src/index.js': 'export default {};', 'tools/validator.py': 'VERSION = 1\n',
            '.github/workflows/release.yml': 'version: 1', 'evaluation/frozen.json': '{}',
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


class ExactReviewTests(unittest.TestCase):
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
