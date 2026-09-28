"""Complete run evidence must precede recovery, receipt selection, or spending."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import fetch_release_artifact as artifacts
from tools import generation_spend_checkpoint as spend
from tools import plan_release as planner
from tools import restore_generation_checkpoint as restore
from tools.offline_ai import Ledger


def artifact(name, identifier, **extra):
    return {'name': name, 'id': identifier, 'expired': False} | extra


def archive(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as output:
        for name, content in files.items():
            output.writestr(name, content)
    return stream.getvalue()


class CompleteRunArtifacts(unittest.TestCase):
    repository = 'owner/repo'
    run_id = '123'
    candidate_id = 'c' * 64

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.rows = []
        self.downloads = {}
        self.paths = []
        self.page_error = None
        self.page_override = None
        self.meta = {'head_branch': 'main', 'event': 'schedule',
                     'path': '.github/workflows/refresh-opportunities.yml'}
        for target, replacement in (
                ('tools.fetch_release_artifact.subprocess.check_output', self.command),
                ('tools.offline_ai_checkpoint.api', self.api),
                ('tools.generation_spend_checkpoint.api', self.api)):
            mocked = patch(target, side_effect=replacement)
            mocked.start()
            self.addCleanup(mocked.stop)

    @staticmethod
    def filler(count):
        return [artifact(f'unrelated-{index}', 1000 + index) for index in range(count)]

    def command(self, command, **kwargs):
        self.assertEqual(command[:2], ['gh', 'api'])
        self.assertEqual(kwargs, {'timeout': 60})
        prefix = f'repos/{self.repository}/'
        self.assertTrue(command[2].startswith(prefix), command)
        return self.api(self.repository, command[2][len(prefix):])

    def api(self, repository, path):
        self.assertEqual(repository, self.repository)
        self.paths.append(path)
        if path == f'actions/runs/{self.run_id}':
            return json.dumps(self.meta).encode()
        if path.startswith(f'actions/runs/{self.run_id}/artifacts?per_page=100&page='):
            page = int(path.rsplit('=', 1)[1])
            if self.page_error and page == 2:
                raise self.page_error
            value = (self.page_override(page) if self.page_override else
                     {'total_count': len(self.rows), 'artifacts': self.rows[(page - 1) * 100:page * 100]})
            return json.dumps(value).encode()
        if path.startswith('actions/artifacts/') and path.endswith('/zip'):
            return self.downloads[int(path.split('/')[2])]
        self.fail('Unexpected GitHub endpoint: ' + path)

    def fetch(self, name, suffix='download'):
        return artifacts.fetch(self.repository, self.run_id, name, self.root / suffix)

    def assert_no_download(self):
        self.assertFalse(any(path.endswith('/zip') for path in self.paths), self.paths)

    def test_release_plan_later_page_is_selected_and_fetched_through_real_downloader(self):
        sha = 'b' * 40
        self.rows = self.filler(100) + [artifact('release-plan-2', 2)]
        self.downloads[2] = archive({'release-plan.json': json.dumps({'release_sha': sha})})
        result = planner.release_plan_sha(self.repository, self.run_id, 3, self.root / 'plan')
        self.assertEqual(result, sha)
        self.assertEqual(self.paths.count(f'actions/runs/{self.run_id}/artifacts?per_page=100&page=2'), 2)
        self.assertEqual(self.paths[-1], 'actions/artifacts/2/zip')

    def test_exact_candidate_later_page_still_requires_authenticated_origin_and_safe_zip_paths(self):
        name = 'candidate-' + self.candidate_id
        self.rows = self.filler(100) + [artifact(name, 2)]
        self.downloads[2] = archive({'files/data/catalog.json': '{"safe":true}'})
        self.assertEqual(self.fetch(name), self.meta)
        self.assertEqual((self.root / 'download/files/data/catalog.json').read_text(), '{"safe":true}')
        self.meta['head_branch'] = 'untrusted'
        self.paths.clear()
        with self.assertRaisesRegex(ValueError, 'protected release workflow'):
            self.fetch(name, 'untrusted')
        self.assertEqual(self.paths, [f'actions/runs/{self.run_id}'])
        self.meta['head_branch'] = 'main'
        self.downloads[2] = archive({'../escape.txt': 'unsafe'})
        with self.assertRaises(ValueError):
            self.fetch(name, 'unsafe')
        self.assertFalse((self.root / 'escape.txt').exists())

    def test_duplicate_exact_identity_across_pages_never_downloads_or_reconstructs(self):
        name = 'candidate-' + self.candidate_id
        for expired in (False, True):
            with self.subTest(expired=expired):
                self.rows = [artifact(name, 1)] + self.filler(99) + [artifact(name, 2, expired=expired)]
                with patch.object(artifacts, 'reconstruct') as recover:
                    with self.assertRaisesRegex(ValueError, 'Conflicting artifact identities'):
                        self.fetch(name)
                    recover.assert_not_called()
                self.assert_no_download()

    def test_report_alias_uses_newest_numeric_attempt_across_pages(self):
        name = 'validation-' + self.candidate_id
        self.rows = [artifact(name + '-9', 90)] + self.filler(99) + [artifact(name + '-10', 10)]
        self.downloads[10] = archive({'validation.json': '{"attempt":10}'})
        self.fetch(name)
        self.assertEqual((self.root / 'download/validation.json').read_text(), '{"attempt":10}')
        self.assertNotIn('actions/artifacts/90/zip', self.paths)

    def test_expired_newest_report_or_expired_exact_selector_cannot_fall_back(self):
        name = 'validation-' + self.candidate_id
        for selected in (name + '-10', name):
            with self.subTest(selected=selected):
                self.rows = [artifact(name + '-9', 9)] + self.filler(99) + [artifact(selected, 10, expired=True)]
                with self.assertRaises(artifacts.ArtifactUnavailable):
                    self.fetch(name)
                self.assert_no_download()

    def test_duplicate_newest_alias_across_pages_cannot_select_older_receipt(self):
        name = 'publication-' + self.candidate_id
        self.rows = [artifact(name + '-2', 2), artifact(name + '-1', 1)] + self.filler(98) + [
            artifact(name + '-2', 3, expired=True)]
        with patch.object(artifacts, 'reconstruct') as recover:
            with self.assertRaisesRegex(ValueError, 'Conflicting artifact identities'):
                self.fetch(name)
            recover.assert_not_called()
        self.assert_no_download()

    def test_incomplete_or_malformed_history_never_downloads_or_reconstructs_first_page_match(self):
        name = 'candidate-' + self.candidate_id
        self.rows = [artifact(name, 1)] + self.filler(99) + [artifact('later', 2)]
        cases = (
            (subprocess.CalledProcessError(1, ['gh', 'api']), None, subprocess.CalledProcessError),
            (None, lambda page: {'artifacts': self.rows[:1], 'total_count': 101}, ValueError),
            (None, lambda page: {'artifacts': {}}, ValueError),
            (None, lambda page: {'artifacts': self.rows[:100]}, ValueError),
        )
        for error, override, failure in cases:
            with self.subTest(error=error, override=override):
                self.page_error, self.page_override = error, override
                self.paths.clear()
                with patch.object(artifacts, 'reconstruct') as recover:
                    with self.assertRaises(failure):
                        self.fetch(name)
                    recover.assert_not_called()
                self.assert_no_download()
                self.assertLessEqual(len(self.paths), 101)

    def candidate_reader(self, kind):
        if kind == 'planner':
            return planner.completed_attempt(self.root, {'GITHUB_REPOSITORY': self.repository,
                'GITHUB_RUN_ID': self.run_id, 'GITHUB_RUN_ATTEMPT': '2'}, self.root / 'candidate')
        output = self.root / 'output.txt'
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': self.repository, 'GITHUB_RUN_ID': self.run_id,
                                    'RUNNER_TEMP': str(self.root), 'GITHUB_OUTPUT': str(output)}):
            restore.main()
        return output.read_text() if output.exists() else ''

    def test_both_generation_readers_restore_later_page_candidate_without_new_generation(self):
        name = 'candidate-' + self.candidate_id
        manifest = {'candidate_id': self.candidate_id}
        self.rows = self.filler(100) + [artifact(name, 2)]
        for kind in ('planner', 'restore'):
            with self.subTest(kind=kind):
                self.downloads[2] = archive({kind + '.json': '{}'})
                with patch.object(planner.c, 'load', return_value=manifest) as load, \
                        patch.object(planner.c, 'verify_dependencies') as verify:
                    result = self.candidate_reader(kind)
                    load.assert_called_once_with(self.root / 'candidate', self.candidate_id)
                    verify.assert_called_once()
                self.assertTrue((self.root / 'candidate' / (kind + '.json')).exists())
                self.assertEqual(result, manifest if kind == 'planner' else 'candidate_id=' + self.candidate_id + '\n')

    def test_both_generation_readers_hold_cross_page_ambiguity_and_incomplete_history(self):
        name = 'candidate-' + self.candidate_id
        self.rows = [artifact(name, 1)] + self.filler(99) + [artifact(name, 2, expired=True)]
        for kind in ('planner', 'restore'):
            for incomplete in (False, True):
                with self.subTest(kind=kind, incomplete=incomplete):
                    self.page_error = subprocess.CalledProcessError(1, ['gh', 'api']) if incomplete else None
                    with patch.object(artifacts, 'reconstruct') as recover:
                        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                            self.candidate_reader(kind)
                        recover.assert_not_called()
                    self.assert_no_download()

    def test_expired_generation_identity_is_not_silently_treated_as_no_candidate(self):
        name = 'candidate-' + self.candidate_id
        self.rows = self.filler(100) + [artifact(name, 1, expired=True)]
        for kind in ('planner', 'restore'):
            with self.subTest(kind=kind), patch.object(artifacts, 'reconstruct',
                    side_effect=artifacts.ArtifactUnavailable('Exact candidate unavailable')) as recover:
                with self.assertRaisesRegex(artifacts.ArtifactUnavailable, 'Exact candidate unavailable'):
                    self.candidate_reader(kind)
                recover.assert_called_once_with(self.repository, self.run_id, name, self.root / 'candidate')
        self.assert_no_download()

    def prepare_spend(self):
        spend.prepare(self.repository, self.run_id, '3', self.root / 'offline-123',
                      self.root / 'reservation.json', 'pilot')

    def spend_rows(self):
        return [artifact('generation-spend-reservation-123-1', 1),
                artifact('generation-spend-state-123-1', 2)] + self.filler(98) + [
                artifact('generation-spend-reservation-123-2', 3),
                artifact('generation-spend-state-123-2', 4)]

    def test_spend_restore_uses_later_page_newest_state_and_preserves_unknown_charges(self):
        ledger = Ledger(self.root / 'old/ledger.json', 'offline-123', 2)
        ledger.reserve('anthropic', 'fixture-model', 'verification', 'key', 1900000, 1)
        self.rows = self.spend_rows()
        self.downloads[4] = archive({'ledger.json': ledger.path.read_bytes()})
        self.prepare_spend()
        restored = Ledger(self.root / 'offline-123/ledger.json', 'offline-123', 2)
        self.assertEqual(restored.summary()['charged_usd'], 1.9)
        self.assertNotIn('actions/artifacts/2/zip', self.paths)
        with self.assertRaisesRegex(RuntimeError, 'budget_exhausted'):
            restored.reserve('openai', 'fixture-model', 'verification', 'other', 200000, 1)

    def test_spend_restore_never_falls_back_when_newest_state_is_missing_expired_or_ambiguous(self):
        for state in ('missing', 'expired', 'duplicate'):
            with self.subTest(state=state):
                self.rows = self.spend_rows()
                if state == 'missing':
                    self.rows.pop()
                elif state == 'expired':
                    self.rows[-1]['expired'] = True
                else:
                    self.rows[2] = artifact('generation-spend-state-123-2', 5, expired=True)
                with self.assertRaisesRegex(ValueError, 'remaining allowance unavailable'):
                    self.prepare_spend()
                self.assert_no_download()
                self.assertFalse((self.root / 'reservation.json').exists())
                self.assertFalse((self.root / 'offline-123/ledger.json').exists())

    def test_spend_incomplete_history_cannot_restore_older_state_or_create_new_allowance(self):
        self.rows = self.spend_rows()
        self.page_error = subprocess.CalledProcessError(1, ['gh', 'api'])
        with self.assertRaises(subprocess.CalledProcessError):
            self.prepare_spend()
        self.assert_no_download()
        self.assertFalse((self.root / 'reservation.json').exists())
        self.assertFalse((self.root / 'offline-123/ledger.json').exists())


if __name__ == '__main__':
    unittest.main()
