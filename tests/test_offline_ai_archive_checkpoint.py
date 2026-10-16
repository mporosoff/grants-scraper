"""Task spending cannot roll back when a pilot survives only in an archive."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_release_checkpoint_archive import artifact, packed, run_metadata
from tools import offline_ai_checkpoint as task
from tools import release_checkpoint_archive as archive
from tools.offline_ai import Ledger


REPOSITORY, PILOT, BACKUP = 'owner/project', '101', '901'


class ArchivedTaskCheckpointContracts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.old = Ledger(self.root / 'old-ledger.json', task.TASK, 2, 30)
        self.old.reserve('anthropic', 'fixture-model', 'cov4', 'old', 300000, 1)
        self.new = Ledger(self.root / 'new-ledger.json', task.TASK, 2, 30)
        self.new.reserve('anthropic', 'fixture-model', 'cov4', 'old', 300000, 1)
        self.new.reserve('anthropic', 'fixture-model', 'cov4', 'unknown-new', 1500000, 1)
        self.new_bytes = self.new.path.read_bytes()
        self.raw = {22: packed({'reservation.json': b'{"task":"protected"}'}),
                    23: packed({'ledger.json': self.new_bytes,
                                'team-responses/completed.json': b'{"exact":"newer decision"}'})}
        self.new_rows = [artifact(22, task.PREFIX + '-reservation-' + PILOT + '-2', self.raw[22]),
                         artifact(23, task.PREFIX + '-state-' + PILOT + '-2', self.raw[23])]
        meta = run_metadata(); meta['event'] = 'workflow_dispatch'
        self.values = {f'actions/runs/{PILOT}': meta,
                       f'actions/runs/{PILOT}/attempts/2': meta,
                       f'actions/runs/{PILOT}/artifacts?per_page=100&page=1': {'artifacts': self.new_rows, 'total_count': 2},
                       **{f'actions/artifacts/{identifier}/zip': raw for identifier, raw in self.raw.items()}}
        self.calls = []
        snapshot = self.root / 'archive'
        saved = archive.capture(REPOSITORY, PILOT, 2, snapshot, api=self.read)
        raw = packed({path.relative_to(snapshot).as_posix(): path.read_bytes()
                      for path in snapshot.rglob('*') if path.is_file()})
        self.outer = artifact(1001, saved['artifact_name'], raw, BACKUP)
        old_raw = packed({'ledger.json': self.old.path.read_bytes()})
        self.old_rows = [artifact(9, task.PREFIX + '-reservation-100-1', self.raw[22], '100'),
                         artifact(10, task.PREFIX + '-state-100-1', old_raw, '100')]
        old_meta = run_metadata('100'); old_meta.update(path=task.WORKFLOW, event='workflow_dispatch', run_attempt=1)
        self.values.update({'actions/artifacts?per_page=100&page=1': {'artifacts': self.old_rows + [self.outer], 'total_count': 3},
                            f'actions/runs/{BACKUP}': run_metadata(BACKUP, backup=True),
                            'actions/runs/100': old_meta,
                            'actions/artifacts/1001': self.outer, 'actions/artifacts/1001/zip': raw,
                            'actions/artifacts/10/zip': old_raw})
        for identifier in self.raw:
            del self.values[f'actions/artifacts/{identifier}/zip']
        self.calls.clear()
        self.environment = {'GITHUB_RUN_ID': PILOT, 'GITHUB_RUN_ATTEMPT': '3', 'GITHUB_SHA': 'a' * 40}

    def read(self, path):
        self.calls.append(path)
        value = self.values[path]
        return value if isinstance(value, bytes) else json.dumps(value).encode()

    def api(self, repository, path):
        self.assertEqual(repository, REPOSITORY)
        return self.read(path)

    def restore(self, destination):
        with patch.dict(os.environ, self.environment), patch.object(task, 'api', side_effect=self.api):
            task.prepare(REPOSITORY, destination, self.root / 'reservation.json')

    def test_newest_archived_pilot_task_preserves_all_charges_over_older_native_state(self):
        destination = self.root / 'restored-task'
        destination.mkdir()
        # Emulates the complete run-state restore that precedes task restore.
        (destination / 'ledger.json').write_bytes(self.new_bytes)
        self.restore(destination)
        self.assertEqual((destination / 'ledger.json').read_bytes(), self.new_bytes)
        ledger = Ledger(destination / 'ledger.json', task.TASK, 2, 30)
        self.assertEqual(len(ledger.read()['requests']), 2)
        self.assertEqual(ledger.summary()['charged_usd'], 1.8)
        self.assertEqual(ledger.read()['requests'][-1]['status'], 'reserved_unknown')
        self.assertEqual((destination / 'team-responses/completed.json').read_bytes(), b'{"exact":"newer decision"}')
        with self.assertRaisesRegex(RuntimeError, 'budget_exhausted'):
            ledger.reserve('anthropic', 'fixture-model', 'cov4', 'next', 300000, 1)
        self.assertNotIn('actions/artifacts/10/zip', self.calls)
        self.assertNotIn('actions/artifacts/23/zip', self.calls)

    def test_original_evaluation_workflow_native_state_still_restores_without_archives(self):
        self.values['actions/artifacts?per_page=100&page=1'] = {'artifacts': self.old_rows, 'total_count': 2}
        destination = self.root / 'native-task'
        self.restore(destination)
        self.assertEqual((destination / 'ledger.json').read_bytes(), self.old.path.read_bytes())
        self.assertIn('actions/artifacts/10/zip', self.calls)
        self.assertNotIn('actions/artifacts/1001/zip', self.calls)

    def test_a_newer_native_reservation_without_state_does_not_reuse_older_archived_task(self):
        missing = artifact(30, task.PREFIX + '-reservation-102-1', self.raw[22], '102')
        rows = self.old_rows + [self.outer, missing]
        self.values['actions/artifacts?per_page=100&page=1'] = {'artifacts': rows, 'total_count': len(rows)}
        destination = self.root / 'must-remain-empty'
        with self.assertRaisesRegex(ValueError, 'checkpoint_missing_or_expired'):
            self.restore(destination)
        self.assertFalse(destination.exists())

    def test_malformed_newer_archive_cannot_fall_back_to_older_native_task(self):
        changed = deepcopy(self.outer); changed['digest'] = 'sha256:' + '0' * 64
        self.values['actions/artifacts?per_page=100&page=1'] = {'artifacts': self.old_rows + [changed], 'total_count': 3}
        destination = self.root / 'must-remain-empty'
        with self.assertRaisesRegex(ValueError, 'digest'):
            self.restore(destination)
        self.assertFalse(destination.exists())
        self.assertNotIn('actions/artifacts/10/zip', self.calls)


if __name__ == '__main__':
    unittest.main()
