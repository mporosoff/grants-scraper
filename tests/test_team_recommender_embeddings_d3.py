import copy
import json
import unittest
from unittest.mock import patch
from tests import test_team_recommender_executor as base
from tests import test_team_recommender_judge_d1 as d1
from tools import team_recommender_executor as e
from tools import team_recommender_embeddings_d3 as d3
from tools.team_recommender_items import judge_items
from tools.offline_spend import Deferred, ConfigurationFailure, identity


class D3Contracts(unittest.TestCase):
    setUp = base.ExecutorContract.setUp
    embedding = base.ExecutorContract.embedding
    judge = base.ExecutorContract.judge
    packet = base.ExecutorContract.packet
    response = base.ExecutorContract.response
    revised = d1.D1Contract.revised

    def request(self, representation=d3.CONTEXT, role='document', owners=None):
        people = d3.profiles(self.settings)
        owners = owners or [self.person]
        if role == 'query':
            owner, scope = next(iter(d3.queries().items()))
            t = scope['core']; rows = [{'id': d3.digest(t), 'owner': owner, 'text': t}]
        else:
            rows = []
            for owner in owners:
                p = people[owner]
                if representation == d3.CONTEXT:
                    rows.append({'id': d3.digest(d3.canonical(p['chunks'])), 'owner': owner, 'chunks': p['chunks']})
                else:
                    t = p['phrases'][0] if representation == d3.PHRASES else p['combined']
                    rows.append({'id': d3.digest(t), 'owner': owner, 'text': t})
        return {'representation': representation, 'model': d3.MODELS[representation], 'input_role': role, 'rows': rows}

    def payload(self, request):
        vector = [1.] + [0.] * 1023
        rows = []
        for i, row in enumerate(request['rows']):
            if request['representation'] == d3.CONTEXT:
                n = len(row['chunks']) if request['input_role'] == 'document' else 1
                rows.append({'index': i, 'data': [{'index': j, 'embedding': vector} for j in range(n)]})
            else:
                rows.append({'index': i, 'embedding': vector})
        return {'model': request['model'], 'usage': {'total_tokens': 100}, 'data': rows}

    def test_original_fields_and_exact_document_structure(self):
        before = copy.deepcopy(self.settings); people = d3.profiles(self.settings)
        self.assertEqual(before, self.settings); self.assertEqual(len(people), 155)
        for owner, p in people.items():
            self.assertEqual(p['combined'], '\n\n'.join(p['chunks']))
            self.assertEqual(len(p['chunks']), len(p['attribution']))
            self.assertEqual(len(p['phrases']), len(set(p['phrases'])))
            for a in p['attribution']:
                for ref in a['claim_refs']:
                    self.assertTrue(any(c['claim_id']==ref['claim_id'] and c['revision']==ref['revision'] and c['text']==a['text'] for c in self.settings['profile_claims'][owner]))

    def test_duplicate_claims_missing_summaries_and_metadata_names(self):
        before = d3.profiles(self.settings)[self.person]
        self.settings['profile_claims'][self.person].append(copy.deepcopy(self.claim))
        self.assertEqual(d3.profiles(self.settings)[self.person]['combined'], before['combined'])
        self.settings['d1_profile_fields'][self.person]['research_summary'] = ''
        self.assertFalse(any(a['field']=='research_summary' for a in d3.profiles(self.settings)[self.person]['attribution']))
        same = d3.profiles(self.settings)
        self.settings['d1_profile_fields'][self.person]['name'] = 'Cosmetic changed name'
        self.assertEqual(d3.profiles(self.settings), same)

    def test_context_groups_are_one_person_and_query_groups_are_singletons(self):
        owners = list(self.settings['profile_claims'])[:2];r = self.request(owners=owners)
        body, bound = e.embedding_contract(r, self.settings)
        self.assertEqual(body['inputs'], [d3.profiles(self.settings)[p]['chunks'] for p in owners])
        self.assertFalse(body['enable_auto_chunking']);self.assertLessEqual(bound,100000)
        q = self.request(role='query'); body,_ = e.embedding_contract(q,self.settings)
        self.assertEqual(body['inputs'], [[q['rows'][0]['text']]])
        bad = copy.deepcopy(r);bad['rows'][0]['chunks'] += bad['rows'][1]['chunks']
        bad['rows'][0]['id'] = d3.digest(d3.canonical(bad['rows'][0]['chunks']))
        with self.assertRaisesRegex(ValueError,'one_exact_frozen_person'):e.embedding_contract(bad,self.settings)

    def test_whole_context_invalidation_and_space_identity(self):
        r = self.request(); original = d3.paid_items(r)
        changed = copy.deepcopy(r);changed['rows'][0]['chunks'][0] += ' fixture edit'
        changed['rows'][0]['id'] = d3.digest(d3.canonical(changed['rows'][0]['chunks']))
        self.assertFalse(set(original) & set(d3.paid_items(changed)))
        with self.assertRaises(ValueError):e.embedding_contract(changed,self.settings)
        reordered=copy.deepcopy(r);reordered['rows'][0]['chunks'].reverse();reordered['rows'][0]['id']=d3.digest(d3.canonical(reordered['rows'][0]['chunks']))
        self.assertNotEqual(original,d3.paid_items(reordered))
        with self.assertRaises(ValueError):e.embedding_contract(reordered,self.settings)
        q = self.request(d3.PHRASES,'query');same=copy.deepcopy(q);same['representation']=d3.COMBINED
        self.assertEqual(d3.paid_items(q),d3.paid_items(same))
        other=self.request(d3.CONTEXT,'query');self.assertNotEqual(d3.paid_items(q),d3.paid_items(other))

    def test_no_arbitrary_model_endpoint_text_or_source(self):
        for rep in d3.MODELS:
            r=self.request(rep);e.embedding_contract(r,self.settings)
            for key,value in [('model','voyage-code-4'),('endpoint','https://example.org'),('stage',3),('representation','D3-arbitrary')]:
                bad=copy.deepcopy(r);bad[key]=value
                with self.assertRaises(ValueError):e.embedding_contract(bad,self.settings)
        q=self.request(role='query');q['rows'][0]['text']='New invented experiment';q['rows'][0]['id']=d3.digest(q['rows'][0]['text'])
        with self.assertRaises(ValueError):e.embedding_contract(q,self.settings)
        q=self.request(role='query');q['rows'][0]['owner']='unprepared-or-holdout'
        with self.assertRaises(ValueError):e.embedding_contract(q,self.settings)

    def test_bounded_source_context_format_is_not_arbitrary_expansion(self):
        q=self.request(role='query');owner=q['rows'][0]['owner'];text=d3.query_texts(d3.queries()[owner],True)[0]
        q.update(query_format=d3.QUERY_FORMAT);q['rows'][0].update(text=text,id=d3.digest(text))
        e.embedding_contract(q,self.settings)
        q['rows'][0]['text']+=' invented exclusion';q['rows'][0]['id']=d3.digest(q['rows'][0]['text'])
        with self.assertRaises(ValueError):e.embedding_contract(q,self.settings)

    def test_nested_response_indices_shape_norm_and_space(self):
        r=self.request();contract=e.embedding_contract(r,self.settings);p=self.payload(r)
        value=e.result_value('embeddings',p,r,contract,self.settings)
        self.assertEqual(len(value['rows']),len(r['rows'][0]['chunks']))
        for mode in ['model','index','count','finite','norm']:
            bad=copy.deepcopy(p)
            if mode=='model':bad['model']=d3.STANDARD_MODEL
            elif mode=='index':bad['data'][0]['data'][0]['index']=999
            elif mode=='count':bad['data'][0]['data'].pop()
            elif mode=='finite':bad['data'][0]['data'][0]['embedding'][0]=float('nan')
            else:bad['data'][0]['data'][0]['embedding']=[0.]*1024
            with self.assertRaises((ValueError,ConfigurationFailure)):e.result_value('embeddings',bad,r,contract,self.settings)

    def test_exact_cache_reuse_and_price_per_intended_model(self):
        for rep in d3.MODELS:
            r=self.request(rep);path,_,packet=self.packet();packet['requests']=[r];raw=json.dumps(packet).encode();path.write_bytes(raw);calls=[]
            def post(url,**kwargs):
                calls.append(url);self.assertEqual(url,d3.endpoint(r));self.assertEqual(kwargs['json']['model'],r['model'])
                self.assertEqual(e.ExperimentLedger(self.state/'ledger.json').read()['requests'][-1]['status'],'reserved_unknown')
                return self.response(self.payload(r))
            e.execute(self.state,path,e.sha(raw),post)
            for _ in range(3):e.execute(self.state,path,e.sha(raw),lambda *a,**k:self.fail('duplicate fixture dispatch'))
            self.assertEqual(len(calls),1);self.assertEqual(e.ExperimentLedger(self.state/'ledger.json').read()['requests'][-1]['charged_microusd'],12)
        self.assertEqual(e.usage_cost('embeddings',{'usage':{'total_tokens':101}},d3.CONTEXT_MODEL)[1],13)

    def test_crash_boundaries_and_rebatched_restoration_never_duplicate(self):
        for rep in (d3.COMBINED,d3.CONTEXT):
            for boundary in ['invalid','transport','ledger','cache','receipt','checkpoint']:
                with self.subTest(rep=rep,boundary=boundary):
                    self.state=self.root/(rep+'-'+boundary);self.state.mkdir();(self.state/'ledger.json').write_bytes((e.CONFIG/'initial-ledger.json').read_bytes())
                    r=self.request(rep);path,_,packet=self.packet();packet['requests']=[r];raw=json.dumps(packet).encode();path.write_bytes(raw);calls=[]
                    def post(*a,**kw):
                        calls.append(1)
                        if boundary=='transport':raise e.requests.Timeout('fixture')
                        p=self.payload(r)
                        if boundary=='invalid':p['data']=[]
                        return self.response(p)
                    original=e.atomic_json;reconcile=e.ExperimentLedger.reconcile
                    def write(target,value):
                        if boundary=='cache' and target.parent.name=='cache' or boundary=='receipt' and target.parent.name=='receipts' or boundary=='checkpoint' and target.name=='checkpoint.json':raise OSError('fixture crash')
                        return original(target,value)
                    def after_reconcile(obj,*args,**kw):
                        reconcile(obj,*args,**kw)
                        if boundary=='ledger':raise OSError('fixture after ledger write')
                    with patch.object(e,'atomic_json',write),patch.object(e.ExperimentLedger,'reconcile',after_reconcile):
                        try:e.execute(self.state,path,e.sha(raw),post)
                        except (ValueError,OSError,e.requests.RequestException):pass
                    self.assertEqual(len(calls),1)
                    # Cache-complete late crashes may reuse exact success; all
                    # others remain recovery-required. None dispatch again.
                    for _ in range(3):
                        try:e.execute(self.state,path,e.sha(raw),lambda *a,**k:self.fail('duplicate exact dispatch'))
                        except Deferred:pass
                    other=next(p for p in self.settings['profile_claims'] if p!=self.person)
                    r['rows'] += self.request(rep,owners=[other])['rows'];raw=json.dumps(packet).encode();path.write_bytes(raw)
                    before=(self.state/'ledger.json').read_bytes()
                    for _ in range(3):
                        with self.assertRaisesRegex(Deferred,'no_rebatch'):e.execute(self.state,path,e.sha(raw),lambda *a,**k:self.fail('duplicate rebatched dispatch'))
                    self.assertEqual((self.state/'ledger.json').read_bytes(),before)

    def test_d3_judge_uses_unchanged_questions_and_exact_item_cache_identity(self):
        r=self.revised();r['protocol']='D1F';before=judge_items(r);body=e.judge_contract(r,self.settings)[0]
        r['purpose']='d3-call';self.assertEqual(judge_items(r),before);self.assertEqual(e.judge_contract(r,self.settings)[0],body)

    def test_new_model_budget_route_requires_finite_D3_purpose_and_correct_rate(self):
        ledger=e.ExperimentLedger(self.state/'ledger.json')
        kw=dict(trusted_route=True,input_tokens=100,execution_metadata={'purpose':'d3-embedding','row_inputs':['fixture:row']})
        with self.assertRaisesRegex(ValueError,'underreserved'):ledger.reserve_experiment('voyage',d3.STANDARD_MODEL,2,'first',2,1,**kw)
        with self.assertRaises(ConfigurationFailure):ledger.reserve_experiment('voyage',d3.STANDARD_MODEL,2,'first',12,1,trusted_route=True,input_tokens=100)
        token=ledger.reserve_experiment('voyage',d3.STANDARD_MODEL,2,'first',12,1,**kw)
        with self.assertRaises(Deferred):ledger.reserve_experiment('voyage',d3.STANDARD_MODEL,2,'second',12,1,**kw)
        self.assertEqual(len(ledger.read()['requests']),1)
        self.assertEqual(ledger.read()['logical_id'],e.AUTHORIZATION_ID)


if __name__=='__main__':unittest.main()
