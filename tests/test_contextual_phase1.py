"""Synthetic contract/accounting fixtures, not scientific judgments."""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import requests
from tools.contextual_team_check import packet, RESPONSE_CONTRACT, LEGACY_FORMAT, REVISED_FORMAT
from tools.contextual_team_phase1 import plan, execute, ensure_remaining_plan_fits, prepared_packets
from tools.contextual_team_option1 import configuration_for_job
from tools.contextual_team_executor import Runner, RecoveryRequired
from tools.contextual_team_cost import text_reservation
from tools.contextual_team_policy import check_reservation
from tools.offline_spend import identity, atomic_json, Deferred, Refusal, ConfigurationFailure
from tools.team_recommender_budget import ExperimentLedger
from tests.test_contextual_team_executor import Response, Crash


def answer(body):
    data=json.loads(body['messages'][0]['content'])
    return {'verdicts':[{'item_id':q['item_id'],
        'verdict':'unsupported' if q['task_type']=='explanation_audit' else 'unrelated',
        'evidence_ref':q['people'][0],
        'reason':'Fixture only. A complete multi-sentence rationale is preserved without truncation.'}
        for q in data['items']]}


def envelope(value,stop='end_turn'):
    return {'model':'claude-sonnet-5','usage':{'input_tokens':10,'output_tokens':20},
        'stop_reason':stop,'content':[{'type':'text','text':json.dumps(value)}]}


class CheckContract(unittest.TestCase):
    def setUp(self):
        self.p=plan();self.config=configuration_for_job({'release_id':self.p['release_id'],'scope_id':'332894','person_id':''})
        self.scope=next(s for s in self.config['scopes'] if s['id']=='332894')
        self.graph={'edges':[{'person_id':p['person_id'],'coverage':'method_transfer','central':True,
            'role_id':'fixture-role','claim_id':p['claims'][0]['claim_id'],'reason':'Fixture assertion, not science.',
            'evidence_quote':p['claims'][0]['evidence'],'gap':'Fixture only.'}
            for p in self.config['people'] if p['person_id'] in self.p['members']]}

    def packets(self):
        return [(kind,*packet(self.scope,self.graph,self.p['members'],kind,self.config,revised=True)) for kind in ('group','explanation')]

    def test_both_batches_preserve_complete_questions_and_scientific_prompt(self):
        for kind,body,check in self.packets():
            original,_=packet(self.scope,self.graph,self.p['members'],kind,self.config)
            self.assertEqual(body['messages'],original['messages'])
            self.assertEqual(body['system'],original['system'].replace(LEGACY_FORMAT,REVISED_FORMAT))
            self.assertNotIn('60 ASCII',body['system'])
            self.assertEqual(body['thinking'],{'type':'disabled'});self.assertEqual(body['max_tokens'],2048)
            self.assertEqual(len(answer(body)['verdicts']),4 if kind=='group' else 3)
            value=answer(body)
            for reason in ('x'*72,'Fixture: résumé and λ. '+('A complete further explanatory sentence. '*20)):
                for row in value['verdicts']:row['reason']=reason
                self.assertEqual(check(envelope(value),False),value)
                self.assertEqual(check(value,True),value)

    def test_both_batches_reject_missing_duplicate_unknown_and_wrongly_mapped_ids(self):
        for kind,body,check in self.packets():
            for mutation in ('missing','duplicate','unknown','wrong_person','wrong_claim','extra'):
                with self.subTest(kind=kind,mutation=mutation):
                    value=answer(body)
                    if mutation=='missing':value['verdicts'].pop()
                    elif mutation=='duplicate':value['verdicts'][-1]=copy.deepcopy(value['verdicts'][0])
                    elif mutation=='unknown':value['verdicts'][-1]['item_id']='not-a-question'
                    elif mutation=='extra':value['verdicts'].append(copy.deepcopy(value['verdicts'][0]))
                    else:
                        row=next(v for v in value['verdicts'] if v['item_id'].endswith('-1'))
                        other=next(p for p in self.config['people'] if p['person_id']==self.p['members'][1])
                        row['evidence_ref']=other['person_id'] if mutation=='wrong_person' else other['claims'][0]['claim_id']
                    with self.assertRaises(ValueError):check(envelope(value),False)

    def test_both_batches_reject_bad_enum_type_extra_fields_empty_and_oversize_reasons(self):
        for kind,body,check in self.packets():
            for field,value in [('verdict','approved'),('reason',42),('reason',''),('reason','x'*32768),('evidence_ref',None),('extra','field')]:
                with self.subTest(kind=kind,field=field):
                    bad=answer(body);bad['verdicts'][0][field]=value
                    with self.assertRaises(ValueError):check(envelope(bad),False)

    def test_completion_parser_rejects_partial_refused_or_truncated_both_batches(self):
        for _,body,check in self.packets():
            for stop,text in [('max_tokens',json.dumps(answer(body))),('refusal','{}'),('end_turn','{"verdicts":[')]:
                payload=envelope(answer(body),stop);payload['content'][0]['text']=text
                with self.assertRaises((ValueError,Refusal)):check(payload,False)
            payload=envelope(answer(body));payload['content'].insert(0,{'type':'thinking','thinking':'DO NOT RETAIN THIS'})
            self.assertNotIn('DO NOT RETAIN',json.dumps(check(payload,False)))

    def test_fixed_authority_graph_members_and_contract_are_not_caller_choices(self):
        with self.assertRaises(ConfigurationFailure):prepared_packets(Path('absent'),[],self.p)
        wrong=[{'scope_id':self.p['scope_id'],'graph_id':self.p['graph_id'],'members':list(reversed(self.p['members']))}]
        with self.assertRaises(ConfigurationFailure):prepared_packets(Path('absent'),wrong,self.p)
        self.assertEqual(self.p['response_contract_sha256'],identity(RESPONSE_CONTRACT))
        self.assertEqual(self.p['maximum_new_attempts'],2)
        self.assertEqual(self.p['total_reserved_microusd'],126956)


class CheckLifecycle(CheckContract):
    def setUp(self):
        super().setUp()
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)/'state';self.state.mkdir()
        ledger=ExperimentLedger(self.state/'ledger.json',initialize=True);state=ledger.read()
        rows=[{'id':'fixture-'+str(i),'key':identity(['fixture',i]),'purpose':'fixture-history',
               'status':'valid','charged_microusd':0,'provider':'anthropic','stage':2} for i in range(659)]
        rows[-1].update(self.p['repair_of']);rows[0]['charged_microusd']=self.p['starting_spend_microusd']-rows[-1]['charged_microusd']
        self.p['starting_request_rows_sha256']=identity(rows);state['requests']=rows;atomic_json(ledger.path,state)
        self.locked=[]
        for op,(_,body,check) in zip(self.p['operations'],self.packets()):
            bound,cost=text_reservation(body);op.update(body_sha256=identity(body),input_token_bound=bound,maximum_microusd=cost)
            self.locked.append((op,body,check))
        self.mock=patch('tools.contextual_team_phase1.plan',return_value=self.p);self.mock.start();self.addCleanup(self.mock.stop)
        self.env=patch.dict(os.environ,{'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'fixture','GITHUB_RUN_ATTEMPT':'1','ANTHROPIC_API_KEY':'fixture-only'})
        self.env.start();self.addCleanup(self.env.stop)
        self.calls=[];self.failure=None

    def provider(self,url,**kwargs):
        body=kwargs['json'];self.calls.append(copy.deepcopy(body))
        if self.failure=='timeout':raise requests.Timeout('fixture only')
        bad=self.failure=='invalid' or (self.failure=='second_invalid' and len(self.calls)==2)
        return Response(envelope({} if bad else answer(body)))

    def runner(self,state=None,crash=lambda boundary:None):return Runner(state or self.state,self.config,post=self.provider,crash=crash)

    def call_one(self,runner,op_index=0):
        op,body,check=self.locked[op_index]
        return runner.request(op['purpose'],[op['purpose'],self.p['release_id'],self.p['scope_id'],op['kind']],body,check,
            ceiling=op['input_token_bound'],repair_metadata={'phase1_lock':self.p['lock_id'],
              'response_contract_sha256':self.p['response_contract_sha256'],'repair_of':op['repair_of']})

    def test_negative_science_completes_both_then_exact_reuse_never_dispatches(self):
        out=Path(self.tmp.name)/'result.json'
        for _ in range(3):execute(self.runner(),self.locked,self.p,out)
        result=json.loads(out.read_bytes())
        self.assertEqual(len(self.calls),2);self.assertEqual(len(result['results']),2)
        self.assertEqual(len(result['durable_requests']),2)
        self.assertEqual(sum(r['charged_microusd'] for r in result['durable_requests']),440)
        self.assertEqual(result['results'][0]['value']['verdicts'][0]['verdict'],'unrelated')

    def test_first_valid_persists_when_second_fails_and_empty_result_is_not_zero_spend(self):
        self.failure='second_invalid';out=Path(self.tmp.name)/'result.json'
        with self.assertRaises(ValueError):execute(self.runner(),self.locked,self.p,out)
        result=json.loads(out.read_bytes());self.assertEqual(len(result['results']),1)
        self.assertEqual([r['status'] for r in result['durable_requests']],['valid','failed'])
        self.assertEqual(self.call_one(self.runner()),result['results'][0]['value'])
        for _ in range(3):
            with self.assertRaises(RecoveryRequired):execute(self.runner(),self.locked,self.p,out)
        self.assertEqual(len(self.calls),2)

    def test_first_technical_failure_stops_shared_boundary_and_preserves_charge(self):
        self.failure='invalid';out=Path(self.tmp.name)/'result.json'
        with self.assertRaises(ValueError):execute(self.runner(),self.locked,self.p,out)
        result=json.loads(out.read_bytes());self.assertEqual(result['results'],[])
        self.assertEqual(len(result['durable_requests']),1)
        self.assertEqual(result['durable_requests'][0]['charged_microusd'],220)
        self.assertEqual(len(self.calls),1)

    def test_crash_boundaries_repeated_restoration_zero_duplicate_dispatches(self):
        pristine=Path(self.tmp.name)/'pristine';shutil.copytree(self.state,pristine)
        for boundary in ('after_reserve','after_reservation_checkpoint','after_dispatch','before_reconcile',
                         'after_reconcile','after_cache','after_receipt','after_failed_reconcile'):
            with self.subTest(boundary=boundary):
                state=Path(self.tmp.name)/boundary;shutil.copytree(pristine,state)
                saved=Path(self.tmp.name)/(boundary+'-saved')
                def crash(name):
                    if name==boundary:shutil.copytree(state,saved);raise Crash()
                self.failure='invalid' if boundary=='after_failed_reconcile' else None
                with self.assertRaises(Crash):self.call_one(self.runner(state,crash))
                before=len(self.calls)
                for i in range(3):
                    restored=Path(self.tmp.name)/(boundary+'-restored-'+str(i));shutil.copytree(saved,restored)
                    try:self.call_one(self.runner(restored))
                    except Deferred:pass
                    self.assertEqual(len(self.calls),before)

    def test_uncertain_transport_remains_reserved_and_cannot_unlock_second_request(self):
        self.failure='timeout'
        with self.assertRaises(RecoveryRequired):self.call_one(self.runner())
        before=len(self.calls)
        for i in (0,1,0):
            with self.assertRaises(RecoveryRequired):self.call_one(self.runner(),i)
        self.assertEqual(len(self.calls),before)
        row=self.runner().ledger.read()['requests'][-1]
        self.assertEqual(row['status'],'reserved_unknown');self.assertEqual(row['charged_microusd'],row['reserved_microusd'])

    def test_no_legacy_or_rekey_retry_and_exact_body_only(self):
        self.call_one(self.runner());runner=self.runner();op,body,check=self.locked[0]
        with self.assertRaises(RecoveryRequired):runner.request(op['purpose'],['changed-key'],body,check,
            repair_metadata={'phase1_lock':self.p['lock_id'],'response_contract_sha256':self.p['response_contract_sha256'],'repair_of':op['repair_of']})
        for purpose in ('cb-o1-check-group','cb-o1-check-explanation'):
            with self.assertRaises(Deferred):check_reservation(runner.ledger.read(),'anthropic',{'purpose':purpose},1000,100,512)
        op,body,check=self.locked[1];changed=copy.deepcopy(body);changed['messages'][0]['content']+=' '
        with self.assertRaises(ConfigurationFailure):runner.request(op['purpose'],['changed'],changed,check,
            repair_metadata={'phase1_lock':self.p['lock_id'],'response_contract_sha256':self.p['response_contract_sha256'],'repair_of':''})
        self.assertEqual(len(self.calls),1)

    def test_remaining_envelope_history_original_and_intervening_usage(self):
        state=self.runner().ledger.read();ensure_remaining_plan_fits(state,self.p)
        for mutation in ('history','original','old_explanation','money','attempts'):
            changed=copy.deepcopy(state)
            if mutation=='history':changed['requests'].pop(0)
            elif mutation=='original':changed['requests'][-1]['status']='reserved_unknown'
            elif mutation=='old_explanation':changed['requests'].append({'purpose':'cb-o1-check-explanation','id':'other','status':'valid','charged_microusd':220})
            elif mutation=='money':changed['requests'].append({'purpose':'other','id':'other','status':'valid','charged_microusd':250000})
            else:changed['requests'].append({'purpose':'other','id':'other','status':'valid','charged_microusd':0})
            with self.assertRaises(Deferred):ensure_remaining_plan_fits(changed,self.p)


if __name__=='__main__':unittest.main()
