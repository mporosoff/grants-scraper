"""Ordinary release readers recover independent checkpoints without new work."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from tests.test_release_checkpoint_archive import artifact, packed, run_metadata
from tools import fetch_release_artifact as transport
from tools import generation_spend_checkpoint as spending
from tools import plan_release as planner
from tools import release_candidate as candidate
from tools import release_checkpoint_archive as archive
from tools import restore_generation_checkpoint as restoration
from tools.offline_ai import Ledger


REPOSITORY, RUN, BACKUP, ATTEMPT = 'owner/project', '101', '901', 2


class ReleaseArchiveIntegration(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        public = b'complete original generated catalog\n'
        self.manifest = {
            'schema_version': 1, 'candidate_format': candidate.VERSION,
            'generation_sha': 'a' * 40, 'generation_run_id': RUN,
            'generation_run_attempt': str(ATTEMPT),
            'files': {'data/opportunities.js': candidate.digest(public)},
        }
        self.identifier = candidate.digest(candidate.encoded(self.manifest))
        self.manifest['candidate_id'] = self.identifier
        self.failed = {'candidate_id': self.identifier, 'validation_sha': 'a' * 40,
                       'gates': {gate: 'passed' for gate in candidate.GATES}}
        self.failed['gates']['notice-projection'] = 'failed'
        self.passed = deepcopy(self.failed)
        self.passed['gates']['notice-projection'] = 'passed'
        ledger = Ledger(self.root / 'original-ledger.json', 'offline-' + RUN, 2, 30)
        ledger.reserve('anthropic', 'fixture-model', 'verification', 'uncertain', 1900000, 1)
        self.ledger_bytes = ledger.path.read_bytes()
        self.settings = {'budgets_usd': {'maintenance': 2}, 'max_requests': 30,
                         'generation_provider_pauses': {}}
        self.raw = {
            11: packed({'candidate.json': candidate.encoded(self.manifest),
                        'files/data/opportunities.js': public}),
            12: packed({'validation-report.json': candidate.encoded(self.failed)}),
            13: packed({'spend-reservation.json': candidate.encoded(
                {'run_id': RUN, 'attempt': str(ATTEMPT), 'maximum_logical_spend_usd': 2})}),
            14: packed({'ledger.json': self.ledger_bytes,
                        'team-responses/completed.json': b'{"safe":"completed response"}'}),
            15: packed({'source-refresh-summary.json': b'{"healthy":true}'}),
        }
        names = {11: 'candidate-' + self.identifier,
                 12: f'validation-{self.identifier}-{ATTEMPT}',
                 13: f'generation-spend-reservation-{RUN}-{ATTEMPT}',
                 14: f'generation-spend-state-{RUN}-{ATTEMPT}',
                 15: f'source-refresh-summary-{RUN}-{ATTEMPT}'}
        self.originals = [artifact(identifier, names[identifier], raw)
                          for identifier, raw in self.raw.items()]
        self.values = {
            f'actions/runs/{RUN}': run_metadata(),
            f'actions/runs/{RUN}/attempts/{ATTEMPT}': run_metadata(),
            f'actions/runs/{RUN}/artifacts?per_page=100&page=1':
                {'artifacts': self.originals, 'total_count': len(self.originals)},
            **{f'actions/artifacts/{identifier}/zip': raw for identifier, raw in self.raw.items()},
        }
        self.calls = []
        snapshot = self.root / 'independent-checkpoint'
        self.capture = archive.capture(REPOSITORY, RUN, ATTEMPT, snapshot, api=self.read)
        outer_bytes = packed({path.relative_to(snapshot).as_posix(): path.read_bytes()
                              for path in snapshot.rglob('*') if path.is_file()})
        self.outer = artifact(1001, self.capture['artifact_name'], outer_bytes, BACKUP)
        older_raw = packed({'validation.json': candidate.encoded(self.passed)})
        self.older = artifact(9, f'validation-{self.identifier}-1', older_raw, '100')
        self.values.update({
            f'actions/runs/{BACKUP}': run_metadata(BACKUP, backup=True),
            'actions/artifacts/1001': self.outer,
            'actions/artifacts/1001/zip': outer_bytes,
            'actions/artifacts?per_page=100&page=1':
                {'artifacts': [self.older, self.outer], 'total_count': 2},
            f'actions/runs/{RUN}/artifacts?per_page=100&page=1':
                {'artifacts': [], 'total_count': 0},
            'actions/runs/100': run_metadata('100'),
            'actions/runs/100/artifacts?per_page=100&page=1':
                {'artifacts': [self.older], 'total_count': 1},
            'actions/artifacts/9/zip': older_raw,
        })
        # Only independent transport remains for the original attempt.
        for identifier in self.raw:
            del self.values[f'actions/artifacts/{identifier}/zip']
        self.calls.clear()

    def read(self, path):
        self.calls.append(path)
        value = self.values[path]
        return value if isinstance(value, bytes) else json.dumps(value).encode()

    def repository_api(self, repository, path):
        self.assertEqual(repository, REPOSITORY)
        return self.read(path)

    def command(self, command, **_):
        self.assertEqual(command[:2], ['gh', 'api'])
        prefix = 'repos/' + REPOSITORY + '/'
        self.assertTrue(command[2].startswith(prefix))
        return self.read(command[2][len(prefix):])

    def test_rerun_restores_missing_native_candidate_through_ordinary_reader(self):
        output = self.root / 'github-output'
        environment = {'GITHUB_REPOSITORY': REPOSITORY, 'GITHUB_RUN_ID': RUN,
                       'GITHUB_RUN_ATTEMPT': '3', 'RUNNER_TEMP': str(self.root / 'rerun'),
                       'GITHUB_OUTPUT': str(output)}
        with patch.dict(os.environ, environment), \
                patch.object(transport.subprocess, 'check_output', side_effect=self.command), \
                patch.object(transport, 'reconstruct') as reconstruct, \
                patch.object(candidate, 'create', side_effect=AssertionError('Repeated generation')), \
                patch.object(candidate, 'verify_dependencies') as dependencies:
            restoration.main()
        bundle = self.root / 'rerun/candidate'
        self.assertEqual(candidate.load(bundle), self.manifest)
        self.assertEqual((bundle / 'files/data/opportunities.js').read_bytes(),
                         b'complete original generated catalog\n')
        self.assertEqual(output.read_text(), 'candidate_id=' + self.identifier + '\n')
        dependencies.assert_called_once_with(candidate.ROOT, self.manifest)
        reconstruct.assert_not_called()
        self.assertNotIn('actions/artifacts/11/zip', self.calls)

    def test_newest_archived_failed_validation_beats_older_native_pass(self):
        with patch('tools.offline_ai_checkpoint.api', side_effect=self.repository_api), \
                patch.object(transport.subprocess, 'check_output', side_effect=self.command):
            run, report = planner.latest_report(REPOSITORY, self.identifier, 'validation',
                                                self.root / 'reports')
        self.assertEqual((run, report), (RUN, self.failed))
        self.assertNotIn('actions/artifacts/9/zip', self.calls)
        self.assertNotIn('actions/artifacts/12/zip', self.calls)

    def test_archived_spend_state_keeps_original_unknown_charges_and_cap(self):
        state, reservation = self.root / ('offline-' + RUN), self.root / 'reservation.json'
        with patch.object(spending, 'api', side_effect=self.repository_api), \
                patch.object(spending, 'config', return_value=self.settings):
            spending.prepare(REPOSITORY, RUN, '3', state, reservation, 'maintenance')
        self.assertEqual((state / 'ledger.json').read_bytes(), self.ledger_bytes)
        restored = Ledger(state / 'ledger.json', 'offline-' + RUN, 2, 30)
        self.assertEqual(restored.read()['requests'][0]['status'], 'reserved_unknown')
        self.assertEqual(restored.summary()['charged_usd'], 1.9)
        self.assertEqual(json.loads(reservation.read_bytes())['maximum_logical_spend_usd'], 2)
        self.assertEqual((state / 'team-responses/completed.json').read_bytes(),
                         b'{"safe":"completed response"}')
        with self.assertRaisesRegex(RuntimeError, 'budget_exhausted'):
            restored.reserve('anthropic', 'fixture-model', 'verification', 'new', 200000, 1)
        self.assertNotIn('actions/artifacts/14/zip', self.calls)

    def test_conflicting_native_and_archived_identity_fails_before_write(self):
        conflicting = deepcopy(self.originals[0])
        conflicting['digest'] = 'sha256:' + '0' * 64
        self.values[f'actions/runs/{RUN}/artifacts?per_page=100&page=1'] = {
            'artifacts': [conflicting], 'total_count': 1}
        destination = self.root / 'conflicting-candidate'
        with patch.object(transport.subprocess, 'check_output', side_effect=self.command), \
                self.assertRaisesRegex(ValueError, 'identities disagree'):
            transport.fetch(REPOSITORY, RUN, 'candidate-' + self.identifier, destination)
        self.assertFalse(destination.exists())
        self.assertNotIn('actions/artifacts/11/zip', self.calls)

    def test_malformed_archive_aborts_without_falling_back_to_old_pass(self):
        invalid = packed({'manifest.json': b'{}'})
        self.outer['digest'] = 'sha256:' + candidate.digest(invalid)
        self.outer['size_in_bytes'] = len(invalid)
        self.values['actions/artifacts/1001/zip'] = invalid
        with patch('tools.offline_ai_checkpoint.api', side_effect=self.repository_api), \
                patch.object(transport.subprocess, 'check_output', side_effect=self.command), \
                self.assertRaisesRegex(ValueError, 'Checkpoint manifest'):
            planner.latest_report(REPOSITORY, self.identifier, 'validation', self.root / 'reports')
        self.assertNotIn('actions/artifacts/9/zip', self.calls)
        self.assertFalse((self.root / 'reports').exists())

    def test_completed_workflow_preserves_every_zip_with_read_only_permissions(self):
        self.assertEqual({row['metadata']['id'] for row in self.capture['artifacts']}, set(self.raw))
        for row in self.capture['artifacts']:
            self.assertEqual((self.root / 'independent-checkpoint' / row['path']).read_bytes(),
                             self.raw[row['metadata']['id']])
        path = candidate.ROOT / archive.BACKUP_WORKFLOW
        workflow = yaml.safe_load(path.read_text(encoding='utf-8'))
        trigger = workflow.get('on', workflow.get(True))['workflow_run']
        self.assertEqual(trigger, {'workflows': ['Funding Finder immutable release'],
                                   'types': ['completed'], 'branches': ['main']})
        self.assertEqual(workflow['permissions'], {'contents': 'read', 'actions': 'read'})
        job = workflow['jobs']['preserve']
        self.assertNotIn('permissions', job)
        self.assertIn('head_repository.full_name == github.repository', job['if'])
        steps = job['steps']
        capture = next(step for step in steps if step.get('id') == 'capture')
        self.assertIn('tools.release_checkpoint_archive capture', capture['run'])
        self.assertEqual(capture['env']['SOURCE_ATTEMPT'], '${{ github.event.workflow_run.run_attempt }}')
        upload = next(step for step in steps if step.get('uses', '').startswith('actions/upload-artifact@'))
        self.assertEqual(upload['with']['path'], '${{ runner.temp }}/release-checkpoint')
        self.assertEqual(upload['with']['if-no-files-found'], 'error')
        text = json.dumps(workflow).lower()
        self.assertNotIn('test:e2e', text)
        self.assertNotIn('playwright', text)


if __name__ == '__main__':
    unittest.main()
