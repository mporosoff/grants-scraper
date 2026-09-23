"""Portable exact-hold lifecycle tests; archives and API responses are synthetic."""
import copy
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import test_contextual_team_completion_policy as budget_fixture
from tools import contextual_team_ec_disposition as disposition
from tools import contextual_team_ec_recovery as recovery
from tools import team_recommender_executor as existing
from tools.offline_spend import atomic_json, encoded, identity, Deferred, ConfigurationFailure


def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for name, raw in files.items():
            zipped.writestr(name, raw)
    return output.getvalue()


def state_archive(state):
    return archive({p.relative_to(state).as_posix():p.read_bytes() for p in state.rglob('*.json')})


class Fixture(unittest.TestCase):
    def setUp(self):
        self.budget = budget_fixture.CompletionBudget('runTest'); self.budget.setUp()
        self.addCleanup(self.budget.doCleanups)
        self.bind(patch('subprocess.check_output',side_effect=AssertionError('no live subprocess')))
        self.source = self.budget.state; self.root = self.source.parent
        self.destination = self.root/'restored'
        self.prior = self.budget.install().read()
        self.p = copy.deepcopy(disposition.plan()); source = self.p['source']
        row = {'id':disposition.REQUEST_ID, 'key':source['request_key'], 'provider':'anthropic',
            'stage':2, 'purpose':disposition.CLOSED_PURPOSE, 'status':'reserved_unknown',
            'charged_microusd':153198, 'reserved_microusd':153198, 'usage':None}
        self.prior['requests'].append(row)
        atomic_json(self.source/'ledger.json', self.prior)
        atomic_json(self.source/'receipts'/(row['id']+'.json'), {'status':'reserved_unknown',
            'error_type':'ReadTimeout', 'usage':None, 'synthetic_fixture':True})
        run = source['run']
        with patch.dict(os.environ, {'GITHUB_RUN_ID':str(run['id']), 'GITHUB_RUN_ATTEMPT':str(run['run_attempt']),
                'GITHUB_SHA':run['head_sha']}):
            existing.checkpoint(self.source)
        self.cp = json.loads((self.source/'checkpoint.json').read_bytes())
        source.update(ledger_sha256=existing.sha((self.source/'ledger.json').read_bytes()),
            checkpoint_sha256=existing.sha((self.source/'checkpoint.json').read_bytes()),
            requests=len(self.prior['requests']), requests_sha256=identity(self.prior['requests']),
            events=len(self.prior['events']), events_sha256=identity(self.prior['events']),
            native_counts=len(self.budget.counts), native_counts_sha256=identity(self.budget.counts),
            checkpoint_files=len(self.cp['files']), checkpoint_files_sha256=identity(self.cp['files']),
            request_sha256=identity(row), receipt_sha256=existing.sha((self.source/'receipts'/(row['id']+'.json')).read_bytes()))
        self.bind(patch.object(disposition, 'plan', return_value=self.p))
        self.current = {'id':9001, 'run_attempt':1, 'head_sha':'a'*40, 'head_branch':'main',
            'event':'workflow_dispatch', 'path':existing.WORKFLOW, 'status':'in_progress', 'conclusion':None}
        self.runs = {run['id']:copy.deepcopy(run), 9001:self.current}; self.active=[self.current]
        self.artifacts=[]; self.raws={}
        self.add_artifact(source['artifact'], run, '2026-09-23T13:43:06Z', state_archive(self.source))
        self.add_artifact(source['reservation_artifact'], run, source['reservation_artifact']['created_at'],
            archive({'team-reservation.json':encoded({'scope_id':recovery.SELECTOR['iteration3_ec_disposition'],
                'operation':'check', 'run_id':str(run['id']), 'attempt':str(run['run_attempt']),
                'code_sha':run['head_sha']})+b'\n'}))
        self.env={'GITHUB_REPOSITORY':existing.REPOSITORY, 'GITHUB_REF':'refs/heads/main',
            'GITHUB_EVENT_NAME':'workflow_dispatch', 'GITHUB_WORKFLOW_REF':existing.REPOSITORY+'/'+existing.WORKFLOW+'@refs/heads/main',
            'GITHUB_RUN_ID':'9001', 'GITHUB_RUN_ATTEMPT':'1', 'GITHUB_SHA':'a'*40,
            'GITHUB_OUTPUT':str(self.root/'github-output'), 'CONTEXTUAL_CHECK':json.dumps(recovery.SELECTOR),
            'CONTEXTUAL_JOB':'', 'PACKET_HASH':'', 'PACKET_COMMIT':'', 'ANTHROPIC_API_KEY':'', 'OPENAI_API_KEY':'', 'VOYAGE_API_KEY':''}
        self.bind(patch.dict(os.environ,self.env))
        self.source_bytes={p.relative_to(self.source).as_posix():p.read_bytes() for p in self.source.rglob('*.json')}

    def bind(self, item):
        value=item.start(); self.addCleanup(item.stop); return value

    def add_artifact(self, expected, run, clock, raw):
        expected['digest']='sha256:'+existing.sha(raw)
        value=dict(expected, created_at=clock, expired=False,
            workflow_run={'id':run['id'], 'head_sha':run['head_sha'], 'head_branch':'main'})
        self.artifacts.append(value); self.raws[value['id']]=raw; return value

    def api(self,path):
        if path.startswith('actions/artifacts?'):return encoded({'artifacts':self.artifacts})
        if '?status=in_progress' in path:return encoded({'workflow_runs':self.active,'total_count':len(self.active)})
        if path.startswith('actions/runs/'):
            bits=path.split('/'); key=(int(bits[2]),int(bits[4])) if len(bits)>3 else int(bits[2])
            return encoded(self.runs[key])
        if path.startswith('actions/artifacts/'):
            aid=int(path.split('/')[2]); return self.raws[aid] if path.endswith('/zip') else encoded(next(a for a in self.artifacts if a['id']==aid))
        raise AssertionError('unexpected API route '+path)

    def restore(self,destination=None):
        return existing.restore(destination or self.destination, {}, self.api)

    def successor(self,record,complete=False):
        run=dict(self.current,id=9002,status='completed',conclusion='failure');self.runs[9002]=run
        a=self.add_artifact({'id':190002,'name':existing.PREFIX+'-reservation-9002-1'},run,
            '2026-09-23T16:00:00Z',archive({'team-reservation.json':encoded(record)+b'\n'}))
        if complete:
            with patch.dict(os.environ,{'GITHUB_RUN_ID':'9002'}):existing.checkpoint(self.destination)
            self.add_artifact({'id':290002,'name':a['name'].replace('-reservation-','-state-')},run,
                '2026-09-23T16:01:00Z',state_archive(self.destination))
        return a


class ECRecovery(Fixture):
    def test_no_additional_exposure(self):
        e=disposition.event()
        self.assertEqual(e['additional_exposure'],{'microusd':0,'attempts':0,'native_counts':0})
        self.assertEqual(e['held_microusd'],153198)

    def test_restore_preserves_full_history_hold_files_and_idempotence(self):
        ledger=self.restore(); value=ledger.read()
        self.assertEqual(value['requests'],self.prior['requests'])
        self.assertEqual(value['events'],self.prior['events']+[disposition.event()])
        self.assertEqual(sum(r['charged_microusd'] for r in value['requests']),sum(r['charged_microusd'] for r in self.prior['requests']))
        for name,raw in self.source_bytes.items():
            if name not in ('ledger.json','checkpoint.json'):self.assertEqual((self.destination/name).read_bytes(),raw)
        self.assertEqual(recovery.validate_local(self.destination)['source_checkpoint'],self.cp)
        self.assertEqual(self.restore().read(),value)

    def test_all_interruption_points_and_archive_restore_resume_once(self):
        for point in ('before_receipt','after_receipt','before_event','after_event','before_checkpoint','after_checkpoint'):
            with self.subTest(point=point):
                state=self.root/point; existing.unpack_state(self.raws[self.p['source']['artifact']['id']],state)
                def crash(actual):
                    if actual==point:raise KeyboardInterrupt(point)
                with self.assertRaises(KeyboardInterrupt):recovery.install(state,self.cp,crash)
                restored=self.root/(point+'-again');existing.unpack_state(state_archive(state),restored)
                recovery.install(restored,self.cp); recovery.install(restored,self.cp)
                self.assertEqual(recovery.validate_local(restored)['ledger']['events'],self.prior['events']+[disposition.event()])

    def test_concurrent_install_has_one_event(self):
        existing.unpack_state(self.raws[self.p['source']['artifact']['id']],self.destination)
        with ThreadPoolExecutor(max_workers=3) as workers:list(workers.map(lambda _:recovery.install(self.destination,self.cp),range(3)))
        self.assertEqual(recovery.validate_local(self.destination)['ledger']['events'].count(disposition.event()),1)

    def test_artifact_run_digest_and_active_owner_tampering(self):
        for change in ('run','digest','active','expired'):
            saved=copy.deepcopy((self.artifacts,self.raws,self.runs,self.active))
            if change=='run':self.runs[self.p['source']['run']['id']]['conclusion']='success'
            if change=='digest':self.raws[self.p['source']['artifact']['id']]=b'bad'
            if change=='active':self.active.append({'id':9003})
            if change=='expired':self.artifacts[0]['expired']=True
            with self.assertRaises((ConfigurationFailure,Deferred)):self.restore()
            self.assertFalse((self.destination/'ledger.json').exists())
            self.artifacts,self.raws,self.runs,self.active=saved

    def test_event_hold_receipt_count_and_file_tampering(self):
        self.restore(); clean={p.relative_to(self.destination).as_posix():p.read_bytes() for p in self.destination.rglob('*.json')}
        for change in ('duplicate','bool','charge','receipt','count','file','remove_event'):
            with self.subTest(change=change):
                state=json.loads(clean['ledger.json'])
                if change=='duplicate':state['events'].append(disposition.event())
                if change=='bool':state['events'][-1]['additional_allowance']=False
                if change=='charge':state['requests'][-1]['charged_microusd']=0
                if change=='remove_event':state['events'].pop()
                atomic_json(self.destination/'ledger.json',state)
                if change=='receipt':recovery.receipt_path(self.destination).write_bytes(b'{}')
                if change=='count':
                    cp=json.loads(clean['checkpoint.json']);cp['phase2_token_preflight']['rows'][0]['input_tokens']+=1
                    atomic_json(self.destination/'checkpoint.json',cp)
                if change=='file':(self.destination/'receipts'/(disposition.REQUEST_ID+'.json')).write_bytes(b'{}')
                with self.assertRaises((ConfigurationFailure,Deferred,KeyError)):recovery.validate_local(self.destination)
                for name,raw in clean.items():(self.destination/name).write_bytes(raw)

    def test_original_purpose_and_request_key_closed_but_same_count_key_allowed(self):
        state=self.restore().read()
        for purpose,key in ((disposition.CLOSED_PURPOSE,None),('cb-fc-i3c-ec_check',self.p['source']['request_key'])):
            with self.assertRaisesRegex(Deferred,'permanently_closed'):disposition.assert_operation_open(state,purpose,key)
        disposition.assert_operation_open(state,'cb-fc-i3c-ec_check','c'*64)

    def test_missing_paid_reservation_never_falls_back_but_exact_zero_orphan_can(self):
        ledger=self.restore(); run=dict(self.current,id=9002)
        record=recovery.reservation_record(run,ledger.ec_disposition_anchor,existing.sha(ledger.path.read_bytes()))
        self.successor(record)
        self.assertEqual(self.restore(self.root/'zero-restored').read(),ledger.read())
        self.raws[190002]=archive({'team-reservation.json':encoded(record|{'maximum_new_native_counts':1})+b'\n'})
        for a in self.artifacts:
            if a['id']==190002:a['digest']='sha256:'+existing.sha(self.raws[190002])
        with self.assertRaisesRegex(Deferred,'unknown_new_reservation'):self.restore(self.root/'bad-restored')

    def test_complete_later_unknown_can_restore_without_paid_history_guard(self):
        ledger=self.restore(); value=ledger.read()
        value['requests'].append({'id':'e'*32,'key':'e'*64,'provider':'anthropic','stage':2,
            'purpose':'cb-fc-i3c-ai_verify','status':'reserved_unknown','charged_microusd':123,'usage':None})
        atomic_json(ledger.path,value)
        self.successor({'ordinary_paid_work':True},complete=True)
        restored=self.restore(self.root/'later')
        self.assertEqual(restored.read()['requests'],value['requests'])
        self.assertEqual(disposition.allowed_unknown_ids(restored.read()),frozenset((disposition.REQUEST_ID,)))

    def test_later_owner_cannot_remove_both_receipt_and_event(self):
        a={'created_at':'2026-09-23T16:00:00Z'}
        with self.assertRaises(Deferred):recovery.validate_restored(self.source,a)

    def test_trusted_prepare_execute_needs_no_provider_keys_and_reserves_zero(self):
        args=SimpleNamespace(action='prepare',state=self.destination,reservation=self.root/'reservation.json',result=self.root/'result.json')
        with patch.object(existing,'api',side_effect=self.api):
            recovery.run(args);args.action='execute';recovery.run(args)
        record=json.loads(args.reservation.read_bytes());result=json.loads(args.result.read_bytes())
        self.assertEqual([record[k] for k in ('maximum_new_microusd','maximum_new_metered_attempts','maximum_new_native_counts')],[0,0,0])
        self.assertEqual((self.root/'github-output').read_text(),'text_provider=none\n')
        self.assertFalse(result['scientific_result_recovered']);self.assertEqual(result['paid_requests_replayed'],0)

    def test_selector_exact_and_other_routes_unchanged(self):
        for raw in ('{"iteration3_ec_disposition":"344592:ab-0025","extra":true}',
                    '{"iteration3_ec_disposition":"344592:ab-0025","iteration3_ec_disposition":"344592:ab-0025"}'):
            with patch.dict(os.environ,{'CONTEXTUAL_CHECK':raw}),self.assertRaises(ConfigurationFailure):recovery.selected()
        with patch.dict(os.environ,{'CONTEXTUAL_CHECK':'{"iteration3_check":"332894"}'}):
            self.assertIsNone(recovery.maybe_restore(self.destination,[],lambda _:self.fail('other selector called API')))
