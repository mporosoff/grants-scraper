import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_team_recommender_executor as fixtures
from tools import team_recommender_executor as e, team_recommender_budget as b
from tools import team_recommender_post_audit_executor as p
from tools.offline_spend import atomic_json, identity, Deferred


class PostAuditContract(unittest.TestCase):
    setUp = fixtures.ExecutorContract.setUp
    response = fixtures.ExecutorContract.response
    archive = fixtures.ExecutorContract.archive
    restore_api = fixtures.ExecutorContract.restore_api

    def packet(self):
        h = next(iter(p.inputs()['requests']))
        request = {'protocol':p.PROTOCOL, 'purpose':p.PURPOSE, 'body_sha256':h}
        packet = {'schema_version':1, 'authorization_id':e.AUTHORIZATION_ID,
                  'registry_generation':p.REGISTRY, 'operation':'development-judge', 'requests':[request]}
        raw = json.dumps(packet).encode(); path = self.root/'post.json'; path.write_bytes(raw)
        return path, e.sha(raw), packet

    def payload(self, request):
        contract = p.contract(request, self.settings)
        return {'model':'claude-sonnet-5','stop_reason':'end_turn','usage':{'input_tokens':100,'output_tokens':40},
            'content':[{'type':'text','text':json.dumps({'verdicts':[
                {'item_id':alias,'verdict':'coherent' if kind=='source_suitability' else 'plausible',
                 'evidence_ref':'s0','reason':'specific'} for alias,kind in contract[2].items()]})}]}

    def test_whole_exact_inventory_and_complete_bounded_projection(self):
        requests = p.inputs()['requests']; keys=[]; amount=0; largest=0
        self.assertEqual(len(requests),34)
        for h, row in requests.items():
            r={'protocol':p.PROTOCOL,'purpose':p.PURPOSE,'body_sha256':h}
            contract=e.judge_contract(r,self.settings); body,bound=contract[:2]
            self.assertEqual(body,row['body']);self.assertLessEqual(bound,24000)
            self.assertEqual(body['model'],'claude-sonnet-5');self.assertEqual(body['max_tokens'],512)
            keys+=p.judge_items(r);amount+=(bound*5+1)//2+5120;largest=max(largest,bound)
        self.assertEqual(len(keys),69);self.assertEqual(len(set(keys)),69)
        self.assertEqual(amount,1293612);self.assertEqual(largest,22878)

    def test_no_editable_data_routes_mixed_registry_or_rebatch(self):
        _,_,packet=self.packet();e.validate_packet(packet,self.settings)
        for key in ['endpoint','model','prompt','source_evidence','items','code']:
            bad=copy.deepcopy(packet);bad['requests'][0][key]='untrusted'
            with self.assertRaises(ValueError):e.validate_packet(bad,self.settings)
        for key,value in [('body_sha256','a'*64),('purpose','s3-primary'),('protocol','unknown')]:
            bad=copy.deepcopy(packet);bad['requests'][0][key]=value
            with self.assertRaises((ValueError,KeyError)):e.validate_packet(bad,self.settings)
        bad=copy.deepcopy(packet);bad['registry_generation']=self.settings['registry_generation']
        with self.assertRaises(ValueError):e.validate_packet(bad,self.settings)
        bad=copy.deepcopy(packet);bad['operation']='embeddings'
        with self.assertRaises(ValueError):e.validate_packet(bad,self.settings)
        with patch.object(p,'INPUTS_SHA256','0'*64),self.assertRaises(ValueError):p.inputs()

    def test_exact_cache_and_lost_result_never_pay_again(self):
        path,h,packet=self.packet();calls=[]
        def post(*args,**kwargs):calls.append(1);return self.response(self.payload(packet['requests'][0]))
        e.execute(self.state,path,h,post)
        for _ in range(3):e.execute(self.state,path,h,post)
        self.assertEqual(len(calls),1)
        row=b.ExperimentLedger(self.state/'ledger.json').read()['requests'][0]
        self.assertEqual(row['purpose'],p.PURPOSE);self.assertEqual(row['charged_microusd'],600)
        for cache in (self.state/'cache').glob('*.json'):cache.unlink()
        for _ in range(3):
            with self.assertRaises(Deferred):e.execute(self.state,path,h,post)
        self.assertEqual(len(calls),1)

    def test_generic_packets_cannot_claim_versioned_or_future_paid_purposes(self):
        original = (self.state/'ledger.json').read_bytes()
        with patch.dict(e.PURPOSES, {'future-approved-envelope': 1}):
            for purpose in sorted(set(e.PURPOSES) - e.GENERIC_JUDGE_PURPOSES):
                with self.subTest(purpose=purpose):
                    request = fixtures.ExecutorContract.judge(self)
                    request['purpose'] = purpose
                    packet = {'schema_version':1, 'authorization_id':e.AUTHORIZATION_ID,
                        'registry_generation':self.settings['registry_generation'],
                        'operation':'development-judge', 'requests':[request]}
                    raw = json.dumps(packet).encode()
                    path = self.root/'generic-purpose.json'; path.write_bytes(raw)
                    with self.assertRaisesRegex(ValueError, 'judge_outside_development_authority'):
                        e.execute(self.state,path,e.sha(raw),lambda *a,**k:self.fail('rejected purpose dispatched'))
                    self.assertEqual((self.state/'ledger.json').read_bytes(),original)
        # Legacy questions keep their original contract and exact cache identity.
        request = fixtures.ExecutorContract.judge(self)
        self.assertEqual(e.judge_contract(request,self.settings)[0]['model'],'claude-sonnet-5')

    def test_atomic_post_budget_preserves_global_history_and_bounds(self):
        ledger=b.ExperimentLedger(self.state/'ledger.json');original=ledger.read()
        def reserve():return ledger.reserve_experiment('anthropic','claude-sonnet-5',2,'new',65120,1,
            trusted_route=True,input_tokens=24000,output_tokens=512,
            execution_metadata={'purpose':p.PURPOSE,'judge_items':[]})
        for count,charge,purpose in [(1,1990000,p.PURPOSE),(60,1,p.PURPOSE),(1,5950000,'historical'),(690,1,'historical')]:
            state=copy.deepcopy(original);state['requests']=[{'id':str(i),'key':'old'+str(i),'stage':2,
                'provider':'anthropic','purpose':purpose,'status':'reserved_unknown','charged_microusd':charge,
                'reserved_microusd':charge,'reserved_input_tokens':1,'reserved_output_tokens':1,'judge_items':[]}
                for i in range(count)]
            atomic_json(ledger.path,state)
            with self.assertRaises(Deferred):reserve()
            self.assertEqual(len(ledger.read()['requests']),count)
        atomic_json(ledger.path,original);reserve()
        with self.assertRaises(Deferred):reserve()

    def test_crashes_and_repeated_cloud_restoration_dispatch_at_most_once(self):
        class Crash(BaseException):pass
        for boundary in ('reserved','reconciled','cache','terminal','receipt','checkpoint'):
            for after in (False,True):
                with self.subTest(boundary=boundary,after=after),tempfile.TemporaryDirectory() as tmp:
                    state=Path(tmp);(state/'ledger.json').write_bytes((e.CONFIG/'initial-ledger.json').read_bytes())
                    path,h,packet=self.packet();calls=[];injected=[]
                    def post(*args,**kwargs):
                        calls.append(1);value=self.payload(packet['requests'][0])
                        if boundary=='terminal':value['content'][0]['text']='{}'
                        return self.response(value)
                    def writer(target,value):
                        target=Path(target);kind='other'
                        if target.name=='ledger.json' and value['requests']:
                            row=value['requests'][-1]
                            kind='terminal' if row.get('terminal') else 'reserved' if row['status']=='reserved_unknown' else 'reconciled'
                        elif target.parent.name=='cache':kind='cache'
                        elif target.parent.name=='receipts':kind='receipt'
                        elif target.name=='checkpoint.json':kind='checkpoint'
                        hit=kind==boundary and not injected
                        if hit:
                            injected.append(1)
                            if not after:raise Crash()
                        atomic_json(target,value)
                        if hit:raise Crash()
                    with patch.object(e,'atomic_json',writer),patch.object(b,'atomic_json',writer):
                        with self.assertRaises(Crash):e.execute(state,path,h,post)
                    self.assertEqual(len(injected),1);before=len(calls);raw=self.archive(state)
                    for i in range(3):
                        restored=state/('restore'+str(i));restored.mkdir()
                        try:e.restore(restored,self.settings,self.restore_api(raw))
                        except (ValueError,FileNotFoundError):continue
                        try:e.execute(restored,path,h,post)
                        except (Deferred,ValueError):pass
                        raw=self.archive(restored)
                    self.assertLessEqual(len(calls),1)
                    if before:self.assertEqual(before,len(calls))

if __name__=='__main__':unittest.main()
