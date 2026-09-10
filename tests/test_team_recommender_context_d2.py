import copy
import json
import unittest
from tests import test_team_recommender_executor as base
from tests import test_team_recommender_judge_d1 as d1
from tools import team_recommender_executor as e
from tools.team_recommender_context_d2 import context_inventory, canonical, VERSION
from tools.offline_spend import Deferred, ConfigurationFailure, identity


class D2Contract(unittest.TestCase):
    setUp=base.ExecutorContract.setUp
    embedding=base.ExecutorContract.embedding
    judge=base.ExecutorContract.judge
    packet=base.ExecutorContract.packet
    response=base.ExecutorContract.response
    revised=d1.D1Contract.revised

    def contextual(self):
        inventory=context_inventory(self.settings);key,text=next(iter(inventory[self.person].items()))
        return {'representation':VERSION,'input_role':'document','rows':[{'owner':self.person,'id':key,'text':text}]}

    def test_inventory_is_exact_frozen_field_derivation_without_mutation(self):
        original=copy.deepcopy(self.settings);inventory=context_inventory(self.settings)
        self.assertEqual(self.settings,original)
        self.assertEqual(set(inventory),set(self.settings['profile_claims']))
        for person,rows in inventory.items():
            for key,text in rows.items():
                self.assertEqual(key,e.sha(text.encode('utf-8')))
                value=json.loads(text);fields=self.settings['d1_profile_fields'][person]
                if 'research_summary' in value:
                    self.assertEqual(value,{'research_summary':fields['research_summary']})
                else:
                    claims=[c for c in self.settings['profile_claims'][person] if c['text']==value['evidence']]
                    metadata=[c for c in fields['claims'] if c['id'] in {x['claim_id'] for x in claims}]
                    expected=sorted({canonical({'claim_type':c['claim_type'],'label':c['label']}) for c in metadata})
                    self.assertEqual(value['claims'],[json.loads(c) for c in expected])

    def test_derived_route_cannot_accept_changed_or_unowned_text(self):
        r=self.contextual();body,bound=e.embedding_contract(r,self.settings)
        self.assertEqual(body['input'],[r['rows'][0]['text']]);self.assertEqual(body['input_type'],'document')
        for field,value in [('text',r['rows'][0]['text']+' new capability'),('owner','urh-999999')]:
            bad=copy.deepcopy(r);bad['rows'][0][field]=value;bad['rows'][0]['id']=e.sha(bad['rows'][0]['text'].encode())
            with self.assertRaises(ValueError):e.embedding_contract(bad,self.settings)
        for key,value in [('input_role','query'),('representation','D2-context-v2'),('endpoint','https://example.org'),('prompt','new')]:
            bad=copy.deepcopy(r);bad[key]=value
            with self.assertRaises(ValueError):e.embedding_contract(bad,self.settings)
        bad=copy.deepcopy(r);bad.pop('representation')
        with self.assertRaises(ValueError):e.embedding_contract(bad,self.settings)

    def test_missing_summary_and_duplicate_metadata_do_not_invent_rows(self):
        settings=copy.deepcopy(self.settings);fields=settings['d1_profile_fields'][self.person]
        fields['research_summary']=''
        once=context_inventory(settings)[self.person]
        fields['claims'].append(copy.deepcopy(fields['claims'][0]))
        settings['profile_claims'][self.person].append(copy.deepcopy(settings['profile_claims'][self.person][0]))
        self.assertEqual(context_inventory(settings)[self.person],once)
        self.assertFalse(any('research_summary' in json.loads(text) for text in once.values()))

    def test_d2_purpose_preserves_exact_judge_body_and_cache_identity(self):
        r=self.revised();r['protocol']='D1F'
        prior=e.judge_contract(r,self.settings);oldkey=identity([e.AUTHORIZATION_ID,'development-judge',prior[0]])
        r['purpose']='d2-call';current=e.judge_contract(r,self.settings)
        self.assertEqual(prior,current)
        self.assertEqual(oldkey,identity([e.AUTHORIZATION_ID,'development-judge',current[0]]))
        r['protocol']='D1'
        with self.assertRaises(ValueError):e.judge_contract(r,self.settings)
        r=self.revised();r.update(protocol='D1F',purpose='d2-group')
        with self.assertRaises(ValueError):e.judge_contract(r,self.settings)

    def test_cross_purpose_reuse_and_lost_cache_never_repeat_paid_request(self):
        path,_,packet=self.packet('development-judge');r=self.revised();r['protocol']='D1F';packet['requests']=[r]
        calls=[]
        def post(*args,**kwargs):
            calls.append(1)
            value={'verdicts':[{'item_id':'i01','verdict':'plausible','evidence_ref':'p1','reason':'interest'}]}
            return self.response({'model':self.settings['judge_model'],'usage':{'input_tokens':100,'output_tokens':50},'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(value)}]})
        def execute():
            raw=json.dumps(packet).encode();path.write_bytes(raw);e.execute(self.state,path,e.sha(raw),post)
        execute();r['purpose']='d2-call'
        for _ in range(3):execute()
        for cache in (self.state/'cache').glob('*.json'):cache.unlink()
        for _ in range(3):
            with self.assertRaises(Deferred):execute()
        self.assertEqual(len(calls),1)

    def test_d2_caps_preserve_historical_spend_and_lifetime_limit(self):
        ledger=e.ExperimentLedger(self.state/'ledger.json');state=ledger.read()
        state['requests']=[{'key':'old','charged_microusd':2_138_302,'provider':'anthropic','stage':2,'purpose':'d1-call','reserved_microusd':4_198_676,'reserved_input_tokens':1_347_679,'reserved_output_tokens':82_944}]
        e.atomic_json(ledger.path,state)
        token=ledger.reserve_experiment('anthropic',self.settings['judge_model'],2,'d2-one',10000,1,trusted_route=True,input_tokens=1000,output_tokens=512,execution_metadata={'purpose':'d2-call'})
        self.assertEqual(ledger.read()['requests'][0],state['requests'][0]);self.assertEqual(len(ledger.read()['requests']),2)
        with self.assertRaises(Deferred):ledger.reserve_experiment('anthropic',self.settings['judge_model'],2,'d2-one',10000,1,trusted_route=True,input_tokens=1000,output_tokens=512,execution_metadata={'purpose':'d2-call'})
        changed=ledger.read();changed['requests'][1]['reserved_input_tokens']=1_100_000;e.atomic_json(ledger.path,changed)
        with self.assertRaisesRegex(Deferred,'finite_judge_phase'):ledger.reserve_experiment('anthropic',self.settings['judge_model'],2,'d2-next',10000,1,trusted_route=True,input_tokens=1000,output_tokens=512,execution_metadata={'purpose':'d2-call'})
        changed['requests'][1]['reserved_input_tokens']=1000;changed['requests'][0]['charged_microusd']=5_990_001;e.atomic_json(ledger.path,changed)
        with self.assertRaises(Deferred):ledger.reserve_experiment('anthropic',self.settings['judge_model'],2,'d2-stage-stop',10000,1,trusted_route=True,input_tokens=1000,output_tokens=512,execution_metadata={'purpose':'d2-call'})
        with self.assertRaises(ConfigurationFailure):ledger.reserve_experiment('anthropic',self.settings['judge_model'],3,'holdout',10000,1,approved_stage=3,trusted_route=True,input_tokens=1000,output_tokens=512,execution_metadata={'purpose':'d2-call'})

    def test_d2_context_reservations_stop_at_five_and_keep_whole_ledger(self):
        ledger=e.ExperimentLedger(self.state/'ledger.json')
        for i in range(5):ledger.reserve_experiment('voyage',self.settings['embedding_model'],2,str(i),100,1,trusted_route=True,input_tokens=100,execution_metadata={'purpose':'d2-context','row_inputs':['document:'+str(i)]})
        with self.assertRaisesRegex(Deferred,'d2_context'):ledger.reserve_experiment('voyage',self.settings['embedding_model'],2,'six',100,1,trusted_route=True,input_tokens=100,execution_metadata={'purpose':'d2-context','row_inputs':['document:six']})
        self.assertEqual(len(ledger.read()['requests']),5)

    def test_real_derived_contract_fixture_dispatch_and_exact_reuse(self):
        path,_,packet=self.packet();packet['requests']=[self.contextual()]
        raw=json.dumps(packet).encode();path.write_bytes(raw);calls=[]
        def post(*args,**kwargs):
            calls.append(kwargs['json']['input'])
            return self.response({'model':self.settings['embedding_model'],'usage':{'total_tokens':100},
                'data':[{'index':0,'embedding':[1.0]+[0.0]*1023}]})
        for _ in range(3):e.execute(self.state,path,e.sha(raw),post)
        self.assertEqual(calls,[[packet['requests'][0]['rows'][0]['text']]])
        rows=e.ExperimentLedger(self.state/'ledger.json').read()['requests']
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['purpose'],'d2-context')
        self.assertEqual(rows[0]['charged_microusd'],2)
