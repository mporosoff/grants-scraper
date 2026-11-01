"""Two-document recovery preserves native ownership across partial acquisition."""
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
from tools import catalog_correction_release as entrypoint, catalog_reconcile_spend as spend
from tools import release_candidate as c, program_area_history as history, scheduled_catalog as daily
from tools.offline_spend import atomic_json, identity


class PrimaryDocumentReleaseContract(unittest.TestCase):
    def environment(self, **changes):
        return {'GITHUB_REPOSITORY': 'mporosoff/grants-scraper', 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_WORKFLOW_REF': 'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main',
            'REQUESTED_STAGE': 'primary-document-revalidation', 'CANDIDATE_RUN': '123456',
            'CANDIDATE_ID': 'a' * 64, **changes}

    def test_explicit_selector_has_no_llm_or_automatic_generation_authority(self):
        with patch.object(c, 'git', return_value='b' * 40):
            result = bridge.plan(Path('.'), self.environment())
        self.assertEqual((result['stage'], result['program_area_mode'], result['projection_kind']),
            ('program-area-revalidation', 'modern', 'primary_document'))
        self.assertEqual((result['candidate_run'], result['candidate_id']), ('123456', 'a' * 64))
        self.assertEqual((result['openai'], result['anthropic']), ('false', 'false'))
        environment = self.environment(RUNNER_TEMP='.')
        with patch.dict(os.environ, environment, clear=True), patch.object(bridge, 'plan', return_value=result), \
                patch.object(entrypoint, 'atomic_json'), patch.object(entrypoint, 'output'), \
                patch('tools.plan_release.main') as ordinary:
            entrypoint.plan()
        ordinary.assert_not_called()
        for delta in ({'GITHUB_EVENT_NAME': 'schedule'}, {'RECEIPT_RUN': '123'},
                      {'CANDIDATE_RUN': str(p.PARENT_RUN), 'CANDIDATE_ID': p.PARENT_CANDIDATE}):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                bridge.plan(Path('.'), self.environment(**delta))

    def test_dependency_scope_is_closed_to_the_affected_source_family(self):
        base = {group: {'files': {'unchanged': 'a'}, 'fingerprint': 'a'}
            for group in ('source', 'teams', 'semantic')}
        original = {'generation_sha': 'a' * 40, 'dependency_groups': base}
        selected = deepcopy(base)
        source_files = {'scripts/source_documents.py', 'scripts/pull_grants.py', 'scripts/enrich_catalog.py',
            'scripts/extract_document_evidence.py', 'scripts/subtopic_sources.py', 'scripts/notice_semantics.py',
            'scripts/notice_schedule.py', 'scripts/notice_awards.py', 'scripts/submission_schedule.py',
            'scripts/notice_duration.py', 'scripts/notice_fact_guards.py',
            'scripts/build_changes.py', 'scripts/build_feeds.py'}
        selected['source']['files'].update({name: 'b' for name in source_files})
        with patch('tools.release_dependencies.snapshot', return_value=selected), patch.object(c, 'git'):
            p.modern_scope(Path('.'), original, 'primary_document')
            with self.assertRaises(ValueError): p.modern_scope(Path('.'), original, 'document_facts')
        for group, name in [('source', 'scripts/sources/adapters/sam_gov.py'),
                            ('source', 'scripts/notice_eligibility.py'),
                            ('teams', 'scripts/build_opportunity_teams.py'), ('semantic', 'assets/search-hybrid.js')]:
            changed = deepcopy(selected); changed[group]['files'][name] = 'c'
            with self.subTest(name=name), patch('tools.release_dependencies.snapshot', return_value=changed), \
                    self.assertRaisesRegex(ValueError, 'extractor_only_change'):
                p.modern_scope(Path('.'), original, 'primary_document')
        with patch.object(p, 'hashes', return_value={}) as hashes:
            p.modern_contract(Path('.'), 'primary_document')
        self.assertIn('config/primary_document_recovery.json', hashes.call_args.args[1])
        self.assertIn('tools/primary_document_revalidation.py', hashes.call_args.args[1])
        self.assertIn('tools/corpus_clock.mjs', hashes.call_args.args[1])
        self.assertIn('tools/document_fact_revalidation.py', hashes.call_args.args[1])
        self.assertTrue(source_files <= set(hashes.call_args.args[1]))

    def test_only_primary_recipe_admits_its_bound_vector_accounting_helper_change(self):
        base = {group: {'files': {}, 'fingerprint': 'a'} for group in ('source', 'teams', 'semantic')}
        changed = deepcopy(base)
        changed['semantic']['files']['tools/catalog_reconcile_spend.py'] = 'b'*64
        original = {'generation_sha': 'a'*40, 'dependency_groups': base}
        with patch('tools.release_dependencies.snapshot', return_value=changed), patch.object(c, 'git'):
            p.modern_scope(Path('.'), original, 'primary_document')
            for kind in ('program_area', 'document_facts', 'administrative_submission'):
                with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'extractor_only_change'):
                    p.modern_scope(Path('.'), original, kind)
            changed['semantic']['files']['assets/search-hybrid.js'] = 'c'*64
            with self.assertRaisesRegex(ValueError, 'extractor_only_change'):
                p.modern_scope(Path('.'), original, 'primary_document')
        self.assertIn('tools/catalog_reconcile_spend.py', p.MODERN_OPERATION_FILES)

    def test_only_primary_projection_can_change_enrichment_and_child_cache_stays_retained(self):
        files = {name: 'a' * 64 for name in p.PROJECTION + p.PRIMARY_DOCUMENT_OUTPUTS}
        self.assertTrue({'feeds/changes.json', 'feeds/changes.xml'} <= set(files))
        self.assertEqual(set(p.projection_names({'projection_kind': 'primary_document', 'projection_hashes': files})), set(files))
        for kind in ('program_area', 'document_facts', 'administrative_submission'):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                p.projection_names({'projection_kind': kind, 'projection_hashes': files})
        for name in ('data/source_records.json', 'data/subtopics.js'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                p.projection_names({'projection_kind': 'primary_document',
                    'projection_hashes': files | {name: 'b' * 64}})

    def test_actual_workflow_retains_failed_acquisition_but_never_dispatches_vectors_from_it(self):
        flow = yaml.safe_load((c.ROOT/'.github/workflows/refresh-opportunities.yml').read_text(encoding='utf-8'))
        self.assertIn('primary-document-revalidation', flow.get('on', flow.get(True))['workflow_dispatch']['inputs']['stage']['options'])
        job = flow['jobs']['program-area-revalidation']; steps = {s['id']: s for s in job['steps'] if s.get('id')}
        for name in ('modern-reservation-upload', 'modern-state-upload'):
            condition = steps[name]['if']
            values = {'always()': 'True', 'steps.restore.outputs.candidate_id': repr(''),
                'steps.prepare.outputs.candidate_id': repr(''), 'steps.prepare.outputs.modern': repr('true'),
                'steps.prepare.outcome': repr('failure'), 'needs.plan.outputs.projection_kind': repr('primary_document')}
            for key, value in values.items(): condition = condition.replace(key, value)
            self.assertTrue(eval(condition.replace('&&', 'and').replace('||', 'or'), {'__builtins__': {}}, {}))
            self.assertNotIn('overwrite', steps[name]['with'])
        # GitHub applies success() implicitly unless a status function appears.
        # A failed prepare therefore cannot reach either credentialed step.
        for name in ('vectors', 'modern-vectors'):
            self.assertNotIn('always()', steps[name]['if'])
            self.assertNotIn('failure()', steps[name]['if'])
        self.assertFalse(any(key in step.get('env', {}) for step in job['steps']
            for key in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY')))
        self.assertEqual([step['id'] for step in job['steps'] if 'VOYAGE_API_KEY' in step.get('env', {})], ['vectors', 'modern-vectors'])

    def test_actual_closeout_names_the_exact_retry(self):
        flow = yaml.safe_load((c.ROOT/'.github/workflows/refresh-opportunities.yml').read_text(encoding='utf-8'))
        closeout = flow['jobs']['closeout']; script = closeout['steps'][0]['with']['script']
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
        needs = {name: {'result': 'skipped', 'outputs': {}} for name in closeout['needs']}
        needs['plan'] = {'result': 'success', 'outputs': {'stage': 'program-area-revalidation',
            'projection_kind': 'primary_document', 'candidate_id': 'a' * 64, 'candidate_run': '123'}}
        needs['program-area-revalidation']['result'] = 'failure'
        raw = subprocess.check_output([shutil.which('node') or 'node', '-e', harness],
            input=c.encoded({'script': script, 'needs': needs}), cwd=c.ROOT, timeout=30)
        body = json.loads(raw)['body']
        self.assertIn('Original lifecycle stage: primary-document-revalidation\n', body)
        self.assertIn('Allowed next retry: primary-document-revalidation\n', body)


class PrimaryDocumentCheckpointContract(unittest.TestCase):
    def setUp(self):
        self.f = budget_fixtures.ModernProgramAreaBudget()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)

    @contextmanager
    def environment(self, projector, current='456'):
        f = self.f
        with (patch.dict(os.environ, GITHUB_RUN_ID=current, GITHUB_RUN_ATTEMPT='1',
                GITHUB_SHA=f.runs[(current, '1')]['head_sha'], GITHUB_OUTPUT=str(f.root/'github-output')),
                patch.object(p, 'modern_scope'), patch.object(p, 'modern_contract', return_value={'recipe': '1' * 64}),
                patch.object(p, 'modern_projection', side_effect=projector),
                patch.object(p, 'vector_packet', return_value=dict(f.packet, retained_asset_eligible=True)) as vector):
            yield vector

    def prepare(self, name):
        return p.prepare_modern(self.f.bundle, self.f.root/'receipt.json', self.f.root/name,
            '123', self.f.cid, root=self.f.root, api=self.f.api, projection_kind='primary_document')

    def test_constructor_only_replays_the_sealed_projection_and_unchanged_allowance(self):
        f = self.f; calls = []
        outputs = {name: ('safe retained output ' + name).encode() for name in p.PROJECTION}
        changes = {'source_requests': 0, 'document_requests': 2, 'document_ai_requests': 0, 'team_requests': 0}
        def projection(parent, audit, identifier, kind, *, checkpoint_directory, acquire):
            calls.append(acquire)
            self.assertEqual(checkpoint_directory, f.root/'first/primary-document-projection')
            return outputs, changes
        with self.environment(projection):
            self.prepare('first')
            p.checkpoint_modern(f.root/'receipt.json', f.root/'first', root=f.root)
            with patch.dict(os.environ, PROGRAM_AREA_VECTOR_STATE=str(f.root/'first')):
                retained = p.verify_modern_inputs(f.root, f.manifest, f.root/'receipt.json', api=f.api)
        self.assertEqual(calls, [True, False])
        self.assertEqual(retained, {'config/retained-science.json': f.manifest['files']['config/retained-science.json']})
        self.assertEqual(spend.ledger(f.root/'first').read()['requests'], f.original['requests'])
        f.http.assert_not_called()

    def test_primary_recovery_rejects_ai_work_budget_reset_and_changed_original_rows(self):
        f = self.f
        value = {'projection_kind': 'primary_document', 'parent_run': '123',
            'retained_requests': p.retained_requests(f.original)}
        for fault in ('reset', 'prefix', 'classifier'):
            ledger = deepcopy(f.original)
            if fault == 'reset': ledger['limit_microusd'] *= 2
            elif fault == 'prefix': ledger['requests'][0]['charged_microusd'] += 1
            else:
                ledger['requests'].append({'provider': 'anthropic', 'model': 'unallowed', 'stage': 'cov4',
                    'id': '8' * 32, 'key': '9' * 64, 'status': 'valid', 'charged_microusd': 1, 'reserved_microusd': 1})
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                p.require_administrative_budget(value, ledger)

    def test_partial_acquisition_is_reserved_and_cold_replay_preserves_completed_entry(self):
        f = self.f
        def interrupted(parent, audit, identifier, kind, *, checkpoint_directory, acquire):
            self.assertTrue(acquire); self.assertEqual(kind, 'primary_document')
            self.assertEqual(p.read(f.root/'first/reservation.json')['projection_kind'], kind)
            self.assertIn('state_artifact=', (f.root/'github-output').read_text())
            atomic_json(checkpoint_directory/'first-complete.json', {'safe_entry': True, 'original_audit': audit})
            raise ValueError('second_pinned_document_unavailable')
        with self.environment(interrupted) as vectors, self.assertRaisesRegex(ValueError, 'second_pinned'):
            self.prepare('first')
        vectors.assert_not_called()
        self.assertEqual(spend.ledger(f.root/'first').read()['requests'], f.original['requests'])
        outputs = dict(line.split('=', 1) for line in (f.root/'github-output').read_text().splitlines())
        f.add_artifact(outputs['reservation_artifact'], '456', {'reservation.json': Path(outputs['reservation_path']).read_bytes()})
        f.add_artifact(outputs['state_artifact'], '456', f.state_files(f.root/'first'))
        f.runs[('456', '1')]['status'] = 'completed'
        f.runs[('789', '1')] = f.run_meta('789', '1', '9' * 40, current=True)
        def recovered(parent, audit, identifier, kind, *, checkpoint_directory, acquire):
            self.assertEqual(p.read(checkpoint_directory/'first-complete.json'), {'safe_entry': True, 'original_audit': audit})
            return ({name: ('safe two-entry projection ' + name).encode() for name in p.PROJECTION},
                {'source_requests': 0, 'document_requests': 2, 'document_ai_requests': 0, 'team_requests': 0})
        with self.environment(recovered, current='789'):
            result = self.prepare('restored')
        self.assertEqual(result['vector_reused'], 'true')
        self.assertEqual(spend.ledger(f.root/'restored').read()['requests'], f.original['requests'])
        receipt = p.read(f.root/'receipt.json')
        self.assertEqual(receipt['new_document_requests'], 2)
        self.assertEqual(receipt['retained_requests'], p.retained_requests(f.original))
        self.assertEqual(len(receipt['consumed_checkpoints']), 1)
        f.http.assert_not_called()

    def test_completed_changed_recipe_restores_paid_child_and_consumed_native_checkpoint(self):
        f = self.f; state = f.root/'first'
        outputs = {name: ('safe two-document projection '+name).encode() for name in p.PROJECTION}
        changes = {'source_requests': 0, 'document_requests': 2, 'document_ai_requests': 0, 'team_requests': 0}
        contract = {'tools/primary_document_revalidation.py': '1'*64}
        packet = dict(f.packet, corpus_sha256='8'*64)
        def projection(parent, audit, identifier, kind, *, checkpoint_directory, acquire):
            self.assertTrue(acquire)
            saved = checkpoint_directory/'completed-pdfs.json'
            new_requests = 0 if saved.exists() else 2
            if saved.exists(): self.assertEqual(p.read(saved), {'acquisitions': 2})
            else: atomic_json(saved, {'acquisitions': 2})
            return outputs, changes | {'new_document_requests': new_requests}
        with self.environment(projection), patch.object(p, 'modern_contract', return_value=contract), \
                patch.object(p, 'vector_packet', return_value=packet):
            prepared = self.prepare('first')
        spend.prepare(state, packet)
        request = spend.reserve(state, {'url': spend.URL, 'body': json.dumps({'input': ['Corrected public passage'],
            'model': spend.MODEL, 'input_type': 'document', 'truncation': True, 'output_dimension': 1024, 'output_dtype': 'float'})})
        spend.finish(state, {'key': request['key'], 'token': request['token'], 'status': 200,
            'request_id': '7'*32, 'payload': {'model': spend.MODEL, 'usage': {'total_tokens': 52},
                'data': [{'index': 0, 'embedding': [.25]*1024}]}})
        vector_raw = {name: ('corrected whole asset '+name).encode() for name in p.VECTORS}
        vector_raw[p.VECTORS[-1]] = c.encoded({'status': 'written', 'model': spend.MODEL,
            'API_request_count': 1, 'usage_total_tokens': 52, 'API_requests': [{'model': spend.MODEL,
                'http_status': 200, 'usage_total_tokens': 52, 'passage_count': 1, 'request_id': '7'*32}]})
        for name, raw in vector_raw.items(): (f.root/name).write_bytes(raw)
        value = spend.context(state)
        spend.checkpoint(state, {'operation_sha256': value['operation_sha256'], 'outputs': p.hashes(f.root, p.VECTORS)})
        with patch.object(p, 'modern_contract', return_value=contract), \
                patch.object(p, 'vector_packet', return_value=packet | {'retained_asset_eligible': True}):
            sealed = p.checkpoint_modern(f.root/'receipt.json', state, root=f.root)
        child_raw = f.raw | outputs | vector_raw
        child = deepcopy(f.manifest); child.pop('candidate_id')
        child.update(files={name: p.sha(raw) for name,raw in child_raw.items()}, derived_from_candidate=f.cid,
            dependency_groups={'semantic': {'files': {'tools/corpus_clock.mjs': 'c'*64}}},
            program_area_revalidation=sealed | {'affected_generation': {'generation_run_id': '456',
                'generation_run_attempt': '1', 'generation_sha': 'e'*40, 'generation_timestamp': '2026-11-01T21:55:00Z'}})
        child['candidate_id'] = c.digest(c.encoded(child)); bundle = f.root/'completed-child'
        atomic_json(bundle/'candidate.json', child)
        for name,raw in child_raw.items():
            target=bundle/'files'/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(raw)
        p.record_modern_candidate(state, bundle)
        f.add_artifact('candidate-'+child['candidate_id'], '456', {'candidate.json': c.encoded(child),
            **{'files/'+name: raw for name,raw in child_raw.items()}})
        f.add_artifact(prepared['reservation_artifact'], '456', {'reservation.json': Path(prepared['reservation_path']).read_bytes()})
        f.add_artifact(prepared['state_artifact'], '456', f.state_files(state))
        before = spend.ledger(state).read(); f.runs[('456','1')]['status']='completed'
        f.runs[('789','1')]=f.run_meta('789','1','9'*40,current=True)
        updated = {'tools/primary_document_revalidation.py': '2'*64, 'tools/corpus_clock.mjs': 'c'*64}
        with self.environment(projection,current='789'), patch.object(p,'modern_contract',return_value=updated), \
                patch.object(p,'vector_packet',return_value=packet):
            resumed=self.prepare('cold')
        cold=f.root/'cold'; context=spend.context(cold)
        self.assertEqual(spend.ledger(cold).read(),before)
        self.assertEqual(context['retained_vector_source']['candidate_id'],child['candidate_id'])
        self.assertEqual(p.read(cold/'primary-document-projection/completed-pdfs.json'),{'acquisitions':2})
        consumed=p.read(cold/'consumed-checkpoints.json')
        self.assertEqual(consumed[-1]['request_count'],2)
        self.assertEqual(consumed[-1]['candidate']['candidate_id'],child['candidate_id'])
        self.assertEqual(p.read(resumed['reservation_path'])['prior_ledger_sha256'],identity(before))
        self.assertEqual(p.read(f.root/'receipt.json')['new_document_requests'], 0)
        restored=spend.prepare(cold,packet)
        self.assertEqual(restored['status'],'restore')
        self.assertEqual(restored['outputs'],{name:p.sha(raw) for name,raw in vector_raw.items()})
        self.assertEqual(spend.ledger(cold).read(),before)
        f.http.assert_not_called()


class PrimaryDocumentHistoryContract(unittest.TestCase):
    def setUp(self):
        self.f = history_fixtures.ModernHistory(methodName='runTest')
        self.f.setUp(); self.addCleanup(self.f.doCleanups); f = self.f
        f.context.update(projection_kind='primary_document', retained_requests=p.retained_requests(f.ledger))
        f.context['operation_sha256'] = identity({k: v for k, v in f.context.items()
            if k not in {'operation_sha256', 'completed_candidate_id'}})
        f.receipt.update(projection_kind='primary_document', retained_requests=f.context['retained_requests'],
            operation_sha256=f.context['operation_sha256'])
        f.voucher.update(projection_kind='primary_document', operation_sha256=f.context['operation_sha256'])
        f.child.pop('candidate_id'); f.child['candidate_id'] = c.digest(c.encoded(f.child))
        f.context['completed_candidate_id'] = f.child['candidate_id']; f.pointer['candidate_id'] = f.child['candidate_id']
        for name in list(f.state):
            if name.startswith('complete-candidates/'): f.state.pop(name)
        f.state['complete-candidates/'+f.child['candidate_id']+'/candidate.json'] = f.child
        f.artifacts[-1]['name'] = 'candidate-'+f.child['candidate_id']; f.native_artifacts[:] = deepcopy(f.artifacts)

    def test_typed_completed_publication_retires_exact_parent(self):
        self.assertTrue(self.f.retire())

    def test_kind_mismatch_or_unproved_prefix_does_not_retire_owner(self):
        for kind in (None, 'document_facts', 'program_area'):
            if kind is None: self.f.voucher.pop('projection_kind', None)
            else: self.f.voucher['projection_kind'] = kind
            with self.subTest(kind=kind), self.assertRaisesRegex(daily.Hold, 'projection_kind'):
                self.f.retire()


if __name__ == '__main__':
    unittest.main()
