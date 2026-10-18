"""Whole-directory checkpoint transports preserve evidence, not OS ownership."""
import io
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from tests import test_contextual_team_stage_retention as stage_fixture
from tools import contextual_team_stage_retention as retention
from tools import team_recommender_executor as executor
from tools.offline_spend import ConfigurationFailure


def archive(files, extras=()):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as packet, warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        for name, raw in list(files.items()) + list(extras):
            packet.writestr(name, raw)
    return output.getvalue()


def malformed_sidecars():
    symbolic = zipfile.ZipInfo('ledger.lock')
    symbolic.create_system = 3
    symbolic.external_attr = (stat.S_IFLNK | 0o777) << 16
    directory = zipfile.ZipInfo('ledger.lock')
    directory.create_system = 3
    directory.external_attr = (stat.S_IFDIR | 0o755) << 16
    return [('nonempty', [('ledger.lock', b'not ownership')]),
            ('duplicate', [('ledger.lock', b''), ('ledger.lock', b'')]),
            ('symlink', [(symbolic, b'')]), ('directory_mode', [(directory, b'')]),
            ('nested', [('cache/ledger.lock', b'')]),
            ('unknown', [('different.lock', b'')]),
            ('traversal', [('../ledger.lock', b'')])]


class CheckpointLockSidecar(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.state = self.root/'state'; self.state.mkdir()
        env = patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
                                    'GITHUB_SHA': 'a'*40})
        env.start(); self.addCleanup(env.stop)
        (self.state/'ledger.json').write_bytes((executor.CONFIG/'initial-ledger.json').read_bytes())
        self.ledger = executor.ExperimentLedger(self.state/'ledger.json').read()
        executor.checkpoint(self.state)
        self.files = {p.relative_to(self.state).as_posix(): p.read_bytes()
                      for p in self.state.rglob('*.json')}

    def test_whole_directory_archive_restores_exact_json_and_keeps_existing_lock_inode(self):
        self.assertEqual((self.state/'ledger.lock').read_bytes(), b'')
        raw = archive(self.files, [('ledger.lock', b'')])
        destination = self.root/'restored'; destination.mkdir()
        lock = destination/'ledger.lock'; lock.write_bytes(b'existing local inode')
        inode = lock.stat().st_ino
        executor.unpack_state(raw, destination)
        self.assertEqual(lock.stat().st_ino, inode)
        self.assertEqual(lock.read_bytes(), b'existing local inode')
        self.assertEqual(executor.ExperimentLedger(destination/'ledger.json').read(), self.ledger)
        self.assertEqual({p.relative_to(destination).as_posix(): p.read_bytes()
                          for p in destination.rglob('*.json')}, self.files)

    def test_old_json_only_archive_still_restores(self):
        destination = self.root/'old'
        executor.unpack_state(archive(self.files), destination)
        self.assertEqual({p.relative_to(destination).as_posix(): p.read_bytes()
                          for p in destination.rglob('*.json')}, self.files)

    def test_only_unique_empty_regular_root_sidecar_is_discarded(self):
        for label, extras in malformed_sidecars():
            with self.subTest(case=label), self.assertRaisesRegex(ValueError, 'unsafe_checkpoint_member'):
                executor.unpack_state(archive(self.files, extras), self.root/label)

    def test_encrypted_sidecar_is_rejected_before_read(self):
        raw = bytearray(archive(self.files, [('ledger.lock', b'')]))
        # Mark the lock's actual local and central ZIP headers encrypted.
        with zipfile.ZipFile(io.BytesIO(raw)) as packet:
            offset = packet.getinfo('ledger.lock').header_offset
        raw[offset + 6] |= 1
        central = raw.find(b'PK\x01\x02')
        while central >= 0:
            size = int.from_bytes(raw[central + 28:central + 30], 'little')
            if raw[central + 46:central + 46 + size] == b'ledger.lock':
                raw[central + 8] |= 1; break
            central = raw.find(b'PK\x01\x02', central + 4)
        self.assertGreaterEqual(central, 0)
        with self.assertRaisesRegex(ValueError, 'unsafe_checkpoint_member'):
            executor.unpack_state(bytes(raw), self.root/'encrypted')

    def test_sidecar_still_counts_toward_original_archive_limit(self):
        with patch.object(executor, 'STATE_FILE_LIMIT', len(self.files)):
            with self.assertRaisesRegex(ValueError, 'checkpoint_size_exceeded'):
                executor.unpack_state(archive(self.files, [('ledger.lock', b'')]), self.root/'limit')


class StageLockSidecar(unittest.TestCase):
    def setUp(self):
        self.fixture = stage_fixture.StageRetention('runTest')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        retention.complete(self.fixture.state, self.fixture.job, 'assess', self.fixture.progress('assess'))

    def test_actual_stage_archive_accepts_lock_without_changing_checkpoint_or_local_inode(self):
        fixture = self.fixture; files = fixture.files()
        lock = fixture.state/'ledger.lock'; lock.write_bytes(b'local lock inode')
        inode = lock.stat().st_ino
        api, _ = fixture.artifact(archive(files, [('ledger.lock', b'')]))
        bound = retention.seal(fixture.state, fixture.job, 'verify', api)
        self.assertTrue(bound)
        self.assertEqual(fixture.files(), files)
        self.assertEqual((lock.stat().st_ino, lock.read_bytes()), (inode, b'local lock inode'))
        with patch.dict(os.environ, {'I3_PRIOR_SEAL_SHA256': bound}):
            retention.require_prior(fixture.state, fixture.job, 'verify')

    def test_stage_keeps_strict_archive_shape_and_sidecar_controls(self):
        fixture = self.fixture; files = fixture.files()
        for label, extras in malformed_sidecars():
            with self.subTest(case=label):
                api, _ = fixture.artifact(archive(files, extras))
                with self.assertRaisesRegex(ConfigurationFailure, 'archive_shape'):
                    retention.seal(fixture.state, fixture.job, 'verify', api)
        self.assertFalse(retention.seal_path(fixture.state, fixture.job, 'verify').exists())
        self.assertEqual(fixture.files(), files)

    def test_empty_sidecar_does_not_hide_changed_evidence(self):
        fixture = self.fixture
        files = fixture.files() | {'ledger.json': b'{}'}
        api, _ = fixture.artifact(archive(files, [('ledger.lock', b'')]))
        with self.assertRaisesRegex(ConfigurationFailure, 'archive_not_exact_local_state'):
            retention.seal(fixture.state, fixture.job, 'verify', api)


if __name__ == '__main__':
    unittest.main()
