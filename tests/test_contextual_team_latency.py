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
            return fixture.Response({'model':b['model']+'-2026-09-08','status':'completed','usage':usage|{'output_tokens_details':{'reasoning_tokens':2}},
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

    def test_dated_response_is_preserved_and_reused_but_mismatches_remain_charged(self):
        source=scope_inputs(self.config['scopes'][0]);c,b=wire.body('decomposition',source,'L',24000,True)
        check=lambda v,cached:v if cached else response_value('openai',v)
        r=self.runner();r.request('cb-lr-L',['dated'],b,check)
        row=r.ledger.read()['requests'][-1];cache=self.state/'cache'/(row['key']+'.json')
        receipt=json.loads((self.state/'receipts'/(row['id']+'.json')).read_bytes())
        retained=json.loads(cache.read_bytes())
        self.assertEqual(receipt['returned_model'],'gpt-5.6-luna-2026-09-08')
        self.assertEqual(retained['returned_model'],receipt['returned_model'])
        r.request('cb-lr-L',['dated'],b,check);self.assertEqual(len(self.calls),1)
        retained['returned_model']='gpt-5.6-sol-2026-09-08';atomic_json(cache,retained)
        with self.assertRaises(RecoveryRequired):r.request('cb-lr-L',['dated'],b,check)
        self.assertEqual(len(self.calls),1)
        for returned in ('gpt-5.6-sol','gpt-5.6-luna-2026-09-08-extra',None):
            # A fresh isolated fixture ledger; never a second real spending copy.
            dest=self.state.parent/str(returned);shutil.copytree(self.state,dest)
            ledger=json.loads((dest/'ledger.json').read_bytes());ledger['requests']=ledger['requests'][:680]
            atomic_json(dest/'ledger.json',ledger)
            real=self.provider
            def wrong(url,**kw):
                response=real(url,**kw);response.value['model']=returned;return response
            runner=self.runner(dest);runner.post=wrong;before=len(self.calls)
            with self.assertRaises(ValueError):runner.request('cb-lr-L',['wrong'],b,check)
            row=runner.ledger.read()['requests'][-1]
            self.assertEqual(row['status'],'failed');self.assertGreater(row['charged_microusd'],0)
            for _ in range(3):
                with self.assertRaises(RecoveryRequired):runner.request('cb-lr-L',['wrong'],b,check)
            self.assertEqual(len(self.calls)-before,1)

    def test_nonoverlapping_maximum_union_and_full_variable_packet_bound(self):
        from tools.contextual_team_latency_check import comparison_packet,comparison_bounds,comparison_variable_bytes,comparison_sizing_packet
        data=scope_inputs(self.config['scopes'][0])|{'people':self.config['people'][:12],
             'interpretation':{'roles':[{'id':'role-1'},{'id':'role-2'}]}}
        arms={}
        for name,start in (('S',0),('L',4),('reference',8)):
            arms[name]={'edges':[{'role_id':role['id'],'person_id':p['person_id'],
                'claim_id':p['claims'][0]['claim_id'],'claim_revision':p['claims'][0]['revision']}
                for role in data['interpretation']['roles'] for p in data['people'][start:start+4]]}
        reference=arms.pop('reference')
        with patch('tools.contextual_team_latency_check.eclipse_data',return_value=(data,reference)):
            full,qs,_,_,_=comparison_packet(self.state,sizing_arms=arms)
            fixed,fqs,_,_,_=comparison_packet(self.state,sizing_arms=arms,fixed_only=True)
            limits=comparison_bounds(data,reference)
            self.assertEqual(limits,{'relationships':24,'people':12,'per_arm':8})
            self.assertEqual(len(qs),36);self.assertEqual(len(fqs),12)
            sized,_,extra=comparison_sizing_packet(self.state)
            self.assertGreater(extra,0);self.assertGreaterEqual(extra,len(encoded(full))-len(encoded(sized)))
            self.assertEqual(len(json.loads(sized['messages'][0]['content'])['items']),36)
            native=wire.body('adjudication',data,'L',24000)[1]['text']['format']['schema']
            self.assertEqual(native['properties']['edges']['maxItems'],8)
            # A ninth edge cannot become a valid canonical paid result, even
            # though all supplied reference identities individually exist.
            with self.assertRaises(ValueError):
                wire.resolve('adjudication',{'people':{p['person_id']:{'outcome':'supported'} for p in data['people']},
                    'edges':[{'role_id':'role-1','claim_ref':p['claims'][0]['claim_id']+'@'+str(p['claims'][0]['revision']),
                        'coverage':'direct','central':True,'reason':'Fixture reference transport only.','gap':''}
                        for p in data['people'][:9]]},data)
            too_many=copy.deepcopy(arms)
            too_many['S']['edges'] += [{**e,'claim_id':e['claim_id']+'-extra'} for e in arms['S']['edges']]
            with self.assertRaises(ConfigurationFailure):comparison_packet(self.state,sizing_arms=too_many)

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

    def test_complete_preflight_defers_oversize_comparison_before_any_paid_work(self):
        from tools.contextual_team_latency_preflight import preflight
        from tools.contextual_team_token_preflight import VERSION,SOURCE_SHA
        data=scope_inputs(self.config['scopes'][0])|{'people':self.config['people'][:12],
            'interpretation':{'roles':[{'id':'role-1'},{'id':'role-2'}]}}
        reference={'edges':[{'role_id':role['id'],'person_id':p['person_id'],
            'claim_id':p['claims'][0]['claim_id'],'claim_revision':p['claims'][0]['revision']}
            for role in data['interpretation']['roles'] for p in data['people'][:4]]}
        profile_rows=[{'id':'profile:'+p['person_id'],'input_tokens':1000,'status':'complete'} for p in self.config['people']]
        existing.checkpoint(self.state,token_preflight={'version':VERSION,'source_sha256':SOURCE_SHA,'rows':profile_rows})
        with patch('tools.contextual_team_latency_preflight.eclipse_data',return_value=(data,reference)), \
             patch('tools.contextual_team_latency_check.eclipse_data',return_value=(data,reference)):
            runner=self.runner()
            with patch.object(runner.counter,'count',return_value=26000):
                with self.assertRaises(Deferred):preflight(runner)
            def counts(item):return 26000 if item['id']=='latency:comparison-complete-sizing' else 1000
            with patch.object(runner.counter,'count',side_effect=counts):
                with self.assertRaisesRegex(Deferred,'complete_comparison_input_capacity'):preflight(runner)
            self.assertFalse(latency.result_path(self.state,'preflight').exists())
            with patch.object(runner.counter,'count',return_value=1000):receipt=preflight(runner)
            self.assertEqual(receipt['comparison_question_bound'],36)
            self.assertEqual(receipt['profile_count_cache_reuse'],155)
            self.assertEqual(receipt['all_eight_reserved_microusd'],1496005)
        self.assertEqual(self.calls,[]);self.assertEqual(len(self.runner().ledger.read()['requests']),680)


if __name__=='__main__':unittest.main()
