"""Real failed-source prefix, durable retry accounting, and lock-safe handoff."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import yaml

from tools import generation_source_retry as retry, release_candidate as c, scheduled_catalog
from tools.offline_ai import identity

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'tests/fixtures/generation-source-transport-stop.json').read_text(encoding='utf-8'))
EVENT, GENERATION, MAIN = 'a' * 40, 'b' * 40, 'c' * 40
ENV = {'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_RUN_ID': '500', 'GITHUB_RUN_ATTEMPT': '1'}


def zip_bytes(members):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for name, value in members.items():
            archive.writestr(name, value if isinstance(value, bytes) else json.dumps(value).encode())
    return output.getvalue()


class SourceRetry(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.workflow = yaml.safe_load((ROOT / retry.WORKFLOW).read_text(encoding='utf-8'))
        self.run = {'id': 200, 'run_attempt': 1, 'head_sha': EVENT, 'head_branch': 'main',
                    'path': retry.WORKFLOW, 'event': 'schedule', 'status': 'completed', 'conclusion': 'failure'}
        self.jobs = deepcopy(FIXTURE['jobs'])
        for row in self.jobs:
            row.update(run_id=200, run_attempt=1, head_sha=EVENT)
        self.ledger = {'version': 1, 'logical_id': 'offline-200', 'limit_microusd': 2_000_000,
                       'max_requests': 300, 'requests': [], 'events': [], 'blocked_providers': {}}
        self.reservation = {'run_id': '200', 'attempt': '1', 'mode': 'maintenance',
                            'maximum_logical_spend_usd': 2, 'prior_ledger_hash': identity(self.ledger)}
        self.plan = {'stage': 'generate', 'team_mode': 'maintenance', 'release_sha': GENERATION}
        self.raw = {}
        self.artifacts = []
        self.add_artifact('release-plan-1', {'release-plan.json': self.plan})
        self.add_artifact('generation-spend-reservation-200-1', {'spend-reservation.json': self.reservation})
        self.add_artifact('generation-spend-state-200-1', {'ledger.json': self.ledger, 'ledger.lock': b''})
        self.add_artifact('sam-preflight-200-1', {'sam-preflight.json': {}})
        self.log = FIXTURE['log'].encode()
        self.groups = {group: {'fingerprint': group, 'files': {}} for group in ('source', 'teams', 'semantic')}
        patcher = patch.object(retry, 'run_artifacts', side_effect=lambda *a, **k: deepcopy(self.artifacts))
        patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(retry, 'snapshot', return_value=self.groups)
        patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(c, 'git', side_effect=self.git)
        patcher.start(); self.addCleanup(patcher.stop)

    def git(self, root, *args):
        if args == ('rev-parse', 'HEAD'):
            return MAIN
        if args[0] == 'merge-base':
            return ''
        if args[0] == 'show':
            path = args[1].split(':', 1)[1]
            return (ROOT / path).read_text(encoding='utf-8')
        raise AssertionError(args)

    def add_artifact(self, name, members, run=200):
        identifier = len(self.raw) + 100
        raw = zip_bytes(members)
        self.raw[identifier] = raw
        row = {'id': identifier, 'name': name, 'digest': 'sha256:' + c.digest(raw),
               'expired': False, 'workflow_run': {'id': run}}
        self.artifacts.append(row)
        return row

    def replace_packet(self, name, members):
        row = next(a for a in self.artifacts if a['name'] == name)
        self.raw[row['id']] = zip_bytes(members)
        row['digest'] = 'sha256:' + c.digest(self.raw[row['id']])

    def read(self, path):
        if path == 'actions/runs/200' or path == 'actions/runs/200/attempts/1':
            value = self.run
        elif path == 'git/ref/heads/main':
            value = {'object': {'sha': MAIN}}
        elif path == 'actions/runs/200/attempts/1/jobs?per_page=100&page=1':
            value = {'total_count': len(self.jobs), 'jobs': self.jobs}
        elif path.startswith('actions/artifacts/') and path.endswith('/zip'):
            return self.raw[int(path.split('/')[2])]
        elif path == 'actions/workflows/recover-generation.yml/runs?branch=main&per_page=100&page=1':
            value = {'total_count': 0, 'workflow_runs': []}
        else:
            raise AssertionError(path)
        return json.dumps(value).encode()

    def qualify(self):
        return retry.qualify(ROOT, 'owner/repo', '200', read=self.read, log_reader=lambda _: self.log)

    def test_real_incident_admits_only_zero_provider_original_owner(self):
        value = self.qualify()
        self.assertEqual((value['owner_run'], value['owner_attempt'], value['job_id']), ('200', 1, 135808973833))
        self.assertEqual(value['provider_requests'], 0)
        self.assertFalse(value['source_completed'])
        self.assertEqual(value['attempts'][0]['ledger_sha256'], self.reservation['prior_ledger_hash'])

    def test_any_provider_usage_event_extra_state_or_budget_reset_holds(self):
        original = deepcopy(self.ledger)
        for change in ({'requests': [{'status': 'reserved_unknown'}]}, {'events': [{'provider': 'voyage'}]},
                       {'limit_microusd': 3_000_000}, {'logical_id': 'offline-new'}, {'hidden_requests': []}):
            with self.subTest(change=change):
                self.ledger = original | change
                self.replace_packet('generation-spend-state-200-1', {'ledger.json': self.ledger})
                with self.assertRaises(ValueError):
                    self.qualify()
        self.ledger = original
        self.replace_packet('generation-spend-state-200-1', {'ledger.json': original, 'cov4-cache/complete.json': b'{}'})
        with self.assertRaisesRegex(ValueError, 'completed generation'):
            self.qualify()

    def test_completed_source_tail_or_candidate_cannot_be_retried(self):
        job = next(row for row in self.jobs if row['name'] == 'generate')
        for name in ('Enrich new or changed records with official detail evidence',
                     'Extract citation-backed facts from official notices', 'Build compatible production document vectors'):
            step = next(s for s in job['steps'] if s['name'] == name)
            step['conclusion'] = 'success'
            with self.assertRaisesRegex(ValueError, 'already ran'):
                self.qualify()
            step['conclusion'] = 'skipped'
        self.add_artifact('candidate-' + 'd' * 64, {'candidate.json': {}})
        with self.assertRaisesRegex(ValueError, 'candidate/source output'):
            self.qualify()

    def test_content_errors_or_untrusted_markers_never_authorize_retry(self):
        original = self.log
        self.log = original.replace(b'requests.exceptions.SSLError:', b'ValueError:')
        with self.assertRaisesRegex(ValueError, 'observed Grants.gov'):
            self.qualify()
        marker = {'version': 1, 'operation': 'extract-archive', 'host': 'grants.gov', 'kind': 'tls',
                  'attempts': 3, 'certificate_verification': True, 'source_complete': False, 'retry_safe': True}
        for change in ({}, {'certificate_verification': False}, {'retry_safe': False}, {'source_complete': True},
                       {'host': 'attacker.example'}, {'kind': 'parser'}, {'attempts': True}):
            self.log = original.replace(b'Traceback (most recent call last):',
                ('GRANTS_SOURCE_TRANSPORT_FAILURE ' + json.dumps(marker | change)).encode(), 1)
            if change:
                with self.assertRaises(ValueError):
                    self.qualify()
            else:
                self.qualify()
        self.log = original.replace(b'Traceback (most recent call last):',
            ('GRANTS_SOURCE_TRANSPORT_FAILURE ' + json.dumps(marker | {'host': 'prod-grants-gov-chatbot.s3.amazonaws.com'})).encode(), 1)
        self.qualify()
        self.log = self.log.replace(b'"operation": "extract-archive"', b'"operation": "extract-index"')
        with self.assertRaises(ValueError):
            self.qualify()

    def test_running_owner_missing_steps_or_corrupt_artifacts_hold(self):
        self.run['status'] = 'in_progress'
        with self.assertRaisesRegex(ValueError, 'completed failed'):
            self.qualify()
        self.run['status'] = 'completed'
        job = next(row for row in self.jobs if row['name'] == 'generate')
        removed = job['steps'].pop(15)
        with self.assertRaisesRegex(ValueError, 'missing source/provider'):
            self.qualify()
        job['steps'].insert(15, removed)
        row = self.artifacts[0]
        self.raw[row['id']] += b'corrupt'
        with self.assertRaisesRegex(ValueError, 'digest'):
            self.qualify()

    def test_source_or_job_contract_change_blocks_old_generator(self):
        changed = deepcopy(self.groups)
        changed['source']['fingerprint'] = 'changed'
        with patch.object(retry, 'snapshot', side_effect=[self.groups, changed]):
            with self.assertRaisesRegex(ValueError, 'generation inputs changed'):
                self.qualify()

    def test_queue_is_read_only_bounded_and_never_reports_freshness(self):
        proof = self.qualify()
        with patch.object(retry, 'qualify', return_value=proof), patch.object(retry, 'request_history', return_value=[]) as history:
            value = retry.queue(ROOT, ENV, '200', read=self.read)
            self.assertEqual(value['stage'], 'queued-recovery')
            self.assertNotIn('catalog_generated_at', value)
            self.assertNotIn('verified_live', value)
            history.assert_called_once()
        for records in ([{'owner_attempt': 1}], [{'owner_attempt': 1}, {'owner_attempt': 2}]):
            with patch.object(retry, 'qualify', return_value=proof), patch.object(retry, 'request_history', return_value=records):
                with self.assertRaises(ValueError):
                    retry.queue(ROOT, ENV, '200', read=self.read)

    def test_only_typed_hold_queues_and_queue_stage_starts_no_release_producer(self):
        manifest = {'generation_run_id': '100'}
        manifest['candidate_id'] = c.digest(c.encoded(manifest))
        c.write_json(self.work / 'release/candidate.json', manifest)
        environment = ENV | {'GITHUB_EVENT_NAME': 'schedule'}
        queued = {'stage': 'queued-recovery', 'daily_status': 'recovering', 'recovery_run': '200'}
        with patch.object(scheduled_catalog, 'prior_generation', side_effect=scheduled_catalog.PreCandidateSourceHold('reserved', '200')):
            with patch.object(retry, 'queue', return_value=queued) as queue:
                result = scheduled_catalog.resolve(self.work, environment, {'stage': 'generate'}, self.work / 'reports')
                self.assertEqual(result['stage'], 'queued-recovery')
                self.assertEqual(result['catalog_generated_at'], '')
                queue.assert_called_once()
        with patch.object(scheduled_catalog, 'prior_generation', side_effect=scheduled_catalog.Hold('untrusted', '200')):
            with patch.object(retry, 'queue') as queue:
                result = scheduled_catalog.resolve(self.work, environment, {'stage': 'generate'}, self.work / 'reports')
                self.assertEqual(result['stage'], 'noop')
                queue.assert_not_called()
        for name, job in self.workflow['jobs'].items():
            if name not in ('plan', 'closeout'):
                self.assertNotIn('queued-recovery', job.get('if', ''), name)
        closeout = self.workflow['jobs']['closeout']['steps'][0]['with']['script']
        self.assertIn("planned === 'queued-recovery' ? 'queued_recovery'", closeout)
        self.assertIn('live recovery is still pending', closeout)

    def test_executor_reruns_cannot_ignore_unknown_prior_attempt_request(self):
        row = {'id': 500, 'run_attempt': 2, 'head_sha': MAIN, 'head_branch': 'main', 'path': retry.RECOVERY,
               'event': 'workflow_run', 'status': 'completed', 'conclusion': 'failure'}
        read = lambda _: json.dumps({'total_count': 1, 'workflow_runs': [row]}).encode()
        with self.assertRaisesRegex(ValueError, 'executor was rerun'):
            retry.request_history('owner/repo', '200', read=read, current_run='500')
        bad = ENV | {'GITHUB_RUN_ATTEMPT': '2'}
        for call in (lambda: retry.prepare(ROOT, bad, '300', '1', self.work),
                     lambda: retry.dispatch(ROOT, bad, self.work)):
            with self.assertRaisesRegex(ValueError, 'executor reruns'):
                call()

    def test_request_history_authenticates_timeout_reservation_and_rejects_missing_pair(self):
        proof = self.qualify()
        run = {'id': 400, 'run_attempt': 1, 'head_sha': MAIN, 'head_branch': 'main', 'path': retry.RECOVERY,
               'event': 'workflow_run', 'status': 'completed', 'conclusion': 'failure'}
        intent = {'executor_run': '400', 'executor_attempt': 1, 'proof': {'owner_run': '200', 'owner_attempt': 1}}
        raw_intent = json.dumps(intent).encode()
        request = {'owner_run': '200', 'owner_attempt': 1, 'intent_sha256': c.digest(raw_intent), 'retry_number': 1}
        rows = [self.add_artifact(retry.PREFIX + 'intent-400-1', {'intent.json': raw_intent}, run=400),
                self.add_artifact(retry.PREFIX + 'request-400-1', {'request.json': request}, run=400)]
        def read(path):
            if path.startswith('actions/workflows/'):
                return json.dumps({'total_count': 1, 'workflow_runs': [run]}).encode()
            if path == 'actions/runs/400/artifacts?per_page=100&page=1':
                return json.dumps({'total_count': len(rows), 'artifacts': rows}).encode()
            if path == 'actions/runs/400/attempts/1/jobs?per_page=100&page=1':
                return json.dumps({'total_count': 1, 'jobs': [{'steps': [{'name': retry.DISPATCH_STEP, 'conclusion': 'failure'}]}]}).encode()
            return self.read(path)
        self.assertEqual(retry.request_history('owner/repo', '200', read=read), [request])
        with patch.object(retry, 'qualify', return_value=proof):
            with self.assertRaisesRegex(ValueError, 'acknowledgement is unknown'):
                retry.queue(ROOT, ENV, '200', read=read)
        rows.pop()
        with self.assertRaisesRegex(ValueError, 'unpaired'):
            retry.request_history('owner/repo', '200', read=read)

    def test_dispatch_requires_both_uploaded_bytes_rechecks_owner_and_posts_once(self):
        proof = self.qualify()
        intent = {'executor_run': '500', 'executor_attempt': 1, 'caller_run': '300', 'caller_attempt': 1,
                  'retry_number': 1, 'proof': proof}
        c.write_json(self.work / 'intent.json', intent)
        retry.arm(self.work)
        rows = []
        for kind in ('intent', 'request'):
            rows.append(self.add_artifact(f'{retry.PREFIX}{kind}-500-1',
                        {kind + '.json': (self.work / (kind + '.json')).read_bytes()}, run=500))
        read = lambda path: json.dumps({'total_count': len(rows), 'artifacts': rows}).encode() if path.endswith('page=1') else self.read(path)
        post = Mock(side_effect=TimeoutError('acknowledgement lost'))
        with patch.object(retry, 'prepare', return_value=intent):
            with self.assertRaises(TimeoutError):
                retry.dispatch(ROOT, ENV, self.work, read=read, post=post)
        post.assert_called_once_with('owner/repo', proof['job_id'])
        outcome = json.loads((self.work / 'outcome.json').read_bytes())
        self.assertEqual(outcome['status'], 'acknowledgement_unknown')
        self.assertFalse(outcome['verified_live'])
        rows.pop()
        with patch.object(retry, 'prepare', return_value=intent), self.assertRaisesRegex(ValueError, 'missing/ambiguous'):
            retry.dispatch(ROOT, ENV, self.work, read=read, post=post)
        post.assert_called_once()

    def test_separate_workflow_cannot_hold_release_lock_or_collect_sources(self):
        workflow = yaml.safe_load((ROOT / retry.RECOVERY).read_text(encoding='utf-8'))
        self.assertNotEqual(workflow['concurrency']['group'], self.workflow['concurrency']['group'])
        self.assertEqual(workflow[True]['workflow_run']['types'], ['completed'])
        steps = workflow['jobs']['recover']['steps']
        names = [s.get('name') for s in steps]
        self.assertLess(names.index('Persist retry intent'), names.index('Persist retry request'))
        self.assertLess(names.index('Persist retry request'), names.index(retry.DISPATCH_STEP))
        self.assertNotIn('secrets.', json.dumps(workflow))
        self.assertNotIn('scripts.build_catalog', json.dumps(workflow))


if __name__ == '__main__':
    unittest.main()
