import copy
import json
from unittest.mock import patch

import unittest
from tests import test_team_recommender_executor as base
from tools import team_recommender_executor as e
from tools.offline_spend import Deferred, identity


class D1Contract(unittest.TestCase):
    setUp = base.ExecutorContract.setUp
    embedding = base.ExecutorContract.embedding
    judge = base.ExecutorContract.judge
    packet = base.ExecutorContract.packet
    response = base.ExecutorContract.response
    def revised(self, kind="call_person"):
        r = self.judge()
        r.update(protocol="D1",purpose="d1-call",aspects=[{"id":"a0","text":"optical research","source_ref":"s1"}])
        item=r["items"][0];item["task_type"]=kind
        row=item["profile_evidence"][0]
        fields=self.settings["d1_profile_fields"][self.person]
        claim=next(c for c in fields["claims"] if c["id"]==row["claim_id"])
        row.update(label=claim["label"],claim_type=claim["claim_type"],research_summary=fields["research_summary"])
        return r

    def test_d1_distinct_questions_and_three_complete_responses_fit(self):
        r=self.revised();r["items"]=[dict(copy.deepcopy(r["items"][0]),item_id=f"i{i:02}") for i in range(1,4)]
        body,bound,aliases,refs,schema=e.judge_contract(r,self.settings)
        self.assertLessEqual(bound,12000);self.assertEqual(body["max_tokens"],512)
        value={"verdicts":[{"item_id":a,"verdict":"plausible","evidence_ref":"p1","reason":"x"*60} for a in aliases]}
        # Three complete concise ASCII responses fit the output allowance;
        # normal BPE needs substantially fewer tokens. Validate the full shape.
        self.assertLess(len(json.dumps(value,separators=(',',':'))),512)
        payload={"model":self.settings["judge_model"],"stop_reason":"end_turn","content":[{"type":"text","text":json.dumps(value)}]}
        self.assertEqual(e.result_value("development-judge",payload,r,(body,bound,aliases,refs,schema),self.settings),value)
        r["items"].append(dict(copy.deepcopy(r["items"][0]),item_id="i04"))
        with self.assertRaises(ValueError):e.judge_contract(r,self.settings)

    def test_d1_frozen_fields_aspect_span_and_blinding(self):
        for field in ["label","claim_type","research_summary","text","revision"]:
            r=self.revised();r["items"][0]["profile_evidence"][0][field]="invented"
            with self.assertRaises(ValueError):e.judge_contract(r,self.settings)
        for field in ["score","algorithm","prior_verdict","explanation"]:
            r=self.revised();r["items"][0][field]="unblinded"
            with self.assertRaises(ValueError):e.judge_contract(r,self.settings)
        r=self.revised();r["aspects"][0]["text"]="unsupported scientific aspect"
        with self.assertRaises(ValueError):e.judge_contract(r,self.settings)
        r=self.revised("aspect_person");r["purpose"]="d1-aspect"
        with self.assertRaises(ValueError):e.judge_contract(r,self.settings)
        r["items"][0]["target_aspect"]="a0";e.judge_contract(r,self.settings)

    def test_d1_source_suitability_has_no_directory_inference(self):
        r=self.revised("source_suitability");r.update(purpose="d1-source",aspects=[])
        r["items"][0].update(profile_evidence=[],candidates=[])
        contract=e.judge_contract(r,self.settings)
        self.assertEqual(set(contract[-1]["properties"]["verdicts"]["items"]["properties"]["verdict"]["enum"]),
                         {"coherent","broad-unselected","nonresearch","insufficient-information"})
        r["purpose"]="d1-call"
        with self.assertRaises(ValueError):e.judge_contract(r,self.settings)

    def test_d1_missing_duplicate_wrong_task_and_reference_fail(self):
        r=self.revised();contract=e.judge_contract(r,self.settings)
        for verdicts in [[],[{"item_id":"i01","verdict":"coherent","evidence_ref":"s1","reason":"x"}],
                         [{"item_id":"i01","verdict":"plausible","evidence_ref":"invented","reason":"x"}]]:
            payload={"model":self.settings["judge_model"],"stop_reason":"end_turn","content":[{"type":"text","text":json.dumps({"verdicts":verdicts})}]}
            with self.assertRaises(ValueError):e.result_value("development-judge",payload,r,contract,self.settings)

    def test_d1_exact_cache_and_cacheless_restoration_do_not_redispatch(self):
        path,_,packet=self.packet("development-judge");r=self.revised();packet["requests"]=[r]
        raw=json.dumps(packet).encode();path.write_bytes(raw);digest=e.sha(raw);calls=[]
        value={"verdicts":[{"item_id":"i01","verdict":"plausible","evidence_ref":"p1","reason":"Retained interest supports a discussion."}]}
        def post(*a,**k):
            calls.append(1)
            return self.response({"model":self.settings["judge_model"],"usage":{"input_tokens":100,"output_tokens":50},"stop_reason":"end_turn","content":[{"type":"text","text":json.dumps(value)}]})
        e.execute(self.state,path,digest,post)
        for _ in range(3):e.execute(self.state,path,digest,post)
        for cache in (self.state/'cache').glob('*.json'):cache.unlink()
        for _ in range(3):
            with self.assertRaises(Deferred):e.execute(self.state,path,digest,post)
        self.assertEqual(len(calls),1)

    def test_d1_same_ledger_preserves_old_spend_and_later_stage_reserve(self):
        ledger=e.ExperimentLedger(self.state/'ledger.json')
        state=ledger.read()
        state['requests']=[{'key':'historical','charged_microusd':5_990_000,'provider':'anthropic','stage':2,'purpose':'individual','reserved_microusd':5_990_000,'reserved_input_tokens':1}]
        e.atomic_json(ledger.path,state)
        r=self.revised();body,bound,*_=e.judge_contract(r,self.settings)
        with self.assertRaises(Deferred):
            ledger.reserve_experiment('anthropic',self.settings['judge_model'],2,identity(body),(bound*5+1)//2+5120,1,
                trusted_route=True,input_tokens=bound,output_tokens=512,execution_metadata={'purpose':'d1-call'})
        self.assertEqual(ledger.read()['requests'],state['requests'])

    def test_d1f_enum_reasons_survive_provider_projection_and_fit(self):
        from tools.team_recommender_judge_d1 import REASONS
        r=self.revised();r['protocol']='D1F'
        r['items']=[dict(copy.deepcopy(r['items'][0]),item_id=f'i{i:02}') for i in range(1,4)]
        body,bound,aliases,refs,schema=e.judge_contract(r,self.settings)
        wire=body['output_config']['format']['schema']['properties']['verdicts']['items']['properties']['reason']
        self.assertEqual(wire['enum'],REASONS)
        value={'verdicts':[{'item_id':a,'verdict':'insufficient-information','evidence_ref':'s1','reason':'unsupported'} for a in aliases]}
        self.assertLess(len(json.dumps(value,separators=(',',':'))),512)
        payload={'model':self.settings['judge_model'],'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(value)}]}
        self.assertEqual(e.result_value('development-judge',payload,r,(body,bound,aliases,refs,schema),self.settings),value)
        value['verdicts'][0]['reason']='a sentence outside the declared codes'
        payload['content'][0]['text']=json.dumps(value)
        with self.assertRaises(ValueError):e.result_value('development-judge',payload,r,(body,bound,aliases,refs,schema),self.settings)

    def test_d1f_cannot_replay_paid_d1_after_format_change(self):
        path,_,packet=self.packet('development-judge');r=self.revised();packet['requests']=[r]
        raw=json.dumps(packet).encode();path.write_bytes(raw);calls=[]
        value={'verdicts':[{'item_id':'i01','verdict':'plausible','evidence_ref':'p1','reason':'x'*61}]}
        def post(*a,**k):
            calls.append(1)
            return self.response({'model':self.settings['judge_model'],'usage':{'input_tokens':100,'output_tokens':50},'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(value)}]})
        with self.assertRaises(ValueError):e.execute(self.state,path,e.sha(raw),post)
        r['protocol']='D1F';raw=json.dumps(packet).encode();path.write_bytes(raw)
        for _ in range(3):
            with self.assertRaises(Deferred):e.execute(self.state,path,e.sha(raw),post)
        self.assertEqual(len(calls),1)
        ledger=e.ExperimentLedger(self.state/'ledger.json').read()
        self.assertEqual(len(ledger['requests']),1);self.assertEqual(ledger['requests'][0]['charged_microusd'],700)

    def test_d1f_success_reuses_exact_cache_and_blocks_reverse_format_replay(self):
        path,_,packet=self.packet('development-judge');r=self.revised();r['protocol']='D1F';packet['requests']=[r]
        raw=json.dumps(packet).encode();path.write_bytes(raw);calls=[]
        value={'verdicts':[{'item_id':'i01','verdict':'plausible','evidence_ref':'p1','reason':'interest'}]}
        def post(*a,**k):
            calls.append(1)
            return self.response({'model':self.settings['judge_model'],'usage':{'input_tokens':100,'output_tokens':50},'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(value)}]})
        for _ in range(3):e.execute(self.state,path,e.sha(raw),post)
        r['protocol']='D1';raw=json.dumps(packet).encode();path.write_bytes(raw)
        for _ in range(3):
            with self.assertRaises(Deferred):e.execute(self.state,path,e.sha(raw),post)
        self.assertEqual(len(calls),1)
