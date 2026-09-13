import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from tests import test_team_recommender_executor as fixture
from tools import team_recommender_executor as e
from tools import team_recommender_checkpoint as c
from tools.contextual_team_executor import Runner, RecoveryRequired
from tools.offline_spend import atomic_json, identity, Deferred


class CheckpointOrderContract(unittest.TestCase):
    def setUp(self):
        self.f=fixture.ExecutorContract();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def fixture(self):
        ledger=e.ExperimentLedger(self.f.state/'ledger.json')
        key=identity([e.AUTHORIZATION_ID,'contextual-v1',['fixture']])
        token=ledger.reserve_experiment('anthropic',self.f.settings['judge_model'],2,key,10000,1,
            trusted_route=True,input_tokens=1000,output_tokens=512)
        ledger.reconcile(token,cost_usd='0.001',usage={'input_tokens':100,'output_tokens':80},status='failed')
        row=ledger.read()['requests'][0]
        atomic_json(self.f.state/'receipts'/(token+'.json'),{'key':key,'status':'failed','charged_microusd':1000})
        e.checkpoint(self.f.state);raw=self.f.archive(self.f.state)
        plan={'authorization_id':e.AUTHORIZATION_ID,'required_after':'2026-09-09T01:00:00Z',
            'source_run':123,'source_attempt':'1','source_code_sha':'a'*40,'source_state_artifact':11,
            'source_checkpoint_sha256':e.sha((self.f.state/'checkpoint.json').read_bytes()),
            'source_ledger_sha256':e.sha((self.f.state/'ledger.json').read_bytes()),
            'request_id':token,'request_key':key,'request_sha256':identity(row),
            'receipt_sha256':e.sha((self.f.state/'receipts'/(token+'.json')).read_bytes()),'charged_microusd':1000}
        config=self.f.root/'config';config.mkdir();atomic_json(config/'checkpoint-recovery-v1.json',plan)
        destination=self.f.root/'restored';destination.mkdir();(destination/'ledger.json').write_bytes((e.CONFIG/'initial-ledger.json').read_bytes())
        artifacts=[{'id':11,'name':e.PREFIX+'-state-123-1','expired':False,'workflow_run':{'id':123}}]
        latest={'created_at':'2026-09-13T12:21:47Z'}
        def api(path):
            if path=='actions/runs/123':return json.dumps({'path':e.WORKFLOW,'head_branch':'main','event':'repository_dispatch','head_sha':'a'*40}).encode()
            if path=='actions/artifacts/11/zip':return raw
            self.fail('Unexpected recovery API '+path)
        return destination,config,plan,artifacts,latest,api,row

    def test_real_nonchronological_ids_choose_newest_time(self):
        old={'id':10317232847,'created_at':'2026-09-13T12:10:30Z'}
        new={'id':10317223218,'created_at':'2026-09-13T12:18:30Z'}
        self.assertIs(c.latest_reservation([new,old]),new)

    def test_missing_malformed_and_ambiguous_times_fail_closed(self):
        for value in [None,'','yesterday','2026-02-31T00:00:00Z','2026-09-13T00:00:00+01:00']:
            with self.subTest(value=value),self.assertRaises(Deferred):c.latest_reservation([{'id':1,'created_at':value}])
        with self.assertRaisesRegex(Deferred,'ambiguous'):
            c.latest_reservation([{'id':1,'created_at':'2026-09-13T00:00:00Z'},{'id':2,'created_at':'2026-09-13T00:00:00Z'}])

    def test_newest_missing_checkpoint_cannot_fall_back_to_larger_old_id(self):
        rows=[{'id':100,'name':e.PREFIX+'-reservation-1-1','created_at':'2026-09-09T01:00:00Z'},
              {'id':10,'name':e.PREFIX+'-reservation-2-1','created_at':'2026-09-09T02:00:00Z'},
              {'id':101,'name':e.PREFIX+'-state-1-1','expired':False,'workflow_run':{'id':1}}]
        with self.assertRaisesRegex(Deferred,'latest_authoritative'):
            e.restore(self.f.root/'restore',self.f.settings,lambda path:json.dumps({'artifacts':rows}).encode())

    def test_recovery_is_exact_idempotent_and_never_dispatches_old_paid_request(self):
        dest,config,plan,artifacts,latest,api,row=self.fixture()
        with patch.object(e,'CONFIG',config):
            for _ in range(3):
                c.recover_known_charge(dest,latest,artifacts,api,e)
                self.assertEqual(e.ExperimentLedger(dest/'ledger.json').read()['requests'],[row])
                self.assertEqual(e.sha((dest/'receipts'/(row['id']+'.json')).read_bytes()),plan['receipt_sha256'])
                runner=Runner(dest,{},post=lambda *a,**k:self.fail('duplicate provider dispatch'))
                with self.assertRaises(RecoveryRequired):runner.request('cb-interpret',['fixture'],{'model':'claude-sonnet-5','max_tokens':512},lambda *a:None)
        self.assertEqual(len(e.ExperimentLedger(dest/'ledger.json').read()['events']),1)

    def test_crash_at_each_recovery_write_preserves_one_charge_and_zero_replays(self):
        class Crash(BaseException):pass
        for boundary in ('receipt','ledger','checkpoint'):
            for after in (False,True):
                with self.subTest(boundary=boundary,after=after):
                    f=fixture.ExecutorContract();f.setUp()
                    saved=self.f;self.f=f
                    try:
                        dest,config,plan,artifacts,latest,api,row=self.fixture();original=c.atomic_json
                        def write(path,value):
                            kind='ledger' if path.name=='ledger.json' else 'receipt'
                            if kind==boundary and not after:raise Crash()
                            original(path,value)
                            if kind==boundary and after:raise Crash()
                        checkpoint=e.checkpoint
                        def seal(path):
                            if boundary=='checkpoint' and not after:raise Crash()
                            checkpoint(path)
                            if boundary=='checkpoint' and after:raise Crash()
                        with patch.object(e,'CONFIG',config),patch.object(c,'atomic_json',write),patch.object(e,'checkpoint',seal):
                            with self.assertRaises(Crash):c.recover_known_charge(dest,latest,artifacts,api,e)
                        with patch.object(e,'CONFIG',config):
                            for _ in range(3):
                                c.recover_known_charge(dest,latest,artifacts,api,e)
                                self.assertEqual(e.ExperimentLedger(dest/'ledger.json').read()['requests'],[row])
                                with self.assertRaises(RecoveryRequired):Runner(dest,{},post=lambda *a,**k:self.fail('replay')).request('cb-interpret',['fixture'],{'model':'claude-sonnet-5','max_tokens':512},lambda *a:None)
                    finally:f.doCleanups();self.f=saved

    def test_missing_expired_untrusted_and_hash_conflicting_recovery_are_blocked(self):
        dest,config,plan,artifacts,latest,api,row=self.fixture()
        with patch.object(e,'CONFIG',config):
            for rows in ([],[artifacts[0]|{'expired':True}]):
                with self.assertRaises(Deferred):c.recover_known_charge(dest,latest,rows,api,e)
            def wrong_run(path):
                if path=='actions/runs/123':return json.dumps({'path':e.WORKFLOW,'head_branch':'feature','event':'repository_dispatch','head_sha':'a'*40}).encode()
                return api(path)
            with self.assertRaisesRegex(ValueError,'untrusted'):c.recover_known_charge(dest,latest,artifacts,wrong_run,e)
            atomic_json(config/'checkpoint-recovery-v1.json',plan|{'source_ledger_sha256':'0'*64})
            with self.assertRaisesRegex(ValueError,'hash_conflict'):c.recover_known_charge(dest,latest,artifacts,api,e)
        self.assertEqual(e.ExperimentLedger(dest/'ledger.json').read()['requests'],[])

    def test_conflicting_request_or_receipt_never_overwritten(self):
        dest,config,plan,artifacts,latest,api,row=self.fixture()
        ledger=e.ExperimentLedger(dest/'ledger.json').read();ledger['requests']=[row|{'charged_microusd':999}];atomic_json(dest/'ledger.json',ledger)
        with patch.object(e,'CONFIG',config),self.assertRaisesRegex(Deferred,'request_conflict'):c.recover_known_charge(dest,latest,artifacts,api,e)
        ledger['requests']=[];atomic_json(dest/'ledger.json',ledger);atomic_json(dest/'receipts'/(row['id']+'.json'),{'wrong':True})
        with patch.object(e,'CONFIG',config),self.assertRaisesRegex(Deferred,'receipt_conflict'):c.recover_known_charge(dest,latest,artifacts,api,e)


if __name__=='__main__':unittest.main()
