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
