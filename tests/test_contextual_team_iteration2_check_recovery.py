"""Exact retained-reference recovery; synthetic replies, never provider traffic."""
import copy
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import test_contextual_team_iteration2 as lifecycle
import test_contextual_team_iteration2_check as check_fixture
import test_contextual_team_luna_repair as evidence_fixture
from test_contextual_team_answer_rows import payload
from tools import contextual_team_iteration2_check as checker
from tools import contextual_team_iteration2_check_recovery as recovery
from tools import contextual_team_check as entrypoint
from tools import team_recommender_executor as existing
from tools import contextual_team_iteration2 as workflow
from tools import contextual_team_iteration2_policy as policy
from tools.contextual_team_executor import Runner, RecoveryRequired, scope_inputs
from tools.contextual_team_token_preflight import Counter
from tools.offline_spend import atomic_json, encoded, identity, ConfigurationFailure


def reference_fixture():
    evidence = {'profile_documents': [
        {'person_id': 'person-a', 'claims': [{'claim_id': 'person-a-c001', 'revision': 2}]},
        {'person_id': 'person-b', 'claims': [{'claim_id': 'person-b-c001', 'revision': 1}]}],
        'items': [
            {'item_id': 'source', 'task_type': 'source_suitability', 'people': []},
            {'item_id': 'top-1', 'task_type': 'call_person', 'people': ['person-a']},
            {'item_id': 'top-2', 'task_type': 'call_person', 'people': ['person-b']},
            {'item_id': 'group-1', 'task_type': 'group_usefulness', 'people': ['person-a', 'person-b']},
            {'item_id': 'explanation-1', 'task_type': 'explanation_audit', 'people': ['person-a']}]}
    owned = {q['item_id']: {'scope.science'} | set(q['people']) | {
        c['claim_id']+'@'+str(c['revision']) for p in evidence['profile_documents']
        if p['person_id'] in q['people'] for c in p['claims']} for q in evidence['items']}
    labels = {q['item_id']: checker.SOURCE_LABELS if q['task_type'] == 'source_suitability'
        else checker.EXPLANATION_LABELS if q['task_type'] == 'explanation_audit'
        else checker.USEFUL_LABELS for q in evidence['items']}
    row = checker.obj(item_id=checker.enum(*owned),
        verdict=checker.enum(*dict.fromkeys(checker.SOURCE_LABELS+checker.USEFUL_LABELS+checker.EXPLANATION_LABELS)),
        evidence_ref=checker.string(100), reason=checker.string(1000, 15))
    rows = checker.array(row, len(owned)); rows['minItems'] = len(owned)
    validate = checker.validator(evidence['items'], checker.obj(answers=rows), owned, labels,
        identity(evidence), version=checker.LEGACY_VERSION)
    wire = {'answers': [{'item_id': q['item_id'], 'verdict': labels[q['item_id']][0],
        'evidence_ref': 'scope.science' if not q['people'] else q['people'][0]+'-c001',
        'reason': 'This retained fixture reason is exact and must never be rewritten.'} for q in evidence['items']]}
    return evidence, validate, wire


class ExactReferenceRecovery(unittest.TestCase):
    def setUp(self):
        self.evidence, self.validate, self.wire = reference_fixture()
        blocked = patch('socket.socket.connect', side_effect=AssertionError('no_network'))
        blocked.start(); self.addCleanup(blocked.stop)

    def recover(self, wire=None, evidence=None):
        return recovery.recover_text(json.dumps(self.wire if wire is None else wire),
            self.evidence if evidence is None else evidence, self.validate)

    def test_only_exact_unique_owned_bare_claim_gets_its_retained_revision(self):
        original = copy.deepcopy(self.wire)
        with self.assertRaises(ValueError): self.validate(payload(json.dumps(original), 'anthropic'), False)
        value = self.recover()
        self.assertEqual(self.wire, original)
        self.assertEqual(value['version'], checker.LEGACY_VERSION)
        self.assertEqual(value['input_sha256'], identity(self.evidence))
        for before, after in zip(original['answers'], value['verdicts']):
            self.assertEqual({k: v for k, v in before.items() if k != 'evidence_ref'},
                             {k: v for k, v in after.items() if k != 'evidence_ref'})
            expected = before['evidence_ref']
            if expected != 'scope.science': expected += '@1' if expected.startswith('person-b') else '@2'
            self.assertEqual(after['evidence_ref'], expected)
        self.assertEqual(self.validate(value, True), value)
        self.assertEqual(recovery.recover_text(json.dumps({'answers': value['verdicts']}), self.evidence, self.validate), value)

    def test_exact_person_and_scope_refs_are_preserved_without_qualification(self):
        wire = copy.deepcopy(self.wire)
        wire['answers'][1]['evidence_ref'] = 'person-a'
        value = self.recover(wire)
        self.assertEqual(value['verdicts'][0]['evidence_ref'], 'scope.science')
        self.assertEqual(value['verdicts'][1]['evidence_ref'], 'person-a')

    def test_foreign_stale_composite_alias_and_ambiguous_references_fail_closed(self):
        for ref in ('person-b-c001', 'person-b-c001@1', 'person-a-c001@1', 'person-a-c001@99',
                    'person-a-c001;scope.science', 'person-a-c001@2, person-a',
                    'p01c01', 'PERSON-A-C001', ' person-a-c001', 'person-a-c001 ',
                    'person-a-c001@02', 'person-a-c001@2@2', 'c001'):
            wire = copy.deepcopy(self.wire); wire['answers'][1]['evidence_ref'] = ref
            with self.subTest(ref=ref):
                with self.assertRaises(ValueError): self.recover(wire)
        evidence = copy.deepcopy(self.evidence)
        evidence['profile_documents'][0]['claims'].append({'claim_id': 'person-a-c001', 'revision': 3})
        with self.assertRaises(ValueError): self.recover(evidence=evidence)

    def test_complete_questions_labels_and_original_reason_bounds_remain_strict(self):
        for mutate in (lambda w: w['answers'].pop(),
                       lambda w: w['answers'].append(copy.deepcopy(w['answers'][0])),
                       lambda w: w['answers'].__setitem__(1, copy.deepcopy(w['answers'][0])),
                       lambda w: w['answers'][1].update(item_id='unknown'),
                       lambda w: w['answers'][1].update(verdict='faithful'),
                       lambda w: w['answers'][0].update(verdict='strong'),
                       lambda w: w['answers'][1].update(reason='short'),
                       lambda w: w['answers'][1].update(reason='x'*1001),
                       lambda w: w['answers'][1].update(extra=True),
                       lambda w: w.update(extra=True)):
            wire = copy.deepcopy(self.wire); mutate(wire)
            with self.assertRaises(ValueError): self.recover(wire)
        wire = copy.deepcopy(self.wire); wire['answers'].reverse()
        with self.assertRaises(ValueError): self.recover(wire)

    def test_duplicate_keys_nonjson_constants_and_byte_bound_are_not_repaired(self):
        text = json.dumps(self.wire)
        for invalid in (text.replace('"answers":', '"answers":[],"answers":', 1),
                        text.replace('"reason":', '"reason":"first reason","reason":', 1),
                        text.replace('"evidence_ref":', '"evidence_ref":"scope.science","evidence_ref":', 1),
                        'NaN', '{"answers":NaN}', '[]', 'null', '{}',
                        ' '*(checker.MAX_RESPONSE_BYTES+1)):
            with self.assertRaises(ValueError): recovery.recover_text(invalid, self.evidence, self.validate)


class RecoveryEntrypoint(unittest.TestCase):
    def setUp(self):
        env = {'GITHUB_REPOSITORY': existing.REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_WORKFLOW_REF': existing.REPOSITORY+'/'+existing.WORKFLOW+'@refs/heads/main',
            'GITHUB_SHA': 'a'*40, 'GITHUB_RUN_ID': '9001', 'GITHUB_RUN_ATTEMPT': '1',
            'CONTEXTUAL_CHECK': json.dumps({'iteration2_check_recovery': '363302:a-1'}),
            'CONTEXTUAL_JOB': '', 'PACKET_HASH': '', 'PACKET_COMMIT': ''}
        p = patch.dict(os.environ, env); p.start(); self.addCleanup(p.stop)
        p = patch.object(sys, 'argv', ['contextual_team_check.py', 'prepare', '--state', 'fixture-state'])
        p.start(); self.addCleanup(p.stop)

    def test_exact_manual_main_entrypoint_routes_to_recovery(self):
        with patch.object(recovery, 'run') as run, patch.object(checker, 'run') as normal:
            entrypoint.main(); run.assert_called_once(); normal.assert_not_called()
            self.assertEqual(run.call_args.args[0].state, Path('fixture-state'))

    def test_repository_dispatch_wrong_branch_and_workflow_never_reach_recovery(self):
        for env in ({'GITHUB_EVENT_NAME': 'repository_dispatch'}, {'GITHUB_REF': 'refs/heads/codex/fixture'},
                    {'GITHUB_WORKFLOW_REF': 'other/workflow@refs/heads/main'}, {'GITHUB_REPOSITORY': 'other/repo'}):
            with patch.dict(os.environ, env), patch.object(recovery, 'run') as run:
                with self.assertRaisesRegex(ConfigurationFailure, 'protected_main_manual_execution_required'):
                    entrypoint.main()
                run.assert_not_called()


class RecoveryLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Build a complete synthetic provider history through the real runners.
        # No retained private response or scientist judgment is a test fixture.
        cls.f = lifecycle.Iteration2('runTest'); cls.f.setUp()
        cls.addClassCleanup(cls.f.doCleanups)
        cls.f.p['input_token_ceilings']['check'] = 180000
        cls.f.p['release_id'] = identity({k: v for k, v in cls.f.p.items() if k != 'release_id'})
        cls.f.config['snapshot_id'] = cls.f.p['release_id']; cls.f.install()
        original_vectors = workflow.Iteration2Runner.vectors
        chosen = {p['person_id'] for p in cls.f.data['people']}
        def vectors(runner, docs, role, scope=None):
            if role == 'query': return original_vectors(runner, docs, role, scope)
            return [{'id': d['input_id'], 'embedding':
                ([1.0, 0.0] if d['person_id'] in chosen else [0.0, 1.0]) + [0.0]*1022} for d in docs]
        source_env = {'GITHUB_RUN_ID': '9000', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'a'*40}
        with patch.dict(os.environ, source_env), patch.object(workflow.Iteration2Runner, 'vectors', vectors):
            cls.f.runner().run_scope(cls.f.scope)
            scope, graph, assessment, selection = checker.actual_result(cls.f.state, cls.f.config, cls.f.scope['id'])
            contract, body, validate, _ = checker.packet(scope, graph, assessment, selection, cls.f.config,
                version=checker.LEGACY_VERSION)
            evidence = json.loads(body['messages'][0]['content']); wire = check_fixture.answer(body)
            docs = {p['person_id']: p for p in evidence['profile_documents']}
            for answer, question in zip(wire['answers'], evidence['items']):
                if question['people']:
                    answer['evidence_ref'] = docs[question['people'][0]]['claims'][0]['claim_id']
            cls.text = json.dumps(wire)
            def post(*args, **kwargs):
                response = payload(cls.text, 'anthropic')
                response['usage'] = {'input_tokens': 1000, 'output_tokens': 100}
                return evidence_fixture.Response(response)
            runner = workflow.Iteration2Runner(cls.f.state, cls.f.config, post=post, counter_post=cls.f.counter)
            purpose = policy.operation(scope['id'], 'check')
            metadata = policy.bind_operation(runner.ledger, purpose, body, contract, contract['evidence_sha256'])
            with cls.f.assertRaisesRegex(ValueError, recovery.ERROR):
                runner.request(purpose, [policy.VERSION, purpose, identity(contract), contract['evidence_sha256']],
                    body, validate, repair_metadata=metadata)
        cls.original = runner.ledger.read(); row = cls.original['requests'][-1]
        cls.source_checkpoint = json.loads((cls.f.state/'checkpoint.json').read_bytes())
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, 'w') as archive:
            for path in cls.f.state.rglob('*.json'):
                archive.write(path, path.relative_to(cls.f.state).as_posix())
        cls.source_archive = archive_bytes.getvalue()
        diagnostic_path = cls.f.state/'diagnostics'/(row['id']+'.json')
        diagnostic = json.loads(diagnostic_path.read_bytes())
        cls.expected = recovery.recover_text(cls.text, evidence, validate)
        source = {'run': {'id': 9000, 'run_attempt': 1, 'head_sha': 'a'*40, 'head_branch': 'main',
            'event': 'workflow_dispatch', 'path': existing.WORKFLOW, 'status': 'completed', 'conclusion': 'failure'},
            'artifact': {'id': 12345, 'name': 'fixture-original-state',
                'digest': 'sha256:'+existing.sha(cls.source_archive)},
            'request_id': row['id'], 'request_key': row['key'], 'request_sha256': identity(row),
            'charged_microusd': row['charged_microusd'], 'body_sha256': identity(body),
            'contract_sha256': identity(contract), 'input_sha256': identity(evidence),
            'source_sha256': identity(scope_inputs(scope)), 'graph_sha256': identity(graph),
            'selection_sha256': identity(selection), 'selection_bundle_id': selection['bundle_id'],
            'composer_sha256': selection['composer_sha256'], 'diagnostic_identity': identity(diagnostic),
            'diagnostic_sha256': existing.sha(diagnostic_path.read_bytes()),
            'receipt_sha256': existing.sha((cls.f.state/'receipts'/(row['id']+'.json')).read_bytes()),
            'text_sha256': identity(cls.text), 'raw_text_sha256': existing.sha(cls.text.encode()),
            'ledger_sha256': existing.sha((cls.f.state/'ledger.json').read_bytes()),
            'checkpoint_sha256': existing.sha((cls.f.state/'checkpoint.json').read_bytes()),
            'requests': len(cls.original['requests']), 'requests_sha256': identity(cls.original['requests']),
            'events': len(cls.original['events']), 'events_sha256': identity(cls.original['events']),
            'native_counts': len(cls.source_checkpoint['phase2_token_preflight']['rows']),
            'native_counts_sha256': identity(cls.source_checkpoint['phase2_token_preflight']['rows'])}
        cls.p = {'version': recovery.VERSION, 'authorization_id': existing.AUTHORIZATION_ID,
            'scope_id': scope['id'], 'source': source,
            'validation_contract_sha256': identity(recovery.validation_contract(evidence, contract)),
            'result_sha256': identity(cls.expected)}
        for mock in (patch.object(recovery, 'plan', return_value=cls.p),
                     patch.object(workflow, 'configuration', return_value=cls.f.config),
                     patch.object(Runner, 'request', side_effect=AssertionError('no_paid_request')),
                     patch.object(Counter, 'count', side_effect=AssertionError('no_native_count')),
                     patch('requests.post', side_effect=AssertionError('no_provider_post')),
                     patch('socket.socket.connect', side_effect=AssertionError('no_network'))):
            mock.start(); cls.addClassCleanup(mock.stop)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='i2recover-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)
        self.state = self.root/'state'; shutil.copytree(self.f.state, self.state)
        self.active = []; self.status = 'completed'
        env = {'GITHUB_RUN_ID': '9001', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'b'*40,
            'GITHUB_REPOSITORY': existing.REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_WORKFLOW_REF': existing.REPOSITORY+'/'+existing.WORKFLOW+'@refs/heads/main',
            'CONTEXTUAL_CHECK': json.dumps(recovery.SELECTOR),
            'CONTEXTUAL_JOB': '', 'PACKET_HASH': '', 'PACKET_COMMIT': '',
            'ANTHROPIC_API_KEY': '', 'OPENAI_API_KEY': '', 'VOYAGE_API_KEY': ''}
        p = patch.dict(os.environ, env); p.start(); self.addCleanup(p.stop)

    def api(self, path):
        if path == 'actions/artifacts/12345/zip': return self.source_archive
        if path == 'actions/artifacts/12345':
            return encoded(self.p['source']['artifact'] | {'expired': False,
                'workflow_run': {'id': 9000, 'head_sha': 'a'*40}})
        return encoded({'workflow_runs': self.active} if '?status=' in path
            else self.p['source']['run'] | {'status': self.status})

    def assert_history(self):
        ledger = existing.ExperimentLedger(self.state/'ledger.json').read()
        self.assertEqual(ledger['requests'], self.original['requests'])
        self.assertEqual(ledger['events'], self.original['events']+[recovery.event()])
        self.assertEqual(json.loads((self.state/'checkpoint.json').read_bytes())['phase2_token_preflight'],
                         self.source_checkpoint['phase2_token_preflight'])
        for folder in ('receipts', 'diagnostics'):
            name = self.p['source']['request_id']+'.json'
            self.assertEqual((self.state/folder/name).read_bytes(), (self.f.state/folder/name).read_bytes())
        self.assertFalse((self.state/'cache'/(self.p['source']['request_key']+'.json')).exists())
        checkpoint = json.loads((self.state/'checkpoint.json').read_bytes())
        actual = {p.relative_to(self.state).as_posix(): existing.sha(p.read_bytes())
            for p in self.state.rglob('*.json') if p.name != 'checkpoint.json'}
        self.assertEqual(checkpoint['files'], actual)

    def restored(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            for path in self.state.rglob('*.json'):
                archive.write(path, path.relative_to(self.state).as_posix())
        target = self.root/('restore-'+str(len(list(self.root.iterdir()))))
        existing.unpack_state(raw.getvalue(), target); self.state = target

    def test_failed_charge_and_all_history_survive_separate_idempotent_recovery(self):
        value = recovery.recover(self.state, self.api)
        self.assertFalse(value['cache_hit']); self.assertEqual(value['value'], self.expected)
        self.assertEqual(value['original_request_status'], 'failed')
        self.assertEqual(value['original_charged_microusd'], self.p['source']['charged_microusd'])
        self.assertEqual((value['new_metered_attempts'], value['new_native_count_calls'], value['new_microusd']), (0, 0, 0))
        self.assertNotEqual(value['recovery_key'], self.p['source']['request_key'])
        for _ in range(2):
            self.assert_history(); self.restored()
            self.assertEqual(recovery.read_recovered(self.state)['value'], self.expected)
            self.assertTrue(recovery.recover(self.state, self.api)['cache_hit'])
        self.assert_history()

    def test_all_crash_boundaries_restore_without_paid_or_count_replay(self):
        for index, boundary in enumerate(('after_cache', 'after_receipt', 'after_event', 'before_checkpoint', 'after_checkpoint')):
            with self.subTest(boundary=boundary):
                self.state = self.root/('crash-'+str(index)); shutil.copytree(self.f.state, self.state)
                def crash(point):
                    if point == boundary: raise KeyboardInterrupt('fixture crash')
                with self.assertRaises(KeyboardInterrupt): recovery.recover(self.state, self.api, crash=crash)
                self.restored()
                self.assertEqual(recovery.recover(self.state, self.api)['value'], self.expected)
                self.assertEqual(recovery.read_recovered(self.state)['value'], self.expected)
                self.assert_history()

    def test_concurrent_recovery_and_intervening_evidence_change_are_bound(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: recovery.recover(self.state, self.api), range(2)))
        self.assertEqual([r['value'] for r in results], [self.expected, self.expected]); self.assert_history()
        prepare = recovery.prepare_plan
        def changed(*args, **kwargs):
            result = prepare(*args, **kwargs)
            old = next((self.state/'cache').glob('*.json')); old.write_bytes(old.read_bytes()+b' ')
            return result
        with patch.object(recovery, 'prepare_plan', side_effect=changed):
            with self.assertRaises(RecoveryRequired): recovery.recover(self.state, self.api)

    def test_original_and_derived_tampering_never_becomes_a_successful_cache(self):
        recovery.recover(self.state, self.api); source = self.state
        for index, kind in enumerate(('failed_row', 'known_charge', 'native_count', 'source_receipt',
            'source_diagnostic', 'graph', 'body_binding', 'cache', 'receipt', 'event')):
            with self.subTest(kind=kind):
                self.state = self.root/('tamper-'+str(index)); shutil.copytree(source, self.state)
                cache, receipt = recovery.paths(self.state)
                if kind in ('failed_row', 'known_charge', 'body_binding', 'event'):
                    path = self.state/'ledger.json'; ledger = json.loads(path.read_bytes())
                    if kind == 'failed_row': ledger['requests'][-1]['status'] = 'valid'
                    elif kind == 'known_charge': ledger['requests'][-1]['charged_microusd'] += 1
                    elif kind == 'body_binding': ledger['events'][-2]['body_sha256'] = '0'*64
                    else: ledger['events'][-1]['result_sha256'] = '0'*64
                    atomic_json(path, ledger)
                elif kind == 'native_count':
                    path = self.state/'checkpoint.json'; cp = json.loads(path.read_bytes())
                    cp['phase2_token_preflight']['rows'][-1]['input_tokens'] += 1; atomic_json(path, cp)
                elif kind.startswith('source_'):
                    folder = 'receipts' if kind == 'source_receipt' else 'diagnostics'
                    path = self.state/folder/(self.p['source']['request_id']+'.json')
                    path.write_bytes(path.read_bytes()+b' ')
                elif kind == 'graph':
                    path = workflow.result_path(self.state, self.p['scope_id'])
                    graph = json.loads(path.read_bytes()); graph['value']['pair_decisions'][0]['outcome'] = 'adjacent'
                    atomic_json(path, graph)
                else: (cache if kind == 'cache' else receipt).write_bytes(b'{}\n')
                with self.assertRaises((RecoveryRequired, ConfigurationFailure, KeyError)):
                    recovery.recover(self.state, self.api)

    def test_terminal_source_and_exclusive_owner_are_required_before_writes(self):
        before = {p.relative_to(self.state).as_posix(): p.read_bytes() for p in self.state.rglob('*.json')}
        self.status = 'in_progress'
        with self.assertRaises(RecoveryRequired): recovery.recover(self.state, self.api)
        self.status = 'completed'; self.active = [{'id': 8888}]
        with self.assertRaises(RecoveryRequired): recovery.recover(self.state, self.api)
        self.assertEqual({p.relative_to(self.state).as_posix(): p.read_bytes() for p in self.state.rglob('*.json')}, before)

    def test_source_archive_metadata_digest_and_checkpoint_are_independently_bound(self):
        before = (self.state/'ledger.json').read_bytes()
        for defect in ('digest', 'expired', 'owner', 'bytes'):
            def api(path):
                value = self.api(path)
                if path.endswith('/zip') and defect == 'bytes': return value+b'changed'
                if path == 'actions/artifacts/12345':
                    metadata = json.loads(value)
                    if defect == 'digest': metadata['digest'] = 'sha256:'+'0'*64
                    if defect == 'expired': metadata['expired'] = True
                    if defect == 'owner': metadata['workflow_run']['id'] = 99999
                    return encoded(metadata)
                return value
            with self.subTest(defect=defect):
                with self.assertRaises(RecoveryRequired): recovery.recover(self.state, api)
                self.assertEqual((self.state/'ledger.json').read_bytes(), before)

    def test_first_recovery_after_later_work_uses_historical_snapshot_without_rollback(self):
        ledger = existing.ExperimentLedger(self.state/'ledger.json')
        purpose = policy.operation('fixture-0', 'check')
        _, _, contract, body, _, _, _ = recovery.source_packet(self.state)
        policy.bind_operation(ledger, purpose, body, contract, contract['evidence_sha256'])
        state = ledger.read(); later = copy.deepcopy(state['requests'][-1])
        later.update(id='e'*32, key='f'*64, status='valid', purpose=purpose, charged_microusd=123)
        state['requests'].append(later); atomic_json(ledger.path, state)
        atomic_json(self.state/'cache'/('f'*64+'.json'), {'fixture_later_cache': True})
        atomic_json(self.state/'receipts'/('e'*32+'.json'), {'fixture_later_receipt': True})
        cp_path = self.state/'checkpoint.json'; cp = json.loads(cp_path.read_bytes())
        count = copy.deepcopy(cp['phase2_token_preflight']['rows'][-1])
        count.update(id=purpose, key='f'*64); cp['phase2_token_preflight']['rows'].append(count)
        atomic_json(cp_path, cp); existing.checkpoint(self.state)
        before = {p.relative_to(self.state).as_posix(): p.read_bytes() for p in self.state.rglob('*.json')}
        result = recovery.recover(self.state, self.api)
        self.assertEqual(result['value'], self.expected)
        self.assertEqual(ledger.read()['requests'], state['requests'])
        self.assertEqual(ledger.read()['events'], state['events']+[recovery.event()])
        self.assertEqual(json.loads(cp_path.read_bytes())['phase2_token_preflight'], cp['phase2_token_preflight'])
        for name, raw in before.items():
            if name not in ('ledger.json', 'checkpoint.json'): self.assertEqual((self.state/name).read_bytes(), raw)
        self.restored()
        with patch.object(recovery, 'source_snapshot', side_effect=AssertionError('persisted_snapshot_reused')):
            self.assertEqual(recovery.recover(self.state, self.api)['value'], self.expected)
            self.assertEqual(recovery.read_recovered(self.state)['value'], self.expected)

    def test_only_bundle_metadata_may_change_when_reconstructing_original_selection(self):
        prepared = recovery.source_packet(self.state)
        actual_result = checker.actual_result
        def repackaged(*args):
            scope, graph, assessment, selection = actual_result(*args)
            return scope, graph, assessment, selection | {'bundle_id': '0'*64}
        with patch.object(checker, 'actual_result', side_effect=repackaged):
            restored = recovery.source_packet(self.state)
            self.assertEqual((restored[2], restored[3], restored[6]), (prepared[2], prepared[3], prepared[6]))
        for field, value in (('composer_sha256', '0'*64), ('groups', []), ('primary_view', []), ('option_count', 99999)):
            def changed(*args):
                scope, graph, assessment, selection = actual_result(*args)
                return scope, graph, assessment, selection | {field: value}
            with patch.object(checker, 'actual_result', side_effect=changed):
                with self.assertRaises(RecoveryRequired): recovery.source_packet(self.state)

    def test_normal_selector_reuses_recovered_v1_without_constructing_a_runner(self):
        recovery.recover(self.state, self.api)
        args = SimpleNamespace(action='prepare', state=self.state, reservation=self.root/'ordinary-reservation.json',
            result=self.root/'ordinary-result.json'); output = self.root/'ordinary-output.txt'
        # The synthetic history uses the fixture source scope. The real pinned
        # DOE scope is independently exercised by the local retained-state run.
        with patch.object(recovery, 'SCOPE_ID', self.p['scope_id']), \
             patch.object(existing, 'restore', return_value=existing.ExperimentLedger(self.state/'ledger.json')), \
             patch.object(existing, 'api', side_effect=self.f.api), \
             patch.object(workflow, 'Iteration2Runner', side_effect=AssertionError('no_runner_for_recovered_result')), \
             patch.dict(os.environ, {'CONTEXTUAL_CHECK': json.dumps({'iteration2_check': self.p['scope_id']}),
                 'GITHUB_OUTPUT': str(output)}):
            checker.run(args)
            prepared = json.loads(args.reservation.read_bytes())
            self.assertEqual(prepared['version'], checker.LEGACY_VERSION)
            self.assertEqual((prepared['maximum_new_metered_attempts'], prepared['maximum_new_native_counts']), (0, 0))
            self.assertEqual(output.read_text(), 'text_provider=none\n')
            self.assertEqual(prepared['body_sha256'], self.p['source']['body_sha256'])
            args.action = 'execute'; checker.run(args)
            result = json.loads(args.result.read_bytes())
            self.assertEqual(result['value'], self.expected); self.assertEqual(result['requests'], [])
        self.assert_history()

    def test_trusted_zero_reservation_execute_and_malformed_selectors(self):
        args = SimpleNamespace(action='prepare', state=self.state, reservation=self.root/'reservation.json',
            result=self.root/'result.json'); output = self.root/'step-output.txt'
        with patch.object(existing, 'restore', return_value=existing.ExperimentLedger(self.state/'ledger.json')), \
             patch.object(existing, 'api', side_effect=self.api), patch.dict(os.environ, {'GITHUB_OUTPUT': str(output)}):
            recovery.run(args)
            reservation = json.loads(args.reservation.read_bytes())
            self.assertEqual((reservation['maximum_new_microusd'], reservation['maximum_new_metered_attempts'],
                reservation['maximum_new_native_counts']), (0, 0, 0))
            self.assertEqual(output.read_text(), 'text_provider=none\n')
            args.action = 'execute'; recovery.run(args)
            result = json.loads(args.result.read_bytes())
            self.assertEqual(result['value'], self.expected); self.assertEqual(result['validation_code_sha'], 'b'*40)
        self.assert_history()
        for selector in ({**recovery.SELECTOR, 'extra': True}, {'iteration2_check': '363302:a-1'},
                         {'iteration2_check_recovery': '351715'}, {'iteration2_check_recovery': []}):
            with patch.dict(os.environ, {'CONTEXTUAL_CHECK': json.dumps(selector)}):
                with self.assertRaisesRegex(ConfigurationFailure, 'exact_selector'): recovery.run(args)
        for field in ('CONTEXTUAL_JOB', 'PACKET_HASH', 'PACKET_COMMIT'):
            with patch.dict(os.environ, {field: 'unexpected'}):
                with self.assertRaisesRegex(ConfigurationFailure, 'exact_selector'): recovery.run(args)
        args.action = 'execute'; cache, _ = recovery.paths(self.state); cache.unlink()
        with self.assertRaises(RecoveryRequired): recovery.run(args)


if __name__ == '__main__':
    unittest.main()
