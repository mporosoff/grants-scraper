"""Zero-provider lifecycle fixtures; never scientific validation results."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import contextual_team_phase2 as p2
from tools import team_recommender_executor as existing
from tools.contextual_team_demand_contract import claim_table,edge_table
from tools.contextual_team_references import source_references
from tools.offline_spend import atomic_json,identity,encoded,Deferred


class Response:
    status_code=200
    def __init__(self,value):self.value=value
    def iter_content(self,chunk_size):yield encoded(self.value)
    def close(self):pass


class ColdDemand(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.state=Path(temp.name)/'state';self.state.mkdir()
        env=patch.dict(os.environ,{'ANTHROPIC_API_KEY':'fixture','VOYAGE_API_KEY':'fixture',
            'GITHUB_RUN_ID':'1','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'a'*40})
        env.start();self.addCleanup(env.stop)
        ledger=json.loads((existing.CONFIG/'initial-ledger.json').read_bytes())
        # Artificial historical ledger and vectors, confined to this temp fixture.
        ledger['requests']=[{'id':f'{i:032x}','key':f'{i:064x}','provider':'anthropic','model':'claude-sonnet-5',
            'stage':2,'attempt':1,'charged_microusd':5821980 if i==1 else 0,'status':'valid','purpose':'fixture-history'} for i in range(1,663)]
        self.config=p2.configuration();self.calls=[];self.counts=[];self.noncoherent=False;self.negative=False
        for n,start in enumerate((0,80)):
            docs=self.config['documents'][start:start+80];row=ledger['requests'][n+1]
            row.update(provider='voyage',model='voyage-4-large',row_inputs=['cb:document:'+d['input_id'] for d in docs],body_sha256='b'*64)
            value=[{'id':d['input_id'],'embedding':[1.0]+[0.0]*1023} for d in docs]
            atomic_json(self.state/'cache'/(row['key']+'.json'),{'key':row['key'],'request_id':row['id'],
                'body_sha256':row['body_sha256'],'model':row['model'],'value':value})
        atomic_json(self.state/'ledger.json',ledger);existing.checkpoint(self.state)
        # Bind the test's artificial history, without altering the real lock.
        original_plan=p2.base_plan
        override=patch.object(p2,'plan',side_effect=lambda:original_plan()|{'prior_request_rows_sha256':identity(ledger['requests'])})
        override.start();self.addCleanup(override.stop)

    def count(self,url,**kwargs):
        self.counts.append(kwargs['json']);return Response({'input_tokens':1000})

    def provider(self,url,**kwargs):
        body=kwargs['json'];self.calls.append(body)
        if 'input_type' in body:
            return Response({'model':'voyage-4-large','usage':{'total_tokens':10},
                'data':[{'index':i,'embedding':[1.0]+[0.0]*1023} for i in range(len(body['input']))]})
        data=json.loads(body['messages'][0]['content']);schema=body['output_config']['format']['schema']['properties']
        if 'roles' in schema:
            ref=data['source_references'][0]['source_ref']
            value={'state':'needs_scope_selection' if self.noncoherent else 'coherent',
                'objective':'Synthetic transport fixture, not a scientific recommendation.',
                'roles':[] if self.noncoherent else [{'id':'role-1','label':'Fixture contribution','required':False,'central':True,'source_ref':ref}],
                'limitations':['Synthetic transport fixture only.']}
        else:
            verification='proposed_edges' in data;table=edge_table(data) if verification else claim_table(data)
            useful=[p['person_id'] for p in data['people'][:2]]
            value={'people':{p['person_id']:{'outcome':'insufficient_information' if self.negative or p['person_id'] not in useful else 'supported'} for p in data['people']},'edges_by_contribution':{'role-1':[]}}
            if verification:value['state']='coherent'
            if not self.negative:
                for pid in useful:
                    key=next(k for k,v in table.items() if v['person_id']==pid)
                    value['edges_by_contribution']['role-1'].append({('edge_ref' if verification else 'claim_ref'):key,
                        'coverage':'direct','central':True,'reason':'Synthetic fixture checks reference transport, not applicability.','gap':''})
        return Response({'model':'claude-sonnet-5','stop_reason':'end_turn',
            'usage':{'input_tokens':10,'output_tokens':10},'content':[{'type':'text','text':json.dumps(value)}]})

    def runner(self):return p2.Phase2Runner(self.state,self.config,post=self.provider,counter_post=self.count)

    def test_normal_cold_path_and_exact_repeat_use_same_graph(self):
        scope=self.config['scopes'][0];first=self.runner().run_scope(scope)
        self.assertIn(first['state'],('ready','ready_with_gaps'))
        self.assertEqual(first['retrieval']['eligible'],155);self.assertEqual(len(first['people']),12)
        self.assertEqual(len(self.calls),4);self.assertEqual(len(self.counts),3)
        second=self.runner().run_scope(scope)
        self.assertEqual(first['graph_id'],second['graph_id'])
        self.assertEqual(len(self.calls),4);self.assertEqual(len(self.counts),3)
        rows=self.runner().ledger.read()['requests'][662:]
        self.assertEqual(len(rows),4);self.assertTrue(all(r['phase2_lock']==p2.RELEASE for r in rows))
        self.assertTrue(all(r['charged_microusd']<=r['reserved_microusd'] for r in rows))

    def test_noncoherent_scope_does_not_purchase_later_stages(self):
        self.noncoherent=True;result=self.runner().run_scope(self.config['scopes'][0])
        self.assertEqual(result['state'],'needs_scope_selection');self.assertEqual(len(self.calls),1)
        self.assertTrue(p2.scope_result_path(self.state,self.config['scopes'][0]['id']).exists())

    def test_prepared_negative_is_not_unprepared(self):
        self.negative=True;result=self.runner().run_scope(self.config['scopes'][0])
        self.assertEqual(result['state'],'no_supported_group_in_assessed_set');self.assertEqual(len(result['people']),12)
        self.assertEqual(result['edges'],[]);self.assertEqual(len(self.calls),4)

    def test_source_parent_and_official_currentness_corrections_are_bound(self):
        child,mathbio,_=self.config['scopes']
        self.assertEqual(child['parent_id'],'363302');self.assertTrue(child['conditions']['cost_share_required'])
        self.assertFalse(child['historical_catalog_currentness']['parent']['cost_share_required'])
        self.assertTrue(mathbio['conditions']['rolling']);self.assertIsNone(mathbio['conditions']['close_date'])
        self.assertEqual(mathbio['historical_catalog_currentness']['parent']['close_date'],'2026-10-14')
        self.assertEqual(mathbio['conditions']['deadlines'][1]['date'],'2026-10-13')

    def test_whole_plan_fits_original_reserve_and_retains_all_checks(self):
        plan=p2.plan();self.assertEqual(len(plan['operations']),18)
        self.assertEqual(plan['maximum_inventory_microusd'],2497240)
        self.assertEqual(sum(x['maximum_microusd'] for x in plan['operations']),2497240)
        self.assertEqual(sum(x['stage'].startswith('check-') for x in plan['operations']),6)
        self.assertGreaterEqual(10_000_000-5821980-2497240,1678020)
        p2.ensure_remaining_plan_fits(self.runner().ledger.read())
        ledger=self.runner().ledger.read();ledger['requests'].append(copy.deepcopy(ledger['requests'][0]))
        with self.assertRaises(Deferred):p2.ensure_remaining_plan_fits(ledger)

    def test_native_oversize_stops_before_metered_dispatch_without_clipping(self):
        runner=self.runner();runner.counter.post=lambda *a,**k:Response({'input_tokens':50000})
        with self.assertRaises(Deferred):runner.run_scope(self.config['scopes'][0])
        self.assertEqual(self.calls,[]);self.assertEqual(len(runner.ledger.read()['requests']),662)

    def test_missing_document_vectors_never_rebuild_directory(self):
        for p in (self.state/'cache').glob('*.json'):p.unlink()
        runner=self.runner()
        with self.assertRaises(p2.RecoveryRequired):runner.run_scope(self.config['scopes'][0])
        self.assertEqual(len(self.calls),1);self.assertTrue(all(b['model']=='claude-sonnet-5' for b in self.calls))

    def test_paid_unknown_or_failed_operation_cannot_be_rekeyed(self):
        runner=self.runner();scope=self.config['scopes'][0];runner.run_scope(scope)
        state=runner.ledger.read();row=next(r for r in state['requests'] if r.get('purpose')=='cb-p2-interpret');row['status']='failed'
        atomic_json(runner.ledger.path,state);before=len(self.calls);count_before=len(self.counts)
        with self.assertRaises(p2.RecoveryRequired):runner.run_scope(scope)
        self.assertEqual(len(self.calls),before);self.assertEqual(len(self.counts),count_before)
        runner.scope_id=scope['id']
        with self.assertRaises(p2.RecoveryRequired):runner.request('cb-p2-interpret',['different-key'],self.calls[0],lambda x,**k:x)
        self.assertEqual(len(self.calls),before);self.assertEqual(len(self.counts),count_before)


if __name__=='__main__':unittest.main()
