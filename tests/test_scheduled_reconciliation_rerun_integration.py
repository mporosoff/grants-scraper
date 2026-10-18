"""Published reconciliation retries through the public scheduled-history reader."""
from contextlib import ExitStack
from copy import deepcopy
import io
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch
import zipfile

import yaml

from tools import release_candidate as c
from tools import scheduled_catalog as scheduled
from tools.offline_spend import identity


class PublishedReconciliationHistory(unittest.TestCase):
    REPOSITORY = 'owner/repo'
    HEAD = 'b' * 40
    ASSEMBLY = 'e' * 40
    PARENT = 'a' * 64

    @classmethod
    def setUpClass(cls):
        repository = Path(__file__).resolve().parents[1]
        cls.workflow = (repository / scheduled.WORKFLOW).read_text(encoding='utf-8')
        cls.pages = (repository / '.github/workflows/pages.yml').read_text(encoding='utf-8')
        cls.job_names = sorted(yaml.safe_load(cls.workflow)['jobs'])
        cls.restore_steps = yaml.safe_load(cls.workflow)['jobs']['catalog-reconcile']['steps']

    def setUp(self):
        self.root = Path('protected-fixture')
        self.api_calls = []
        self.artifacts = {}
        self.payloads = {}
        self.metadata = {}
        self.job_rows = {}
        self.next_artifact = 10
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(c, 'ROOT', self.root))
        self.stack.enter_context(patch.object(c, 'git', side_effect=self.git))
        self.stack.enter_context(patch.object(scheduled, 'api', side_effect=self.api))
        self.http = self.stack.enter_context(patch('urllib.request.OpenerDirector.open',
            side_effect=AssertionError('history selection must not call sources or providers')))
        self.provider_http = self.stack.enter_context(patch('requests.sessions.Session.request',
            side_effect=AssertionError('history selection must not call providers')))

    @staticmethod
    def packed(members):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, value in members.items():
                archive.writestr(name, value if isinstance(value, bytes) else c.encoded(value))
        return stream.getvalue()

    def meta(self, run, attempt, *, conclusion='success'):
        value = {'id': run, 'run_attempt': attempt, 'head_sha': self.HEAD, 'head_branch': 'main',
            'path': scheduled.WORKFLOW, 'event': 'workflow_dispatch', 'status': 'completed',
            'conclusion': conclusion}
        self.metadata[run, attempt] = value
        self.job_rows[run, attempt] = [{'id': run * 10000 + attempt * 100 + index,
            'name': name, 'run_id': run, 'run_attempt': attempt, 'head_sha': self.HEAD,
            'head_branch': 'main', 'status': 'completed',
            'conclusion': 'success' if name in ('plan', 'catalog-reconcile', 'candidate', 'validate',
                'publish', 'pages', 'verify-live', 'closeout') else 'skipped'}
            for index, name in enumerate(self.job_names, 1)]
        return value

    def artifact(self, run, name, members):
        raw = self.packed(members)
        row = {'id': self.next_artifact, 'name': name, 'digest': 'sha256:' + c.digest(raw), 'expired': False,
            'workflow_run': {'id': run, 'head_sha': self.HEAD, 'head_branch': 'main',
                'repository_id': 1, 'head_repository_id': 1}}
        self.next_artifact += 1
        self.artifacts.setdefault(run, []).append(row)
        self.payloads[row['id']] = raw
        return {'id': row['id'], 'name': name, 'sha256': c.digest(raw)}

    def fixture(self, *, producer_run=220, producer_attempt=2, consumed=True):
        self.producer_run, self.producer_attempt = producer_run, producer_attempt
        self.ledger = {'version': 1, 'logical_id': 'offline-100', 'limit_microusd': 2_000_000,
            'max_requests': 300, 'requests': [{'id': '1' * 32, 'provider': 'anthropic', 'model': 'prior-model',
                'stage': 'documents', 'key': '2' * 64, 'attempt': 1, 'reserved_microusd': 30,
                'charged_microusd': 25, 'status': 'complete', 'usage': None}],
            'events': [], 'blocked_providers': {}}
        self.request_identity = identity([{key: row.get(key) for key in
            ('id', 'provider', 'model', 'stage', 'key', 'attempt', 'reserved_microusd')}
            for row in self.ledger['requests']])
        self.context = {'version': 'catalog-source-reconciliation-1', 'parent_candidate_id': self.PARENT,
            'parent_run': '100', 'parent_attempt': '1', 'parent_generation_sha': 'c' * 40,
            'parent_manifest_sha256': 'd' * 64, 'operation_contract': {'reviewed-source': 'f' * 64},
            'original_spend': {'ledger_sha256': identity(self.ledger)}}
        self.context['operation_sha256'] = identity(self.context)
        links = []
        if consumed:
            self.meta(220, 1, conclusion='failure')
            family = 'offline-ai-reconcile-' + self.PARENT
            pins = {role: self.artifact(220, f'{family}-{role}-220-1',
                {'reservation.json' if role == 'reservation' else 'ledger.json': self.ledger})
                for role in ('reservation', 'state')}
            links.append({'producer': {'run_id': '220', 'run_attempt': '1', 'head_sha': self.HEAD,
                'event': 'workflow_dispatch', 'path': scheduled.WORKFLOW}, **pins,
                'ledger_sha256': identity(self.ledger), 'request_count': 1, 'charged_microusd': 25,
                'request_prefix_sha256': identity(self.ledger['requests']),
                'request_identity_prefix_sha256': self.request_identity})
        self.meta(producer_run, producer_attempt)
        receipt = self.context | {'source_slug': 'sam-gov', 'consumed_checkpoints': links,
            'ledger_sha256': identity(self.ledger), 'affected_generation': {
                'generation_run_id': str(producer_run), 'generation_run_attempt': str(producer_attempt),
                'generation_sha': self.ASSEMBLY, 'generation_timestamp': '2026-10-18T12:00:00Z'}}
        self.child = {'generation_run_id': '100', 'generation_run_attempt': '1',
            'generation_sha': self.context['parent_generation_sha'], 'assembly_sha': self.ASSEMBLY,
            'derived_from_candidate': self.PARENT, 'files': {}, 'source_reconciliation': receipt}
        self.child['candidate_id'] = c.digest(c.encoded(self.child))
        self.pointer = {'candidate_id': self.child['candidate_id'], 'artifact_run': str(producer_run)}
        self.own_marker = {'version': 'catalog-source-reconciliation-1',
            'parent_candidate_id': self.PARENT, 'operation_sha256': self.context['operation_sha256'],
            'producer_run': str(producer_run), 'producer_attempt': str(producer_attempt),
            'prior_ledger_sha256': identity(self.ledger)}
        family = 'offline-ai-reconcile-' + self.PARENT
        self.own_reservation = self.artifact(producer_run, f'{family}-reservation-{producer_run}-{producer_attempt}',
            {'reservation.json': self.own_marker})
        self.own_state = self.artifact(producer_run, f'{family}-state-{producer_run}-{producer_attempt}',
            {'ledger.json': self.ledger, 'reconciliation.json': self.context | {
                'completed_candidate_id': self.child['candidate_id']}, 'reservation.json': self.own_marker,
                'complete-candidates/' + self.child['candidate_id'] + '/candidate.json': self.child})
        self.own_candidate = self.artifact(producer_run, 'candidate-' + self.child['candidate_id'],
            {'candidate.json': self.child})

    def git(self, root, *args):
        self.assertEqual(root, self.root)
        if args[0] == 'log':
            return 'protected-publication'
        self.assertEqual(args[0], 'show')
        revision, name = args[1].split(':', 1)
        if revision == 'protected-publication':
            if name == 'release/candidate-source.json': return json.dumps(self.pointer)
            if name == 'release/candidate.json': return json.dumps(self.child)
        elif revision == self.HEAD:
            if name == scheduled.WORKFLOW: return self.workflow
            if name == '.github/workflows/pages.yml': return self.pages
        self.fail('unexpected protected Git lookup: ' + repr(args))

    def api(self, repository, path):
        self.assertEqual(repository, self.REPOSITORY); self.api_calls.append(path)
        if path.startswith('actions/workflows/refresh-opportunities.yml/runs?'):
            latest = {run: value for (run, attempt), value in sorted(self.metadata.items())}
            return json.dumps({'workflow_runs': sorted(latest.values(), key=lambda value: value['id'], reverse=True)
                + [{'id': 100}], 'total_count': len(latest) + 1})
        if path.startswith('actions/artifacts?'):
            return json.dumps({'artifacts': [], 'total_count': 0})
        match = re.fullmatch(r'actions/runs/(\d+)/artifacts\?per_page=100&page=1', path)
        if match:
            rows = self.artifacts.get(int(match[1]), [])
            return json.dumps({'artifacts': rows, 'total_count': len(rows)})
        match = re.fullmatch(r'actions/artifacts/(\d+)/zip', path)
        if match: return self.payloads[int(match[1])]
        match = re.fullmatch(r'actions/runs/(\d+)/attempts/(\d+)(?:/jobs\?per_page=100&page=1)?', path)
        if match:
            key = int(match[1]), int(match[2])
            if '/jobs?' not in path: return json.dumps(self.metadata[key])
            rows = self.job_rows[key]
            return json.dumps({'jobs': rows, 'total_count': len(rows)})
        match = re.fullmatch(r'actions/runs/(\d+)/jobs\?per_page=100&page=1', path)
        if match:
            run = int(match[1]); attempt = max(a for r, a in self.metadata if r == run)
            rows = self.job_rows[run, attempt]
            return json.dumps({'jobs': rows, 'total_count': len(rows)})
        self.fail('unexpected API lookup: ' + path)

    def select(self):
        return scheduled.prior_generation(self.root,
            {'GITHUB_REPOSITORY': self.REPOSITORY, 'GITHUB_RUN_ID': '300'}, {'generation_run_id': '100'})

    def later(self, attempt=3):
        self.meta(self.producer_run, attempt)
        self.job_rows[self.producer_run, attempt] = [row for row in self.job_rows[self.producer_run, attempt]
            if row['name'] in ('validate', 'publish', 'pages', 'verify-live', 'closeout')]
        for row in self.job_rows[self.producer_run, attempt]:
            if row['name'] == 'pages': row['name'] = 'pages / deploy'

    def completed_restore_retry(self, *, change=None):
        """A successful restore uploads state, but all source/paid steps skip."""
        attempt = self.producer_attempt + 1
        self.later(attempt)
        with zipfile.ZipFile(io.BytesIO(self.payloads[self.own_state['id']])) as archive:
            members = {name: json.loads(archive.read(name)) for name in archive.namelist()}
        members['complete-candidates/' + self.child['candidate_id'] + '/candidate.json'] = self.child
        members['consumed-checkpoints.json'] = [{
            'producer': {'run_id': str(self.producer_run), 'run_attempt': str(self.producer_attempt),
                'head_sha': self.HEAD, 'event': 'workflow_dispatch', 'path': scheduled.WORKFLOW},
            'reservation': self.own_reservation, 'state': self.own_state,
            'ledger_sha256': identity(self.ledger), 'request_count': 1, 'charged_microusd': 25,
            'request_prefix_sha256': identity(self.ledger['requests']),
            'request_identity_prefix_sha256': self.request_identity,
            'candidate': {'candidate_id': self.child['candidate_id'],
                'manifest_sha256': c.digest(c.encoded(self.child)), 'producer': {
                    'run_id': str(self.producer_run), 'run_attempt': str(self.producer_attempt),
                    'head_sha': self.HEAD, 'event': 'workflow_dispatch', 'path': scheduled.WORKFLOW},
                'artifact': self.own_candidate}}]
        if change: change(members)
        family = 'offline-ai-reconcile-' + self.PARENT
        self.restore_state = self.artifact(self.producer_run,
            f'{family}-state-{self.producer_run}-{attempt}', members)
        steps = self.completed_restore_steps()
        self.job_rows[self.producer_run, attempt].append({'id': self.producer_run * 10000 + attempt * 100 + 90,
            'name': 'catalog-reconcile', 'run_id': self.producer_run, 'run_attempt': attempt,
            'head_sha': self.HEAD, 'head_branch': 'main', 'status': 'completed',
            'conclusion': 'success', 'steps': steps})

    def completed_restore_steps(self, *, native_upload=False):
        steps = []
        for number, step in enumerate(self.restore_steps, 1):
            guard = step.get('if', '')
            skipped = "steps.restore.outputs.candidate_id == ''" in guard or "steps.persist.outcome" in guard
            if native_upload and "steps.persist.outcome" in guard: skipped = False
            steps.append({'name': step.get('name', 'Run ' + step.get('uses', 'unnamed')),
                'number': number, 'status': 'completed', 'conclusion': 'skipped' if skipped else 'success'})
        return steps

    def reuploaded_child_dispatch(self, *, change=None, new_voucher=False):
        """A new dispatcher uploads a privately completed original candidate."""
        self.fixture(producer_attempt=1, consumed=False)
        self.metadata[220, 1]['conclusion'] = 'failure'
        for row in self.job_rows[220, 1]:
            if row['name'] == 'catalog-reconcile': row['conclusion'] = 'failure'
        self.artifacts[220] = [row for row in self.artifacts[220] if row['id'] != self.own_candidate['id']]
        self.meta(250, 1)
        for row in self.job_rows[250, 1]:
            if row['name'] == 'catalog-reconcile': row['steps'] = self.completed_restore_steps(native_upload=True)
        with zipfile.ZipFile(io.BytesIO(self.payloads[self.own_state['id']])) as archive:
            members = {name: json.loads(archive.read(name)) for name in archive.namelist()}
        members['consumed-checkpoints.json'] = [{
            'producer': {'run_id': '220', 'run_attempt': '1', 'head_sha': self.HEAD,
                'event': 'workflow_dispatch', 'path': scheduled.WORKFLOW},
            'reservation': self.own_reservation, 'state': self.own_state,
            'ledger_sha256': identity(self.ledger), 'request_count': 1, 'charged_microusd': 25,
            'request_prefix_sha256': identity(self.ledger['requests']),
            'request_identity_prefix_sha256': self.request_identity}]
        if change: change(members)
        self.transport_state = self.artifact(250, 'offline-ai-reconcile-' + self.PARENT + '-state-250-1', members)
        self.transport_candidate = self.artifact(250, 'candidate-' + self.child['candidate_id'], {'candidate.json': self.child})
        if new_voucher:
            self.artifact(250, 'offline-ai-reconcile-' + self.PARENT + '-reservation-250-1',
                {'reservation.json': self.own_marker | {'producer_run': '250'}})
        self.pointer['artifact_run'] = '250'

    def assert_read_own_proof(self):
        for pin in (self.own_reservation, self.own_state):
            self.assertIn(f'actions/artifacts/{pin["id"]}/zip', self.api_calls)
        self.http.assert_not_called(); self.provider_http.assert_not_called()

    def test_same_run_failed_attempt1_then_published_attempt2_retires_both_authenticated_owners(self):
        self.fixture()
        self.assertIsNone(self.select())
        self.assert_read_own_proof()

    def test_separate_successful_dispatch_retires_its_own_and_consumed_failed_producer(self):
        self.fixture(producer_run=250, producer_attempt=1)
        self.assertIsNone(self.select())
        self.assert_read_own_proof()

    def test_published_first_attempt_with_no_consumed_links_still_authenticates_own_private_pair(self):
        self.fixture(producer_attempt=1, consumed=False)
        self.assertIsNone(self.select())
        self.assert_read_own_proof()

    def test_later_downstream_only_retry_keeps_original_published_producer(self):
        self.fixture(); self.later()
        self.assertIsNone(self.select())
        self.assertIn('actions/runs/220/attempts/3/jobs?per_page=100&page=1', self.api_calls)
        self.assertEqual(self.child['source_reconciliation']['affected_generation']['generation_run_attempt'], '2')
        self.assert_read_own_proof()

    def test_later_unacknowledged_reservation_or_candidate_holds_instead_of_using_published_shortcut(self):
        for kind in ('reservation', 'candidate'):
            with self.subTest(kind=kind):
                self.artifacts.clear(); self.payloads.clear(); self.metadata.clear(); self.job_rows.clear()
                self.fixture(producer_attempt=1, consumed=False); self.later(attempt=2)
                name = ('offline-ai-reconcile-' + self.PARENT + '-reservation-220-2' if kind == 'reservation'
                    else 'candidate-' + '9' * 64)
                self.artifact(220, name, {'unexpected.json': {'later_work': True}})
                with self.assertRaises(scheduled.Hold): self.select()

    def test_later_started_correction_without_a_voucher_still_holds(self):
        self.fixture(); self.later()
        self.job_rows[220, 3].append({'id': 2299999, 'name': 'catalog-reconcile', 'run_id': 220,
            'run_attempt': 3, 'head_sha': self.HEAD, 'head_branch': 'main', 'status': 'completed',
            'conclusion': 'failure'})
        with self.assertRaises(scheduled.Hold): self.select()
        self.assertIn('actions/runs/220/attempts/3/jobs?per_page=100&page=1', self.api_calls)

    def test_complete_child_restore_retry_keeps_identical_budget_without_new_voucher(self):
        self.fixture(producer_attempt=1, consumed=False); self.completed_restore_retry()
        before = deepcopy(self.ledger)
        self.assertIsNone(self.select())
        self.assertEqual(self.ledger, before)
        self.assertIn(f'actions/artifacts/{self.restore_state["id"]}/zip', self.api_calls)
        self.assertIn('actions/runs/220/attempts/2/jobs?per_page=100&page=1', self.api_calls)
        self.assertFalse(any(row['name'].endswith('-reservation-220-2') for row in self.artifacts[220]))
        self.assert_read_own_proof()

    def test_restore_state_changed_ledger_or_operation_and_any_new_voucher_hold(self):
        def changed_ledger(members):
            members['ledger.json']['blocked_providers'] = {'voyage': 'unknown_accounting'}
        def changed_operation(members):
            context = members['reconciliation.json']
            context['operation_contract']['reviewed-source'] = '7' * 64
            context['operation_sha256'] = identity({key: value for key, value in context.items()
                if key not in ('operation_sha256', 'completed_candidate_id')})
        for kind, change in (('ledger', changed_ledger), ('operation', changed_operation), ('new-voucher', None)):
            with self.subTest(kind=kind):
                self.artifacts.clear(); self.payloads.clear(); self.metadata.clear(); self.job_rows.clear()
                self.fixture(producer_attempt=1, consumed=False); self.completed_restore_retry(change=change)
                if kind == 'new-voucher':
                    self.artifact(220, 'offline-ai-reconcile-' + self.PARENT + '-reservation-220-2',
                        {'reservation.json': self.own_marker | {'producer_attempt': '2'}})
                with self.assertRaises(scheduled.Hold): self.select()

    def test_new_dispatch_reuploads_exact_privately_completed_child_without_relabelling_origin(self):
        self.reuploaded_child_dispatch()
        self.assertIsNone(self.select())
        self.assertEqual(self.pointer['artifact_run'], '250')
        self.assertEqual(self.child['source_reconciliation']['affected_generation']['generation_run_id'], '220')
        self.assertIn(f'actions/artifacts/{self.transport_state["id"]}/zip', self.api_calls)
        self.assertIn(f'actions/artifacts/{self.own_state["id"]}/zip', self.api_calls)
        self.http.assert_not_called(); self.provider_http.assert_not_called()

    def test_new_transport_with_changed_ledger_or_new_voucher_cannot_retire_original_owner(self):
        for kind in ('ledger', 'new-voucher'):
            with self.subTest(kind=kind):
                self.artifacts.clear(); self.payloads.clear(); self.metadata.clear(); self.job_rows.clear()
                self.reuploaded_child_dispatch(change=(lambda members:
                    members['ledger.json'].update(requests=[])) if kind == 'ledger' else None,
                    new_voucher=kind == 'new-voucher')
                with self.assertRaises(scheduled.Hold): self.select()


if __name__ == '__main__':
    unittest.main()
