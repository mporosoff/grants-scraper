"""Zero-provider contract, budget and irreversible persistence regressions."""
import copy
import json
import os
import shutil
import unittest
from unittest.mock import patch
from tests import test_contextual_phase2 as fixture
from tools import contextual_team_latency as latency
from tools import contextual_team_latency_policy as policy
from tools import contextual_team_latency_contract as wire
from tools import contextual_team_requirements as requirements
from tools.contextual_team_executor import scope_inputs, RecoveryRequired
from tools.contextual_team_contract import verification_inputs
from tools.offline_ai import response_value
from tools.offline_spend import atomic_json, identity, encoded, Deferred, Refusal, ConfigurationFailure
from tools import team_recommender_executor as existing


class Latency(unittest.TestCase):
    def setUp(self):
        self.f=fixture.ColdDemand();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.config=latency.configuration();self.state=self.f.state;self.calls=[]
        ledger=json.loads((self.state/'ledger.json').read_bytes())
        for i in range(662,680):ledger['requests'].append({'id':f'{i+1:032x}','key':f'{i+1:064x}',
            'provider':'anthropic','model':'fixture','stage':2,'attempt':1,'charged_microusd':0,'status':'valid'})
        ledger['requests'][0]['charged_microusd']=7232138
        atomic_json(self.state/'ledger.json',ledger);existing.checkpoint(self.state)
        original=policy.plan();p=patch.object(policy,'plan',return_value=original|{'prior_rows_sha256':identity(ledger['requests'])})
        p.start();self.addCleanup(p.stop)
        env=patch.dict(os.environ,{'OPENAI_API_KEY':'fixture-only'});env.start();self.addCleanup(env.stop)

    def provider(self,url,**kw):
        b=kw['json'];self.calls.append((url,b))
        if 'input_type' in b:return fixture.Response({'model':b['model'],'usage':{'total_tokens':10},
            'data':[{'index':i,'embedding':[1.0]+[0.0]*1023} for i in range(len(b['input']))]})
        data=json.loads(b['input'] if b['model']=='gpt-5.6-luna' else b['messages'][0]['content'])
        if 'people' not in data:
            ref=data['source_references'][0]['source_ref']
            value={'state':'coherent','objective':'Synthetic mechanics fixture, not actual source interpretation.',
                'approach':'A source-grounded laboratory approach in this zero-provider fixture.',
                'roles':[{'id':'role-1','label':'Required scientific contribution','kind':'approach_necessary',
                    'applicability':'applies','condition':'','central':True,'source_ref':ref},
                    {'id':'role-2','label':'Unselected optional direction','kind':'optional_direction',
                     'applicability':'applies','condition':'','central':False,'source_ref':ref}],
                'limitations':['Synthetic transport fixture only.']}
        else:
            verify='proposed_edges' in data;table=data['proposed_edge_references' if verify else 'claim_references']
            useful=[p['person_id'] for p in data['people'][:2]]
            value={'people':{p['person_id']:{'outcome':'supported' if p['person_id'] in useful else 'insufficient_information'} for p in data['people']},'edges':[]}
            if verify:value['state']='coherent'
            for pid in useful:
                key=next(k for k,r in table.items() if r['person_id']==pid)
                edge={('edge_ref' if verify else 'claim_ref'):key,'coverage':'direct','central':True,
                      'reason':'Synthetic fixture tests the complete reference contract.','gap':''}
                if not verify:edge['role_id']='role-1'
                value['edges'].append(edge)
        usage={'input_tokens':10,'output_tokens':10}
        if b['model']=='gpt-5.6-luna':
            return fixture.Response({'model':b['model'],'status':'completed','usage':usage|{'output_tokens_details':{'reasoning_tokens':2}},
                'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(value)}]}]})
        return fixture.Response({'model':b['model'],'stop_reason':'end_turn','usage':usage,
                                'content':[{'type':'text','text':json.dumps(value)}]})

    def runner(self,state=None,**kw):
        return latency.LatencyRunner(state or self.state,self.config,post=self.provider,counter_post=self.f.count,**kw)

    def test_both_native_routes_complete_same_new_workflow_and_reuse(self):
        # Separate temporary ledger copies prevent either fixture borrowing the
        # other's logical operations. No real authorization history is changed.
        for route in ('S','L'):
            dest=self.state.parent/route;shutil.copytree(self.state,dest)
            with patch.object(latency.LatencyRunner,'selected_route',return_value=route):
                r=self.runner(dest);g=r.run_scope(self.config['scopes'][0]);before=len(self.calls)
                again=self.runner(dest).run_scope(self.config['scopes'][0])
            self.assertEqual(g['graph_id'],again['graph_id']);self.assertEqual(before,len(self.calls))
            self.assertEqual(g['version'],requirements.GRAPH_VERSION);self.assertEqual(g['state'],'ready')
            self.assertEqual(len(g['retrieval']['per_contribution']),1)
            self.assertEqual(g['retrieval']['eligible'],155);self.assertEqual(len(g['people']),12)
            self.assertTrue(all(e['role_id']=='role-1' for e in g['edges']))
            rows=r.ledger.read()['requests'][680:];self.assertEqual(len(rows),4)
            self.assertEqual({row['provider'] for row in rows},{'voyage','openai' if route=='L' else 'anthropic'})
            self.assertTrue(all(row['charged_microusd']<=row['reserved_microusd'] for row in rows))

    def test_same_evidence_and_canonical_schema_across_named_models(self):
        source=scope_inputs(self.config['scopes'][0]);c,b=wire.body('decomposition',source,'S',8000,True)
        self.assertEqual(b['thinking'],{'type':'adaptive'});self.assertEqual(b['output_config']['effort'],'medium')
        _,l=wire.body('decomposition',source,'L',8000,True)
        self.assertEqual(json.loads(b['messages'][0]['content']),json.loads(l['input']))
        self.assertEqual(b['system'],l['instructions']);self.assertFalse(l['store'])
        self.assertEqual(l['reasoning'],{'effort':'low'});self.assertEqual(l['text']['verbosity'],'low')
        self.assertTrue(l['text']['format']['strict']);self.assertEqual(c['schema'],l['text']['format']['schema'])

    def test_openai_incomplete_refusal_and_invalid_usage_never_become_science(self):
        for status in ('incomplete','failed','cancelled'):
            with self.assertRaises(ValueError):response_value('openai',{'status':status,'output':[]})
        with self.assertRaises(Refusal):response_value('openai',{'status':'completed','output':[{'type':'message','content':[{'type':'refusal'}]}]})
        with self.assertRaises(ValueError):self.runner().request_usage('openai',{'usage':{'input_tokens':10}},'gpt-5.6-luna')
        u,c=self.runner().request_usage('openai',{'usage':{'input_tokens':100,'output_tokens':100,'output_tokens_details':{'reasoning_tokens':80}}},'gpt-5.6-luna')
        self.assertEqual(c,140);self.assertEqual(u['reasoning_tokens'],80)

    def test_whole_plan_reserves_checks_and_protected_dollars_slots(self):
        state=self.runner().ledger.read();policy.remaining_fits(state)
        self.assertLessEqual(plan_cost:=sum(o['maximum_microusd'] for o in policy.plan()['operations']),1500000)
        self.assertEqual(plan_cost,1496005)
        changed=copy.deepcopy(state);changed['requests'].append({'charged_microusd':10000,'status':'valid'})
        with self.assertRaises(Deferred):policy.remaining_fits(changed)
        changed=copy.deepcopy(state);changed['requests'][3]['charged_microusd']+=1
        with self.assertRaises(ConfigurationFailure):policy.history(changed)

    def test_reconciled_and_uncertain_paid_lifecycle_has_no_duplicate_dispatch(self):
        class Crash(BaseException):pass
        source=scope_inputs(self.config['scopes'][0])
        for route in ('S','L'):
            for boundary in ('after_reserve','after_reservation_checkpoint','after_dispatch','before_reconcile','after_reconcile','after_cache','after_receipt','after_failed_reconcile'):
                dest=self.state.parent/(route+'-'+boundary);shutil.copytree(self.state,dest)
                def crash(name):
                    if name==boundary:raise Crash()
                r=self.runner(dest,crash=crash);before=len(self.calls)
                if boundary=='after_failed_reconcile':
                    real=r.post
                    def bad(url,**kw):
                        response=real(url,**kw);response.value['status' if route=='L' else 'stop_reason']='incomplete' if route=='L' else 'max_tokens';return response
                    r.post=bad
                c,body=wire.body('decomposition',source,route,24000,True)
                check=lambda v,cached: v if cached else response_value(c['route']['provider'],v)
                with self.assertRaises(Crash):r.request('cb-lr-'+route,[route,'fixture'],body,check)
                # A missing successful cache or failure receipt is not attempt2.
                for _ in range(3):
                    try:self.runner(dest).request('cb-lr-'+route,[route,'fixture'],body,check)
                    except (Deferred,ValueError):pass
                self.assertLessEqual(len(self.calls)-before,1,(route,boundary))
                self.assertEqual(len(r.ledger.read()['requests'])-680,1)

    def test_changed_body_cannot_rekey_one_named_operation(self):
        source=scope_inputs(self.config['scopes'][0]);c,b=wire.body('decomposition',source,'L',24000,True)
        check=lambda v,cached:v if cached else response_value('openai',v)
        r=self.runner();r.request('cb-lr-L',['original'],b,check);before=len(self.calls)
        b['instructions']+=' Changed'
        with self.assertRaises(Deferred):r.request('cb-lr-L',['different-key'],b,check)
        self.assertEqual(len(self.calls),before)

    def test_complete_unicode_checker_and_question_owned_references(self):
        from tools.contextual_team_contract import obj,enum,string
        from tools.contextual_team_phase2_check import validator
        questions=[{'item_id':'q'+str(i)} for i in range(36)]
        fields={q['item_id']:obj(verdict=enum('plausible'),evidence_ref=enum(q['item_id']+'-claim'),
                                 reason=string(300)) for q in questions}
        schema=obj(verdicts=obj(**fields));check=validator(questions,schema,65536)
        value={'verdicts':{q['item_id']:{'verdict':'plausible','evidence_ref':q['item_id']+'-claim',
                                      'reason':'界'*300} for q in questions}}
        payload={'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}]}
        resolved=check(payload,False);self.assertEqual(len(resolved['verdicts']),36)
        self.assertEqual(check(resolved,True),resolved)
        for bad in ('missing','wrong-reference'):
            v=copy.deepcopy(value)
            if bad=='missing':v['verdicts'].pop('q0')
            else:v['verdicts']['q0']['evidence_ref']='q1-claim'
            with self.assertRaises(ValueError):check({'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(v)}]},False)


if __name__=='__main__':unittest.main()
