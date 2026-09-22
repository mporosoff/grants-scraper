"""Authenticated lost-state lifecycle using synthetic archives, no live calls."""
import copy
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import test_contextual_team_completion_policy as budget_fixture
from tools import contextual_team_checkpoint_recovery as recovery
from tools import contextual_team_checkpoint_disposition as disposition
from tools import team_recommender_executor as existing
from tools.offline_spend import atomic_json, encoded, identity, Deferred, ConfigurationFailure


def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for name, data in files.items():
            zipped.writestr(name, data)
    return output.getvalue()


def state_archive(state):
    return archive({p.relative_to(state).as_posix(): p.read_bytes() for p in state.rglob('*.json')})


class Fixture(unittest.TestCase):
    def setUp(self):
        self.budget = budget_fixture.CompletionBudget('runTest'); self.budget.setUp()
        self.addCleanup(self.budget.doCleanups)
        self.source = self.budget.state; self.prior = self.budget.install().read()
        self.root = self.source.parent; self.destination = self.root/'restored'
        self.p = copy.deepcopy(disposition.plan())
        prior = self.p['prior']; failed = self.p['failed']
        with patch.dict(os.environ, {'GITHUB_RUN_ID': str(prior['run']['id']),
                'GITHUB_RUN_ATTEMPT': str(prior['run']['run_attempt']), 'GITHUB_SHA': prior['run']['head_sha']}):
            existing.checkpoint(self.source)
        self.original_checkpoint = json.loads((self.source/'checkpoint.json').read_bytes())
        prior.update(ledger_sha256=existing.sha((self.source/'ledger.json').read_bytes()),
            checkpoint_sha256=existing.sha((self.source/'checkpoint.json').read_bytes()),
            requests=len(self.prior['requests']), requests_sha256=identity(self.prior['requests']),
            events=len(self.prior['events']), events_sha256=identity(self.prior['events']),
            native_counts=len(self.budget.counts), native_counts_sha256=identity(self.budget.counts))
        failed['reservation']['prior_ledger_sha256'] = prior['ledger_sha256']
        reservation_bytes = encoded(failed['reservation'])+b'\n'
        failed.update(reservation_sha256=existing.sha(reservation_bytes),
            reservation_identity=identity(failed['reservation']))
        self.bind(patch.object(disposition, 'plan', return_value=self.p))
        self.env = {'GITHUB_REPOSITORY': existing.REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_WORKFLOW_REF': existing.REPOSITORY+'/'+existing.WORKFLOW+'@refs/heads/main',
            'GITHUB_RUN_ID': '9001', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'a'*40,
            'GITHUB_OUTPUT': str(self.root/'github-output'), 'CONTEXTUAL_CHECK': json.dumps(recovery.SELECTOR),
            'CONTEXTUAL_JOB': '', 'PACKET_HASH': '', 'PACKET_COMMIT': ''}
        self.bind(patch.dict(os.environ, self.env))
        self.current = {'id': 9001, 'run_attempt': 1, 'head_sha': 'a'*40, 'head_branch': 'main',
            'event': 'workflow_dispatch', 'path': existing.WORKFLOW, 'status': 'in_progress', 'conclusion': None}
        self.runs = {prior['run']['id']: copy.deepcopy(prior['run']), failed['run']['id']: copy.deepcopy(failed['run']), 9001: self.current}
        self.artifacts = []; self.raws = {}; self.active = [self.current]
        self.add_artifact(prior['artifact'], prior['run'], '2026-09-21T21:03:00Z', state_archive(self.source))
        self.add_artifact(failed['artifact'], failed['run'], failed['artifact_created_at'], archive({'team-reservation.json': reservation_bytes}))
        self.source_bytes = {p.relative_to(self.source).as_posix(): p.read_bytes() for p in self.source.rglob('*.json')}
        self.args = SimpleNamespace(action='prepare', state=self.destination,
            reservation=self.root/'team-reservation.json', result=self.root/'result.json')

    def bind(self, value):
        result = value.start(); self.addCleanup(value.stop); return result

    def add_artifact(self, expected, run, clock, raw):
        expected['digest'] = 'sha256:'+existing.sha(raw)
        artifact = dict(expected, created_at=clock, expired=False,
            workflow_run={'id': run['id'], 'head_sha': run['head_sha'], 'head_branch': 'main'})
        self.artifacts.append(artifact); self.raws[artifact['id']] = raw
        return artifact

    def api(self, path):
        if path.startswith('actions/artifacts?'):
            return encoded({'artifacts': self.artifacts})
        if '?status=in_progress' in path:
            return encoded({'workflow_runs': self.active, 'total_count': len(self.active)})
        if path.startswith('actions/runs/'):
            bits = path.split('/'); key = (int(bits[2]), int(bits[4])) if len(bits) > 3 else int(bits[2])
            return encoded(self.runs[key])
        if path.startswith('actions/artifacts/'):
            aid = int(path.split('/')[2])
            return self.raws[aid] if path.endswith('/zip') else encoded(next(a for a in self.artifacts if a['id'] == aid))
        raise AssertionError('unexpected API route '+path)

    def restore(self, destination=None):
        return existing.restore(destination or self.destination, {}, self.api)

    def add_successor(self, run_id=9001, *, complete=False, record=None, attempt=1):
        run = dict(self.current, id=run_id, run_attempt=attempt, status='completed', conclusion='failure')
        if record is None:
            ledger = self.restore()
            record = recovery.reservation_record(run, ledger.checkpoint_disposition_anchor,
                existing.sha(ledger.path.read_bytes()))
        self.runs[run_id] = run
        artifact = self.add_artifact({'id': run_id+100000, 'name': existing.PREFIX+'-reservation-'+str(run_id)+'-'+str(attempt)},
            run, '2026-09-22T12:00:00Z', archive({'team-reservation.json': encoded(record)+b'\n'}))
        if complete:
            self.add_artifact({'id': run_id+200000, 'name': artifact['name'].replace('-reservation-', '-state-')},
                run, '2026-09-22T12:01:00Z', state_archive(self.destination))
        return artifact, record


class CheckpointRecovery(Fixture):
    def test_authenticated_restore_preserves_every_original_file_and_counts(self):
        ledger = self.restore(); state = ledger.read()
        self.assertEqual(state['requests'], self.prior['requests'])
        self.assertEqual(state['events'], self.prior['events']+[disposition.event()])
        self.assertEqual(disposition.exposure(state), self.p['hold'])
        for name, raw in self.source_bytes.items():
            if name not in {'ledger.json', 'checkpoint.json'}:
                self.assertEqual((self.destination/name).read_bytes(), raw)
        self.assertEqual(json.loads((self.destination/'checkpoint.json').read_bytes())['phase2_token_preflight']['rows'], self.budget.counts)
        recovery.validate_local(self.destination)
        self.assertEqual(self.restore().read(), state)

    def test_failed_run_artifact_digest_reservation_and_owner_tampering_fail_before_write(self):
        mutations = [lambda: self.runs[self.p['failed']['run']['id']].update(conclusion='success'),
            lambda: self.artifacts[-1].update(expired=True),
            lambda: self.artifacts[-1]['workflow_run'].update(head_sha='b'*40),
            lambda: self.raws.__setitem__(self.p['failed']['artifact']['id'], b'corrupted'),
            lambda: self.p['failed'].update(reservation_sha256='0'*64),
            lambda: self.current.update(head_sha='b'*40),
            lambda: self.active.append({'id': 1234})]
        for mutate in mutations:
            saved = copy.deepcopy((self.p, self.artifacts, self.raws, self.runs, self.current, self.active))
            mutate()
            with self.assertRaises((Deferred, ConfigurationFailure)): self.restore()
            self.assertFalse((self.destination/'ledger.json').exists())
            p, self.artifacts, self.raws, self.runs, self.current, self.active = saved
            self.p.clear(); self.p.update(p)
            self.runs[9001] = self.current

    def test_original_files_ledger_counts_receipt_and_event_tampering_fail(self):
        self.restore(); clean = {p.relative_to(self.destination).as_posix(): p.read_bytes() for p in self.destination.rglob('*.json')}
        def ledger_change(fn):
            value=json.loads((self.destination/'ledger.json').read_bytes());fn(value);atomic_json(self.destination/'ledger.json',value)
        changes = [lambda: recovery.receipt_path(self.destination).write_bytes(b'{}'),
            lambda: recovery.receipt_path(self.destination).unlink(),
            lambda: ledger_change(lambda x:x['events'].pop()),
            lambda: ledger_change(lambda x:x['events'].append(disposition.event())),
            lambda: ledger_change(lambda x:x['requests'][0].update(charged_microusd=1)),
            lambda: (self.destination/'checkpoint.json').write_bytes(encoded(self.original_checkpoint | {'phase2_token_preflight': {'rows': []}})),
            lambda: next((self.destination/'diagnostics').glob('*.json')).write_bytes(b'{}')]
        for mutate in changes:
            mutate()
            with self.assertRaises((Deferred, ConfigurationFailure, ValueError, KeyError)): recovery.validate_local(self.destination)
            for name,data in clean.items(): (self.destination/name).write_bytes(data)

    def test_each_crash_boundary_is_checkpointed_and_idempotent_after_archive_restore(self):
        for point in ('after_receipt', 'after_event', 'before_checkpoint', 'after_checkpoint'):
            state=self.root/point; existing.unpack_state(self.raws[self.p['prior']['artifact']['id']],state)
            def crash(actual):
                if actual==point: raise KeyboardInterrupt(point)
            with self.assertRaises(KeyboardInterrupt): recovery.install(state,self.original_checkpoint,crash)
            restored=self.root/(point+'-restored');existing.unpack_state(state_archive(state),restored)
            recovery.install(restored,self.original_checkpoint); recovery.install(restored,self.original_checkpoint)
            self.assertEqual(existing.ExperimentLedger(restored/'ledger.json').read()['events'],self.prior['events']+[disposition.event()])

    def test_concurrent_install_has_one_event_and_one_receipt(self):
        existing.unpack_state(self.raws[self.p['prior']['artifact']['id']],self.destination)
        with ThreadPoolExecutor(max_workers=3) as workers:
            list(workers.map(lambda _:recovery.install(self.destination,self.original_checkpoint),range(3)))
        value=recovery.validate_local(self.destination)
        self.assertEqual(value['ledger']['events'].count(disposition.event()),1)

    def test_unknown_new_reservation_never_falls_back(self):
        self.add_successor(9002,record={'new_paid_work':'unknown'})
        with self.assertRaisesRegex(Deferred,'unknown_new_reservation'):self.restore()

    def test_orphaned_zero_provider_reservation_resumes_only_exact_selector(self):
        ledger=self.restore();run=dict(self.current,id=9002,status='completed',conclusion='failure')
        record=recovery.reservation_record(run,ledger.checkpoint_disposition_anchor,existing.sha(ledger.path.read_bytes()))
        self.add_successor(9002,record=record)
        with patch.dict(os.environ,{'CONTEXTUAL_CHECK':''}):
            with self.assertRaisesRegex(Deferred,'latest_authoritative_checkpoint_missing'):self.restore(self.root/'ordinary')
        recovered=self.restore(self.root/'orphan-recovery')
        self.assertEqual(recovered.read(),ledger.read())
        record['maximum_new_native_counts']=1
        self.raws[109002]=archive({'team-reservation.json':encoded(record)+b'\n'})
        self.artifacts[-1]['digest']='sha256:'+existing.sha(self.raws[109002])
        with self.assertRaisesRegex(Deferred,'unknown_new_reservation'):self.restore(self.root/'changed-orphan')

    def test_boolean_zero_is_not_an_exact_orphan_reservation(self):
        ledger=self.restore();run=dict(self.current,id=9002,status='completed',conclusion='failure')
        record=recovery.reservation_record(run,ledger.checkpoint_disposition_anchor,existing.sha(ledger.path.read_bytes()))
        record['maximum_new_microusd']=False
        self.add_successor(9002,record=record)
        with self.assertRaisesRegex(Deferred,'unknown_new_reservation'):self.restore(self.root/'boolean-zero')

    def test_late_original_math_state_requires_explicit_reconciliation(self):
        failed=self.p['failed'];self.artifacts.append(dict(failed['artifact'],id=888,
            name=failed['artifact']['name'].replace('-reservation-','-state-')))
        with self.assertRaisesRegex(Deferred,'late_original_state_requires_reconciliation'):self.restore()

    def test_orphan_recovery_can_resume_as_a_new_attempt_of_same_workflow_run(self):
        ledger=self.restore();prior_run=dict(self.current,status='completed',conclusion='failure')
        record=recovery.reservation_record(prior_run,ledger.checkpoint_disposition_anchor,existing.sha(ledger.path.read_bytes()))
        self.add_successor(9001,record=record)
        self.runs[(9001,1)]=prior_run
        self.current=dict(self.current,run_attempt=2);self.runs[9001]=self.current;self.active=[self.current]
        with patch.dict(os.environ,{'GITHUB_RUN_ATTEMPT':'2'}):
            restored=self.restore(self.root/'new-attempt')
        self.assertEqual(restored.read(),ledger.read())

    def test_ordinary_successor_restore_requires_event_and_receipt_together(self):
        self.restore();self.add_successor(9001,complete=True)
        with patch.dict(os.environ,{'CONTEXTUAL_CHECK':''}),patch('tools.team_recommender_checkpoint.recover_known_charge'):
            restored=self.restore(self.root/'ordinary-good')
            recovery.validate_local(restored.path.parent)
            receipt=recovery.receipt_path(self.destination);receipt.unlink()
            existing.checkpoint(self.destination)
            self.raws[209001]=state_archive(self.destination)
            with self.assertRaisesRegex(Deferred,'receipt_required'):
                self.restore(self.root/'ordinary-bad')

    def test_future_history_is_allowed_but_complete_disposition_cannot_disappear(self):
        self.restore(); ledger=existing.ExperimentLedger(self.destination/'ledger.json').read()
        ledger['events'].append({'kind':'unrelated_authorized_future_event'})
        ledger['requests'].append({'id':'future','purpose':'cb-fc-i2-other:assess','charged_microusd':0})
        atomic_json(self.destination/'ledger.json',ledger)
        cp=json.loads((self.destination/'checkpoint.json').read_bytes());counts=cp['phase2_token_preflight'];counts['rows'].append({'id':'cb-fc-i2-other:verify'})
        existing.checkpoint(self.destination,token_preflight=counts)
        recovery.validate_local(self.destination)
        latest={'created_at':'2026-09-22T12:00:00Z','workflow_run':{'id':9002}}
        recovery.validate_restored(self.destination,latest)
        ledger['events'].remove(disposition.event());atomic_json(self.destination/'ledger.json',ledger)
        with self.assertRaises((Deferred,ConfigurationFailure)):recovery.validate_restored(self.destination,latest)

    def test_exact_prepare_execute_reserves_zero_and_binds_changed_record(self):
        real_restore=existing.restore
        with patch.object(existing,'api',side_effect=self.api),patch.object(existing,'policy',return_value={}),\
                patch.object(existing,'restore',side_effect=lambda state,settings:real_restore(state,settings,self.api)):
            recovery.run(self.args)
            record=json.loads(self.args.reservation.read_bytes())
            self.assertEqual([record[k] for k in ['maximum_new_microusd','maximum_new_metered_attempts','maximum_new_native_counts']],[0,0,0])
            self.assertEqual(Path(self.env['GITHUB_OUTPUT']).read_text(),'text_provider=none\n')
            self.args.action='execute';recovery.run(self.args)
            result=json.loads(self.args.result.read_bytes());self.assertFalse(result['scientific_result_recovered'])
            self.assertEqual(result['actual_usage'],'unknown')
            record['restore_anchor']['id']+=1;atomic_json(self.args.reservation,record)
            with self.assertRaisesRegex(Deferred,'prepared_identity_changed'):recovery.run(self.args)

    def test_untrusted_or_extra_selectors_cannot_restore(self):
        for change in ({'GITHUB_EVENT_NAME':'repository_dispatch'},{'GITHUB_REF':'refs/heads/other'},
                {'CONTEXTUAL_JOB':'{}'},{'PACKET_HASH':'a'*64},
                {'CONTEXTUAL_CHECK':json.dumps(recovery.SELECTOR|{'extra':True})},
                {'CONTEXTUAL_CHECK':'{"iteration2_checkpoint_disposition":"other","iteration2_checkpoint_disposition":"341997"}'},
                {'CONTEXTUAL_CHECK':'{"iteration2_checkpoint_disposition":"other"}'}):
            with patch.dict(os.environ,change),self.assertRaises(ConfigurationFailure):self.restore()


if __name__=='__main__': unittest.main()
