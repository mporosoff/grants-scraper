"""Portable fixture responses only. Retained assessment replay is a private check."""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import zipfile
import test_contextual_team_luna_repair as fixture
from tools import contextual_team_compact_check as compact
from tools import contextual_team_luna_repair as prior_runner
from tools import contextual_team_diagnostics as diagnostic
from tools import contextual_team_pair_contract as pairs
from tools import team_recommender_executor as existing
from tools.contextual_team_executor import Runner, RecoveryRequired
from tools.offline_spend import identity, encoded, atomic_json, Deferred, ConfigurationFailure
from tools.team_recommender_budget import ExperimentLedger


class CompactContinuation(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.state = Path(temp.name)/'state'; self.state.mkdir(); self.calls = []
        self.data = fixture.real_data()
        self.bind(patch('socket.socket.connect', side_effect=AssertionError('no_live_provider')))
        self.bind(patch.dict(os.environ, {'GITHUB_RUN_ID':'999','GITHUB_RUN_ATTEMPT':'1',
            'GITHUB_SHA':'a'*40,'ANTHROPIC_API_KEY':'fixture-secret'}))
        s = ExperimentLedger(self.state/'ledger.json', initialize=True).read()
        s['requests'] = [{'id':f'{i:032x}','key':f'{i:064x}','status':'valid',
            'charged_microusd':0,'stage':2,'provider':'anthropic'} for i in range(685)]
        s['requests'][0]['charged_microusd'] = 7346880
        for i, rid, amount in ((682,compact.prior.OLD_ID,146074),(684,compact.OLD_ID,205254)):
            s['requests'][i].update(id=rid,status='reserved_unknown',usage=None,charged_microusd=amount,
                purpose='cb-lr-comparison-check' if i==682 else 'cb-lc-check')
        s['events'] = [compact.prior.EVENT]
        self.original = copy.deepcopy(s['requests'])
        self.bind(patch.object(compact,'PRIOR_ROWS',identity(s['requests'])))
        atomic_json(self.state/'ledger.json',s)
        for folder, name in (('receipts','OLD_RECEIPT'),('diagnostics','OLD_DIAGNOSTIC')):
            path=self.state/folder/(compact.OLD_ID+'.json')
            atomic_json(path,{'fixture':'terminal HTTP400, unknown usage'})
            self.bind(patch.object(compact,name,existing.sha(path.read_bytes())))
        self.old_run = {'id':34967272858,'run_attempt':1,'status':'completed','conclusion':'failure',
            'path':existing.WORKFLOW,'head_branch':'main','event':'workflow_dispatch',
            'head_sha':'ef44f981803e2cde77a8d1a6659115e722c66e02'}
        self.active = []
        self.bind(patch.object(prior_runner,'eclipse_data',return_value=(self.data,None)))
        _, packets = prior_runner.locked_packets(self.state)
        contract, body = packets['assessment']
        key=identity([existing.AUTHORIZATION_ID,'contextual-v1',
            [compact.prior.VERSION,'assessment',identity(contract),identity(self.data)]])
        a=pairs.resolve(fixture.answer(self.data),self.data)
        s['requests'][683].update(key=key,model='gpt-5.6-luna',provider='openai',body_sha256=identity(body))
        atomic_json(self.state/'cache'/(key+'.json'),{'key':key,'body_sha256':identity(body),
            'model':'gpt-5.6-luna','returned_model':'gpt-5.6-luna','request_id':s['requests'][683]['id'],'value':a})
        atomic_json(self.state/'ledger.json',s)
        self.original=copy.deepcopy(s['requests'])
        compact.PRIOR_ROWS=identity(s['requests'])  # patched attribute is restored by cleanup
        self.bind(patch.object(compact.prior,'PRIOR_ROWS',identity(s['requests'][:683])))
        self.real_plan=compact.plan()
        test_plan=self.real_plan | {'retained_assessment_sha256':identity(a)}
        self.bind(patch.object(compact,'plan',return_value=test_plan))
        compact.install_authority(self.state,self.api)

    def bind(self,p):
        value=p.start();self.addCleanup(p.stop);return value

    def api(self,path):
        return encoded({'workflow_runs':self.active} if '?status=' in path else self.old_run)

    def provider(self,url,**kwargs):
        self.calls.append(url)
        return fixture.Response({'model':'claude-sonnet-5','stop_reason':'end_turn',
            'usage':{'input_tokens':100,'output_tokens':200},'content':[
                {'type':'text','text':json.dumps(fixture.answer(self.data,True))}]})

    def runner(self,**kwargs):
        return compact.CompactRunner(self.state,{},post=self.provider,**kwargs)

    def restored(self):
        existing.checkpoint(self.state)
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:
            for p in self.state.rglob('*.json'):z.write(p,p.relative_to(self.state).as_posix())
        dest=self.state.parent/(self.state.name+'-restored')
        existing.unpack_state(raw.getvalue(),dest);self.state=dest

    def test_exact_complete_packet_and_separate_authority(self):
        data,c,b=compact.packet(self.state)
        self.assertEqual(len(data['people']),12);self.assertEqual(c['maximum_pairs'],24)
        self.assertEqual(identity(b),self.real_plan['body_sha256'])
        self.assertEqual(len(encoded(b)),58847)
        self.assertEqual(compact.plan()['reserved_microusd'],263282)
        self.assertEqual(b['max_tokens'],12000)
        payload=json.loads(b['messages'][0]['content'])
        self.assertEqual(payload['people'],self.data['people'])
        self.assertNotIn('proposed_edges',payload)
        self.assertEqual(compact.plan()['native_count_calls'],0)
        self.assertNotEqual(compact.VERSION,compact.prior.VERSION)

    def test_authority_idempotent_and_original_holds_unchanged(self):
        for _ in range(3):compact.install_authority(self.state,self.api)
        s=self.runner().ledger.read()
        self.assertEqual(s['requests'],self.original)
        self.assertEqual(s['events'].count(compact.EVENT),1)
        self.assertTrue(Runner(self.state,{}).has_unknown_request())
        with self.assertRaises(Deferred):compact.prior.history(s)

    def test_single_dispatch_exact_cache_and_restore_reuse(self):
        first=self.runner().perform()
        for _ in range(3):
            self.restored();out=self.runner().perform()
            self.assertTrue(out['cache_hit']);self.assertEqual(out['value'],first['value'])
        s=self.runner().ledger.read()
        self.assertEqual(s['requests'][:685],self.original)
        self.assertEqual(len(s['requests']),686);self.assertEqual(len(self.calls),1)

    def test_every_paid_write_boundary_survives_repeated_restoration(self):
        original=self.state
        for boundary in ('after_reserve','after_reservation_checkpoint','after_dispatch',
            'before_reconcile','after_reconcile','after_cache','after_receipt'):
            with self.subTest(boundary=boundary):
                self.state=original.parent/boundary;shutil.copytree(original,self.state)
                before=len(self.calls)
                def crash(point):
                    if point==boundary:raise KeyboardInterrupt('fixture crash')
                with self.assertRaises(KeyboardInterrupt):self.runner(crash=crash).perform()
                dispatched=len(self.calls)-before
                for _ in range(3):
                    self.restored()
                    try:self.runner().perform()
                    except (RecoveryRequired,Deferred):pass
                self.assertEqual(len(self.calls)-before,dispatched)
        self.state=original

    def test_failed_reconcile_and_diagnostics_interruptions_never_replay(self):
        original=self.state
        for boundary in ('diagnostic_header','diagnostic_final','after_failed_reconcile'):
            with self.subTest(boundary=boundary):
                self.state=original.parent/boundary;shutil.copytree(original,self.state)
                sent=[];writes=[]
                def post(*a,**kw):
                    sent.append(1)
                    return fixture.Response({'model':'claude-sonnet-5','stop_reason':'end_turn',
                        'usage':{'input_tokens':100,'output_tokens':20},
                        'content':[{'type':'text','text':'{}'}]})
                def write(path,value):
                    if path.parent.name=='diagnostics':
                        writes.append(1)
                        if (boundary=='diagnostic_header' and len(writes)==1
                            or boundary=='diagnostic_final' and len(writes)==2):raise KeyboardInterrupt()
                    atomic_json(path,value)
                def crash(point):
                    if point==boundary:raise KeyboardInterrupt()
                with patch.object(diagnostic,'atomic_json',side_effect=write):
                    with self.assertRaises(KeyboardInterrupt):
                        compact.CompactRunner(self.state,{},post=post,crash=crash).perform()
                for _ in range(3):
                    self.restored()
                    with self.assertRaises(RecoveryRequired):self.runner().perform()
                self.assertEqual(len(sent),1);self.assertEqual(self.calls,[])
        self.state=original

    def test_uncertain_transport_and_http_failure_stop_without_retry(self):
        original=self.state
        for response in ('transport','http'):
            self.state=original.parent/response;shutil.copytree(original,self.state);sent=[]
            def post(*a,**kw):
                sent.append(1)
                if response=='transport':raise OSError('uncertain transport')
                return fixture.Response({'error':{'type':'invalid_request_error'}},400)
            with self.assertRaises(RecoveryRequired):compact.CompactRunner(self.state,{},post=post).perform()
            for _ in range(3):
                self.restored()
                with self.assertRaises(RecoveryRequired):self.runner().perform()
            self.assertEqual(len(sent),1)
        self.state=original

    def test_concurrent_callers_dispatch_once(self):
        def go(_):
            try:return self.runner().perform()
            except (RecoveryRequired,Deferred):return None
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(go,range(2)))
        self.assertEqual(len(self.calls),1)

    def test_lost_reconciled_result_cannot_rekey(self):
        out=self.runner().perform();s=self.runner().ledger.read();row=s['requests'][-1]
        (self.state/'cache'/(row['key']+'.json')).unlink()
        for _ in range(3):
            self.restored()
            with self.assertRaises(RecoveryRequired):self.runner().perform()
        metadata={k:row[k] for k in ('purpose','compact_continuation','continuation_lock_sha256',
            'body_sha256','pair_contract_sha256','repair_of','packet_sha256')}
        with self.assertRaises(RecoveryRequired):
            self.runner().ledger.reserve_experiment('anthropic','claude-sonnet-5',2,'new-key',263282,1,
                trusted_route=True,input_tokens=71641,output_tokens=12000,execution_metadata=metadata)
        self.assertEqual(len(self.calls),1)

    def test_authority_requires_terminal_evidence_no_other_active_owner(self):
        self.old_run['status']='in_progress'
        with self.assertRaises(RecoveryRequired):compact.install_authority(self.state,self.api)
        self.old_run['status']='completed';self.active=[{'id':1000}]
        with self.assertRaises(RecoveryRequired):compact.install_authority(self.state,self.api)
        self.active=[]
        (self.state/'diagnostics'/(compact.OLD_ID+'.json')).write_text('{}')
        with self.assertRaises(ConfigurationFailure):compact.install_authority(self.state,self.api)
        self.assertFalse(self.calls)

    def test_other_uncertainty_and_protected_reserves_still_block(self):
        s=self.runner().ledger.read()
        for row in ({'id':'other','status':'reserved_unknown','charged_microusd':1},
                    {'id':'later','status':'valid','charged_microusd':1000000}):
            state=copy.deepcopy(s);state['requests'].append(row)
            with self.assertRaises((Deferred,RecoveryRequired)):compact.remaining_fits(state,263282)
        state=copy.deepcopy(s);state['requests'] += [{'id':str(i),'status':'valid','charged_microusd':0} for i in range(3)]
        with self.assertRaises(Deferred):compact.remaining_fits(state,263282)

    def test_authority_interrupted_writes_are_idempotent_and_do_not_change_rows(self):
        original=self.state
        for stop in ('receipt','ledger','checkpoint'):
            self.state=original.parent/stop;shutil.copytree(original,self.state)
            s=self.runner().ledger.read();s['events'].remove(compact.EVENT);atomic_json(self.state/'ledger.json',s)
            def write(path,value):
                atomic_json(path,value)
                if (stop=='receipt' and path.parent.name=='receipts'
                    or stop=='ledger' and path.name=='ledger.json'):raise KeyboardInterrupt()
            with patch.object(compact,'atomic_json',side_effect=write):
                with patch.object(existing,'checkpoint',side_effect=KeyboardInterrupt() if stop=='checkpoint' else existing.checkpoint):
                    with self.assertRaises(KeyboardInterrupt):compact.install_authority(self.state,self.api)
            for _ in range(3):
                self.restored();compact.install_authority(self.state,self.api)
            self.assertEqual(self.runner().ledger.read()['requests'],self.original)
        self.state=original

    def test_missing_or_changed_assessment_is_not_regenerated(self):
        row=self.original[683];path=self.state/'cache'/(row['key']+'.json')
        path.unlink()
        with self.assertRaises(RecoveryRequired):self.runner().perform()
        self.assertEqual(self.calls,[])

    def test_trusted_entrypoint_prepares_and_executes_one_operation_without_counter(self):
        from types import SimpleNamespace
        from tools.contextual_team_token_preflight import Counter
        args=SimpleNamespace(action='prepare',state=self.state,
            reservation=self.state.parent/'reservation.json',result=self.state.parent/'result.json')
        with patch.object(existing,'trusted_environment'), patch.object(existing,'restore',return_value=self.runner().ledger), \
             patch.object(existing,'api',side_effect=self.api), \
             patch.dict(os.environ,{'CONTEXTUAL_CHECK':json.dumps({'compact_check_continuation':compact.VERSION})}), \
             patch.object(Counter,'count',side_effect=AssertionError('no_native_count_needed')):
            compact.run(args)
            reservation=json.loads(args.reservation.read_bytes())
            self.assertEqual(reservation['maximum_new_attempts'],1)
            self.assertEqual(reservation['retained_unknown_hold_microusd'],351328)
            args.action='execute'
            runner=self.runner()
            with patch.object(compact,'CompactRunner',return_value=runner):compact.run(args)
            self.assertEqual(len(json.loads(args.result.read_bytes())['value']['people']),12)
        self.assertEqual(len(self.calls),1)

    def test_mixed_operation_and_changed_contract_metadata_are_rejected(self):
        from types import SimpleNamespace
        with patch.object(existing,'trusted_environment'), patch.dict(os.environ,{
            'CONTEXTUAL_CHECK':json.dumps({'compact_check_continuation':compact.VERSION,'luna_contract_repair':'assessment'})}):
            with self.assertRaises(ConfigurationFailure):compact.run(SimpleNamespace())
        metadata={'purpose':compact.PURPOSE,'compact_continuation':compact.VERSION,
            'continuation_lock_sha256':identity(compact.plan()),'body_sha256':compact.plan()['body_sha256'],
            'pair_contract_sha256':compact.plan()['contract_sha256'],'repair_of':compact.OLD_ID,
            'packet_sha256':compact.prior.plan()['source_inputs_sha256']}
        for field in metadata:
            with self.subTest(field=field):
                with self.assertRaises(ConfigurationFailure):
                    compact.check_reservation(self.runner().ledger.read(),'anthropic',metadata | {field:'wrong'},263282,71641,12000)


if __name__=='__main__':unittest.main()
