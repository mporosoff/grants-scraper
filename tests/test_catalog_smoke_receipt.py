"""Synthetic retained responses; no HTTP, provider, private fixture or live owner."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from tools import catalog_smoke_receipt as bridge
from tools import catalog_correction_policy as policy
from tools.offline_spend import atomic_json, encoded, identity, ConfigurationFailure


class Interrupted(BaseException):
    pass


def H(n):
    return f'{n:064x}'


def proof():
    files = {'@toolchain': H(1), 'workers/search-voyage-proxy/src/index.js': H(2),
        'workers/search-voyage-proxy/generated/corpus-allowlist.json': H(3),
        'workers/search-voyage-proxy/wrangler.jsonc': H(4)}
    version = '11111111-2222-3333-4444-555555555555'
    return {'fingerprint': bridge.existing.sha(encoded(files)+b'\n'), 'version_id': version,
        'checkpoint': {'baseSha': 'a'*40, 'source': 'verified-serving-bytes',
            'activeDeploymentId': '66666666-7777-8888-9999-aaaaaaaaaaaa', 'activeVersionId': version},
        'reconciliation': {'schema_version': 1, 'observed_at': '2026-09-23T20:00:00Z', 'protected_input_sha': 'a'*40,
            'script_etag': H(7), 'content_version_id': version, 'module_hashes': {'index.js': H(8)},
            'input_hashes': files, 'configuration_fingerprint': H(10),
            'method': 'authenticated-serving-bytes-and-configuration', 'production_mutated': False}}


class Synthetic:
    def __init__(self):
        self.stack = ExitStack(); self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='smoke-unit-')))
        self.state = self.root/'state'; self.inputs = self.root/'inputs'; self.inputs.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {'PATH': os.environ.get('PATH', ''), 'SYSTEMROOT': os.environ.get('SYSTEMROOT', ''),
            'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'a'*40,
            'CONTEXTUAL_CHECK': '{"catalog_correction":"smoke-previous-rerank"}',
            'GITHUB_REPOSITORY': bridge.existing.REPOSITORY, 'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_WORKFLOW_REF': bridge.existing.REPOSITORY+'/'+bridge.existing.WORKFLOW+'@refs/heads/main'}, clear=True))
        self.ledger = bridge.existing.ExperimentLedger(self.state/'ledger.json', initialize=True)
        self.p = deepcopy(policy.plan())
        self.stack.enter_context(patch.object(policy, 'plan', return_value=self.p))
        # Empty synthetic predecessor isolates the new receipt mechanism; the
        # real historical authority/prefix suite is owned by the catalog policy.
        self.stack.enter_context(patch.object(policy, 'history'))
        self.stack.enter_context(patch.object(policy, 'counts', return_value=[]))
        shared = {'passage_id': self.p['smoke_shared_passage_id'], 'text': 'Public common source passage.'}
        shared['text_sha256'] = bridge.existing.sha(shared['text'].encode())
        current = {'corpus_sha256': H(11), 'model_space_fingerprint': H(12)}
        previous = {'corpus_sha256': H(13), 'model_space_fingerprint': H(14)}
        self.expected = {'version': 'search-worker-smoke-inputs-v1', 'worker_origin': bridge.WORKER,
            'worker_input_fingerprint': proof()['fingerprint'], 'query': 'catalysis', 'shared_passage': shared,
            'current': current, 'previous': previous, 'operations': []}
        state = self.ledger.read()
        for i, name in enumerate(bridge.NAMES):
            op = self.p['operations'][name]; key = policy.logical_key(name); request_id = f'{i+1:032x}'
            body = {'model': op['model'], 'input': ['catalysis'], 'input_type': 'query', 'output_dimension': 1024,
                'output_dtype': 'float', 'truncation': True} if i == 0 else {
                    'model': op['model'], 'query': 'Rank public funding opportunities by whether their authoritative scientific or programmatic scope supports the complete research intent. Do not reward partial word overlap when a major query concept is absent.\n\nResearch query: catalysis',
                    'documents': [shared['text']], 'top_k': 1, 'return_documents': False, 'truncation': True}
            raw = encoded(body); (self.inputs/op['body_file']).write_bytes(raw)
            op.update(body_sha256=identity(body), wire_sha256=bridge.existing.sha(raw), input_tokens=len(raw)+1024)
            public = {'query': 'catalysis'} if i == 0 else {'query': 'catalysis', **(current if i == 1 else previous), 'candidates': [shared]}
            wire = encoded(public).decode(); usage = {'total_tokens': 1}; charge = 1
            payload = {'model': op['model'], 'usage': usage, 'latency_ms': 1.5}
            payload.update({'embedding': [1.0]+[0.0]*1023} if i == 0 else {'rankings': [{'index': 0, 'passage_id': shared['passage_id'], 'relevance_score': .75}]})
            response = json.dumps(payload, separators=(', ', ': '))
            row = {'id': request_id, 'key': key, 'purpose': op['purpose'], 'provider': 'voyage', 'model': op['model'],
                'body_sha256': op['body_sha256'], 'code_sha': 'a'*40, 'usage': usage, 'charged_microusd': charge, 'status': 'valid'}
            state['requests'].append(row)
            atomic_json(self.state/'cache'/(key+'.json'), {'key': key, 'body_sha256': op['body_sha256'], 'model': op['model'],
                'request_id': request_id, 'response_text': response, 'response_sha256': bridge.existing.sha(response.encode())})
            atomic_json(self.state/'receipts'/(request_id+'.json'), {'version': policy.VERSION, 'name': name,
                'purpose': op['purpose'], 'key': key, 'request_id': request_id, 'body_sha256': op['body_sha256'],
                'provider': 'voyage', 'model': op['model'], 'status': 'valid', 'http_status': 200, 'code_sha': 'a'*40,
                'sent_body_sha256': identity(public), 'automatic_retries': 0, 'public_body_text': wire,
                'external_http_body_sha256': bridge.existing.sha(wire.encode()), 'response_sha256': bridge.existing.sha(response.encode()),
                'usage': usage, 'charged_microusd': charge, 'serving_proof': proof()})
            self.expected['operations'].append({'purpose': op['purpose'], 'path': '/embed-query' if i == 0 else '/rerank',
                'public_body_text': wire, 'provider_body_text': raw.decode(), 'provider_body_sha256': bridge.existing.sha(raw),
                'external_http_body_sha256': bridge.existing.sha(wire.encode())})
        atomic_json(self.ledger.path, state); bridge.existing.checkpoint(self.state)
        self.context = {'expected': self.expected, 'serving_proof': proof(), 'candidate_inputs': {}}
        self.post = Mock(side_effect=self.response)

    def close(self):
        self.stack.close()

    def response(self, url, **kwargs):
        assert url == bridge.WORKER+'/rerank'
        assert json.loads(kwargs['data'])['corpus_sha256'] == 'f'*64
        bridge.validate_checkpoint(self.state)  # intent is durable before call
        response = Mock(status_code=400)
        response.iter_content.return_value = [b'{"error":{"code":"invalid_candidates"}}']
        return response

    def node(self, action, value):
        if action == 'proof':
            return proof()
        return bridge.node(action, value)

    def finish(self, **kw):
        return bridge.finalize_smoke(self.state, self.inputs, context_loader=lambda *a, **k: deepcopy(self.context),
            node_call=self.node, post=self.post, now=lambda: '2026-09-23T20:01:00Z', **kw)

    def archive(self):
        target = io.BytesIO()
        with zipfile.ZipFile(target, 'w') as z:
            for p in self.state.rglob('*.json'):
                z.writestr(p.relative_to(self.state).as_posix(), p.read_bytes())
        return target.getvalue()


class SmokeReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        blocker = patch('socket.socket.connect', side_effect=AssertionError('No network'))
        blocker.start(); cls.addClassCleanup(blocker.stop)

    def fixture(self):
        f = Synthetic(); self.addCleanup(f.close); return f

    def test_complete_three_cached_checks_unknown_control_and_no_self_reference(self):
        f = self.fixture(); old = {p.relative_to(f.state).as_posix(): p.read_bytes() for p in f.state.rglob('*.json') if p.name != 'checkpoint.json'}
        result = f.finish(); self.assertFalse(result['cache_hit']); self.assertEqual(f.post.call_count, 1)
        receipt = json.loads((f.state/result['receipt_path']).read_bytes())
        self.assertEqual(len(receipt['operations']), 3)
        self.assertEqual(set(receipt['owner']), {'authorization_id', 'run_id', 'run_attempt', 'code_sha'})
        for path, raw in old.items(): self.assertEqual((f.state/path).read_bytes(), raw)
        bridge.validate_checkpoint(f.state)
        self.assertTrue(f.finish()['cache_hit']); self.assertEqual(f.post.call_count, 1)

    def test_foreign_partial_tampered_receipts_reject_before_probe(self):
        for field, bad in (('request_id', 'f'*32), ('charged_microusd', True), ('model', 'other'),
            ('public_body_text', '{}'), ('status', 'failed'), ('sent_body_sha256', 'f'*64)):
            with self.subTest(field=field):
                f = self.fixture(); path = f.state/'receipts'/('1'.zfill(32)+'.json')
                saved = json.loads(path.read_bytes()); saved[field] = bad; atomic_json(path, saved)
                bridge.existing.checkpoint(f.state)
                with self.assertRaises(ConfigurationFailure): f.finish()
                f.post.assert_not_called()

    def test_retained_raw_response_cannot_be_changed_by_reserialization(self):
        f = self.fixture(); path = f.state/'cache'/(policy.logical_key(bridge.NAMES[0])+'.json')
        saved = json.loads(path.read_bytes()); saved['response_text'] += ' '; atomic_json(path, saved)
        with self.assertRaises(ConfigurationFailure): f.finish()
        f.post.assert_not_called()

    def test_real_failure_evidence_is_durable_and_no_automatic_probe_retry(self):
        f = self.fixture(); response = Mock(status_code=200); response.iter_content.return_value = [b'{}']
        f.post.side_effect = None; f.post.return_value = response
        with self.assertRaisesRegex(ConfigurationFailure, 'nonpaid_control_rejection'): f.finish()
        bridge.validate_checkpoint(f.state)
        with self.assertRaisesRegex(ConfigurationFailure, 'prior_nonpaid_probe'): f.finish()
        self.assertEqual(f.post.call_count, 1)

    def test_crash_boundaries_preserve_owner_and_exact_cached_success(self):
        for point in ('before_probe', 'after_probe', 'after_cache', 'before_checkpoint', 'after_checkpoint'):
            with self.subTest(point=point):
                f = self.fixture(); original = f.ledger.path.read_bytes()
                def crash(where):
                    if where == point: raise Interrupted()
                with self.assertRaises(Interrupted): f.finish(crash=crash)
                self.assertEqual(f.ledger.path.read_bytes(), original); bridge.validate_checkpoint(f.state)
                if point in ('after_cache', 'before_checkpoint', 'after_checkpoint'):
                    self.assertTrue(f.finish()['cache_hit']); self.assertEqual(f.post.call_count, 1)
                elif point == 'after_probe':
                    self.assertFalse(f.finish()['cache_hit']); self.assertEqual(f.post.call_count, 1)
                else:
                    with self.assertRaisesRegex(ConfigurationFailure, 'prior_nonpaid_probe'): f.finish()

    def test_concurrent_finalizers_share_one_probe_and_immutable_aggregate(self):
        f = self.fixture()
        with ThreadPoolExecutor(2) as pool:
            values = list(pool.map(lambda _: f.finish(), range(2)))
        self.assertEqual(sorted(v['cache_hit'] for v in values), [False, True]); self.assertEqual(f.post.call_count, 1)

    def test_provider_credentials_are_forbidden_even_for_nonpaid_finalizer(self):
        f = self.fixture()
        for key in ('VOYAGE_API_KEY', 'ANTHROPIC_API_KEY', 'OPENAI_API_KEY'):
            with patch.dict(os.environ, {key: 'synthetic'}), self.assertRaisesRegex(ConfigurationFailure, 'no_provider_credentials'): f.finish()
        f.post.assert_not_called()
        for selector in ('{}', '{"catalog_correction":"embedding-1"}', '{"catalog_correction":"smoke-previous-rerank","extra":true}'):
            with patch.dict(os.environ, {'CONTEXTUAL_CHECK': selector}), self.assertRaisesRegex(ConfigurationFailure, 'exact_last_smoke_selector'): f.finish()

    def test_returned_400_survives_fresh_proof_failure_without_probe_replay(self):
        f = self.fixture(); original_node = f.node
        def failed_proof(action, value):
            if action == 'proof': raise ConfigurationFailure('temporary_read_only_proof_failure')
            return original_node(action, value)
        f.node = failed_proof
        with self.assertRaisesRegex(ConfigurationFailure, 'temporary_read_only'): f.finish()
        f.node = original_node; bridge.validate_checkpoint(f.state)
        self.assertFalse(f.finish()['cache_hit']); self.assertEqual(f.post.call_count, 1)

    def test_original_run_attempt_is_fetched_explicitly_without_using_later_attempt_status(self):
        latest = {'id': 123, 'run_attempt': 2, 'head_sha': 'a'*40, 'head_branch': 'main', 'event': 'workflow_dispatch',
            'path': bridge.existing.WORKFLOW, 'status': 'completed', 'conclusion': 'success'}
        old = dict(latest, run_attempt=1, conclusion='failure')
        api = Mock(side_effect=lambda p: encoded(old if p.endswith('/attempts/1') else latest))
        self.assertEqual(bridge.trusted_run(123, bridge.existing.WORKFLOW, attempt=1, allow_failed=True, api=api), old)
        self.assertEqual(api.call_args_list[-1].args, ('actions/runs/123/attempts/1',))
        old['run_attempt'] = 2
        with self.assertRaisesRegex(ConfigurationFailure, 'exact_run_attempt'):
            bridge.trusted_run(123, bridge.existing.WORKFLOW, attempt=1, allow_failed=True, api=api)

    def test_authenticator_binds_latest_run_zip_checkpoint_cache_and_receipt(self):
        f = self.fixture(); f.finish(); raw = f.archive()
        run = {'id': 123, 'run_attempt': 1, 'head_sha': 'a'*40, 'head_branch': 'main', 'event': 'workflow_dispatch',
            'path': bridge.existing.WORKFLOW, 'status': 'completed', 'conclusion': 'success'}
        state = {'id': 125, 'name': bridge.existing.PREFIX+'-state-123-1', 'digest': 'sha256:'+bridge.existing.sha(raw),
            'expired': False, 'workflow_run': {'id': 123, 'head_sha': 'a'*40}, 'created_at': '2026-09-23T20:03:00Z'}
        reservation = dict(state, id=124, name=bridge.existing.PREFIX+'-reservation-123-1', created_at='2026-09-23T20:00:00Z')
        replies = {'actions/artifacts?per_page=100&page=1': {'artifacts': [state, reservation]}, 'actions/runs/123': run,
            'actions/artifacts/125': state,
            'actions/workflows/team-recommender-offline.yml/runs?branch=main&per_page=100': {'workflow_runs': [run]}}
        def api(path): return raw if path == 'actions/artifacts/125/zip' else encoded(replies[path])
        def authenticate(): return bridge.authenticate_owner(f.inputs, api=api, node_call=f.node,
            context_loader=lambda *a, **kw: deepcopy(f.context))
        result = authenticate(); self.assertEqual(result['anchor']['artifact']['id'], 125)
        self.assertEqual(result['anchor']['receipt_sha256'], bridge.existing.sha(result['receipt_text'].encode()))
        for mutation in ('digest', 'run_head', 'orphan', 'active', 'latest_attempt'):
            original = deepcopy(replies)
            if mutation == 'digest': replies['actions/artifacts/125']['digest'] = 'sha256:'+'f'*64
            elif mutation == 'run_head': replies['actions/runs/123']['head_sha'] = 'b'*40
            elif mutation == 'orphan': replies['actions/artifacts?per_page=100&page=1']['artifacts'].append(dict(reservation,
                name=bridge.existing.PREFIX+'-reservation-126-1', created_at='2026-09-23T20:04:00Z'))
            elif mutation == 'active': replies['actions/workflows/team-recommender-offline.yml/runs?branch=main&per_page=100']['workflow_runs'].append({'status': 'in_progress'})
            else: replies['actions/runs/123']['run_attempt'] = 2
            with self.subTest(mutation=mutation), self.assertRaises(ConfigurationFailure): authenticate()
            replies.clear(); replies.update(original)

    def test_failed_origin_successful_latest_retains_exact_aggregate_and_full_original_evidence(self):
        f = self.fixture(); f.finish(); original_raw = f.archive()
        origin_receipt = (f.state/bridge.receipt_path()).read_bytes()
        old_run = {'id': 123, 'run_attempt': 1, 'head_sha': 'a'*40, 'head_branch': 'main', 'event': 'workflow_dispatch',
            'path': bridge.existing.WORKFLOW, 'status': 'completed', 'conclusion': 'failure'}
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '126'}):
            self.assertTrue(f.finish()['cache_hit'])
        latest_raw = f.archive(); self.assertEqual((f.state/bridge.receipt_path()).read_bytes(), origin_receipt)
        new_run = dict(old_run, id=126, conclusion='success')
        def meta(id, run, kind, raw, clock):
            return {'id': id, 'name': f"{bridge.existing.PREFIX}-{kind}-{run}-1", 'digest': 'sha256:'+bridge.existing.sha(raw),
                'expired': False, 'workflow_run': {'id': run, 'head_sha': 'a'*40}, 'created_at': clock}
        old_state = meta(125, 123, 'state', original_raw, '2026-09-23T20:02:00Z')
        new_state = meta(128, 126, 'state', latest_raw, '2026-09-23T20:04:00Z')
        reservation = meta(127, 126, 'reservation', b'', '2026-09-23T20:03:00Z')
        replies = {'actions/artifacts?per_page=100&page=1': {'artifacts': [old_state, new_state, reservation]},
            'actions/runs/123': old_run, 'actions/runs/126': new_run, 'actions/artifacts/125': old_state, 'actions/artifacts/128': new_state,
            'actions/workflows/team-recommender-offline.yml/runs?branch=main&per_page=100': {'workflow_runs': [old_run, new_run]}}
        def api(path):
            if path == 'actions/artifacts/125/zip': return original_raw
            if path == 'actions/artifacts/128/zip': return latest_raw
            return encoded(replies[path])
        value = bridge.authenticate_owner(f.inputs, api=api, node_call=f.node,
            context_loader=lambda *a, **kw: deepcopy(f.context))
        self.assertEqual(value['anchor']['run']['id'], 126)
        self.assertEqual(value['anchor']['aggregate_origin']['run']['id'], 123)
        self.assertEqual(value['receipt_text'].encode(), origin_receipt); self.assertEqual(f.post.call_count, 1)

    def test_archive_paths_duplicates_symlinks_and_extra_context_members_rejected(self):
        for names in (['../bad'], ['C:/bad'], ['a', 'a'], ['context.json', 'extra.json']):
            data = io.BytesIO()
            with zipfile.ZipFile(data, 'w') as z:
                for name in names: z.writestr(name, '{}')
            with tempfile.TemporaryDirectory() as folder, self.subTest(names=names), self.assertRaises(ConfigurationFailure):
                bridge.unpack_public(data.getvalue(), folder, context=True)

    def test_context_authenticates_all_three_artifact_zips_before_pure_source_validation(self):
        from tools import catalog_source_correction as source
        f = self.fixture()
        def zipped(files):
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, 'w') as z:
                for name, value in files.items(): z.writestr(name, value)
            return raw.getvalue()
        candidate_zip = zipped({'candidate-manifest.json': b'{}'})
        export_zip = zipped({'export.json': b'{}'})
        refresh = {'id': 555, 'run_attempt': 1, 'head_sha': 'a'*40, 'head_branch': 'main', 'event': 'workflow_dispatch',
            'path': bridge.REFRESH, 'status': 'in_progress', 'conclusion': None}
        owner = dict(refresh, id=122, path=bridge.existing.WORKFLOW, status='completed', conclusion='success')
        candidate = {'candidate_id': H(200), 'artifact_run': 555, 'artifact_id': 201,
            'artifact_digest': 'sha256:'+bridge.existing.sha(candidate_zip), 'manifest_sha256': H(203)}
        export = {'owner_run': 122, 'artifact_id': 202, 'artifact_digest': 'sha256:'+bridge.existing.sha(export_zip), 'export_sha256': H(204)}
        p = proof(); p['checkpoint']['source'] = 'verified-candidate-serving-bytes'
        p['reconciliation']['method'] = 'authenticated-candidate-serving-bytes-and-configuration'
        p['candidate'] = {k: candidate[k] for k in ('candidate_id', 'artifact_id', 'artifact_digest', 'manifest_sha256')}
        p['candidate']['code_sha'] = 'a'*40
        context = {'version': bridge.CONTEXT_VERSION, 'source_plan_sha256': H(205),
            'refresh': {'run_id': 555, 'run_attempt': 1, 'head_sha': 'a'*40}, 'candidate': candidate,
            'correction_export': export, 'generations': {'current': {}, 'previous': {}}, 'serving_proof': p}
        context_zip = zipped({'context.json': encoded(context)})
        def meta(id, name, run, raw):
            return {'id': id, 'name': name, 'digest': 'sha256:'+bridge.existing.sha(raw), 'expired': False,
                'workflow_run': {'id': run, 'head_sha': 'a'*40}, 'created_at': '2026-09-23T20:00:00Z'}
        cmeta = meta(200, bridge.CONTEXT_PREFIX+H(200)+'-555-1', 555, context_zip)
        replies = {'actions/artifacts?per_page=100&page=1': {'artifacts': [cmeta]}, 'actions/runs/555': refresh,
            'actions/runs/122': owner, 'actions/artifacts/200': cmeta,
            'actions/artifacts/201': meta(201, 'candidate-'+H(200), 555, candidate_zip),
            'actions/artifacts/202': meta(202, 'catalog-correction-export-122-1', 122, export_zip)}
        zips = {'actions/artifacts/200/zip': context_zip, 'actions/artifacts/201/zip': candidate_zip, 'actions/artifacts/202/zip': export_zip}
        def api(path): return zips[path] if path in zips else encoded(replies[path])
        def project(observed, candidate_root, export_root, state, inputs):
            self.assertEqual(observed, context)
            self.assertEqual((candidate_root/'candidate-manifest.json').read_bytes(), b'{}')
            self.assertEqual((export_root/'export.json').read_bytes(), b'{}')
            return {'expected': f.expected, 'candidate_inputs': {}}
        with patch.object(source, 'verify_inputs'), patch.object(source, 'validate_context_packet', side_effect=project) as validator:
            value = bridge.load_context(f.state, f.inputs, api=api, node_call=lambda *a: p)
            self.assertEqual(value['context'], context); self.assertEqual(validator.call_count, 1)
            for field, bad in (('expired', True), ('digest', 'sha256:'+'f'*64), ('name', 'foreign')):
                old = deepcopy(replies['actions/artifacts/201']); replies['actions/artifacts/201'][field] = bad
                with self.subTest(field=field), self.assertRaises(ConfigurationFailure): bridge.load_context(f.state, f.inputs, api=api)
                self.assertEqual(validator.call_count, 1); replies['actions/artifacts/201'] = old
            refresh.update(status='completed', conclusion='failure')
            self.assertEqual(bridge.load_context(f.state, f.inputs, api=api, node_call=lambda *a: p)['context'], context)


if __name__ == '__main__': unittest.main()
