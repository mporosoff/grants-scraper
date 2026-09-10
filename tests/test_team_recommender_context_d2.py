import copy
import json
import unittest
from unittest.mock import patch
from tools.team_recommender_items import judge_items, claimed_judge_items, historical_index
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

    def test_judgment_identity_ignores_batch_and_evidence_aliases(self):
        r=self.revised();r['protocol']='D1F';keys=judge_items(r)
        altered=copy.deepcopy(r);altered['purpose']='d2-call';item=altered['items'][0]
        item['item_id']='i03';item['profile_evidence'][0]['id']='p9'
        altered['source_evidence']['passages'][0]['id']='s9'
        altered['aspects'][0]['source_ref']='s9';altered['aspects'][0]['id']='renamed'
        self.assertEqual(judge_items(altered),keys)
        item['profile_evidence'][0]['text']+=' materially changed evidence'
        self.assertNotEqual(judge_items(altered),keys)

    def test_rebatch_after_each_dispatch_persistence_boundary_never_repays(self):
        for operation in ('development-judge','embeddings'):
            for boundary in ('success','invalid','transport','ledger','cache','receipt','checkpoint'):
                with self.subTest(operation=operation,boundary=boundary):
                    # Separate fixture state, preserving every attempt within this case.
                    self.state=self.root/(operation+'-'+boundary);self.state.mkdir()
                    (self.state/'ledger.json').write_bytes((e.CONFIG/'initial-ledger.json').read_bytes())
                    path,_,packet=self.packet(operation);r=self.revised() if operation=='development-judge' else self.contextual()
                    if operation=='development-judge':r['protocol']='D1F'
                    packet['requests']=[r];raw=json.dumps(packet).encode();path.write_bytes(raw);calls=[]
                    def post(*a,**kw):
                        calls.append(1)
                        if boundary=='transport':raise e.requests.Timeout('fixture')
                        if operation=='embeddings':
                            return self.response({'model':self.settings['embedding_model'],'usage':{'total_tokens':100},
                                'data':[] if boundary=='invalid' else [{'index':0,'embedding':[1.]+[0.]*1023}]})
                        value={'verdicts':[] if boundary=='invalid' else [{'item_id':'i01','verdict':'plausible','evidence_ref':'p1','reason':'interest'}]}
                        return self.response({'model':self.settings['judge_model'],'usage':{'input_tokens':100,'output_tokens':50},'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(value)}]})
                    original=e.atomic_json
                    def write(target,value):
                        if (boundary=='cache' and target.parent.name=='cache' or boundary=='receipt' and target.parent.name=='receipts' or boundary=='checkpoint' and target.name=='checkpoint.json'):
                            raise OSError('fixture interruption')
                        return original(target,value)
                    ledger_class=e.ExperimentLedger;reconcile=ledger_class.reconcile
                    def reconcile_then_crash(obj,*a,**kw):
                        reconcile(obj,*a,**kw)
                        if boundary=='ledger':raise OSError('after reconciled ledger persisted')
                    with patch.object(e,'atomic_json',write),patch.object(ledger_class,'reconcile',reconcile_then_crash):
                        try:e.execute(self.state,path,e.sha(raw),post)
                        except (OSError,ValueError,e.requests.RequestException):pass
                    self.assertEqual(len(calls),1)
                    if operation=='embeddings':
                        inventory=context_inventory(self.settings)
                        second=next({'id':k,'owner':p,'text':t} for p,rows in inventory.items() for k,t in rows.items() if k!=r['rows'][0]['id'])
                        r['rows'].append(second)
                    else:
                        r['purpose']='d2-call';second=copy.deepcopy(r['items'][0]);second['item_id']='i02'
                        # A different valid question, with the already purchased first item.
                        second['profile_evidence'][0]['id']='p2';second['task_type']='call_person'
                        r['items'][0]['item_id']='i03'
                        # Use different existing evidence for a second real candidate.
                        other=next(p for p in self.settings['profile_claims'] if p!=self.person)
                        claim=self.settings['profile_claims'][other][0];fields=self.settings['d1_profile_fields'][other]
                        meta=next(c for c in fields['claims'] if c['id']==claim['claim_id'])
                        second['candidates']=[other];second['profile_evidence']=[{'id':'p2','person_id':other,'claim_id':claim['claim_id'],'revision':claim['revision'],'text':claim['text'],'source_url':claim['source_urls'][0],'label':meta['label'],'claim_type':meta['claim_type'],'research_summary':fields['research_summary']}]
                        r['items'].append(second)
                    raw=json.dumps(packet).encode();path.write_bytes(raw)
                    before=e.ExperimentLedger(self.state/'ledger.json').read()
                    for _ in range(3):
                        with self.assertRaisesRegex(Deferred,'no_rebatch'):e.execute(self.state,path,e.sha(raw),post)
                    self.assertEqual(len(calls),1);self.assertEqual(e.ExperimentLedger(self.state/'ledger.json').read(),before)

    def test_historical_index_covers_paid_failures_without_changing_old_rows(self):
        index=historical_index();self.assertEqual(len(index),162)
        self.assertEqual(e.sha((e.CONFIG/'prior-items-d2.json').read_bytes()),'7de6cee13e6321f7e3a8ea1ab38af8d5d1a5b4548ea46364c157760acc8059ca')
        key,old=next(iter(index.items()));row={'key':key,'purpose':'d1-call',**old};row.pop('judge_items')
        before=copy.deepcopy(row)
        self.assertEqual(claimed_judge_items(row),old['judge_items']);self.assertEqual(row,before)
        row['body_sha256']='f'*64
        with self.assertRaises(Deferred):claimed_judge_items(row)

    def test_overlapping_reservations_are_atomic_across_ledger_instances(self):
        import concurrent.futures
        for provider in ('anthropic','voyage'):
            path=self.root/(provider+'-atomic.json');ledger=e.ExperimentLedger(path,initialize=True)
            def reserve(i):
                metadata={'purpose':'d2-call','judge_items':['same-item']} if provider=='anthropic' else {'purpose':'d2-context','row_inputs':['document:same']}
                try:
                    return e.ExperimentLedger(path).reserve_experiment(provider,self.settings['judge_model' if provider=='anthropic' else 'embedding_model'],2,str(i),10000 if provider=='anthropic' else 100,1,trusted_route=True,input_tokens=100,output_tokens=512 if provider=='anthropic' else 0,execution_metadata=metadata)
                except Deferred:return None
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(reserve,range(16)))
            self.assertEqual(sum(r is not None for r in results),1)

    def test_whole_packet_overlap_is_rejected_before_any_dispatch(self):
        for operation in ('embeddings','development-judge'):
            path,_,packet=self.packet(operation)
            first=self.contextual() if operation=='embeddings' else self.revised()
            if operation=='development-judge':first.update(protocol='D1F',purpose='d2-call')
            second=copy.deepcopy(first)
            if operation=='embeddings':
                inventory=context_inventory(self.settings)
                second['rows'].append(next({'id':k,'owner':p,'text':t} for p,rows in inventory.items() for k,t in rows.items() if k!=first['rows'][0]['id']))
            else:second['items'][0]['item_id']='i02'
            packet['requests']=[first,second];raw=json.dumps(packet).encode();path.write_bytes(raw)
            for _ in range(3):
                with self.assertRaisesRegex(Deferred,'overlapping_paid_packet'):
                    e.execute(self.state,path,e.sha(raw),lambda *a,**k:self.fail('partial packet dispatched'))
            self.assertEqual(e.ExperimentLedger(self.state/'ledger.json').read()['requests'],[])

    def test_restored_historical_failed_claim_blocks_rebatch_without_cache(self):
        from tools.team_recommender_items import preflight
        r=self.revised();r.update(protocol='D1F',purpose='d2-call')
        path,_,packet=self.packet('development-judge');packet['requests']=[r]
        key='a'*64;historical={key:{'body_sha256':'b'*64,'packet_sha256':'c'*64,'judge_items':judge_items(r)}}
        for status in ('valid','failed','reserved_unknown'):
            ledger=e.ExperimentLedger(self.state/'ledger.json');state=ledger.read()
            state['requests']=[{'key':key,'purpose':'d1-call','status':status,'body_sha256':'b'*64,'packet_sha256':'c'*64}]
            e.atomic_json(ledger.path,state)
            with patch('tools.team_recommender_items.historical_index',return_value=historical):
                for _ in range(3):
                    with self.assertRaisesRegex(Deferred,'no_rebatch'):preflight(packet,self.settings,e.ExperimentLedger(ledger.path))

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
