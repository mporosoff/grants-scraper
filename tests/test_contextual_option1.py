import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from tools.contextual_team_option1 import Option1Runner,plan,configuration_for_job,ensure_remaining_plan_fits
from tools.contextual_team_executor import scope_inputs, RecoveryRequired
from tools.contextual_team_contract import verification_inputs
from tools.offline_spend import Deferred,atomic_json,identity
from tools.team_recommender_budget import ExperimentLedger
from tests.test_contextual_team_executor import FixtureProvider,Crash


class ReferenceProvider(FixtureProvider):
    def __call__(self,*args,**kwargs):
        response=super().__call__(*args,**kwargs)
        value=json.loads(response.value['content'][0]['text'])
        for edge in value.get('edges',[]):edge.pop('evidence_quote')
        response.value['content'][0]['text']=json.dumps(value)
        return response


class Option1Lifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)/'state';self.state.mkdir()
        self.p=plan();self.config=configuration_for_job({'release_id':self.p['release_id'],'scope_id':'332894','person_id':''})
        ledger=ExperimentLedger(self.state/'ledger.json',initialize=True);state=ledger.read()
        rows=[{'id':'fixture-'+str(i),'key':identity(['fixture',i]),'purpose':'fixture-history','status':'valid','charged_microusd':0,'provider':'anthropic','stage':2} for i in range(653)]
        rows[0]['charged_microusd']=self.p['starting_spend_microusd']
        for row,op in zip(rows[-2:],[o for o in self.p['operations'] if o['repair_of']]):
            row.update(id=op['repair_of'],status='failed',usage={'input_tokens':10,'output_tokens':20},body_sha256='f'*64)
        state['requests']=rows;atomic_json(ledger.path,state)
        self.scope=next(s for s in self.config['scopes'] if s['id']=='332894')
        people=self.config['people'][:2]
        interpretation={'state':'coherent','objective':'Fixture only, not a real interpretation.',
          'roles':[{'id':'role-1','label':'Fixture contribution','required':True,'central':True,
                    'quote':self.scope['science']['title'],'source_field':'title'}],'limitations':[]}
        self.data=scope_inputs(self.scope)|{'interpretation':interpretation,'people':people}
        self.data=verification_inputs(self.data,{'edges':[{'role_id':'role-1','person_id':p['person_id'],
          'claim_id':p['claims'][0]['claim_id'],'claim_revision':p['claims'][0]['revision'],
          'coverage':'direct','central':True} for p in people]})
        self.env=patch.dict(os.environ,{'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'fixture','GITHUB_RUN_ATTEMPT':'1','ANTHROPIC_API_KEY':'fixture-only'})
        self.env.start();self.addCleanup(self.env.stop);self.provider=ReferenceProvider()

    def runner(self,state=None,crash=lambda name:None):return Option1Runner(state or self.state,self.config,post=self.provider,crash=crash)

    def test_successful_reference_resolution_and_repeated_exact_cache_reuse(self):
        result=self.runner().scientific('verification',self.data,self.scope)
        for _ in range(3):self.assertEqual(self.runner().scientific('verification',self.data,self.scope),result)
        self.assertEqual(len(self.provider.calls),1)
        body=self.provider.calls[0][1];self.assertEqual(body['max_tokens'],24000)
        self.assertEqual(body['output_config']['format']['type'],'json_schema')
        row=self.runner().ledger.read()['requests'][-1]
        self.assertEqual(row['repair_of'],'a97083b5dbd14afebd5e17166d068a3e')
        self.assertEqual(row['charged_microusd'],220)

    def test_every_crash_boundary_and_invalid_response_remains_nonreplayable(self):
        pristine=Path(self.tmp.name)/'pristine';shutil.copytree(self.state,pristine)
        for boundary in ['after_reserve','after_reservation_checkpoint','after_dispatch','before_reconcile','after_reconcile','after_cache','after_receipt','after_failed_reconcile']:
            with self.subTest(boundary=boundary):
                state=Path(self.tmp.name)/boundary;shutil.copytree(pristine,state)
                saved=Path(self.tmp.name)/(boundary+'-saved')
                def crash(name):
                    if name==boundary:shutil.copytree(state,saved);raise Crash()
                self.provider.invalid=boundary=='after_failed_reconcile'
                with self.assertRaises(Crash):self.runner(state,crash).scientific('verification',self.data,self.scope)
                before=len(self.provider.calls)
                for i in range(3):
                    restored=Path(self.tmp.name)/(boundary+'-restored-'+str(i));shutil.copytree(saved,restored)
                    try:self.runner(restored).scientific('verification',self.data,self.scope)
                    except Deferred:pass
                    self.assertEqual(len(self.provider.calls),before)

    def test_body_changes_cannot_repeat_the_same_operation_and_legacy_misses_never_purchase(self):
        self.runner().scientific('verification',self.data,self.scope)
        changed=copy.deepcopy(self.data);changed['scope']['limitations'].append('Changed fixture.')
        with self.assertRaisesRegex(Deferred,'already_claimed_no_rekey'):self.runner().scientific('verification',changed,self.scope)
        with self.assertRaises(RecoveryRequired):self.runner().scientific('decomposition',scope_inputs(self.scope),self.scope)
        with self.assertRaises(RecoveryRequired):self.runner().vectors(self.config['documents'][:1],'document')
        self.assertEqual(len(self.provider.calls),1)

    def test_later_usage_and_lost_or_uncertain_originals_do_not_reset_authority(self):
        runner=self.runner();state=runner.ledger.read();ensure_remaining_plan_fits(state,self.p)
        state['requests'][0]['charged_microusd']+=100000
        with self.assertRaises(Deferred):ensure_remaining_plan_fits(state,self.p)
        pristine=runner.ledger.read()
        for change in ('unknown','missing','reserve'):
            rows=copy.deepcopy(pristine);old=next(r for r in rows['requests'] if r['id']=='a97083b5dbd14afebd5e17166d068a3e')
            if change=='unknown':old['status']='reserved_unknown'
            elif change=='missing':old['id']='missing-original'
            else:rows['requests'][0]['charged_microusd']=6900000
            atomic_json(runner.ledger.path,rows)
            with self.assertRaises(Deferred):self.runner().scientific('verification',self.data,self.scope)
        self.assertEqual(len(self.provider.calls),0)


if __name__=='__main__':unittest.main()
