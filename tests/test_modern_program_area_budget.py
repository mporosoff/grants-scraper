"""Modern program-area continuation: native provenance and one shared allowance."""
from contextlib import ExitStack
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import program_area_revalidation as p, release_candidate as c
from tools import catalog_reconcile_spend as spend
from tools.offline_spend import Ledger, atomic_json, identity


def zipped(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, raw in files.items(): archive.writestr(name, raw)
    return stream.getvalue()


class ModernProgramAreaBudget(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); (self.root/'tools').mkdir()
        (self.root/'tools/clock.py').write_bytes(b'fixed_science = True\n')
        self.native_state = self.root/'offline-123'
        self.book = Ledger(self.native_state/'ledger.json', 'offline-123', 2, 300)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(spend, '__file__', str(self.root/'tools/catalog_reconcile_spend.py')))
        self.stack.enter_context(patch.object(spend, 'GENERATION_INPUTS', ('tools/clock.py',)))
        self.stack.enter_context(patch.object(spend, 'VECTOR_PREPROCESSORS', ('tools/clock.py',)))
        self.stack.enter_context(patch.object(spend, 'production_ledger', return_value=self.book))
        self.stack.enter_context(patch.dict('os.environ', GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1',
            GITHUB_REPOSITORY='owner/repo', GITHUB_SHA='b'*40))
        self.packet = {'run_id': '123', 'mode': 'maintenance', 'corpus_sha256': 'c'*64,
            'configuration_sha256': 'd'*64, 'passage_count': 1, 'retained_asset_eligible': False,
            'source_hashes': {'tools/clock.py': p.sha((self.root/'tools/clock.py').read_bytes())}}
        prepared = spend.prepare(self.native_state, self.packet, generation=True)
        request = spend.reserve(self.native_state, {'url': spend.URL, 'body': json.dumps({
            'input': ['Public research passage'], 'model': spend.MODEL, 'input_type': 'document',
            'truncation': True, 'output_dimension': 1024, 'output_dtype': 'float'})}, generation=True)
        spend.finish(self.native_state, {'key': request['key'], 'token': request['token'], 'status': 200,
            'request_id': 'f'*32, 'payload': {'model': spend.MODEL, 'usage': {'total_tokens': 51},
                'data': [{'index': 0, 'embedding': [.125]*1024}]}}, generation=True)
        self.raw = {n: ('synthetic completed vector bytes '+n).encode() for n in p.VECTORS}
        self.raw[p.VECTORS[-1]] = c.encoded({'status': 'written', 'model': spend.MODEL, 'API_request_count': 1,
            'usage_total_tokens': 51, 'API_requests': [{'model': spend.MODEL, 'http_status': 200,
                'request_id': 'f'*32, 'usage_total_tokens': 51, 'passage_count': 1}]})
        self.raw['config/retained-science.json'] = b'{"retained":true}\n'
        for name, raw in self.raw.items():
            path = self.root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        spend.checkpoint(self.native_state, {'operation_sha256': prepared['operation_sha256'],
            'outputs': {n: p.sha(self.raw[n]) for n in p.VECTORS}}, generation=True)
        self.original = deepcopy(self.book.read()); self.original_hash = identity(self.original)
        self.bundle = self.root/'parent'; (self.bundle/'files').mkdir(parents=True)
        files = {n: p.sha(raw) for n, raw in self.raw.items()}
        self.manifest = {'schema_version': 1, 'candidate_format': c.VERSION, 'files': files,
            'generation_files': files, 'generation_sha': 'a'*40, 'generation_run_id': '123',
            'generation_run_attempt': '1', 'dependency_groups': {}}
        self.manifest['candidate_id'] = c.digest(c.encoded(self.manifest)); self.cid = self.manifest['candidate_id']
        (self.bundle/'candidate.json').write_bytes(c.encoded(self.manifest))
        for name, raw in self.raw.items():
            path = self.bundle/'files'/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        self.runs = {('123','1'): self.run_meta('123','1','b'*40), ('456','1'): self.run_meta('456','1','e'*40, current=True)}
        self.artifacts = []; self.archives = {}
        self.add_artifact('candidate-'+self.cid, '123', {'candidate.json': c.encoded(self.manifest),
            **{'files/'+n: raw for n, raw in self.raw.items()}})
        self.add_artifact('release-plan-1', '123', {'release-plan.json': c.encoded({'release_sha': 'a'*40, 'stage': 'generate'})})
        self.add_artifact('generation-spend-reservation-123-1', '123', {'spend-reservation.json': c.encoded({
            'run_id': '123', 'attempt': '1', 'mode': 'maintenance', 'maximum_logical_spend_usd': 2})})
        self.add_artifact('generation-spend-state-123-1', '123', self.state_files(self.native_state))
        self.stack.enter_context(patch('tools.release_checkpoint_archive.preserved_artifacts', return_value=[]))
        self.git = self.stack.enter_context(patch.object(c, 'git', side_effect=self.git_read))
        self.http = self.stack.enter_context(patch('requests.sessions.Session.request',
            side_effect=AssertionError('no source or provider HTTP')))

    def run_meta(self, run, attempt, sha, current=False):
        return {'id': int(run), 'run_attempt': int(attempt), 'head_sha': sha, 'head_branch': 'main',
            'path': p.auth.REFRESH, 'event': 'workflow_dispatch',
            'status': 'in_progress' if current else 'completed', 'conclusion': None if current else 'failure'}

    def git_read(self, root, *args):
        if args == ('show', 'b'*40+':'+p.auth.REFRESH):
            return ('jobs:\n  generate:\n    steps:\n      - id: semantic-vectors\n'
                '        run: node tools/run_budgeted_vectors.mjs --production --write\n')
        if args[:2] == ('merge-base', '--is-ancestor'): return ''
        self.fail('unexpected Git access '+repr(args))

    def state_files(self, state):
        return {n.relative_to(state).as_posix(): n.read_bytes() for n in state.rglob('*') if n.is_file()}

    def add_artifact(self, name, run, files):
        raw = zipped(files); identifier = len(self.artifacts)+1
        meta = self.runs[(run,'1')]
        row = {'id': identifier, 'name': name, 'expired': False, 'digest': 'sha256:'+p.sha(raw),
            'workflow_run': {'id': int(run), 'head_sha': meta['head_sha'], 'head_branch': 'main'}}
        self.artifacts.append(row); self.archives[identifier] = raw
        return row

    def api(self, route):
        if route.startswith('actions/runs/') and '/attempts/' in route:
            parts = route.split('/'); return c.encoded(self.runs[(parts[2],parts[4])])
        if route.startswith('actions/runs/') and '/artifacts?' in route:
            run = int(route.split('/')[2]); rows = [r for r in self.artifacts if r['workflow_run']['id'] == run]
            return c.encoded({'total_count': len(rows), 'artifacts': rows})
        if route.startswith('actions/artifacts?'):
            return c.encoded({'total_count': len(self.artifacts), 'artifacts': self.artifacts})
        if route.startswith('actions/artifacts/') and route.endswith('/zip'):
            return self.archives[int(route.split('/')[2])]
        self.fail('unexpected API '+route)

    def authenticate(self, name='restored'):
        state = self.root/name
        original, spending, producer, artifact = p.modern_original(self.bundle, state, 'owner/repo',
            '123', self.cid, self.api, self.root)
        value = {'version': p.MODERN_VERSION, 'parent_candidate_id': self.cid, 'parent_run': '123',
            'parent_attempt': '1', 'parent_generation_sha': original['generation_sha'],
            'parent_manifest_sha256': p.sha((self.bundle/'candidate.json').read_bytes()),
            'parent_producer': producer, 'parent_artifact': artifact, 'original_spend': spending,
            'operation_contract': {'extractor': 'f'*64}, 'audit_at': '2026-10-19T01:00:00Z'}
        value['operation_sha256'] = identity(value); atomic_json(state/'reconciliation.json', value)
        atomic_json(state/'consumed-checkpoints.json', [])
        spend.import_history(state, self.bundle, spending['ledger_sha256'])
        return state, value

    def test_native_event_plan_and_original_measured_budget_authenticate_without_double_charge(self):
        state, value = self.authenticate(); ledger = spend.ledger(state).read()
        self.assertEqual(value['parent_producer']['head_sha'], 'b'*40)
        self.assertEqual(value['parent_generation_sha'], 'a'*40)
        self.assertEqual(value['original_spend']['ledger_sha256'], self.original_hash)
        self.assertEqual(ledger['requests'], self.original['requests'])
        self.assertEqual(sum(r['charged_microusd'] for r in ledger['requests']), 2)
        before = deepcopy(ledger); spend.import_history(state, self.bundle, self.original_hash)
        self.assertEqual(spend.ledger(state).read(), before)

    def test_tampered_native_artifact_or_wrong_checkout_fails_before_spend_restore(self):
        self.archives[1] += b'tampered'
        with self.assertRaisesRegex(ValueError, 'artifact_digest'): self.authenticate()
        self.assertFalse((self.root/'restored/ledger.json').exists())
        self.archives[1] = zipped({'candidate.json': c.encoded(self.manifest),
            **{'files/'+n: raw for n, raw in self.raw.items()}})
        self.artifacts[0]['digest'] = 'sha256:'+p.sha(self.archives[1])
        self.archives[2] = zipped({'release-plan.json': c.encoded({'release_sha': '9'*40})})
        self.artifacts[1]['digest'] = 'sha256:'+p.sha(self.archives[2])
        with self.assertRaisesRegex(ValueError, 'actual_generation_checkout'): self.authenticate()
        self.assertFalse((self.root/'restored/ledger.json').exists())

    def test_same_corpus_retains_exact_sealed_native_origin_and_changed_corpus_cannot(self):
        state, value = self.authenticate(); before = spend.ledger(state).read()
        packet = dict(self.packet, retained_asset_eligible=True)
        reused, accounting = p.modern_native_vectors(self.root, state, self.bundle, self.manifest, value, packet)
        self.assertTrue(reused); self.assertEqual(accounting['classification'], 'budgeted')
        for changed in (dict(packet, corpus_sha256='8'*64), dict(packet, configuration_sha256='9'*64),
                dict(packet, retained_asset_eligible=False), dict(packet, source_hashes={'tools/clock.py': '7'*64})):
            with self.subTest(changed=changed):
                self.assertFalse(p.modern_native_vectors(self.root, state, self.bundle, self.manifest, value, changed)[0])
        self.assertEqual(spend.ledger(state).read(), before)

    def test_changed_corpus_uses_existing_wrapper_operation_and_same_ledger_prefix(self):
        state, value = self.authenticate(); before = spend.ledger(state).read()
        packet = dict(self.packet, corpus_sha256='8'*64)
        self.assertEqual(spend.prepare(state, packet)['status'], 'prepared')
        request = spend.reserve(state, {'url': spend.URL, 'body': json.dumps({'input': ['Corrected public facet'],
            'model': spend.MODEL, 'input_type': 'document', 'truncation': True,
            'output_dimension': 1024, 'output_dtype': 'float'})})
        self.assertEqual(request['status'], 'reserved')
        after = spend.ledger(state).read()
        self.assertEqual(after['requests'][:len(before['requests'])], before['requests'])
        self.assertEqual(after['logical_id'], 'offline-123'); self.assertEqual(after['limit_microusd'], 2_000_000)
        self.assertEqual(after['max_requests'], 300); self.assertEqual(len(after['requests']), 2)
        with self.assertRaisesRegex(ValueError, 'previous_dispatch_unknown'):
            spend.reserve(state, {'url': spend.URL, 'body': json.dumps({'input': ['Corrected public facet'],
                'model': spend.MODEL, 'input_type': 'document', 'truncation': True,
                'output_dimension': 1024, 'output_dtype': 'float'})})

    def test_modern_scope_rejects_unrelated_source_team_or_embedding_change(self):
        base = {group: {'files': {'existing': 'a'}, 'fingerprint': 'a'} for group in ('source','teams','semantic')}
        original = dict(self.manifest, dependency_groups=base)
        for group in ('source','teams','semantic'):
            after = deepcopy(base); after[group]['files']['unrelated'] = 'b'
            with self.subTest(group=group), patch('tools.release_dependencies.snapshot', return_value=after):
                with self.assertRaisesRegex(ValueError, 'extractor_only_change'):
                    p.modern_scope(self.root, original)

    def prepare(self, state, *, changed=True, output=None, current='456', attempt='1'):
        outputs = {n: ('corrected projection '+n).encode() for n in p.PROJECTION}
        packet = dict(self.packet, retained_asset_eligible=not changed)
        if changed: packet['corpus_sha256'] = '8'*64
        with patch.dict('os.environ', GITHUB_RUN_ID=current, GITHUB_RUN_ATTEMPT=attempt,
                GITHUB_SHA=self.runs[(current,'1')]['head_sha']), \
                patch.object(p, 'modern_scope'), \
                patch.object(p, 'modern_contract', return_value={'scripts/extract_document_evidence.py': '6'*64}), \
                patch.object(p, 'projection', return_value=(outputs, {'source_requests': 0,
                    'document_ai_requests': 0, 'team_requests': 0})), \
                patch.object(p, 'vector_packet', return_value=packet):
            return p.prepare_modern(self.bundle, self.root/'receipt.json', state, '123', self.cid,
                root=self.root, api=self.api, output=output)

    def test_prepare_changed_corpus_restores_complete_cache_and_no_new_allowance(self):
        state = self.root/'program-state'
        prepared = self.prepare(state)
        self.assertEqual(prepared['vector_reused'], 'false')
        self.assertEqual(prepared['parent_run'], '123')
        ledger = spend.ledger(state).read()
        self.assertEqual(ledger['requests'], self.original['requests'])
        self.assertEqual(len(list((state/'vector-responses').glob('*.json'))), 1)
        value = spend.context(state)
        self.assertEqual(value['version'], p.MODERN_VERSION)
        reservation = p.read(prepared['reservation_path'])
        self.assertEqual(reservation['prior_ledger_sha256'], identity(ledger))
        self.assertEqual(reservation['operation_sha256'], value['operation_sha256'])
        self.assertEqual(reservation['parent_candidate_id'], self.cid)
        self.assertEqual((self.root/'config/retained-science.json').read_bytes(), self.raw['config/retained-science.json'])
        self.http.assert_not_called()

    def test_paired_cold_resume_keeps_measured_prefix_and_accepted_response_without_dispatch(self):
        state = self.root/'program-state'; prepared = self.prepare(state)
        changed = dict(self.packet, corpus_sha256='8'*64)
        spend.prepare(state, changed)
        body = {'url': spend.URL, 'body': json.dumps({'input': ['Corrected public facet'], 'model': spend.MODEL,
            'input_type': 'document', 'truncation': True, 'output_dimension': 1024, 'output_dtype': 'float'})}
        reserved = spend.reserve(state, body)
        spend.finish(state, {'key': reserved['key'], 'token': reserved['token'], 'status': 200,
            'request_id': '7'*32, 'payload': {'model': spend.MODEL, 'usage': {'total_tokens': 52},
                'data': [{'index': 0, 'embedding': [.25]*1024}]}})
        before = spend.ledger(state).read()
        self.runs[('456','1')]['status'] = 'completed'
        self.add_artifact(prepared['reservation_artifact'], '456', {'reservation.json': Path(prepared['reservation_path']).read_bytes()})
        self.add_artifact(prepared['state_artifact'], '456', self.state_files(state))
        self.runs[('789','1')] = self.run_meta('789','1','9'*40, current=True)
        restored = self.root/'cold-program-state'; second = self.prepare(restored, current='789')
        self.assertEqual(second['vector_reused'], 'false')
        self.assertEqual(spend.ledger(restored).read()['requests'], before['requests'])
        self.assertEqual(spend.reserve(restored, body)['status'], 'cached')
        after = spend.ledger(restored).read()
        self.assertEqual(after['requests'], before['requests'])
        self.assertEqual(len(after['requests']), 2)
        consumed = p.read(restored/'consumed-checkpoints.json')
        self.assertEqual(len(consumed), 1)
        self.assertEqual(consumed[0]['request_count'], 2)
        self.assertEqual(consumed[0]['ledger_sha256'], identity(before))
        self.http.assert_not_called()

    def test_latest_unpaired_reservation_and_context_tamper_hold_before_projection(self):
        state = self.root/'program-state'; prepared = self.prepare(state)
        self.runs[('456','1')]['status'] = 'completed'
        self.add_artifact(prepared['reservation_artifact'], '456', {'reservation.json': Path(prepared['reservation_path']).read_bytes()})
        with patch.object(p, 'projection', side_effect=AssertionError('must hold before projection')):
            with self.assertRaisesRegex(ValueError, 'newest_paired_checkpoint'):
                p.modern_history(self.bundle, self.root/'cold', self.root, 'owner/repo', '123', self.cid, self.api)
        broken = self.state_files(state)
        context = json.loads(broken['reconciliation.json']); context['parent_run'] = '999'
        broken['reconciliation.json'] = c.encoded(context)
        self.add_artifact(prepared['state_artifact'], '456', broken)
        with self.assertRaisesRegex(ValueError, 'operation_identity'):
            p.modern_history(self.bundle, self.root/'cold2', self.root, 'owner/repo', '123', self.cid, self.api)
        self.assertFalse((self.root/'cold/reservation.json').exists())

    def seal_and_verify(self, state, packet):
        receipt = self.root/'receipt.json'
        outputs = {n: ('corrected projection '+n).encode() for n in p.PROJECTION}
        with patch.object(p, 'vector_packet', return_value=dict(packet, retained_asset_eligible=True)), \
                patch.object(p, 'modern_scope'), \
                patch.object(p, 'modern_contract', return_value={'scripts/extract_document_evidence.py': '6'*64}), \
                patch.object(p, 'projection', return_value=(outputs, {'source_requests': 0,
                    'document_ai_requests': 0, 'team_requests': 0})), \
                patch.dict('os.environ', PROGRAM_AREA_VECTOR_STATE=str(state)):
            sealed = p.checkpoint_modern(receipt, state, root=self.root)
            receipt_before = receipt.read_bytes(); ledger_before = (state/'ledger.json').read_bytes()
            self.assertEqual(p.verify_modern_inputs(self.root, self.manifest, receipt, api=self.api),
                {'config/retained-science.json': p.sha(self.raw['config/retained-science.json'])})
            self.assertEqual(receipt.read_bytes(), receipt_before)
            self.assertEqual((state/'ledger.json').read_bytes(), ledger_before)
            wrong = deepcopy(sealed); wrong['vector_outputs'][p.VECTORS[0]] = '9'*64
            atomic_json(receipt, wrong); before = receipt.read_bytes()
            with self.assertRaisesRegex(ValueError, 'receipt_sealed'):
                p.verify_modern_inputs(self.root, self.manifest, receipt, api=self.api)
            self.assertEqual(receipt.read_bytes(), before, 'constructor rejection must not rewrite receipt')
        return sealed

    def test_same_corpus_checkpoint_preserves_native_four_bytes_and_origin_without_new_charge(self):
        state = self.root/'program-state'; prepared = self.prepare(state, changed=False)
        self.assertEqual(prepared['vector_reused'], 'true')
        before = spend.ledger(state).read()
        sealed = self.seal_and_verify(state, self.packet)
        self.assertEqual(sealed['vector_accounting']['classification'], 'retained_native_asset')
        self.assertEqual(sealed['vector_accounting']['new_requests'], 0)
        self.assertEqual(sealed['vector_outputs'], {n: p.sha(self.raw[n]) for n in p.VECTORS})
        self.assertEqual(spend.ledger(state).read(), before)

    def test_changed_corpus_completion_uses_measured_new_charge_and_preserves_original_request(self):
        state = self.root/'program-state'; self.prepare(state)
        changed = dict(self.packet, corpus_sha256='8'*64)
        stage = spend.prepare(state, changed)
        request = spend.reserve(state, {'url': spend.URL, 'body': json.dumps({'input': ['Corrected public facet'],
            'model': spend.MODEL, 'input_type': 'document', 'truncation': True,
            'output_dimension': 1024, 'output_dtype': 'float'})})
        spend.finish(state, {'key': request['key'], 'token': request['token'], 'status': 200,
            'request_id': '7'*32, 'payload': {'model': spend.MODEL, 'usage': {'total_tokens': 52},
                'data': [{'index': 0, 'embedding': [.25]*1024}]}})
        for name in p.VECTORS:
            (self.root/name).write_bytes(('new synthetic completed asset '+name).encode())
        (self.root/p.VECTORS[-1]).write_bytes(c.encoded({'status': 'written', 'model': spend.MODEL,
            'API_request_count': 1, 'usage_total_tokens': 52, 'API_requests': [{'model': spend.MODEL,
                'http_status': 200, 'usage_total_tokens': 52, 'passage_count': 1, 'request_id': '7'*32}]}))
        spend.checkpoint(state, {'operation_sha256': stage['operation_sha256'], 'outputs': p.hashes(self.root, p.VECTORS)})
        sealed = self.seal_and_verify(state, changed)
        self.assertEqual(sealed['vector_accounting']['classification'], 'budgeted')
        ledger = spend.ledger(state).read()
        self.assertEqual(ledger['requests'][:1], self.original['requests'])
        self.assertEqual(sum(r['charged_microusd'] for r in ledger['requests']), 4)
        self.assertEqual(len(ledger['requests']), 2)
        self.http.assert_not_called()

    def test_two_completed_transports_keep_exact_child_and_pin_each_native_candidate(self):
        state = self.root/'program-state'; prepared = self.prepare(state, changed=False)
        sealed = self.seal_and_verify(state, self.packet)
        child = deepcopy(self.manifest); child.pop('candidate_id')
        child['derived_from_candidate'] = self.cid
        child['program_area_revalidation'] = sealed | {'affected_generation': {
            'generation_run_id': '456', 'generation_run_attempt': '1', 'generation_sha': 'e'*40,
            'generation_timestamp': '2026-10-19T02:00:00Z'}}
        child['candidate_id'] = c.digest(c.encoded(child))
        bundle = self.root/'complete-child'; (bundle/'files').mkdir(parents=True)
        (bundle/'candidate.json').write_bytes(c.encoded(child))
        for name, raw in self.raw.items():
            target = bundle/'files'/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        p.record_modern_candidate(state, bundle)
        payload = {'candidate.json': c.encoded(child), **{'files/'+n: raw for n, raw in self.raw.items()}}
        self.add_artifact('candidate-'+child['candidate_id'], '456', payload)
        self.add_artifact(prepared['reservation_artifact'], '456', {'reservation.json': Path(prepared['reservation_path']).read_bytes()})
        self.add_artifact(prepared['state_artifact'], '456', self.state_files(state))
        self.runs[('456','1')]['status'] = 'completed'
        self.runs[('789','1')] = self.run_meta('789','1','9'*40, current=True)
        with patch.object(c, 'verify_dependencies'), patch('tools.program_area_history.completed_restore') as proof:
            same = self.prepare(self.root/'same-run', changed=False, current='456', attempt='2', output=self.root/'same-child')
            self.assertEqual(same['artifact_run'], '456')
            self.assertEqual(same['upload_candidate'], 'false', 'immutable native artifact cannot be uploaded twice')
            first_state = self.root/'restore-one'; first_out = self.root/'child-one'
            first = self.prepare(first_state, changed=False, current='789', output=first_out)
            self.assertEqual(first['candidate_id'], child['candidate_id'])
            self.assertEqual(first['artifact_run'], '456'); self.assertEqual(first['upload_candidate'], 'false')
            self.assertEqual((first_out/'candidate.json').read_bytes(), (bundle/'candidate.json').read_bytes())
            native = self.add_artifact('candidate-'+child['candidate_id'], '789', payload)
            self.add_artifact(first['state_artifact'], '789', self.state_files(first_state))
            self.runs[('789','1')]['status'] = 'completed'
            self.runs[('888','1')] = self.run_meta('888','1','8'*40, current=True)
            second_state = self.root/'restore-two'; second_out = self.root/'child-two'
            second = self.prepare(second_state, changed=False, current='888', output=second_out)
            self.assertEqual(second['candidate_id'], child['candidate_id'])
            self.assertEqual(second['artifact_run'], '789'); self.assertEqual(second['upload_candidate'], 'false')
            self.assertEqual((second_out/'candidate.json').read_bytes(), (bundle/'candidate.json').read_bytes())
            self.assertEqual(spend.ledger(second_state).read()['requests'], self.original['requests'])
            links = p.read(second_state/'consumed-checkpoints.json')
            self.assertEqual(len(links), 2)
            self.assertTrue(links[-1]['restored'])
            self.assertEqual(links[-1]['producer']['run_id'], '789')
            self.assertEqual(links[-1]['candidate']['artifact']['id'], native['id'])
            self.assertEqual(links[-1]['candidate']['candidate_id'], child['candidate_id'])
            self.assertEqual(links[-1]['reservation'], links[0]['reservation'])
            proof.assert_called_once()
        self.http.assert_not_called()


if __name__ == '__main__': unittest.main()
