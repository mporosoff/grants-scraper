"""First publication of a runtime child retires only its proven source owner."""
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

from tools import release_candidate as c, scheduled_catalog as scheduled
from tools.offline_spend import identity


class RuntimeReconciliationPublication(unittest.TestCase):
    HEAD = 'b' * 40
    PARENT = 'a' * 64

    def setUp(self):
        self.root = Path('runtime-source-fixture')
        repository = Path(__file__).resolve().parents[1]
        self.workflow = (repository / scheduled.WORKFLOW).read_text(encoding='utf8')
        self.pages = (repository / '.github/workflows/pages.yml').read_text(encoding='utf8')
        self.raw = {'data/opportunities.js': b'public retained catalog\n',
            'data/search-v2-voyage-vectors.f16': b'\x00\xff\x80\x00'}
        self.hashes = {name: c.digest(raw) for name, raw in self.raw.items()}
        self.protected_raw = dict(self.raw)
        self.ledger = {'version': 1, 'logical_id': 'offline-100', 'limit_microusd': 2_000_000,
            'max_requests': 300, 'requests': [{'id': '1' * 32, 'provider': 'voyage', 'model': 'voyage-4-lite',
                'stage': 'reconciled_vectors', 'key': '2' * 64, 'attempt': 1, 'status': 'valid',
                'reserved_microusd': 30, 'charged_microusd': 25, 'usage': None}],
            'events': [], 'blocked_providers': {}}
        self.context = {'version': 'catalog-source-reconciliation-1', 'parent_candidate_id': self.PARENT,
            'parent_run': '100', 'parent_attempt': '1', 'parent_generation_sha': 'c' * 40,
            'parent_manifest_sha256': 'd' * 64, 'operation_contract': {'reviewed-source': 'e' * 64},
            'original_spend': {'ledger_sha256': 'f' * 64}}
        self.context['operation_sha256'] = identity(self.context)
        receipt = self.context | {'source_slug': 'sam-gov', 'consumed_checkpoints': [],
            'ledger_sha256': identity(self.ledger), 'affected_generation': {'generation_run_id': '220',
                'generation_run_attempt': '1', 'generation_sha': self.HEAD,
                'generation_timestamp': '2026-10-18T12:00:00Z'}}
        self.source = {'candidate_format': c.VERSION, 'schema_version': 1, 'generation_run_id': '100',
            'generation_run_attempt': '1', 'generation_sha': 'c' * 40,
            'generation_timestamp': '2026-10-17T12:00:00Z', 'generation_dependencies': {'files': {'code': 'f' * 64}},
            'generator_versions': {'generator': 1}, 'generation_baseline': {'data/opportunities.js': 'e' * 64},
            'generation_files': self.hashes, 'team_identity': {'generation_id': '7' * 64},
            'semantic_identity': {'corpus_sha256': '8' * 64},
            'original_generation': {'generation_run_id': '100', 'generation_sha': 'c' * 40},
            'files': self.hashes | {'team_match.html': c.digest(b'old runtime')},
            'dependency_groups': {name: {'files': {'code': str(index) * 64}, 'fingerprint': str(index) * 64}
                for index, name in enumerate(('source', 'teams', 'semantic', 'runtime', 'validation'), 1)},
            'assembly_sha': self.HEAD, 'derived_from_candidate': self.PARENT, 'source_reconciliation': receipt}
        self.source['candidate_id'] = c.digest(c.encoded(self.source))
        self.child = deepcopy(self.source)
        self.child.update(derived_from_candidate=self.source['candidate_id'], assembly_sha='d' * 40)
        self.child['files']['team_match.html'] = c.digest(b'corrected runtime')
        self.child['dependency_groups']['runtime']['fingerprint'] = '9' * 64
        self.seal_child()
        self.run = {'id': 220, 'run_attempt': 1, 'head_sha': self.HEAD, 'head_branch': 'main',
            'path': scheduled.WORKFLOW, 'event': 'workflow_dispatch', 'status': 'completed', 'conclusion': 'failure'}
        self.runs = {220: self.run}
        self.attempts = {(220, 1): deepcopy(self.run)}
        self.job_rows = {}
        self.later_jobs = []
        self.marker = {'version': 'catalog-source-reconciliation-1', 'parent_candidate_id': self.PARENT,
            'operation_sha256': self.context['operation_sha256'], 'producer_run': '220', 'producer_attempt': '1',
            'prior_ledger_sha256': identity(self.ledger)}
        self.state = {'reservation.json': self.marker, 'ledger.json': self.ledger,
            'reconciliation.json': self.context | {'completed_candidate_id': self.source['candidate_id']},
            'complete-candidates/' + self.source['candidate_id'] + '/candidate.json': self.source}
        self.artifacts, self.payloads, self.api_calls, self.binary_reads = [], {}, [], []
        self.inventories = {220: self.artifacts}
        self.family = 'offline-ai-reconcile-' + self.PARENT
        self.add_artifact(10, self.family + '-reservation-220-1', {'reservation.json': self.marker})
        self.add_artifact(11, self.family + '-state-220-1', self.state)
        self.add_artifact(12, 'candidate-' + self.source['candidate_id'], {'candidate.json': self.source})
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(c, 'ROOT', self.root))
        self.stack.enter_context(patch.object(c, 'git', side_effect=self.git))
        self.stack.enter_context(patch.object(scheduled, 'api', side_effect=self.api))
        self.stack.enter_context(patch.object(scheduled.subprocess, 'check_output', side_effect=self.git_bytes))
        self.http = self.stack.enter_context(patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('No source HTTP')))
        self.paid = self.stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('No provider HTTP')))

    def seal_child(self):
        self.child.pop('candidate_id', None)
        self.child['candidate_id'] = c.digest(c.encoded(self.child))
        self.pointer = {'candidate_id': self.child['candidate_id'], 'artifact_run': '250'}

    def add_artifact(self, identifier, name, members, *, run=220):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path, value in members.items(): archive.writestr(path, c.encoded(value))
        self.payloads[identifier] = stream.getvalue()
        inventory = self.inventories.setdefault(run, [])
        inventory[:] = [row for row in inventory if row['id'] != identifier]
        inventory.append({'id': identifier, 'name': name, 'digest': 'sha256:' + c.digest(stream.getvalue()),
            'expired': False, 'workflow_run': {'id': run, 'head_sha': self.HEAD, 'head_branch': 'main'}})
        return {'id': identifier, 'name': name, 'sha256': c.digest(stream.getvalue())}

    def git(self, root, *args):
        if args[0] == 'log': return 'protected-runtime'
        self.assertEqual(args[0], 'show')
        revision, name = args[1].split(':', 1)
        if revision == 'protected-runtime':
            if name == 'release/candidate-source.json': return json.dumps(self.pointer)
            if name == 'release/candidate.json': return json.dumps(self.child)
        if revision == self.HEAD:
            if name == scheduled.WORKFLOW: return self.workflow
            if name == '.github/workflows/pages.yml': return self.pages
        self.fail('Unexpected Git metadata: ' + repr(args))

    def git_bytes(self, command, **options):
        self.assertEqual(command[:4], ['git', '-C', str(self.root), 'show'])
        revision, name = command[4].split(':', 1)
        self.assertEqual(revision, 'protected-runtime'); self.binary_reads.append(name)
        self.assertNotIn('text', options)
        return self.protected_raw[name]

    def api(self, repository, path):
        self.assertEqual(repository, 'owner/repo'); self.api_calls.append(path)
        if path.startswith('actions/workflows/refresh-opportunities.yml/runs?'):
            return json.dumps({'workflow_runs': sorted(self.runs.values(), key=lambda run: run['id'], reverse=True) + [{'id': 100}]})
        match = re.fullmatch(r'actions/runs/(\d+)/artifacts\?per_page=100&page=1', path)
        if match:
            rows = self.inventories[int(match[1])]
            return json.dumps({'artifacts': rows, 'total_count': len(rows)})
        if path == 'actions/artifacts?per_page=100&page=1': return json.dumps({'artifacts': [], 'total_count': 0})
        match = re.fullmatch(r'actions/artifacts/(\d+)/zip', path)
        if match: return self.payloads[int(match[1])]
        match = re.fullmatch(r'actions/runs/(\d+)/attempts/(\d+)(?:/jobs\?per_page=100&page=1)?', path)
        if match:
            key = int(match[1]), int(match[2])
            if '/jobs?' in path:
                rows = self.job_rows.get(key, self.later_jobs)
                return json.dumps({'jobs': rows, 'total_count': len(rows)})
            return json.dumps(self.attempts[key])
        match = re.fullmatch(r'actions/runs/(\d+)', path)
        if match: return json.dumps(self.runs[int(match[1])])
        self.fail('Unexpected API: ' + path)

    def select(self):
        # The real caller passes the newly published manifest, so originalrun100
        # is the floor. Only source producer220 is still scanned above it.
        return scheduled.prior_generation(self.root, {'GITHUB_REPOSITORY': 'owner/repo',
            'GITHUB_RUN_ID': '300'}, self.child)

    def later(self, *, job='validate'):
        self.run['run_attempt'] = 2
        self.attempts[220, 2] = deepcopy(self.run)
        self.later_jobs = [{'id': 2000, 'name': job, 'run_id': 220, 'run_attempt': 2,
            'head_sha': self.HEAD, 'head_branch': 'main', 'status': 'completed', 'conclusion': 'success'}]

    def reseal_source(self):
        self.source.pop('candidate_id', None)
        self.source['candidate_id'] = c.digest(c.encoded(self.source))
        self.child = deepcopy(self.source)
        self.child.update(derived_from_candidate=self.source['candidate_id'], assembly_sha='d' * 40)
        self.child['files']['team_match.html'] = c.digest(b'corrected runtime')
        self.child['dependency_groups']['runtime']['fingerprint'] = '9' * 64
        self.seal_child()
        self.state = {'reservation.json': self.marker, 'ledger.json': self.ledger,
            'reconciliation.json': self.context | {'completed_candidate_id': self.source['candidate_id']},
            'complete-candidates/' + self.source['candidate_id'] + '/candidate.json': self.source}
        self.add_artifact(11, self.family + '-state-220-1', self.state)
        self.add_artifact(12, 'candidate-' + self.source['candidate_id'], {'candidate.json': self.source})

    def consumed_prior(self):
        prior = self.run | {'id': 180}
        self.runs[180] = prior; self.attempts[180, 1] = deepcopy(prior)
        pins = {role: self.add_artifact(number, self.family + f'-{role}-180-1',
            {'prior.json': {}}, run=180) for role, number in (('reservation', 30), ('state', 31))}
        link = {'producer': {'run_id': '180', 'run_attempt': '1', 'head_sha': self.HEAD,
            'event': 'workflow_dispatch', 'path': scheduled.WORKFLOW}, **pins,
            'request_count': 1, 'charged_microusd': 25, 'ledger_sha256': identity(self.ledger),
            'request_prefix_sha256': identity(self.ledger['requests']),
            'request_identity_prefix_sha256': identity([{key: row.get(key) for key in
                ('id', 'provider', 'model', 'stage', 'key', 'attempt', 'reserved_microusd')}
                for row in self.ledger['requests']])}
        self.source['source_reconciliation']['consumed_checkpoints'] = [link]
        self.reseal_source()

    def zero_work_transport(self):
        self.artifacts[:] = [row for row in self.artifacts if row['id'] != 12]
        transport = self.run | {'id': 240, 'conclusion': 'success'}
        self.runs[240] = transport; self.attempts[240, 1] = deepcopy(transport)
        self.add_artifact(40, 'candidate-' + self.source['candidate_id'], {'candidate.json': self.source}, run=240)
        self.add_artifact(41, self.family + '-state-240-1', self.state, run=240)
        steps = []
        for number, step in enumerate(yaml.safe_load(self.workflow)['jobs']['catalog-reconcile']['steps'], 1):
            steps.append({'name': step.get('name', 'Run ' + step.get('uses', 'setup')), 'number': number,
                'status': 'completed', 'conclusion': 'skipped' if step.get('if') ==
                    "steps.restore.outputs.candidate_id == ''" else 'success'})
        self.job_rows[240, 1] = [{'id': 240001, 'name': 'catalog-reconcile', 'run_id': 240, 'run_attempt': 1,
            'head_sha': self.HEAD, 'head_branch': 'main', 'status': 'completed', 'conclusion': 'success', 'steps': steps}]

    def test_actual_caller_floor_retires_unpublished_source_child_through_proven_runtime_publication(self):
        self.assertIsNone(self.select())
        self.assertIn('data/search-v2-voyage-vectors.f16', self.binary_reads)
        self.assertIn('actions/artifacts/11/zip', self.api_calls)
        self.assertEqual(self.ledger['requests'][0]['charged_microusd'], 25)
        self.http.assert_not_called(); self.paid.assert_not_called()

    def test_changed_generation_files_identity_source_receipt_and_published_hashes_hold(self):
        valid = deepcopy(self.child)
        changes = (lambda child: child['generation_files'].pop('data/search-v2-voyage-vectors.f16'),
            lambda child: child.update(generation_sha='f' * 40),
            lambda child: child['source_reconciliation'].update(ledger_sha256='f' * 64),
            lambda child: child['semantic_identity'].update(corpus_sha256='f' * 64),
            lambda child: child['dependency_groups']['teams'].update(fingerprint='f' * 64),
            lambda child: child['files'].update({'data/opportunities.js': 'f' * 64}))
        for index, change in enumerate(changes):
            with self.subTest(change=index):
                self.child = deepcopy(valid); change(self.child); self.seal_child()
                with self.assertRaises(scheduled.Hold): self.select()

    def test_canonical_publication_pointer_and_immediate_private_parent_are_required(self):
        original, pointer = deepcopy(self.child), deepcopy(self.pointer)
        self.pointer['candidate_id'] = 'f' * 64
        with self.assertRaises(scheduled.Hold): self.select()
        self.pointer = deepcopy(pointer)
        self.child['assembly_sha'] = 'f' * 40  # Invalid canonical ID must not authenticate by receipt alone.
        with self.assertRaises(scheduled.Hold): self.select()
        self.child = deepcopy(original); self.child['derived_from_candidate'] = 'f' * 64; self.seal_child()
        with self.assertRaises(scheduled.Hold): self.select()

    def test_changed_protected_binary_or_private_completed_manifest_and_ledger_hold(self):
        self.protected_raw['data/search-v2-voyage-vectors.f16'] = b'changed binary'
        with self.assertRaises(scheduled.Hold): self.select()
        self.protected_raw = dict(self.raw)
        state = deepcopy(self.state)
        state['complete-candidates/' + self.source['candidate_id'] + '/candidate.json']['generation_sha'] = 'f' * 40
        self.add_artifact(11, self.family + '-state-220-1', state)
        with self.assertRaises(scheduled.Hold): self.select()
        state = deepcopy(self.state); state['ledger.json']['requests'][0]['charged_microusd'] = 0
        self.add_artifact(11, self.family + '-state-220-1', state)
        with self.assertRaises(scheduled.Hold): self.select()

    def test_unknown_later_allowance_candidate_and_started_correction_remain_owners(self):
        for kind in ('reservation', 'candidate', 'correction'):
            with self.subTest(kind=kind):
                self.artifacts[:] = [row for row in self.artifacts if row['id'] < 20]
                self.later(job='catalog-reconcile' if kind == 'correction' else 'validate')
                if kind != 'correction':
                    name = self.family + '-reservation-220-2' if kind == 'reservation' else 'candidate-' + '9' * 64
                    self.add_artifact(20, name, {'unacknowledged.json': {}})
                with self.assertRaises(scheduled.Hold): self.select()

    def test_only_downstream_later_attempt_can_retain_the_original_source_identity(self):
        self.later()
        self.assertIsNone(self.select())
        self.assertIn('actions/runs/220/attempts/2/jobs?per_page=100&page=1', self.api_calls)
        self.assertEqual(self.source['source_reconciliation']['affected_generation']['generation_run_attempt'], '1')

    def test_runtime_publishing_run_is_not_misclassified_as_source_transport(self):
        runtime = self.run | {'id': 250, 'conclusion': 'success'}
        self.runs[250] = runtime
        self.add_artifact(60, 'candidate-' + self.child['candidate_id'], {'candidate.json': self.child}, run=250)
        self.assertIsNone(self.select())
        self.assertNotIn('actions/artifacts/60/zip', self.api_calls)
        self.assertNotIn('actions/runs/250/attempts/1', self.api_calls)

    def test_unpublished_source_boundary_retires_consumed_earlier_repair_above_actual_floor(self):
        self.consumed_prior()
        self.assertIsNone(self.select())
        self.assertIn('actions/runs/220', self.api_calls)
        self.assertIn('actions/runs/180/artifacts?per_page=100&page=1', self.api_calls)

    def test_consumed_role_cannot_hide_new_voucher_candidate_or_later_paid_work(self):
        self.consumed_prior()
        for kind in ('reservation', 'candidate', 'correction'):
            with self.subTest(kind=kind):
                self.inventories[180][:] = [row for row in self.inventories[180] if row['id'] < 50]
                self.runs[180]['run_attempt'] = 2; self.attempts[180, 2] = deepcopy(self.runs[180])
                self.job_rows[180, 2] = [{'id': 180002, 'name': 'catalog-reconcile' if kind == 'correction' else 'validate',
                    'run_id': 180, 'run_attempt': 2, 'head_sha': self.HEAD, 'head_branch': 'main',
                    'status': 'completed', 'conclusion': 'success'}]
                if kind != 'correction':
                    name = self.family + '-reservation-180-2' if kind == 'reservation' else 'candidate-' + '9' * 64
                    self.add_artifact(50, name, {'unacknowledged.json': {}}, run=180)
                with self.assertRaises(scheduled.Hold): self.select()

    def test_private_completed_source_can_be_transported_then_first_published_as_runtime_child(self):
        self.zero_work_transport()
        self.assertIsNone(self.select())
        self.assertIn('actions/artifacts/41/zip', self.api_calls)
        self.assertIn('actions/runs/240/attempts/1/jobs?per_page=100&page=1', self.api_calls)

    def test_transport_changed_ledger_new_voucher_or_executed_paid_step_hold(self):
        self.zero_work_transport()
        original_state, original_steps = deepcopy(self.state), deepcopy(self.job_rows[240, 1][0]['steps'])
        for kind in ('ledger', 'voucher', 'candidate', 'paid-step'):
            with self.subTest(kind=kind):
                self.inventories[240][:] = [row for row in self.inventories[240] if row['id'] < 50]
                state = deepcopy(original_state)
                if kind == 'ledger': state['ledger.json']['requests'][0]['charged_microusd'] = 0
                self.add_artifact(41, self.family + '-state-240-1', state, run=240)
                self.job_rows[240, 1][0]['steps'] = deepcopy(original_steps)
                if kind == 'voucher': self.add_artifact(50, self.family + '-reservation-240-1', {'reservation.json': self.marker}, run=240)
                if kind == 'candidate': self.add_artifact(50, 'candidate-' + '9' * 64, {'candidate.json': {}}, run=240)
                if kind == 'paid-step':
                    next(step for step in self.job_rows[240, 1][0]['steps'] if step['name'] ==
                        'Build only the affected homogeneous vector corpus within the original budget')['conclusion'] = 'success'
                with self.assertRaises(scheduled.Hold): self.select()


if __name__ == '__main__':
    unittest.main()
