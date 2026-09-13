import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from tools.contextual_team_executor import Runner, scope_inputs
from tools.contextual_team_policy import inputs
from tools.contextual_team_contract import contract
from tools.contextual_team_cost import text_reservation
from tools.contextual_team_check import packet
from tools.offline_ai import request_body
from tools.offline_spend import Deferred
from tools.team_recommender_budget import ExperimentLedger


class Crash(BaseException):pass


class Response:
    status_code=200
    def __init__(self,value):self.value=value
    def iter_content(self,size):yield json.dumps(self.value).encode()
    def close(self):pass


class FixtureProvider:
    def __init__(self):self.calls=[];self.invalid=False
    def __call__(self,url,**kwargs):
        body=kwargs['json'];self.calls.append((url,copy.deepcopy(body)))
        if body['model']=='voyage-4-large':
            return Response({'model':body['model'],'usage':{'total_tokens':10},
                'data':[{'index':i,'embedding':[1.0]+[0.0]*1023} for i in range(len(body['input']))]})
        data=json.loads(body['messages'][0]['content'])
        if 'people' not in data:
            value={'state':'coherent','objective':'Fixture purpose from supplied scientific source.',
                'roles':[{'id':'role-1','label':'Fixture contribution','required':True,
                    'quote':data['scope']['science']['description'][:40],'source_field':'description','central':True}],
                'limitations':['Fixture only; not a scientific evaluation.']}
        else:
            edges=[];people=[]
            for i,p in enumerate(data['people']):
                c=p['claims'][0];use=i<2
                people.append({'person_id':p['person_id'],'outcome':'supported' if use else 'insufficient_information'})
                if use:edges.append({'role_id':'role-1','person_id':p['person_id'],'claim_id':c['claim_id'],
                    'claim_revision':c['revision'],'coverage':'direct','central':True,'evidence_quote':c['evidence'][:40],
                    'reason':'Fixture contribution with retained evidence.','gap':'Fixture, not semantic evidence.'})
            value={'people':people,'edges':edges}
            if 'proposed_edges' in data:value['state']='coherent'
        return Response({'model':body['model'],'usage':{'input_tokens':10,'output_tokens':20},'stop_reason':'end_turn',
            'content':[{'type':'text','text':json.dumps({} if self.invalid else value)}]})


class ContextualExecutor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.configuration=inputs()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)/'state';self.state.mkdir()
        ExperimentLedger(self.state/'ledger.json',initialize=True)
        self.env=patch.dict(os.environ,{'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1',
            'ANTHROPIC_API_KEY':'fixture-only','VOYAGE_API_KEY':'fixture-only'})
        self.env.start();self.addCleanup(self.env.stop);self.provider=FixtureProvider()
        self.scope=next(s for s in self.configuration['scopes'] if s['id']=='344592:ab-0025')

    def runner(self,state=None,crash=lambda name:None):return Runner(state or self.state,self.configuration,post=self.provider,crash=crash)

    def test_full_directory_pipeline_exact_cache_and_explicit_extension(self):
        first=self.runner().run_scope(self.scope)
        self.assertEqual(len(self.provider.calls),6)
        self.assertEqual(first['retrieval']['eligible'],len(self.configuration['documents']))
        self.assertEqual(len(first['people']),12)
        second=self.runner().run_scope(self.scope)
        self.assertEqual(second['graph_id'],first['graph_id']);self.assertEqual(len(self.provider.calls),6)
        pid=next(p['person_id'] for p in self.configuration['people'] if p['person_id'] not in first['retrieval']['shortlist'])
        extended=self.runner().run_scope(self.scope,pid)
        self.assertEqual(len(self.provider.calls),8);self.assertEqual(len(extended['people']),13)
        self.runner().run_scope(self.scope,pid);self.assertEqual(len(self.provider.calls),8)
        for scope in self.configuration['scopes']:
            if scope['state']=='needs_scope_selection':self.assertEqual(self.runner().run_scope(scope)['state'],'needs_scope_selection')
        self.assertEqual(len(self.provider.calls),8)

    def test_every_persistence_boundary_restores_without_duplicate_dispatch(self):
        for boundary in ['after_reserve','after_reservation_checkpoint','after_dispatch','before_reconcile',
                         'after_reconcile','after_cache','after_receipt','after_failed_reconcile']:
            with self.subTest(boundary=boundary):
                state=Path(self.tmp.name)/boundary;state.mkdir();ExperimentLedger(state/'ledger.json',initialize=True)
                saved=Path(self.tmp.name)/(boundary+'-persisted')
                def crash(name):
                    if name==boundary:
                        shutil.copytree(state,saved);raise Crash()
                self.provider.invalid=boundary=='after_failed_reconcile'
                with self.assertRaises(Crash):self.runner(state,crash).scientific('decomposition',scope_inputs(self.scope),self.scope)
                before=len(self.provider.calls)
                for i in range(3):
                    restored=Path(self.tmp.name)/(boundary+'-restore-'+str(i));shutil.copytree(saved,restored)
                    try:self.runner(restored).scientific('decomposition',scope_inputs(self.scope),self.scope)
                    except Deferred:pass
                    self.assertEqual(len(self.provider.calls),before)
                self.provider.invalid=False

    def test_lost_row_cache_is_not_rebought_with_different_batch(self):
        docs=self.configuration['documents'][:2]
        self.runner().vectors(docs,'document');self.assertEqual(len(self.provider.calls),1)
        self.runner().vectors(list(reversed(docs)),'document');self.assertEqual(len(self.provider.calls),1)
        for p in (self.state/'cache').glob('*.json'):p.unlink()
        with self.assertRaisesRegex(Deferred,'recovery'):self.runner().vectors([docs[0]],'document')
        self.assertEqual(len(self.provider.calls),1)

    def test_changed_unselected_profile_reuses_unchanged_rows_but_not_old_text(self):
        docs=copy.deepcopy(self.configuration['documents'][:3])
        self.runner().vectors(docs,'document')
        from tools.offline_spend import identity
        docs[2]['text']+=' Fixture material change.';docs[2]['input_id']=identity(docs[2]['text'])
        self.runner().vectors(docs,'document')
        self.assertEqual(len(self.provider.calls),2)
        self.assertEqual(self.provider.calls[-1][1]['input'],[docs[2]['text']])

    def test_no_cache_price_contract_and_complete_judge_packet(self):
        c=contract('decomposition');body=request_body(c['route'],c['settings'],c['prompt'],scope_inputs(self.scope),c['schema'])
        bound,amount=text_reservation(body);self.assertEqual(amount,bound*2+80000)
        body['cache_control']={'type':'ephemeral'}
        with self.assertRaises(ValueError):text_reservation(body)
        graph=self.runner().run_scope(self.scope);members=[p['person_id'] for p in graph['people'][:2]]
        for kind in ['group','explanation']:
            body,_=packet(self.scope,graph,members,kind,self.configuration)
            self.assertEqual(body['thinking'],{'type':'disabled'})
            data=json.loads(body['messages'][0]['content'])
            for person in data['profile_documents']:
                self.assertEqual(person,next(p for p in self.configuration['people'] if p['person_id']==person['person_id']))
            if kind=='group':self.assertNotIn('Fixture contribution with retained evidence.',body['messages'][0]['content'])

    def test_task_cap_cannot_reset_or_reuse_stage2_ceiling(self):
        ledger=ExperimentLedger(self.state/'ledger.json');s=ledger.read()
        s['requests']=[{'key':'historical','charged_microusd':9_290_600,'purpose':'history'}];self.state.joinpath('ledger.json').write_text(json.dumps(s))
        c=contract('decomposition');body=request_body(c['route'],c['settings'],c['prompt'],scope_inputs(self.scope),c['schema'])
        with self.assertRaisesRegex(Deferred,'reserve_exhausted'):
            self.runner().request('cb-interpret',['fresh'],body,lambda v,cached:v)
        self.assertEqual(len(self.provider.calls),0)

    def test_incidental_receipt_dates_do_not_repurchase_interpretation(self):
        before=copy.deepcopy(self.scope);after=copy.deepcopy(self.scope)
        before['science']['retrieved_at']='2020-01-01'
        after['science']['retrieved_at']='2026-09-12'
        self.assertEqual(scope_inputs(before),scope_inputs(after))
        self.runner().scientific('decomposition',scope_inputs(before),before)
        self.runner().scientific('decomposition',scope_inputs(after),after)
        self.assertEqual(len(self.provider.calls),1)

    def test_historical_context_embedding_cannot_inherit_new_ceiling(self):
        ledger=ExperimentLedger(self.state/'ledger.json')
        metadata={'purpose':'d2-context','row_inputs':[]}
        ledger.reserve_experiment('voyage','voyage-4-lite',2,'old-context',100,1,
            trusted_route=True,input_tokens=10,execution_metadata=metadata)
        state=ledger.read()
        state['requests'].append({'key':'prior-judge','provider':'anthropic','stage':2,
            'charged_microusd':5_999_900,'reserved_microusd':1,'purpose':'history'})
        self.state.joinpath('ledger.json').write_text(json.dumps(state))
        with self.assertRaisesRegex(Deferred,'stage_or_total'):
            ledger.reserve_experiment('voyage','voyage-4-lite',2,'old-context-new',100,1,
                trusted_route=True,input_tokens=10,execution_metadata=metadata)


if __name__=='__main__':unittest.main()
