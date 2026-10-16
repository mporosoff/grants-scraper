"""One downloaded original ledger can seed only its exact no-spend recovery."""
from contextlib import ExitStack
from copy import deepcopy
import io
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from tools import generation_spend_recovery as recovery
from tools import generation_spend_checkpoint as spending


class DownloadedSpendRecovery(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.seed = self.root / 'seed'
        shutil.copytree(recovery.CONFIG.parent, self.seed)
        self.stack.enter_context(patch.object(recovery, 'CONFIG', self.seed / 'manifest.json'))
        self.destination = self.root / ('offline-' + recovery.RUN)
        self.current = {'id': int(recovery.RUN), 'run_attempt': 4, 'head_sha': recovery.EVENT_SHA,
                        'path': recovery.WORKFLOW, 'head_branch': 'main', 'event': 'schedule', 'status': 'in_progress'}
        self.original = self.current | {'run_attempt': 1, 'status': 'completed', 'conclusion': 'failure'}
        self.second = self.original | {'run_attempt': 2}
        self.third = self.original | {'run_attempt': 3}
        self.original_job = {'id': recovery.ORIGINAL_JOB, 'run_id': int(recovery.RUN), 'run_attempt': 1,
                             'head_sha': recovery.EVENT_SHA, 'name': 'generate',
                             'status': 'completed', 'conclusion': 'failure'}
        names = {5: recovery.RESTORE_STEP, 6: recovery.RESERVE_STEP,
                 16: recovery.PROVIDER_STEPS[0], 21: recovery.PROVIDER_STEPS[1],
                 28: recovery.PROVIDER_STEPS[2]}
        successful = {1, 2, 3, 4, 14, 22, 34, 69, 70, 71}
        steps = [{'name': names.get(number, f'Historical generate step {number}'), 'number': number,
                  'conclusion': 'success' if number in successful else 'failure' if number == 5 else 'skipped'}
                 for number in (*range(1, 36), 69, 70, 71)]
        self.jobs = [{'id': recovery.NO_SPEND_JOBS[2], 'name': 'generate', 'status': 'completed',
                      'conclusion': 'failure', 'steps': steps}]
        self.jobs.extend({'name': name, 'status': 'completed', 'conclusion': 'success' if name == 'plan' else 'failure'
                         if name == 'closeout' else 'skipped'} for name in (
            'plan', 'assemble', 'catalog-correction', 'program-area-revalidation',
            'catalog-source-recovery', 'catalog-access-correction', 'catalog-identity-correction',
            'catalog-url-correction', 'candidate', 'validate', 'publish', 'pages', 'verify-live', 'closeout'))
        self.third_jobs = deepcopy(self.jobs)
        self.third_jobs[0]['id'] = recovery.NO_SPEND_JOBS[3]
        self.log = '\n'.join('\n'.join((
            '2026-10-15 SHA256 digest of uploaded artifact zip is ' + artifact['zip_sha256'],
            '2026-10-15 Finalizing artifact upload',
            f'2026-10-15 Artifact {artifact["name"]}.zip successfully finalized. Artifact ID {artifact["id"]}'))
            for artifact in recovery.ARTIFACTS.values()).encode()
        self.artifacts = [{'id': 100, 'name': 'release-plan-3', 'expired': False},
                          {'id': 101, 'name': 'release-plan-4', 'expired': False}]
        self.api = Mock(side_effect=self.response)
        self.log_reader = Mock(side_effect=lambda job_id: self.log)

    def response(self, path):
        values = {f'actions/runs/{recovery.RUN}/attempts/1': self.original,
                  f'actions/runs/{recovery.RUN}/attempts/2': self.second,
                  f'actions/runs/{recovery.RUN}/attempts/3': self.third,
                  f'actions/jobs/{recovery.ORIGINAL_JOB}': self.original_job,
                  f'actions/runs/{recovery.RUN}/attempts/2/jobs?per_page=100&page=1':
                      {'total_count': len(self.jobs), 'jobs': self.jobs},
                  f'actions/runs/{recovery.RUN}/attempts/3/jobs?per_page=100&page=1':
                      {'total_count': len(self.third_jobs), 'jobs': self.third_jobs},
                  f'actions/runs/{recovery.RUN}/artifacts?per_page=100&page=1':
                      {'total_count': len(self.artifacts), 'artifacts': self.artifacts},
                  'actions/artifacts?per_page=100&page=1': {'total_count': 0, 'artifacts': []}}
        if path == f'actions/jobs/{recovery.ORIGINAL_JOB}/logs':
            return self.log
        return json.dumps(values[path]).encode()

    def restore(self, **changes):
        arguments = {'repository': recovery.REPOSITORY, 'run': recovery.RUN, 'attempt': '4',
                     'destination': self.destination, 'mode': 'maintenance', 'meta': self.current,
                     'artifacts': self.artifacts, 'api': self.api, 'log_reader': self.log_reader}
        return recovery.restore(**(arguments | changes))

    def test_exact_original_bytes_and_unknown_charge_survive_without_a_new_allowance(self):
        self.assertTrue(self.restore())
        original = self.seed / 'state'
        files = [path for path in original.rglob('*') if path.is_file()]
        self.assertEqual(len(files), 44)
        for path in files:
            self.assertEqual((self.destination / path.relative_to(original)).read_bytes(), path.read_bytes())
        ledger = json.loads((self.destination / 'ledger.json').read_bytes())
        self.assertEqual((ledger['limit_microusd'], ledger['max_requests'], len(ledger['requests'])), (2_000_000, 300, 44))
        self.assertEqual(sum(row['charged_microusd'] for row in ledger['requests']), 279679)
        unknown = [row for row in ledger['requests'] if row['status'] == 'reserved_unknown']
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]['charged_microusd'], unknown[0]['reserved_microusd'])
        self.assertIsNone(unknown[0]['usage'])
        provenance = json.loads((self.destination / 'recovery-provenance.json').read_bytes())
        self.assertFalse(provenance['archive_reauthenticated'])
        self.assertFalse(provenance['candidate_or_validation_evidence'])
        self.assertEqual(provenance['additional_allowance_microusd'], 0)
        self.assertEqual(provenance['recovery_attempt'], '4')
        self.log_reader.assert_called_once_with(recovery.ORIGINAL_JOB)

    def test_attempt_extension_keeps_every_original_payload_hash_unchanged(self):
        plan, packets = recovery.payloads()
        fingerprints = {name: hashlib.sha256(raw).hexdigest() for name, raw in packets.items()}
        self.assertEqual(fingerprints, plan['files'])
        self.assertEqual(len(fingerprints), 44)
        self.assertEqual(hashlib.sha256(json.dumps(fingerprints, sort_keys=True,
            separators=(',', ':')).encode()).hexdigest(),
            '94f8c75f0ed9f1e805cc3ec8dd9db5526d7f729748d2cc2d5f64e05e1e400e2d')
        self.assertEqual(plan['ledger_sha256'],
            '0b822bd3bd8b143fdb823db59337c8380807ad82303554458d256e8bce1ce05d')
        self.assertEqual(plan['allowed_attempt'], '4')

    def test_every_other_run_or_attempt_keeps_the_missing_checkpoint_hold(self):
        for run, attempt in ((recovery.RUN, '2'), (recovery.RUN, '3'), (recovery.RUN, '5'), ('123', '4')):
            with self.subTest(run=run, attempt=attempt):
                self.assertFalse(self.restore(run=run, attempt=attempt))
        self.assertFalse(self.destination.exists())
        self.api.assert_not_called()
        self.log_reader.assert_not_called()

    def test_foreign_repository_modes_pilot_or_current_attempt_fail_before_install(self):
        cases = ({'repository': 'foreign/repository'}, {'mode': 'backfill'}, {'qualification_pilot': True},
                 {'meta': self.current | {'head_sha': 'a' * 40}},
                 {'meta': self.current | {'run_attempt': 5}})
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.restore(**changes)
        self.assertFalse(self.destination.exists())

    def test_manifest_or_any_raw_member_tampering_is_rejected_before_writes(self):
        manifest_path = self.seed / 'manifest.json'
        raw_manifest = manifest_path.read_bytes()
        manifest_path.write_bytes(raw_manifest + b'\n')
        with self.assertRaisesRegex(ValueError, 'protected manifest hash'):
            self.restore()
        manifest_path.write_bytes(raw_manifest)
        cached = next((self.seed / 'state/cov4-cache').glob('*.json'))
        cached.write_bytes(cached.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'member bytes'):
            self.restore()
        self.assertFalse(self.destination.exists())
        self.api.assert_not_called()

    def test_historical_artifact_context_must_match_exact_ids_and_digest(self):
        self.log = self.log.replace(recovery.ARTIFACTS['state']['zip_sha256'].encode(), b'0' * 64)
        with self.assertRaisesRegex(ValueError, 'historical upload digest'):
            self.restore()
        self.assertFalse(self.destination.exists())

    def test_unrelated_original_job_cannot_authenticate_the_download(self):
        self.original_job['run_attempt'] = 2
        with self.assertRaisesRegex(ValueError, 'original generate job'):
            self.restore()
        self.assertFalse(self.destination.exists())
        self.log_reader.assert_not_called()

    def test_later_attempt_with_reservation_or_provider_work_cannot_roll_back(self):
        generate = self.jobs[0]
        for name in (recovery.RESTORE_STEP, recovery.RESERVE_STEP, *recovery.PROVIDER_STEPS):
            with self.subTest(step=name):
                before = deepcopy(generate['steps'])
                next(step for step in generate['steps'] if step['name'] == name)['conclusion'] = 'success'
                with self.assertRaisesRegex(ValueError, 'later attempt reserved or dispatched'):
                    self.restore()
                generate['steps'] = before
        self.assertFalse(self.destination.exists())

    def test_ambiguous_or_incomplete_attempt_history_and_other_producers_are_rejected(self):
        self.jobs.append({'name': 'unknown producer', 'conclusion': 'success'})
        with self.assertRaisesRegex(ValueError, 'complete no-spend attempt'):
            self.restore()
        self.jobs.pop()
        next(job for job in self.jobs if job['name'] == 'assemble')['conclusion'] = 'success'
        with self.assertRaisesRegex(ValueError, 'another lifecycle job'):
            self.restore()
        self.assertFalse(self.destination.exists())

    def test_third_attempt_reservation_dispatch_or_incomplete_steps_cannot_roll_back(self):
        for name in (recovery.RESTORE_STEP, recovery.RESERVE_STEP, *recovery.PROVIDER_STEPS):
            with self.subTest(step=name):
                steps = self.third_jobs[0]['steps']
                original = deepcopy(steps)
                next(step for step in steps if step['name'] == name)['conclusion'] = 'success'
                with self.assertRaisesRegex(ValueError, 'later attempt reserved or dispatched'):
                    self.restore()
                self.third_jobs[0]['steps'] = original
        self.third_jobs[0]['steps'].pop()
        with self.assertRaisesRegex(ValueError, 'complete no-spend generate steps'):
            self.restore()
        self.assertFalse(self.destination.exists())
        self.log_reader.assert_not_called()

    def test_third_attempt_missing_job_incorrect_identity_or_pending_job_is_rejected(self):
        original = deepcopy(self.third_jobs)
        changes = ('missing', 'wrong_job_id', 'pending', 'duplicate_step')
        for change in changes:
            with self.subTest(change=change):
                self.third_jobs = deepcopy(original)
                if change == 'missing':
                    self.third_jobs.pop()
                elif change == 'wrong_job_id':
                    self.third_jobs[0]['id'] += 1
                elif change == 'pending':
                    self.third_jobs[-1]['status'] = 'in_progress'
                else:
                    self.third_jobs[0]['steps'].append(self.third_jobs[0]['steps'][0])
                with self.assertRaises(ValueError):
                    self.restore()
                self.assertFalse(self.destination.exists())
        self.log_reader.assert_not_called()

    def test_new_artifact_during_history_authentication_prevents_seed_installation(self):
        original_read = self.response
        def changed(path):
            if path == f'actions/runs/{recovery.RUN}/artifacts?per_page=100&page=1':
                rows = self.artifacts + [{'id': 102, 'name': 'generation-spend-reservation-' + recovery.RUN + '-4'}]
                return json.dumps({'artifacts': rows, 'total_count': len(rows)}).encode()
            return original_read(path)
        self.api.side_effect = changed
        with self.assertRaisesRegex(ValueError, 'artifact inventory changed'):
            self.restore()
        self.assertFalse(self.destination.exists())

    def test_existing_state_and_new_retained_evidence_are_never_overwritten(self):
        self.destination.mkdir()
        retained = self.destination / 'ledger.json'
        retained.write_bytes(b'existing later state')
        with self.assertRaisesRegex(ValueError, 'empty original state destination'):
            self.restore()
        self.assertEqual(retained.read_bytes(), b'existing later state')
        with self.assertRaisesRegex(ValueError, 'unexpected retained generation evidence'):
            self.restore(artifacts=[{'name': 'candidate-' + 'a' * 64}])

    def test_staging_failure_leaves_no_partial_financial_state(self):
        original = Path.write_bytes
        def fail(path, raw):
            if path.name != 'ledger.json':
                raise OSError('disk unavailable')
            return original(path, raw)
        with patch.object(Path, 'write_bytes', fail), self.assertRaisesRegex(OSError, 'disk unavailable'):
            self.restore()
        self.assertFalse(self.destination.exists())

    def test_checkpoint_preparation_uses_exact_recovered_ledger_for_next_reservation(self):
        def api(_repo, path):
            if path == 'actions/runs/' + recovery.RUN:
                return json.dumps(self.current).encode()
            if '/artifacts?' in path:
                return json.dumps({'artifacts': self.artifacts}).encode()
            return self.response(path)
        reservation = self.root / 'reservation.json'
        with patch.object(spending, 'api', side_effect=api), \
                patch.object(spending, 'read_job_log', return_value=self.log) as read_log:
            spending.prepare(recovery.REPOSITORY, recovery.RUN, '4', self.destination, reservation, 'maintenance')
        read_log.assert_called_once_with(recovery.REPOSITORY, recovery.ORIGINAL_JOB)
        self.assertEqual((self.destination / 'ledger.json').read_bytes(), (self.seed / 'state/ledger.json').read_bytes())
        value = json.loads(reservation.read_bytes())
        self.assertEqual(value['maximum_logical_spend_usd'], 2)
        self.assertEqual(value['prior_ledger_hash'], spending.identity(json.loads((self.destination / 'ledger.json').read_bytes())))

    def test_native_latest_state_takes_precedence_over_the_fixed_seed(self):
        ledger = json.loads((self.seed / 'state/ledger.json').read_bytes())
        ledger['events'].append({'kind': 'later authentic native checkpoint'})
        native = json.dumps(ledger).encode()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('ledger.json', native)
        artifacts = [{'id': 1, 'name': 'generation-spend-reservation-' + recovery.RUN + '-2'},
                     {'id': 2, 'name': 'generation-spend-state-' + recovery.RUN + '-2', 'expired': False}]
        def api(_repo, path):
            if path.endswith('/zip'):
                return stream.getvalue()
            return json.dumps({'artifacts': artifacts} if '/artifacts?' in path else self.current).encode()
        with patch.object(spending, 'api', side_effect=api), patch.object(recovery, 'restore') as fallback:
            spending.prepare(recovery.REPOSITORY, recovery.RUN, '4', self.destination, self.root / 'reservation.json', 'maintenance')
        fallback.assert_not_called()
        self.assertEqual((self.destination / 'ledger.json').read_bytes(), native)


if __name__ == '__main__':
    unittest.main()
