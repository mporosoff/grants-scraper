import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_team_recommender_executor as fixtures
from tools import team_recommender_executor as e, team_recommender_budget as b
from tools import team_recommender_stage3_executor as s
from tools.team_recommender_embeddings_d3 import paid_items
from tools.team_recommender_items import preflight
from tools.offline_spend import atomic_json, identity, Deferred


class Stage3Contract(unittest.TestCase):
    setUp=fixtures.ExecutorContract.setUp
    response=fixtures.ExecutorContract.response
    archive=fixtures.ExecutorContract.archive
    restore_api=fixtures.ExecutorContract.restore_api

    def embedding(self):
        row=next(iter(s.inputs(self.settings)['query_rows'].values()))
        return {'representation':s.REPRESENTATION,'model':'voyage-4-large','input_role':'query','rows':[row]}

    def judge(self):
        frozen=s.inputs(self.settings)
        sid=min((k for k in frozen['heldout_ids'] if frozen['contexts'][k]['aspects']),
                key=lambda k:len(json.dumps(frozen['contexts'][k])))
        person=min(frozen['profile_documents'],key=lambda k:len(json.dumps(frozen['profile_documents'][k])))
        ctx=frozen['contexts'][sid]
        return {'protocol':s.PROTOCOL,'scope_id':sid,'purpose':'s3-primary',
            'source_evidence':ctx['source_evidence'],'aspects':ctx['aspects'],
            'items':[{'item_id':'i01','task_type':'call_person','candidates':[person],
                      'profile_documents':[frozen['profile_documents'][person]]}]}

    def packet(self,operation='embeddings'):
        value={'schema_version':1,'authorization_id':e.AUTHORIZATION_ID,
            'registry_generation':self.settings['registry_generation'],'operation':operation,
            'requests':[self.embedding() if operation=='embeddings' else self.judge()]}
        path=self.root/'s3-packet.json';raw=json.dumps(value).encode();path.write_bytes(raw)
        return path,e.sha(raw),value

    def test_only_exact_E2_query_inputs_and_paid_space_reuse(self):
        r=self.embedding();body,bound=e.embedding_contract(r,self.settings)
        self.assertEqual(body['model'],'voyage-4-large');self.assertFalse(body['truncation']);self.assertLessEqual(bound,20000)
        prior=dict(r,representation='D3-combined-v1')
        self.assertEqual(paid_items(r),paid_items(prior))
        for defect in ('owner','text','model','role','endpoint'):
            bad=copy.deepcopy(r)
            if defect in ('owner','text'):bad['rows'][0][defect]='changed'
            elif defect=='model':bad['model']='voyage-context-4'
            elif defect=='role':bad['input_role']='document'
            else:bad['endpoint']='https://untrusted.invalid'
            with self.assertRaises(ValueError):e.embedding_contract(bad,self.settings)

    def test_complete_profiles_source_ownership_and_blinding(self):
        r=self.judge();body,bound,*_=e.judge_contract(r,self.settings)
        self.assertLessEqual(bound,12000);self.assertEqual(body['max_tokens'],512)
        self.assertEqual(body['thinking'],{'type':'disabled'})
        data=json.loads(body['messages'][0]['content'])
        self.assertEqual(data['profile_documents'][0]['research_summary'],r['items'][0]['profile_documents'][0]['research_summary'])
        for defect in ('summary','claim','missing','source','sibling','algorithm','explanation'):
            bad=copy.deepcopy(r);item=bad['items'][0]
            if defect=='summary':item['profile_documents'][0]['research_summary']+=' changed'
            if defect=='claim':item['profile_documents'][0]['statements'][0]['claims'][0]['revision']+=1
            if defect=='missing':item['profile_documents'][0]['statements']=[]
            if defect=='source':bad['source_evidence']['passages'][0]['text']='changed'
            if defect=='sibling':bad['scope_id']=next(k for k in s.inputs(self.settings)['heldout_ids'] if k!=r['scope_id'])
            if defect=='algorithm':item['algorithm']='expected winner'
            if defect=='explanation':item['explanation']='persuasive text'
            with self.assertRaises(ValueError,msg=defect):e.judge_contract(bad,self.settings)

    def test_comparison_union_same_documents_balanced_remapping(self):
        r=self.judge();docs=s.inputs(self.settings)['profile_documents']
        people=sorted(docs,key=lambda k:len(json.dumps(docs[k])))[:3]
        r['items']=[{'item_id':'i01','task_type':'comparison','candidates':{'A':people[:2],'B':people[1:]},
                     'profile_documents':[docs[p] for p in sorted(people)]}]
        body=e.judge_contract(r,self.settings)[0];data=json.loads(body['messages'][0]['content'])
        self.assertEqual(len(data['profile_documents']),3)
        swapped=copy.deepcopy(r);swapped['items'][0]['candidates']={'A':people[1:],'B':people[:2]}
        self.assertEqual(json.loads(e.judge_contract(swapped,self.settings)[0]['messages'][0]['content'])['profile_documents'],data['profile_documents'])
        from tools.team_recommender_evidence_projection import remap_winner
        self.assertEqual(remap_winner('A',True),'B');self.assertEqual(remap_winner('tie',True),'tie')
        self.assertNotEqual(s.judge_items(r),s.judge_items(swapped))

    def test_indivisible_complete_packet_is_deferred_without_dispatch(self):
        r=self.judge();docs=s.inputs(self.settings)['profile_documents']
        people=sorted(docs,key=lambda k:len(json.dumps(docs[k])),reverse=True)[:4]
        r['items']=[{'item_id':'i01','task_type':'group_usefulness','candidates':people,
                     'profile_documents':[docs[p] for p in sorted(people)]}]
        path,h,packet=self.packet('development-judge');packet['requests']=[r]
        raw=json.dumps(packet).encode();path.write_bytes(raw)
        with self.assertRaisesRegex(Deferred,'complete_evidence'):
            e.execute(self.state,path,e.sha(raw),lambda *a,**k:self.fail('oversized paid dispatch'))
        self.assertEqual(b.ExperimentLedger(self.state/'ledger.json').read()['requests'],[])

    def test_exact_judge_results_reuse_and_cannot_rebatch(self):
        path,h,packet=self.packet('development-judge');calls=[]
        def post(*args,**kwargs):
            calls.append(1)
            return self.response({'model':'claude-sonnet-5','stop_reason':'end_turn',
                'usage':{'input_tokens':100,'output_tokens':40},'content':[{'type':'text','text':json.dumps({
                'verdicts':[{'item_id':'i01','verdict':'plausible','evidence_ref':'s0','reason':'specific'}]})}]})
        e.execute(self.state,path,h,post)
        for _ in range(3):e.execute(self.state,path,h,lambda *a,**k:self.fail('duplicate fixture dispatch'))
        ledger=b.ExperimentLedger(self.state/'ledger.json');self.assertEqual(len(calls),1)
        self.assertEqual(ledger.read()['requests'][0]['stage'],3)
        bad=copy.deepcopy(packet);bad['requests'][0]['items'][0]['candidates'].reverse()
        # A different packet alias/purpose cannot obtain new authority for the same item.
        bad['requests'][0]['purpose']='s3-control'
        self.assertEqual(s.judge_items(bad['requests'][0]),s.judge_items(packet['requests'][0]))
        preflight(bad,self.settings,ledger)  # Identical body is an exact cache reuse.

    def test_new_stage_restore_crash_never_duplicates_fixture_dispatch(self):
        class Crash(BaseException):pass
        for boundary in ('reserved','reconciled','cache','terminal','receipt','checkpoint'):
            for after in (False,True):
                with self.subTest(boundary=boundary,after=after),tempfile.TemporaryDirectory() as tmp:
                    state=Path(tmp);(state/'ledger.json').write_bytes((e.CONFIG/'initial-ledger.json').read_bytes())
                    path,h,_=self.packet();calls=[];injected=[]
                    def post(*args,**kwargs):
                        calls.append(1)
                        return self.response({'model':'voyage-4-large','usage':{'total_tokens':10},
                            'data':[{'index':0,'embedding':([0] if boundary=='terminal' else [1.]+[0.]*1023)}]})
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
                    self.assertEqual(len(injected),1)
                    before=len(calls);raw=self.archive(state)
                    for i in range(3):
                        restored=state/('restore'+str(i));restored.mkdir()
                        try:e.restore(restored,self.settings,self.restore_api(raw))
                        except (ValueError,FileNotFoundError):continue
                        try:e.execute(restored,path,h,post)
                        except (Deferred,ValueError):pass
                        # Archive only this restored checkpoint, not its parent.
                        raw=self.archive(restored)
                    self.assertLessEqual(len(calls),1)
                    if before:self.assertEqual(before,len(calls))

    def test_stage3_phase_and_lifetime_reserves_are_one_atomic_ledger(self):
        ledger=b.ExperimentLedger(self.state/'ledger.json')
        def reserve(key,amount=7620):
            return ledger.reserve_experiment('anthropic','claude-sonnet-5',3,key,amount,1,
                trusted_route=True,approved_stage=3,input_tokens=1000,output_tokens=512,
                execution_metadata={'purpose':'s3-primary','judge_items':[],'row_inputs':[]})
        original=ledger.read()
        for count,charge,stage,expected in [(184,1,3,'stage3'),(665,1,2,'stage3'),(1,4_000_000,3,'stage3'),(1,7_135_333,2,'stage3')]:
            state=copy.deepcopy(original)
            state['requests']=[{'id':str(i),'key':'historical'+str(i),'stage':stage,'provider':'anthropic','model':'claude-sonnet-5',
                'purpose':'s3-primary' if stage==3 else 'individual','status':'valid','charged_microusd':charge,
                'reserved_microusd':charge,'reserved_input_tokens':1,'reserved_output_tokens':1,'judge_items':[]}
                for i in range(count)]
            atomic_json(ledger.path,state)
            with self.assertRaisesRegex(Deferred,expected):reserve('new')
            self.assertEqual(len(ledger.read()['requests']),count)
        atomic_json(ledger.path,original)
        token=reserve('exact');ledger.reconcile(token,cost_usd='.0006',usage={'input_tokens':100,'output_tokens':40},status='valid')
        self.assertEqual(b.ExperimentLedger(ledger.path).read()['requests'][0]['charged_microusd'],600)

if __name__=='__main__':unittest.main()
