"""Typed cached-deadline continuations conserve accepted accounting and assets."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_modern_program_area_budget as fixtures
from tools import program_area_revalidation as p, catalog_reconcile_spend as spend, release_candidate as c
from tools.offline_spend import atomic_json, identity


class AdministrativeSubmissionBudget(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ModernProgramAreaBudget()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture

    @contextmanager
    def environment(self, *, current='456', changed=False, preprocessing_changed=False):
        f = self.f
        outputs = {n: ('qualified deadlines ' + n).encode() for n in p.PROJECTION}
        packet = dict(f.packet, retained_asset_eligible=not changed)
        if changed:
            packet['corpus_sha256'] = '8' * 64
        if preprocessing_changed:
            (f.root/'tools/clock.py').write_bytes(b'fixed_runtime_currentness = True\n')
            packet['source_hashes'] = {'tools/clock.py': p.sha((f.root/'tools/clock.py').read_bytes())}
        with patch.dict('os.environ', GITHUB_RUN_ID=current, GITHUB_RUN_ATTEMPT='1',
                GITHUB_SHA=f.runs[(current, '1')]['head_sha']), \
                patch.object(p, 'modern_scope'), \
                patch.object(p, 'modern_contract', return_value={'scripts/extract_document_evidence.py': '6' * 64}), \
                patch.object(p, 'modern_projection', return_value=(outputs, {'projection_kind': 'administrative_submission',
                    'source_requests': 0, 'document_ai_requests': 0, 'team_requests': 0})), \
                patch.object(p, 'vector_packet', return_value=packet):
            yield packet

    def prepare(self, state, *, current='456', changed=False, preprocessing_changed=False, output=None):
        with self.environment(current=current, changed=changed, preprocessing_changed=preprocessing_changed):
            return p.prepare_modern(self.f.bundle, self.f.root / 'receipt.json', state, '123', self.f.cid,
                root=self.f.root, api=self.f.api, output=output, projection_kind='administrative_submission')

    def test_prepare_seals_kind_and_original_requests_without_new_paid_work(self):
        f = self.f
        state = f.root / 'admin-state'
        result = self.prepare(state)
        value = spend.context(state)
        self.assertEqual(result['vector_reused'], 'true')
        self.assertEqual(value['projection_kind'], 'administrative_submission')
        self.assertEqual(value['retained_requests'], p.retained_requests(f.original))
        self.assertEqual(p.read(result['reservation_path'])['projection_kind'], 'administrative_submission')
        self.assertEqual(p.read(f.root / 'receipt.json')['projection_kind'], 'administrative_submission')
        self.assertEqual(spend.ledger(state).read()['requests'], f.original['requests'])
        self.assertEqual({name: p.sha((f.root / name).read_bytes()) for name in p.VECTORS},
            {name: p.sha(f.raw[name]) for name in p.VECTORS})
        f.http.assert_not_called()

    def test_changed_corpus_keeps_existing_original_allowance_for_vector_only_work(self):
        state = self.f.root / 'changed-corpus'
        result = self.prepare(state, changed=True)
        self.assertEqual(result['vector_reused'], 'false')
        self.assertTrue(Path(result['reservation_path']).is_file())
        self.assertEqual(spend.ledger(state).read()['requests'], self.f.original['requests'])
        self.assertEqual((spend.ledger(state).read()['limit_microusd'], spend.ledger(state).read()['max_requests']),
            (2_000_000, 300))
        self.f.http.assert_not_called()

    def test_unknown_kind_rejected_before_checkpoint_or_authentication(self):
        for kind in ('unknown', '', False):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'projection_kind'):
                p.prepare_modern(self.f.bundle, self.f.root / 'receipt.json', self.f.root / 'invalid',
                    '123', self.f.cid, root=self.f.root, api=lambda _: self.fail('must fail before API'),
                    projection_kind=kind)
        self.assertFalse((self.f.root / 'invalid').exists())

    def test_default_old_kind_keeps_old_operation_input_contract(self):
        self.assertEqual(p.projection_kind({}), 'program_area')
        for invalid in (None, False, '', 'future_projection'):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'projection_kind'):
                p.projection_kind({'projection_kind': invalid})
        with patch.object(p, 'hashes', return_value={}) as hashed:
            p.modern_contract(self.f.root)
            self.assertEqual(hashed.call_args.args[1], p.MODERN_OPERATION_FILES)
            p.modern_contract(self.f.root, 'administrative_submission')
            self.assertEqual(set(hashed.call_args.args[1]) - set(p.MODERN_OPERATION_FILES),
                {'tools/administrative_submission_revalidation.py', 'scripts/submission_schedule.py',
                 'scripts/build_catalog.py', 'scripts/currentness.py', 'assets/submission-schedule.js',
                 'assets/search-retrieval.js', 'tools/run_search_diagnosis.mjs'})

    def test_cold_checkpoint_rejects_other_projection_kind_before_projection(self):
        f = self.f; state = f.root / 'first'
        result = self.prepare(state)
        f.runs[('456', '1')]['status'] = 'completed'
        f.add_artifact(result['reservation_artifact'], '456',
            {'reservation.json': Path(result['reservation_path']).read_bytes()})
        f.add_artifact(result['state_artifact'], '456', f.state_files(state))
        with self.assertRaisesRegex(ValueError, 'projection_kind_mismatch'):
            p.modern_history(f.bundle, f.root / 'wrong-kind', f.root, 'owner/repo', '123', f.cid, f.api)
        f.runs[('789', '1')] = f.run_meta('789', '1', '9' * 40, current=True)
        result2 = self.prepare(f.root / 'restored', current='789')
        self.assertEqual(result2['vector_reused'], 'true')
        self.assertEqual(spend.ledger(f.root / 'restored').read()['requests'], f.original['requests'])

    def test_checkpoint_rejects_mismatched_receipt_or_unmanaged_added_request(self):
        f = self.f; state = f.root / 'first'
        self.prepare(state)
        receipt_path = f.root / 'receipt.json'; receipt = p.read(receipt_path)
        wrong = deepcopy(receipt); wrong['projection_kind'] = 'program_area'; atomic_json(receipt_path, wrong)
        with self.environment(), self.assertRaisesRegex(ValueError, 'projection_kind_mismatch'):
            p.checkpoint_modern(receipt_path, state, root=f.root)
        atomic_json(receipt_path, receipt)
        spend.ledger(state).reserve('voyage', spend.MODEL, 'reconciled_vectors', 'bad', 100, 1)
        with self.environment(), self.assertRaisesRegex(ValueError, 'administrative_vector_only_append'):
            p.checkpoint_modern(receipt_path, state, root=f.root)
        f.http.assert_not_called()

    def test_same_corpus_changed_preprocessing_builds_and_seals_vectors_inside_original_prefix(self):
        f = self.f; state = f.root/'preprocessor-change'
        result = self.prepare(state, preprocessing_changed=True)
        self.assertEqual(result['vector_reused'], 'false', 'identical corpus is insufficient when preprocessing code changed')
        with self.environment(preprocessing_changed=True) as packet:
            prepared = spend.prepare(state, packet)
            self.assertEqual(prepared['status'], 'prepared')
            request = spend.reserve(state, {'url': spend.URL, 'body': json.dumps({
                'input': ['Same retained corpus under corrected currentness runtime'], 'model': spend.MODEL,
                'input_type': 'document', 'truncation': True, 'output_dimension': 1024, 'output_dtype': 'float'})})
            spend.finish(state, {'key': request['key'], 'token': request['token'], 'status': 200,
                'request_id': '7'*32, 'payload': {'model': spend.MODEL, 'usage': {'total_tokens': 52},
                    'data': [{'index': 0, 'embedding': [.25]*1024}]}})
            for name in p.VECTORS:
                (f.root/name).write_bytes(('new synthetic coherent vector asset '+name).encode())
            (f.root/p.VECTORS[-1]).write_bytes(c.encoded({'status': 'written', 'model': spend.MODEL,
                'API_request_count': 1, 'usage_total_tokens': 52, 'API_requests': [{'model': spend.MODEL,
                    'http_status': 200, 'request_id': '7'*32, 'usage_total_tokens': 52, 'passage_count': 1}]}))
            spend.checkpoint(state, {'operation_sha256': prepared['operation_sha256'], 'outputs': p.hashes(f.root, p.VECTORS)})
            # The coherent writer now made the packet eligible; no old vector
            # row was relabelled as a corrected completion.
            sealed = p.checkpoint_modern(f.root/'receipt.json', state, root=f.root)
        ledger = spend.ledger(state).read()
        self.assertEqual(ledger['requests'][:len(f.original['requests'])], f.original['requests'])
        self.assertEqual(len(ledger['requests']), len(f.original['requests'])+1)
        self.assertEqual(ledger['requests'][-1]['stage'], 'reconciled_vectors')
        self.assertEqual(sealed['vector_accounting']['classification'], 'budgeted')
        self.assertEqual(sealed['vector_accounting']['accounting_origin']['requests'][0]['id'], request['token'])
        self.assertEqual(sealed['retained_requests'], p.retained_requests(f.original))
        f.http.assert_not_called()

    def test_prefix_guard_preserves_every_original_row_and_refuses_other_paid_stages_or_reset(self):
        f = self.f
        value = {'projection_kind':'administrative_submission','parent_run':'123',
            'retained_requests':p.retained_requests(f.original)}
        for fault in ('changed-prefix', 'missing-prefix', 'new-document', 'new-team', 'new-provider', 'new-model',
                      'new-id', 'budget-reset', 'request-cap-reset'):
            ledger = deepcopy(f.original)
            if fault == 'changed-prefix': ledger['requests'][0]['charged_microusd'] += 1
            elif fault == 'missing-prefix': ledger['requests'].clear()
            elif fault == 'budget-reset': ledger['limit_microusd'] = 4_000_000
            elif fault == 'request-cap-reset': ledger['max_requests'] = 600
            else:
                row = {'id':'8'*32,'key':'9'*64,'provider':'voyage','model':spend.MODEL,
                    'stage':'reconciled_vectors','charged_microusd':100,'reserved_microusd':100,
                    'status':'reserved_unknown'}
                if fault == 'new-document': row['stage'] = 'cov4'
                elif fault == 'new-team': row['stage'] = 'team_generation'
                elif fault == 'new-provider': row['provider'] = 'anthropic'
                elif fault == 'new-model': row['model'] = 'unreviewed-model'
                else: row['key'] = 'unmanaged-key'
                ledger['requests'].append(row)
            with self.subTest(fault=fault), self.assertRaisesRegex(ValueError, 'administrative_'):
                p.require_administrative_budget(value, ledger)

    def test_unknown_vector_reservation_is_preserved_at_full_charge_not_redispatched(self):
        f = self.f; state=f.root/'unknown-vector'
        self.prepare(state, changed=True)
        with self.environment(changed=True) as packet:
            spend.prepare(state, packet)
            body={'url':spend.URL,'body':json.dumps({'input':['Bounded corrected corpus'], 'model':spend.MODEL,
                'input_type':'document','truncation':True,'output_dimension':1024,'output_dtype':'float'})}
            reserved=spend.reserve(state,body)
            before=spend.ledger(state).read()
            p.require_administrative_budget(spend.context(state),before)
            with self.assertRaisesRegex(Exception,'unknown'):
                spend.reserve(state,body)
            after=spend.ledger(state).read()
            self.assertEqual(after,before)
            self.assertEqual(after['requests'][-1]['id'],reserved['token'])
            self.assertEqual(after['requests'][-1]['charged_microusd'],after['requests'][-1]['reserved_microusd'])
        f.http.assert_not_called()

    def test_completed_child_reuses_exact_kind_receipt_and_no_second_reservation(self):
        f = self.f; state = f.root / 'first'; prepared = self.prepare(state)
        with self.environment():
            receipt = p.checkpoint_modern(f.root / 'receipt.json', state, root=f.root)
        child = deepcopy(f.manifest); child.pop('candidate_id')
        child['derived_from_candidate'] = f.cid
        child['program_area_revalidation'] = receipt | {'affected_generation': {
            'generation_run_id': '456', 'generation_run_attempt': '1', 'generation_sha': 'e' * 40}}
        child['candidate_id'] = c.digest(c.encoded(child))
        bundle = f.root / 'complete'
        (bundle / 'files').mkdir(parents=True)
        (bundle / 'candidate.json').write_bytes(c.encoded(child))
        for name, raw in f.raw.items():
            target = bundle / 'files' / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        p.record_modern_candidate(state, bundle)
        f.add_artifact('candidate-' + child['candidate_id'], '456', {'candidate.json': c.encoded(child),
            **{'files/' + n: raw for n, raw in f.raw.items()}})
        f.add_artifact(prepared['reservation_artifact'], '456', {'reservation.json': Path(prepared['reservation_path']).read_bytes()})
        f.add_artifact(prepared['state_artifact'], '456', f.state_files(state))
        f.runs[('456', '1')]['status'] = 'completed'
        f.runs[('789', '1')] = f.run_meta('789', '1', '9' * 40, current=True)
        with patch.object(c, 'verify_dependencies'):
            result = self.prepare(f.root / 'cold', current='789', output=f.root / 'restored-child')
        self.assertEqual(result['candidate_id'], child['candidate_id'])
        self.assertEqual(result['artifact_run'], '456')
        self.assertEqual(result['upload_candidate'], 'false')
        self.assertFalse((f.root / 'cold-reservation').exists())
        self.assertEqual(spend.ledger(f.root / 'cold').read()['requests'], f.original['requests'])
        self.assertEqual((f.root / 'restored-child/candidate.json').read_bytes(), (bundle / 'candidate.json').read_bytes())

    def test_scope_allows_only_admin_selection_semantics(self):
        base = {group: {'files': {'unchanged': 'a'}, 'sha256': 'a'} for group in ('source', 'teams', 'semantic')}
        original = {'generation_sha': 'a' * 40, 'dependency_groups': base}
        selected = deepcopy(base)
        selected['source']['files']['scripts/submission_schedule.py'] = 'b'
        selected['source']['files']['scripts/currentness.py'] = 'b'
        selected['semantic']['files']['assets/submission-schedule.js'] = 'b'
        selected['semantic']['files']['assets/search-retrieval.js'] = 'b'
        selected['semantic']['files']['tools/run_search_diagnosis.mjs'] = 'b'
        with patch('tools.release_dependencies.snapshot', return_value=selected):
            p.modern_scope(self.f.root, original, 'administrative_submission')
            with self.assertRaisesRegex(ValueError, 'extractor_only_change'):
                p.modern_scope(self.f.root, original)
        for group, name in [('source', 'scripts/notice_schedule.py'), ('semantic', 'assets/search-hybrid.js'),
                            ('teams', 'scripts/build_opportunity_teams.py')]:
            changed = deepcopy(selected); changed[group]['files'][name] = 'b'
            with self.subTest(group=group), patch('tools.release_dependencies.snapshot', return_value=changed):
                with self.assertRaisesRegex(ValueError, 'extractor_only_change'):
                    p.modern_scope(self.f.root, original, 'administrative_submission')


if __name__ == '__main__':
    unittest.main()
