"""Real process-death/contender contracts; no source or provider transport."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tests import test_catalog_reconcile_spend as fixtures
from tools import offline_spend as offline, catalog_reconcile_spend as vectors

ROOT = Path(__file__).resolve().parents[1]
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
HOLDER = '''
import sys,time
from pathlib import Path
from tools.offline_spend import Ledger,exclusive_file_lock
from tools.catalog_reconcile_spend import request_locked
kind,path,ready,logical=sys.argv[1:]
if kind=='ledger':
    book=Ledger(Path(path),logical,2,300)
    manager=book.locked()
elif kind=='request':
    manager=request_locked(Path(path),'a'*64)
else:
    manager=exclusive_file_lock(Path(path))
with manager:
    Path(ready).write_text('held')
    time.sleep(60)
'''


class OfflineOSLocks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sequence = 0

    @contextmanager
    def holder(self, kind, path, logical='offline-lock-test'):
        self.sequence += 1
        ready = self.root / f'holder-{self.sequence}.ready'
        process = subprocess.Popen([sys.executable, '-c', HOLDER, kind, str(path), str(ready), logical],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, creationflags=FLAGS)
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(ready.exists(), 'Lock holder did not become ready')
            yield process
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            process.stderr.close()

    def kill(self, process):
        process.kill(); process.wait(timeout=5)

    def test_real_killed_holders_release_existing_empty_request_and_ledger_locks(self):
        path = self.root / 'ledger.json'
        original = offline.Ledger(path, 'offline-lock-test', 2, 300).read()
        with self.holder('ledger', path) as process:
            self.kill(process)
        self.assertEqual(offline.Ledger(path, 'offline-lock-test', 2, 300).read(), original)
        state = self.root / 'vectors'
        with self.holder('request', state) as process:
            self.kill(process)
        with vectors.request_locked(state, 'a' * 64):
            pass
        for lock in (path.with_suffix('.lock'), state / 'vector-intents' / ('a' * 64 + '.lock')):
            self.assertTrue(lock.exists())
            self.assertEqual(lock.read_bytes(), b'')

    def test_live_owner_cannot_be_stolen_and_existing_diagnostics_are_preserved(self):
        original = offline.exclusive_file_lock
        def bounded(path, **options):
            return original(path, timeout=.05, **options)
        path = self.root / 'ledger.json'
        with self.holder('ledger', path) as process:
            with patch.object(offline, 'exclusive_file_lock', side_effect=bounded):
                with self.assertRaisesRegex(offline.Deferred, 'budget_lock_unavailable'):
                    offline.Ledger(path, 'offline-lock-test', 2, 300)
            self.assertIsNone(process.poll())
        with self.holder('request', self.root) as process:
            with patch.object(vectors, 'exclusive_file_lock', side_effect=bounded):
                with self.assertRaisesRegex(offline.Deferred, 'vector_request_lock_unavailable'):
                    with vectors.request_locked(self.root, 'a' * 64):
                        self.fail('A live owner lost exclusion')
            self.assertIsNone(process.poll())

    def test_copied_checkpoint_empty_lock_files_do_not_claim_foreign_host_ownership(self):
        source = self.root / 'source'; source.mkdir()
        path = source / 'ledger.json'
        book = offline.Ledger(path, 'offline-lock-test', 2, 300)
        book.reserve('voyage', vectors.MODEL, 'known-unknown', 'old-request', 15, 1)
        with self.holder('ledger', path) as process:
            self.kill(process)
        with self.holder('request', source) as process:
            self.kill(process)
        restored = self.root / 'restored'; shutil.copytree(source, restored)
        self.assertEqual(offline.Ledger(restored / 'ledger.json', 'offline-lock-test', 2, 300).read(), book.read())
        with vectors.request_locked(restored, 'a' * 64):
            pass

    def test_threads_keep_atomic_request_cap(self):
        book = offline.Ledger(self.root / 'threads.json', 'threads', 2, 5)
        def reserve(index):
            try:
                book.reserve('voyage', vectors.MODEL, 'concurrent', str(index), 200_000, 1)
                return True
            except offline.Deferred:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(reserve, range(24)))
        self.assertEqual(sum(results), 5)
        self.assertEqual(len(book.read()['requests']), 5)
        self.assertEqual(sum(row['charged_microusd'] for row in book.read()['requests']), 1_000_000)

    def test_processes_keep_atomic_spend_cap(self):
        path = self.root / 'processes.json'
        book = offline.Ledger(path, 'processes', 2, 300)
        code = '''
import sys
from tools.offline_spend import Ledger,Deferred
try:
    Ledger(sys.argv[1],'processes',2,300).reserve('voyage','voyage-4-lite','concurrent',sys.argv[2],700000,1)
    print('reserved')
except Deferred:
    print('held')
'''
        children = [subprocess.Popen([sys.executable, '-c', code, str(path), str(index)], cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=FLAGS) for index in range(6)]
        try:
            results = []
            for process in children:
                output, error = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, error)
                results.append(output.strip())
        finally:
            for process in children:
                if process.poll() is None:
                    process.kill(); process.wait(timeout=5)
        self.assertEqual(results.count('reserved'), 2)
        self.assertEqual(len(book.read()['requests']), 2)
        self.assertEqual(sum(row['charged_microusd'] for row in book.read()['requests']), 1_400_000)

    def vector_fixture(self):
        fixture = fixtures.ReconcileSpendTests('runTest')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        return fixture

    def test_accepted_cache_after_killed_ledger_owner_recovers_without_another_request(self):
        fixture = self.vector_fixture()
        reserved = vectors.reserve(fixture.state, fixture.packet())
        with patch.object(vectors, 'complete_saved', side_effect=RuntimeError('interrupted accepted response')):
            with self.assertRaises(RuntimeError):
                vectors.finish(fixture.state, fixture.finish_packet(reserved))
        before = deepcopy(fixture.book.read())
        with self.holder('ledger', fixture.book.path, 'offline-123') as process:
            self.kill(process)
        result = vectors.reserve(fixture.state, fixture.packet())
        self.assertEqual(result['status'], 'cached')
        after = fixture.book.read()
        self.assertEqual(len(after['requests']), len(before['requests']))
        self.assertEqual(after['requests'][:-1], before['requests'][:-1])
        self.assertEqual((after['requests'][-1]['status'], after['requests'][-1]['charged_microusd']), ('valid', 2))

    def test_unknown_dispatch_without_cache_stays_charged_after_killed_request_owner(self):
        fixture = self.vector_fixture()
        reserved = vectors.reserve(fixture.state, fixture.packet())
        before = deepcopy(fixture.book.read())
        lock = fixture.state / 'vector-intents' / (reserved['key'] + '.lock')
        with self.holder('raw', lock) as process:
            self.kill(process)
        with self.assertRaisesRegex(ValueError, 'previous_dispatch_unknown_no_retry'):
            vectors.reserve(fixture.state, fixture.packet())
        self.assertEqual(fixture.book.read(), before)

    def test_finish_can_persist_real_response_after_killed_request_mutex(self):
        fixture = self.vector_fixture()
        reserved = vectors.reserve(fixture.state, fixture.packet())
        lock = fixture.state / 'vector-intents' / (reserved['key'] + '.lock')
        with self.holder('raw', lock) as process:
            self.kill(process)
        vectors.finish(fixture.state, fixture.finish_packet(reserved))
        self.assertEqual(vectors.reserve(fixture.state, fixture.packet())['status'], 'cached')
        self.assertEqual(len(fixture.book.read()['requests']), 3)


if __name__ == '__main__':
    unittest.main()
