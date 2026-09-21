"""Complete real input, bounded failure metadata, fixture answers/counters only."""
import copy
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import test_contextual_team_compact_check as prior_fixture
import test_contextual_team_luna_repair as fixture
from tools import contextual_team_wire_repair as repair
from tools import contextual_team_check_wire as wire
from tools import contextual_team_pair_contract as pairs
from tools import contextual_team_token_preflight as tokens
from tools import team_recommender_executor as existing
from tools.offline_ai import validate_schema
from tools.offline_spend import identity,encoded,atomic_json,ConfigurationFailure,Deferred,Refusal,Incomplete
from tools.contextual_team_executor import RecoveryRequired


def answer(data):
    canonical=fixture.answer(data,True);qs,_,owners=wire.mapping(data)
    result={'decisions':{}}
    for qid,q in qs.items():
        row=canonical['decisions'][q['person_id']][q['role_id']]
        addresses={v:k for k,v in owners[q['person_id']].items()}
        result['decisions'][qid]={**{k:row[k] for k in ('coverage','verdict','reason','gap')},
            'claims':[addresses[v] for v in row['claim_refs'].values() if v!='NONE']}
    return result


class WireContract(unittest.TestCase):
    def setUp(self):self.data=fixture.real_data()

    def test_all_questions_and_original_evidence_losslessly_preserved(self):
        c,b=wire.body(self.data);_,old=pairs.body(self.data,judge=True)
        original=json.loads(old['messages'][0]['content']);new=json.loads(b['messages'][0]['content'])
        self.assertEqual({k:new[k] for k in original},original)
        self.assertEqual(set(new)-set(original),{'wire_questions','wire_claims'})
        self.assertEqual(b['system'],old['system']+wire.FORMAT)
        self.assertEqual((b['model'],b['max_tokens'],b['thinking']),('claude-sonnet-5',12000,{'type':'disabled'}))
        self.assertEqual(len(c['schema']['properties']['decisions']['required']),24)
        expected=pairs.resolve(fixture.answer(self.data,True),self.data,judge=True)
        self.assertEqual(wire.resolve(answer(self.data),self.data),expected)
        self.assertEqual(identity(b),repair.plan()['body_sha256'])
        self.assertEqual(identity(c),repair.plan()['contract_sha256'])

    def test_native_owner_enums_and_complete_local_validation(self):
        valid=answer(self.data);_,b=wire.body(self.data)
        native=b['output_config']['format']['schema']
        validate_schema(valid,native)
        mutations=[lambda v:v['decisions'].pop('q01'),
            lambda v:v['decisions'].update(q25=v['decisions']['q01']),
            lambda v:v['decisions']['q01'].update(claims=['p02c01']),
            lambda v:v['decisions']['q01'].update(source_ref='sibling')]
        for change in mutations:
            v=copy.deepcopy(valid);change(v)
            with self.assertRaises(ValueError):validate_schema(v,native)
            with self.assertRaises(ValueError):wire.resolve(v,self.data)
        for claims in ([],['p01c01','p01c01'],['p01c01']*4):
            v=copy.deepcopy(valid);v['decisions']['q01']['claims']=claims
            with self.assertRaises(ValueError):wire.resolve(v,self.data)
        for field,value in [('reason','short'),('reason','x'*701),('gap','x'*301)]:
            v=copy.deepcopy(valid);v['decisions']['q01'][field]=value
            with self.assertRaises(ValueError):wire.resolve(v,self.data)

    def test_negative_unknown_complete_and_response_boundaries(self):
        v=answer(self.data)
        for row in v['decisions'].values():row.update(coverage='insufficient_information',claims=[],verdict='insufficient-information')
        resolved=wire.resolve(v,self.data)
        self.assertTrue(all(p['outcome']=='insufficient_information' for p in resolved['people']))
        payload={'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(v)}]}
        self.assertEqual(wire.parse(payload,self.data),resolved)
        for stop,error in (('max_tokens',Incomplete),('refusal',Refusal)):
            with self.assertRaises(error):wire.parse(payload|{'stop_reason':stop},self.data)
        duplicate='{"decisions":'+json.dumps(v['decisions'])+',"decisions":'+json.dumps(v['decisions'])+'}'
        with self.assertRaisesRegex(ValueError,'duplicate_response_key'):
            wire.parse(payload|{'content':[{'type':'text','text':duplicate}]},self.data)


class WireRepair(unittest.TestCase):
    def setUp(self):
        self.base=prior_fixture.CompactContinuation();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.state=self.base.state;self.data=self.base.data;self.calls=[];self.counts=[]
        s=self.base.runner().ledger.read()
        folder=Path('tests/fixtures/compact-wire-evidence')
        s['requests'].append(json.loads((folder/'request.json').read_bytes()))
        atomic_json(self.state/'ledger.json',s);self.original=copy.deepcopy(s['requests'])
        self.bind(patch.object(repair,'PRIOR_ROWS',identity(self.original)))
        for name in ('receipts','diagnostics'):
            shutil.copyfile(folder/(name+'.json'),self.state/name/(repair.FAILED+'.json'))
        counts=[{'id':str(i),'key':identity(i),'status':'complete','input_tokens':1} for i in range(187)]
        existing.checkpoint(self.state,token_preflight={'version':tokens.VERSION,'source_sha256':tokens.SOURCE_SHA,'rows':counts})
        self.bind(patch.object(repair,'PRIOR_COUNTS',identity(counts)))
        self.native=20000;self.active=[];self.terminal='completed'
        self.bind(patch.object(repair,'Counter',side_effect=lambda state:tokens.Counter(state,post=self.count_provider)))
        repair.install_authority(self.state,self.api)

    def bind(self,p):value=p.start();self.addCleanup(p.stop);return value
    def api(self,path):
        return encoded({'workflow_runs':self.active} if '?status=' in path else {
            'id':35613118796,'run_attempt':1,'status':self.terminal,'conclusion':'failure',
            'path':existing.WORKFLOW,'head_branch':'main','event':'workflow_dispatch',
            'head_sha':'c4e0ac136c6ff528c97eace81ddb0aecae23f0c9'})
    def count_provider(self,*a,**k):
        self.counts.append(1);return fixture.Response({'input_tokens':self.native})
    def provider(self,*a,**k):
        self.calls.append(1);return fixture.Response({'model':'claude-sonnet-5','stop_reason':'end_turn',
            'usage':{'input_tokens':100,'output_tokens':200},
            'content':[{'type':'text','text':json.dumps(answer(self.data))}]})
    def runner(self,**kw):return repair.WireRunner(self.state,{},post=self.provider,**kw)
    def restored(self):
        self.base.state=self.state;self.base.restored();self.state=self.base.state

    def test_exact_success_count_cache_and_hold_preservation(self):
        first=self.runner().perform()
        for _ in range(3):
            self.restored();self.assertEqual(self.runner().perform()['value'],first['value'])
        s=self.runner().ledger.read()
        self.assertEqual(s['requests'][:686],self.original)
        self.assertEqual(len(s['requests']),687)
        self.assertEqual((len(self.calls),len(self.counts)),(1,1))
        self.assertEqual(sum(r['charged_microusd'] for r in self.original[685:])+200000,463282)

    def test_paid_crash_boundaries_never_duplicate_on_restoration(self):
        original=self.state
        for boundary in ('after_reserve','after_reservation_checkpoint','after_dispatch','before_reconcile','after_reconcile','after_cache','after_receipt'):
            with self.subTest(boundary=boundary):
                self.state=original.parent/boundary;shutil.copytree(original,self.state)
                before=len(self.calls)
                def crash(point):
                    if point==boundary:raise KeyboardInterrupt()
                with self.assertRaises(KeyboardInterrupt):self.runner(crash=crash).perform()
                paid=len(self.calls)-before
                for _ in range(3):
                    self.restored()
                    try:self.runner().perform()
                    except (RecoveryRequired,Deferred):pass
                self.assertEqual(len(self.calls)-before,paid)
        self.state=original

    def test_counter_failure_and_oversize_never_dispatch_model(self):
        with patch.object(tokens.Counter,'count',side_effect=RecoveryRequired('unknown counter')):
            with self.assertRaises(RecoveryRequired):self.runner().perform()
        self.native=40000
        for _ in range(2):
            with self.assertRaisesRegex(Deferred,'complete_input_exceeds_budget'):self.runner().perform()
        self.assertEqual((len(self.calls),len(self.counts)),(0,1))

    def test_concurrent_callers_count_and_pay_once(self):
        def go(_):
            try:return self.runner().perform()
            except (RecoveryRequired,Deferred):return None
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(go,range(2)))
        self.assertEqual((len(self.calls),len(self.counts)),(1,1))

    def test_other_uncertainty_budget_and_changed_metadata_fail_closed(self):
        s=self.runner().ledger.read()
        for extra in ({'id':'other','status':'reserved_unknown','charged_microusd':1},
                      {'id':'paid','status':'valid','charged_microusd':40000}):
            v=copy.deepcopy(s);v['requests'].append(extra)
            with self.assertRaises((Deferred,RecoveryRequired)):repair.remaining_fits(v)
        p=repair.plan();m={'purpose':repair.PURPOSE,'compact_continuation':repair.VERSION,
            'continuation_lock_sha256':identity(p),'body_sha256':p['body_sha256'],
            'pair_contract_sha256':p['contract_sha256'],'repair_of':repair.FAILED,
            'packet_sha256':repair.old.prior.plan()['source_inputs_sha256']}
        repair.check_reservation(s,'anthropic',m,200000,40000,12000)
        for k in m:
            with self.assertRaises(ConfigurationFailure):repair.check_reservation(s,'anthropic',m|{k:'wrong'},200000,40000,12000)

    def test_terminal_guard_and_authority_reinstallation(self):
        for _ in range(3):repair.install_authority(self.state,self.api)
        self.assertEqual(self.runner().ledger.read()['requests'],self.original)
        self.assertEqual(self.runner().ledger.read()['events'].count(repair.EVENT),1)
        self.active=[{'id':1000}]
        with self.assertRaises(RecoveryRequired):repair.install_authority(self.state,self.api)
        self.active=[];self.terminal='in_progress'
        with self.assertRaises(RecoveryRequired):repair.install_authority(self.state,self.api)
        self.terminal='completed'
        (self.state/'diagnostics'/(repair.FAILED+'.json')).write_text('{}')
        with self.assertRaises(ConfigurationFailure):repair.install_authority(self.state,self.api)

    def test_native_count_interruption_cannot_repeat_after_restore(self):
        def fail(*a,**k):
            self.counts.append(1);raise OSError('uncertain native count')
        with patch.object(repair,'Counter',side_effect=lambda state:tokens.Counter(state,post=fail)):
            with self.assertRaises(OSError):self.runner().perform()
        for _ in range(3):
            self.restored()
            with self.assertRaises(RecoveryRequired):self.runner().perform()
        self.assertEqual((len(self.calls),len(self.counts)),(0,1))
        self.assertEqual(self.runner().ledger.read()['requests'],self.original)

    def test_lost_valid_cache_and_invalid_reconciled_result_never_replay(self):
        original=self.state
        for case in ('lost_cache','invalid_result','uncertain_transport'):
            self.state=original.parent/case;shutil.copytree(original,self.state);sent=[]
            def post(*a,**k):
                sent.append(1)
                if case=='uncertain_transport':raise OSError('uncertain')
                if case=='invalid_result':return fixture.Response({'model':'claude-sonnet-5',
                    'stop_reason':'end_turn','usage':{'input_tokens':100,'output_tokens':20},
                    'content':[{'type':'text','text':'{}'}]})
                return self.provider(*a,**k)
            runner=repair.WireRunner(self.state,{},post=post)
            if case=='lost_cache':
                runner.perform();row=runner.ledger.read()['requests'][-1]
                (self.state/'cache'/(row['key']+'.json')).unlink()
            else:
                with self.assertRaises((ValueError,RecoveryRequired)):runner.perform()
            for _ in range(3):
                self.restored()
                with self.assertRaises(RecoveryRequired):self.runner().perform()
            self.assertEqual(len(sent),1)
        self.state=original

    def test_trusted_selector_prepare_execute_and_complete_cache_reuse(self):
        from types import SimpleNamespace
        args=SimpleNamespace(action='prepare',state=self.state,
            reservation=self.state.parent/'reservation.json',result=self.state.parent/'result.json')
        with patch.object(existing,'trusted_environment'), \
             patch.object(existing,'restore',return_value=self.runner().ledger), \
             patch.object(existing,'api',side_effect=self.api), \
             patch.dict(os.environ,{'CONTEXTUAL_CHECK':json.dumps({'compact_wire_repair':repair.VERSION})}):
            repair.run(args)
            reserve=json.loads(args.reservation.read_bytes())
            self.assertEqual((reserve['maximum_new_microusd'],reserve['maximum_new_attempts']),(200000,1))
            self.assertEqual(reserve['retained_unknown_hold_microusd'],614610)
            args.action='execute';runner=self.runner()
            with patch.object(repair,'WireRunner',return_value=runner):repair.run(args)
            self.assertEqual(len(json.loads(args.result.read_bytes())['value']['people']),12)
            args.action='prepare';repair.run(args)
            args.action='execute'
            with patch.object(repair,'WireRunner',return_value=runner):repair.run(args)
        self.assertEqual((len(self.calls),len(self.counts)),(1,1))
        with patch.object(existing,'trusted_environment'),patch.dict(os.environ,{
            'CONTEXTUAL_CHECK':json.dumps({'compact_wire_repair':repair.VERSION,'extra':'no'})}):
            with self.assertRaises(ConfigurationFailure):repair.run(args)


if __name__=='__main__':unittest.main()
