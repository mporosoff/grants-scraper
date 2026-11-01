"""Typed document-fact recovery keeps the original allowance and release route."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

import yaml

from tests import test_modern_program_area_budget as budget_fixtures
from tests import test_program_area_history as history_fixtures
from tools import program_area_revalidation as p, program_area_release as bridge
from tools import catalog_reconcile_spend as spend, release_candidate as c
from tools import program_area_history as history, scheduled_catalog as daily
from tools.offline_spend import atomic_json, identity


class DocumentFactReleaseContract(unittest.TestCase):
    def environment(self, **changes):
        return {"GITHUB_REPOSITORY": "mporosoff/grants-scraper", "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_WORKFLOW_REF": "mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main",
            "REQUESTED_STAGE": "document-fact-revalidation", "CANDIDATE_RUN": "123456",
            "CANDIDATE_ID": "a" * 64, **changes}

    def test_explicit_native_selector_preserves_identity_without_generation_authority(self):
        with patch.object(c, 'git', return_value='b' * 40):
            result = bridge.plan(Path('.'), self.environment())
        self.assertEqual((result['stage'], result['program_area_mode'], result['projection_kind']),
            ('program-area-revalidation', 'modern', 'document_facts'))
        self.assertEqual((result['candidate_run'], result['candidate_id']), ('123456', 'a' * 64))
        self.assertEqual((result['openai'], result['anthropic']), ('false', 'false'))
        for changes in ({'GITHUB_EVENT_NAME': 'schedule'}, {'RECEIPT_RUN': '123'},
                        {'QUALIFICATION_PILOT': 'true'}, {'CANDIDATE_RUN': str(p.PARENT_RUN),
                         'CANDIDATE_ID': p.PARENT_CANDIDATE}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                bridge.plan(Path('.'), self.environment(**changes))

    def test_explicit_bridge_cannot_fall_through_to_auto_generation(self):
        from tools import catalog_correction_release as existing
        environment = self.environment(RUNNER_TEMP='.')
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(bridge, 'plan', return_value={'stage': 'program-area-revalidation',
                    'projection_kind': 'document_facts'}) as explicit, \
                patch.object(existing, 'atomic_json'), patch.object(existing, 'output'), \
                patch('tools.plan_release.main') as ordinary:
            existing.plan()
        explicit.assert_called_once_with(existing.ROOT, environment)
        ordinary.assert_not_called()

    def test_operation_contract_keeps_legacy_defaults_and_pins_document_projection(self):
        self.assertEqual(p.projection_kind({}), 'program_area')
        with patch.object(p, 'hashes', return_value={}) as hashed:
            p.modern_contract(Path('.'))
            self.assertEqual(hashed.call_args.args[1], p.MODERN_OPERATION_FILES)
            p.modern_contract(Path('.'), 'document_facts')
            self.assertEqual(set(hashed.call_args.args[1]) - set(p.MODERN_OPERATION_FILES),
                {'tools/document_fact_revalidation.py', 'scripts/notice_semantics.py', 'scripts/notice_fact_guards.py'})

    def test_document_scope_refuses_other_source_team_or_semantic_changes(self):
        base = {group: {'files': {'unchanged': 'a'}, 'fingerprint': 'a'}
            for group in ('source', 'teams', 'semantic')}
        original = {'generation_sha': 'a' * 40, 'dependency_groups': base}
        selected = deepcopy(base)
        selected['source']['files'].update({name: 'b' for name in
            ('scripts/extract_document_evidence.py', 'scripts/notice_semantics.py', 'scripts/notice_fact_guards.py')})
        with patch('tools.release_dependencies.snapshot', return_value=selected), patch.object(c, 'git'):
            p.modern_scope(Path('.'), original, 'document_facts')
            with self.assertRaisesRegex(ValueError, 'extractor_only_change'):
                p.modern_scope(Path('.'), original)
        for group, name in [('source', 'scripts/submission_schedule.py'),
                            ('source', 'scripts/build_catalog.py'), ('teams', 'scripts/build_opportunity_teams.py'),
                            ('semantic', 'assets/search-hybrid.js')]:
            changed = deepcopy(selected); changed[group]['files'][name] = 'c'
            with self.subTest(name=name), patch('tools.release_dependencies.snapshot', return_value=changed), \
                    self.assertRaisesRegex(ValueError, 'extractor_only_change'):
                p.modern_scope(Path('.'), original, 'document_facts')

    def test_workflow_uses_existing_private_checkpoint_and_budgeted_vector_path(self):
        flow = yaml.safe_load((c.ROOT / '.github/workflows/refresh-opportunities.yml').read_text())
        self.assertIn('document-fact-revalidation', flow.get('on', flow.get(True))['workflow_dispatch']['inputs']['stage']['options'])
        job = flow['jobs']['program-area-revalidation']; steps = {s['id']: s for s in job['steps'] if s.get('id')}
        self.assertEqual(steps['prepare']['env']['EVIDENCE_PROJECTION_KIND'], '${{ needs.plan.outputs.projection_kind }}')
        self.assertIn('--projection-kind "$EVIDENCE_PROJECTION_KIND"', steps['prepare']['run'])
        self.assertIn("steps.prepare.outputs.vector_reused != 'true'", steps['modern-vectors']['if'])
        self.assertIn("steps.modern-reservation-upload.outcome == 'success'", steps['modern-vectors']['if'])
        self.assertEqual([s['id'] for s in job['steps'] if 'VOYAGE_API_KEY' in s.get('env', {})], ['vectors', 'modern-vectors'])
        self.assertFalse(any(k in s.get('env', {}) for s in job['steps'] for k in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY')))
        self.assertTrue(steps['modern-state-upload']['with']['include-hidden-files'])
        self.assertIn("steps.prepare.outcome == 'success'", steps['modern-state-upload']['if'])

    def test_actual_closeout_retains_typed_retry_before_candidate_and_resumes_validation_after_it(self):
        flow = yaml.safe_load((c.ROOT / '.github/workflows/refresh-opportunities.yml').read_text())
        closeout = flow['jobs']['closeout']
        script = closeout['steps'][0]['with']['script']
        harness = """
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
process.env.RESULTS=JSON.stringify(input.needs); process.env.GITHUB_RUN_ATTEMPT='1';
const observed={}; const core={summary:{addRaw(body){observed.body=body;return this;},async write(){}},setFailed(){}};
const github={rest:{issues:{async listForRepo(){return {data:[]};},async create(){},async update(){}}}};
const context={runId:700,eventName:'workflow_dispatch',sha:'b'.repeat(40),serverUrl:'https://github.com',repo:{owner:'o',repo:'r'}};
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('core','github','context',input.script)(core,github,context)
 .then(()=>process.stdout.write(JSON.stringify(observed))).catch(e=>{console.error(e);process.exitCode=1;});
"""
        for failed, next_stage in [('program-area-revalidation', 'document-fact-revalidation'), ('candidate', 'validate')]:
            needs = {name: {'result': 'skipped', 'outputs': {}} for name in closeout['needs']}
            needs['plan'] = {'result': 'success', 'outputs': {'stage': 'program-area-revalidation',
                'projection_kind': 'document_facts', 'candidate_id': 'a' * 64, 'candidate_run': '123'}}
            needs[failed]['result'] = 'failure'
            raw = subprocess.check_output([shutil.which('node') or 'node', '-e', harness],
                input=c.encoded({'script': script, 'needs': needs}), cwd=c.ROOT, timeout=30)
            body = json.loads(raw)['body']
            self.assertIn('Original lifecycle stage: document-fact-revalidation\n', body)
            self.assertIn('Allowed next retry: ' + next_stage + '\n', body)


class DocumentFactBudgetContract(unittest.TestCase):
    def setUp(self):
        self.f = budget_fixtures.ModernProgramAreaBudget()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)

    @contextmanager
    def environment(self, *, current='456', changed=False, recipe='1' * 64):
        f = self.f
        outputs = {name: ('bounded document facts ' + name).encode() for name in p.PROJECTION}
        packet = dict(f.packet, retained_asset_eligible=not changed)
        if changed: packet['corpus_sha256'] = '8' * 64
        with patch.dict(os.environ, GITHUB_RUN_ID=current, GITHUB_RUN_ATTEMPT='1',
                GITHUB_SHA=f.runs[(current, '1')]['head_sha']), patch.object(p, 'modern_scope'), \
                patch.object(p, 'modern_contract', return_value={'tools/document_fact_revalidation.py': recipe}), \
                patch.object(p, 'modern_projection', return_value=(outputs, {'projection_kind': 'document_facts',
                    'source_requests': 0, 'document_ai_requests': 0, 'team_requests': 0})), \
                patch.object(p, 'vector_packet', return_value=packet):
            yield

    def prepare(self, name, *, current='456', changed=False, recipe='1' * 64, output=None):
        with self.environment(current=current, changed=changed, recipe=recipe):
            return p.prepare_modern(self.f.bundle, self.f.root / 'receipt.json', self.f.root / name,
                '123', self.f.cid, root=self.f.root, api=self.f.api, output=output, projection_kind='document_facts')

    def test_preparation_seals_kind_prefix_and_retains_original_vectors_without_provider_work(self):
        result = self.prepare('first'); f = self.f
        value = spend.context(f.root / 'first')
        for document in (value, p.read(result['reservation_path']), p.read(f.root / 'receipt.json')):
            self.assertEqual(document['projection_kind'], 'document_facts')
        self.assertEqual(value['retained_requests'], p.retained_requests(f.original))
        self.assertEqual(value['operation_sha256'], identity({k: v for k, v in value.items() if k != 'operation_sha256'}))
        self.assertEqual(result['vector_reused'], 'true')
        self.assertEqual(spend.ledger(f.root / 'first').read()['requests'], f.original['requests'])
        self.assertEqual(p.hashes(f.root, p.VECTORS), {n: p.sha(f.raw[n]) for n in p.VECTORS})
        f.http.assert_not_called()

    def test_changed_corpus_retains_original_allowance_and_refuses_unmanaged_append(self):
        result = self.prepare('changed', changed=True); f = self.f
        self.assertEqual(result['vector_reused'], 'false')
        value = spend.context(f.root / 'changed'); original = spend.ledger(f.root / 'changed').read()
        self.assertEqual((original['limit_microusd'], original['max_requests']), (2_000_000, 300))
        for fault in ('prefix', 'reset', 'document', 'team', 'unknown-undercharge'):
            ledger = deepcopy(original)
            if fault == 'prefix': ledger['requests'][0]['charged_microusd'] += 1
            elif fault == 'reset': ledger['limit_microusd'] = 4_000_000
            else:
                ledger['requests'].append({'id': '8' * 32, 'key': '9' * 64, 'provider': 'voyage',
                    'model': spend.MODEL, 'stage': {'document': 'cov4', 'team': 'team_generation'}.get(fault, 'reconciled_vectors'),
                    'charged_microusd': 1, 'reserved_microusd': 2, 'status': 'reserved_unknown'})
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                p.require_administrative_budget(value, ledger)
        f.http.assert_not_called()

    def completed_child(self):
        f = self.f; result = self.prepare('first')
        with self.environment(): receipt = p.checkpoint_modern(f.root / 'receipt.json', f.root / 'first', root=f.root)
        child = deepcopy(f.manifest); child.pop('candidate_id')
        child.update(derived_from_candidate=f.cid, program_area_revalidation=receipt | {'affected_generation': {
            'generation_run_id': '456', 'generation_run_attempt': '1', 'generation_sha': 'e' * 40}})
        child['candidate_id'] = c.digest(c.encoded(child)); bundle = f.root / 'complete'
        (bundle / 'files').mkdir(parents=True); (bundle / 'candidate.json').write_bytes(c.encoded(child))
        for name, raw in f.raw.items():
            target = bundle / 'files' / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        p.record_modern_candidate(f.root / 'first', bundle)
        f.add_artifact('candidate-' + child['candidate_id'], '456', {'candidate.json': c.encoded(child),
            **{'files/' + n: raw for n, raw in f.raw.items()}})
        f.add_artifact(result['reservation_artifact'], '456', {'reservation.json': Path(result['reservation_path']).read_bytes()})
        f.add_artifact(result['state_artifact'], '456', f.state_files(f.root / 'first'))
        f.runs[('456', '1')]['status'] = 'completed'
        f.runs[('789', '1')] = f.run_meta('789', '1', '9' * 40, current=True)
        return child

    def test_completed_child_restores_exact_bytes_without_second_reservation(self):
        child = self.completed_child(); f = self.f
        with patch.object(c, 'verify_dependencies'):
            result = self.prepare('restored', current='789', output=f.root / 'restored-child')
        self.assertEqual(result['candidate_id'], child['candidate_id'])
        self.assertEqual(result['artifact_run'], '456')
        self.assertEqual(result['upload_candidate'], 'false')
        self.assertFalse((f.root / 'restored-reservation').exists())
        self.assertEqual(spend.ledger(f.root / 'restored').read()['requests'], f.original['requests'])
        with self.assertRaisesRegex(ValueError, 'projection_kind_mismatch'):
            p.modern_history(f.bundle, f.root / 'wrong-kind', f.root, 'owner/repo', '123', f.cid, f.api)
        f.http.assert_not_called()

    def test_changed_projection_recipe_reprojects_on_new_dispatch_without_losing_accounting(self):
        child = self.completed_child(); f = self.f
        with patch.object(c, 'verify_dependencies'):
            result = self.prepare('corrected', current='789', recipe='2' * 64, output=f.root / 'not-reused')
        self.assertNotIn('candidate_id', result)
        value = spend.context(f.root / 'corrected')
        self.assertNotEqual(value['operation_sha256'], child['program_area_revalidation']['operation_sha256'])
        self.assertNotIn('completed_candidate_id', value)
        self.assertEqual(value['retained_requests'], p.retained_requests(f.original))
        self.assertEqual(spend.ledger(f.root / 'corrected').read()['requests'], f.original['requests'])
        self.assertFalse((f.root / 'not-reused').exists())
        f.http.assert_not_called()


class DocumentFactHistoryContract(unittest.TestCase):
    def setUp(self):
        self.f = history_fixtures.ModernHistory(methodName='runTest')
        self.f.setUp(); self.addCleanup(self.f.doCleanups); f = self.f
        f.context.update(projection_kind='document_facts', retained_requests=p.retained_requests(f.ledger))
        f.context['operation_sha256'] = identity({k: v for k, v in f.context.items()
            if k not in {'operation_sha256', 'completed_candidate_id'}})
        f.receipt.update(projection_kind='document_facts', retained_requests=f.context['retained_requests'],
            operation_sha256=f.context['operation_sha256'])
        f.voucher.update(projection_kind='document_facts', operation_sha256=f.context['operation_sha256'])
        self.reseal_child()

    def reseal_child(self):
        f = self.f
        f.child.pop('candidate_id'); f.child['candidate_id'] = c.digest(c.encoded(f.child))
        f.context['completed_candidate_id'] = f.child['candidate_id']; f.pointer['candidate_id'] = f.child['candidate_id']
        for name in list(f.state):
            if name.startswith('complete-candidates/'): f.state.pop(name)
        f.state['complete-candidates/' + f.child['candidate_id'] + '/candidate.json'] = f.child
        f.artifacts[-1]['name'] = 'candidate-' + f.child['candidate_id']; f.native_artifacts[:] = deepcopy(f.artifacts)

    def test_typed_publication_and_state_only_restore_retire_exact_original_work(self):
        self.assertTrue(self.f.retire())
        self.f.state_only_restorer()
        with patch.object(history, 'completed_restore') as restored:
            self.assertTrue(self.f.retire()); restored.assert_called_once()

    def test_missing_or_mismatched_kind_cannot_retire_document_work(self):
        for kind in (None, 'program_area', 'administrative_submission'):
            if kind is None: self.f.voucher.pop('projection_kind', None)
            else: self.f.voucher['projection_kind'] = kind
            with self.subTest(kind=kind), self.assertRaisesRegex(daily.Hold, 'projection_kind'):
                self.f.retire()

    def test_receipt_must_retain_original_request_proof_and_reject_new_document_work(self):
        self.f.receipt.pop('retained_requests')
        self.reseal_child()
        with self.assertRaisesRegex(daily.Hold, 'exact completed child and ledger'): self.f.retire()
        self.f.receipt['retained_requests'] = self.f.context['retained_requests']
        self.f.ledger['requests'].append({'id': '8' * 32, 'key': '9' * 64, 'provider': 'anthropic',
            'model': 'unallowed', 'stage': 'cov4', 'charged_microusd': 1, 'reserved_microusd': 1, 'status': 'valid'})
        self.f.receipt['ledger_sha256'] = identity(self.f.ledger)
        self.reseal_child()
        with self.assertRaisesRegex(daily.Hold, 'vector_only_append'): self.f.retire()

    def test_accounted_vector_append_retires_with_exact_original_prefix(self):
        self.f.ledger['requests'].append({'id': '8' * 32, 'key': '9' * 64, 'provider': 'voyage',
            'model': spend.MODEL, 'stage': 'reconciled_vectors', 'charged_microusd': 1,
            'reserved_microusd': 2, 'status': 'valid'})
        self.f.receipt['ledger_sha256'] = identity(self.f.ledger)
        self.reseal_child()
        self.assertTrue(self.f.retire())


if __name__ == '__main__':
    unittest.main()
