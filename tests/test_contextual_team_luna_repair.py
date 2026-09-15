"""Real input identities, fixture judgments/usage only; zero provider traffic."""
import copy
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from tools import contextual_team_pair_contract as pairs
from tools import contextual_team_luna_policy as policy
from tools import contextual_team_luna_repair as repair
from tools import contextual_team_diagnostics as diagnostic
from tools import team_recommender_executor as existing
from tools.contextual_team_executor import Runner, RecoveryRequired, scope_inputs
from tools.contextual_team_phase2 import configuration
from tools.offline_ai import validate_schema, anthropic_schema
from tools.offline_spend import identity, atomic_json, encoded, Deferred, ConfigurationFailure
from tools.team_recommender_budget import ExperimentLedger


def real_data():
    c=configuration(); f=json.loads(Path('tests/fixtures/contextual-eclipse-pairs.json').read_bytes())
    scope=next(s for s in c['scopes'] if s['id']=='351715')
    people={p['person_id']:p for p in c['people']}
    return scope_inputs(scope)|{'interpretation':f['interpretation'],
        'people':[people[pid] for pid in f['shortlist']]}


def answer(data, judge=False):
    result={'decisions':{}}
    for i,p in enumerate(data['people']):
        refs=[c['claim_id']+'@'+str(c['revision']) for c in p['claims']]
        result['decisions'][p['person_id']]={}
        for j,r in enumerate(data['interpretation']['roles']):
            category='direct' if i<7 else 'method_transfer' if i==7 else 'adjacent' if i<10 else 'insufficient_information'
            if j: category='adjacent'
            result['decisions'][p['person_id']][r['id']]={
                'coverage':category,'claim_refs':{'primary':refs[0],'second':refs[1],'third':'NONE'},
                'source_ref':r['source_ref'],'reason':'Fixture decision; this is not a scientific judgment.',
                'gap':'Fixture limitation, with Unicode \u03b1 and \u03b2.',
                **({'verdict':'plausible'} if judge else {})}
    return result


class Response:
    def __init__(self,payload,status=200):
        self.raw=encoded(payload); self.status_code=status; self.headers={'request-id':'fixture-request'}
    def iter_content(self,n): yield self.raw
    def close(self): pass


class PairContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.data=real_data()

    def test_actual_12_by_2_identity_and_more_than_four_supports(self):
        self.assertEqual(identity(self.data),policy.plan()['input_sha256'])
        v=pairs.resolve(answer(self.data),self.data)
        self.assertEqual(len(v['people']),12)
        self.assertEqual(sum(len(p['decisions']) for p in v['people']),24)
        self.assertEqual(sum(p['outcome']=='supported' for p in v['people']),7)
        self.assertEqual(v['people'][7]['outcome'],'credible_transfer')
        self.assertEqual(len(v['people'][0]['decisions'][0]['claims']),2)
        self.assertEqual(pairs.validate_cached(json.loads(encoded(v)),self.data),v)
        self.assertEqual(v['state'],'complete_unverified_assessment')

    def test_true_negatives_unknown_and_overlap_are_complete(self):
        a=answer(self.data)
        for person in a['decisions'].values():
            for row in person.values():
                row.update(coverage='insufficient_information',claim_refs=dict.fromkeys(('primary','second','third'),'NONE'))
        v=pairs.resolve(a,self.data)
        self.assertTrue(all(p['outcome']=='insufficient_information' for p in v['people']))
        first=next(iter(a['decisions'].values()))
        first['role-1']['coverage']='adjacent'
        self.assertEqual(pairs.resolve(a,self.data)['people'][0]['outcome'],'adjacent')

    def test_native_keyed_cardinality_ownership_and_local_boundaries(self):
        a=answer(self.data); pid=self.data['people'][0]['person_id']; other=self.data['people'][1]['person_id']
        mutations=[lambda v:v['decisions'].pop(pid),
            lambda v:v['decisions'][pid].pop('role-2'),
            lambda v:v['decisions'].update(invented={}),
            lambda v:v['decisions'][pid]['role-1'].update(source_ref='src-sibling'),
            lambda v:v['decisions'][pid]['role-1']['claim_refs'].update(primary=other+'-c001@2'),
            lambda v:v['decisions'][pid]['role-1']['claim_refs'].update(primary=pid+'-c001@99'),
            lambda v:v['decisions'][pid]['role-1'].update(reason='x'*701)]
        for mutate in mutations:
            v=copy.deepcopy(a);mutate(v)
            with self.assertRaises(ValueError):pairs.resolve(v,self.data)
        native=anthropic_schema(pairs.schema(self.data))
        self.assertEqual(native['properties']['decisions']['required'],[p['person_id'] for p in self.data['people']])
        self.assertEqual(native['properties']['decisions']['properties'][pid]['required'],['role-1','role-2'])
        self.assertEqual(native['properties']['decisions']['properties'][pid]['properties']['role-1']['properties']['claim_refs']['required'],['primary','second','third'])
        for mutate in mutations[:-1]:
            v=copy.deepcopy(a);mutate(v)
            with self.assertRaises(ValueError):validate_schema(v,native)
        a['decisions'][pid]['role-1']['reason']='\u03b1'*700
        pairs.resolve(a,self.data)

    def test_duplicates_and_supported_without_claims_are_rejected(self):
        a=answer(self.data);pid=self.data['people'][0]['person_id'];d=a['decisions'][pid]['role-1']
        d['claim_refs']['second']=d['claim_refs']['primary']
        with self.assertRaisesRegex(ValueError,'duplicate_support'):pairs.resolve(a,self.data)
        d['claim_refs']=dict.fromkeys(('primary','second','third'),'NONE')
        with self.assertRaisesRegex(ValueError,'positive_without'):pairs.resolve(a,self.data)
        payload={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"decisions":{},"decisions":{}}'}]}]}
        with self.assertRaisesRegex(ValueError,'duplicate_response_key'):pairs.parse(payload,'openai',self.data)

    def test_cache_cannot_drop_claims_or_duplicate_people_pairs(self):
        v=pairs.resolve(answer(self.data),self.data)
        for mutate in (lambda x:x['people'].append(x['people'][0]),
            lambda x:x['people'][0]['decisions'].append(x['people'][0]['decisions'][0]),
            lambda x:x['people'][0]['decisions'][0]['claims'].clear()):
            x=copy.deepcopy(v);mutate(x)
            with self.assertRaises(ValueError):pairs.validate_cached(x,self.data)

    def test_frozen_checker_covers_all_pairs_without_prior_labels(self):
        c,b=pairs.body(self.data,judge=True)
        supplied=json.loads(b['messages'][0]['content'])
        self.assertEqual(supplied['people'],self.data['people'])
        self.assertNotIn('proposed_edges',supplied)
        self.assertEqual(c['maximum_pairs'],24)
        self.assertEqual(b['thinking'],{'type':'disabled'})
        self.assertNotIn('effort',b['output_config'])
        self.assertEqual(b['max_tokens'],12000)
        pairs.validate_cached(pairs.resolve(answer(self.data,True),self.data,judge=True),self.data,judge=True)


class CompactCheckerContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=real_data()
        blocked=patch('socket.socket.connect',side_effect=AssertionError('offline_check_only'))
        blocked.start();cls.addClassCleanup(blocked.stop)

    @staticmethod
    def expanded(native):
        """Independently expand only local, acyclic, standalone schema refs."""
        definitions=native['$defs']
        def visit(value, active=()):
            if isinstance(value,list):return [visit(v,active) for v in value]
            if not isinstance(value,dict):return value
            if '$ref' in value:
                if set(value)!={'$ref'} or not value['$ref'].startswith('#/$defs/'):
                    raise AssertionError('nonlocal_or_sibling_reference')
                key=value['$ref'].removeprefix('#/$defs/')
                if key in active:raise AssertionError('recursive_schema')
                return visit(definitions[key],active+(key,))
            return {k:visit(v,active) for k,v in value.items() if k!='$defs'}
        # Validate all definitions, including any that are not referenced.
        for key in definitions:visit({'$ref':'#/$defs/'+key})
        return visit(native)

    def test_native_expansion_preserves_every_constraint_and_reduces_wire(self):
        for count in (1,6,12):
            data=copy.deepcopy(self.data);data['people']=data['people'][:count]
            original=copy.deepcopy(data)
            _,old=pairs.body(data,judge=True)
            _,new=pairs.compact_check_body(data)
            before=old['output_config']['format']['schema']
            after=new['output_config']['format']['schema']
            self.assertEqual(self.expanded(after),before)
            self.assertLess(len(encoded(after)),len(encoded(before)))
            self.assertEqual(data,original)
            self.assertEqual({k:v for k,v in new.items() if k!='output_config'},
                             {k:v for k,v in old.items() if k!='output_config'})

    def test_frozen_operations_stay_identical_and_compact_packet_has_new_identity(self):
        for name in ('assessment','check'):
            c,b=pairs.body(self.data,judge=name=='check')
            op=policy.plan()['operations'][name]
            self.assertEqual(identity(c),op['contract_sha256'])
            self.assertEqual(identity(b),op['body_sha256'])
        old_c,old_b=pairs.body(self.data,judge=True)
        c,b=pairs.compact_check_body(self.data)
        self.assertNotEqual(identity(c),identity(old_c))
        self.assertNotEqual(identity(b),identity(old_b))
        self.assertEqual(c['canonical_contract_sha256'],identity(old_c))
        self.assertEqual(c['native_schema_sha256'],identity(b['output_config']['format']['schema']))
        self.assertEqual(c['schema'],old_c['schema'])
        self.assertEqual(c['prompt'],old_c['prompt'])
        self.assertFalse(c['serving_approved'])
        self.assertEqual(c['maximum_pairs'],24)
        self.assertEqual(pairs.compact_check_body(self.data),(c,b))
        original_body=pairs.body
        def substituted(data, *, judge=False):
            return (c,b) if judge else original_body(data,judge=False)
        with patch.object(repair,'eclipse_data',return_value=(self.data,None)), patch.object(pairs,'body',side_effect=substituted):
            with self.assertRaisesRegex(ConfigurationFailure,'locked_prompt_schema_or_input_changed'):
                repair.locked_packets(Path('unused-offline-state'))

    def test_compact_checker_rejects_missing_pairs_and_wrong_owned_evidence(self):
        _,b=pairs.compact_check_body(self.data)
        native=self.expanded(b['output_config']['format']['schema'])
        a=answer(self.data,True)
        pid=self.data['people'][0]['person_id'];other=self.data['people'][1]['person_id']
        validate_schema(a,native)
        pairs.validate_cached(pairs.resolve(a,self.data,judge=True),self.data,judge=True)
        mutations=(lambda v:v['decisions'].pop(pid),
            lambda v:v['decisions'][pid].pop('role-2'),
            lambda v:v['decisions'].update(invented={}),
            lambda v:v['decisions'][pid]['role-1'].pop('verdict'),
            lambda v:v['decisions'][pid]['role-1'].update(source_ref='src-sibling'),
            lambda v:v['decisions'][pid]['role-1']['claim_refs'].update(primary=other+'-c001@2'),
            lambda v:v['decisions'][pid]['role-1']['claim_refs'].update(primary=pid+'-c001@99'))
        for mutate in mutations:
            v=copy.deepcopy(a);mutate(v)
            with self.assertRaises(ValueError):validate_schema(v,native)
            with self.assertRaises(ValueError):pairs.resolve(v,self.data,judge=True)
        # Native string descriptions still defer exact bounds to the local validator.
        v=copy.deepcopy(a);v['decisions'][pid]['role-1']['reason']='x'*701
        with self.assertRaises(ValueError):pairs.resolve(v,self.data,judge=True)
        v=copy.deepcopy(a);refs=v['decisions'][pid]['role-1']['claim_refs'];refs['second']=refs['primary']
        with self.assertRaisesRegex(ValueError,'duplicate_support_claim'):pairs.resolve(v,self.data,judge=True)
        v=copy.deepcopy(a);v['decisions'][pid]['role-1']['claim_refs']['primary']='NONE'
        with self.assertRaisesRegex(ValueError,'positive_without_retained_support'):pairs.resolve(v,self.data,judge=True)
        payload={'stop_reason':'end_turn','content':[{'type':'text','text':'{"decisions":{},"decisions":{}}'}]}
        with self.assertRaisesRegex(ValueError,'duplicate_response_key'):pairs.parse(payload,'anthropic',self.data,judge=True)



class Execution(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.state=Path(self.temp.name)/'state';self.state.mkdir()
        self.data=real_data();self.calls=[]
        env=patch.dict(os.environ,{'GITHUB_RUN_ID':'999','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'a'*40,
            'OPENAI_API_KEY':'fixture-secret','ANTHROPIC_API_KEY':'fixture-secret'})
        env.start();self.addCleanup(env.stop)
        ledger=ExperimentLedger(self.state/'ledger.json',initialize=True)
        s=ledger.read()
        s['requests']=[{'id':f'{i:032x}','key':f'{i:064x}','provider':'anthropic',
            'model':'fixture','stage':2,'attempt':1,'status':'valid','charged_microusd':0} for i in range(682)]
        s['requests'][0]['charged_microusd']=7339874
        s['requests'].append({'id':policy.OLD_ID,'key':'f'*64,'body_sha256':policy.OLD_BODY,
            'provider':'anthropic','model':'claude-sonnet-5','purpose':'cb-lr-comparison-check',
            'stage':2,'attempt':1,'status':'reserved_unknown','charged_microusd':146074,'usage':None})
        self.original=copy.deepcopy(s['requests'])
        atomic_json(ledger.path,s)
        p=patch.object(policy,'PRIOR_ROWS',identity(s['requests']));p.start();self.addCleanup(p.stop)
        receipt={'http_status':400,'request_id':policy.OLD_ID,'body_sha256':policy.OLD_BODY,'status':'reserved_unknown'}
        atomic_json(self.state/'receipts'/(policy.OLD_ID+'.json'),receipt)
        p=patch.object(policy,'OLD_RECEIPT',existing.sha((self.state/'receipts'/(policy.OLD_ID+'.json')).read_bytes()))
        p.start();self.addCleanup(p.stop)
        self.run={'id':34852296018,'run_attempt':1,'status':'completed','conclusion':'failure',
            'path':existing.WORKFLOW,'head_branch':'main','event':'workflow_dispatch',
            'head_sha':'31b69b0772c759d9d8f7651a02aef924c7bab7e5'}
        policy.install_authority(self.state,lambda _:encoded(self.run))
        p=patch.object(repair,'eclipse_data',return_value=(self.data,None));p.start();self.addCleanup(p.stop)
        _,packets=repair.locked_packets(self.state)
        from tools.contextual_team_token_preflight import count_projection
        key=identity(count_projection(packets['check'][1]))
        count_rows=[{'id':'fixture:'+str(i),'key':identity(i),'status':'complete','input_tokens':1} for i in range(186)]
        p=patch.object(policy,'PRIOR_COUNT_ROWS',identity(count_rows));p.start();self.addCleanup(p.stop)
        existing.checkpoint(self.state,token_preflight={'version':'contextual-phase2-token-preflight-v1',
            'source_sha256':'56a102550e8a231ad893bfe97dc94810c66fe2a6a20c433b4a75be00d0a24e9d','rows':count_rows})
        class Counter:
            def count(inner,item):
                count_rows.append({'id':policy.VERSION+':check','key':key,'status':'complete','input_tokens':25000})
                cp=json.loads((self.state/'checkpoint.json').read_bytes())['phase2_token_preflight']
                cp['rows']=count_rows;existing.checkpoint(self.state,token_preflight=cp)
                return 25000
        repair.preflight(self.state,Counter())

    def provider(self,url,**kwargs):
        self.calls.append(url);b=kwargs['json'];judge='anthropic' in url
        a=answer(self.data,judge);usage={'input_tokens':100,'output_tokens':200}
        if judge:return Response({'model':b['model'],'stop_reason':'end_turn','usage':usage,
            'content':[{'type':'thinking','thinking':'HIDDEN-REASONING'},{'type':'text','text':json.dumps(a)}]})
        return Response({'model':b['model']+'-2026-09-08','status':'completed','usage':usage|{
            'output_tokens_details':{'reasoning_tokens':20}},'output':[{'type':'reasoning','summary':'HIDDEN-REASONING'},
            {'type':'message','content':[{'type':'output_text','text':json.dumps(a)}]}]})

    def runner(self,**kwargs):return repair.RepairRunner(self.state,{},post=self.provider,**kwargs)

    def test_exact_authority_idempotence_and_two_paid_cache_reuses(self):
        for _ in range(3):policy.install_authority(self.state,lambda _:encoded(self.run))
        a=self.runner().perform('assessment');check=self.runner().perform('check')
        for _ in range(3):
            self.assertEqual(self.runner().perform('assessment')['value'],a['value'])
            self.assertEqual(self.runner().perform('check')['value'],check['value'])
        s=self.runner().ledger.read();self.assertEqual(s['requests'][:683],self.original)
        self.assertEqual(sum(e==policy.EVENT for e in s['events']),1)
        self.assertEqual(len(self.calls),2)
        for p in (self.state/'diagnostics').glob('*.json'):
            d=json.loads(p.read_bytes());self.assertTrue(d['final_answer_complete'])
            self.assertNotIn('HIDDEN-REASONING',p.read_text());self.assertFalse(d['accepted_cache'])

    def test_live_or_retried_old_run_and_other_unknown_still_block(self):
        self.run['status']='in_progress'
        with self.assertRaises(Deferred):policy.install_authority(self.state,lambda _:encoded(self.run))
        s=self.runner().ledger.read();s['requests'].append({'id':'other','key':'other','status':'reserved_unknown','charged_microusd':1})
        atomic_json(self.state/'ledger.json',s)
        with self.assertRaises(RecoveryRequired):self.runner().perform('assessment')
        self.assertEqual(self.calls,[])
        self.assertTrue(Runner(self.state,{}).has_unknown_request())

    def test_no_check_before_accepted_assessment(self):
        with self.assertRaises(RecoveryRequired):self.runner().perform('check')
        self.assertFalse(self.calls)

    def test_restore_each_persistence_boundary_zero_duplicates(self):
        original=self.state
        for boundary in ('after_reserve','after_reservation_checkpoint','after_dispatch',
            'before_reconcile','after_reconcile','after_cache','after_receipt'):
            with self.subTest(boundary=boundary):
                self.state=original.parent/boundary;shutil.copytree(original,self.state)
                before=len(self.calls)
                def crash(point):
                    if point==boundary:raise KeyboardInterrupt('fixture crash')
                with self.assertRaises(KeyboardInterrupt):self.runner(crash=crash).perform('assessment')
                for _ in range(3):
                    try:self.runner().perform('assessment')
                    except (RecoveryRequired,Deferred):pass
                self.assertLessEqual(len(self.calls)-before,1)
        self.state=original

    def test_failed_and_uncertain_response_diagnostics_no_duplicate(self):
        original=self.state
        responses=[Response({'error':{'type':'invalid_request_error','message':'Bearer fixture-secret parameter invalid',
            'param':'schema'},'usage':{'input_tokens':10,'output_tokens':2}},400),
            Response({},400),Response({'status':'incomplete','model':'gpt-5.6-luna',
                'usage':{'input_tokens':10,'output_tokens':2},'output':[]}),
            Response({'status':'completed','model':'gpt-5.6-luna','usage':{'input_tokens':10,'output_tokens':2},
                'output':[{'type':'message','content':[{'type':'refusal','refusal':'refused'}]}]}),
            Response({'status':'completed','model':'gpt-5.6-luna','usage':{'input_tokens':10,'output_tokens':2},
                'output':[{'type':'message','content':[{'type':'output_text','text':'{invalid'}]}]})]
        for i,response in enumerate(responses):
            with self.subTest(i=i):
                self.state=original.parent/str(i);shutil.copytree(original,self.state);dispatch=[]
                def post(*a,**kw):dispatch.append(1);return response
                r=repair.RepairRunner(self.state,{},post=post)
                with self.assertRaises(Exception):r.perform('assessment')
                for _ in range(3):
                    with self.assertRaises(RecoveryRequired):r.perform('assessment')
                self.assertEqual(len(dispatch),1)
                d=json.loads(next((self.state/'diagnostics').glob('*.json')).read_bytes())
                self.assertNotIn('fixture-secret',json.dumps(d))
                self.assertFalse(d['accepted_cache'])
                if i==0:self.assertEqual(d['validation']['status'],'failed')
                if i==1:
                    self.assertNotIn('reported_usage',d);self.assertNotIn('error',d)
                    self.assertEqual(d['validation']['status'],'reserved_unknown')
        self.state=original

    def test_concurrent_same_operation_and_checkpoint_roundtrip(self):
        def go(_):
            try:return self.runner().perform('assessment')
            except (Deferred,RecoveryRequired):return None
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(go,range(2)))
        self.assertEqual(len(self.calls),1)
        existing.checkpoint(self.state)
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:
            for p in self.state.rglob('*.json'):z.write(p,p.relative_to(self.state).as_posix())
        target=self.state.parent/'restored';existing.unpack_state(raw.getvalue(),target)
        self.assertEqual((target/'ledger.json').read_bytes(),(self.state/'ledger.json').read_bytes())
        self.assertEqual(len(list((target/'diagnostics').glob('*.json'))),1)

    def test_failed_reconcile_and_diagnostic_write_interruptions_never_replay(self):
        original=self.state
        for boundary in ('diagnostic_header','diagnostic_final','after_failed_reconcile'):
            with self.subTest(boundary=boundary):
                self.state=original.parent/boundary;shutil.copytree(original,self.state)
                sent=[];writes=[]
                def post(*a,**kw):
                    sent.append(1)
                    return Response({'model':'gpt-5.6-luna','status':'completed',
                        'usage':{'input_tokens':10,'output_tokens':5},'output':[
                            {'type':'message','content':[{'type':'output_text','text':'{}'}]}]})
                def write(path,value):
                    if path.parent.name=='diagnostics':
                        writes.append(1)
                        if boundary=='diagnostic_header' and len(writes)==1 or boundary=='diagnostic_final' and len(writes)==2:
                            raise KeyboardInterrupt('fixture interrupted diagnostic')
                    atomic_json(path,value)
                def crash(point):
                    if point==boundary:raise KeyboardInterrupt('fixture failed reconciliation')
                runner=repair.RepairRunner(self.state,{},post=post,crash=crash)
                with patch.object(diagnostic,'atomic_json',side_effect=write):
                    with self.assertRaises(KeyboardInterrupt):runner.perform('assessment')
                for _ in range(3):
                    with self.assertRaises(RecoveryRequired):runner.perform('assessment')
                self.assertEqual(len(sent),1)
        self.state=original

    def test_future_check_is_reserved_and_named_operations_cannot_rekey(self):
        s=self.runner().ledger.read()
        s['requests'].append({'id':'later','key':'later','status':'valid',
                              'charged_microusd':1200000})
        atomic_json(self.state/'ledger.json',s)
        with self.assertRaises(Deferred):policy.remaining_fits(s)
        self.assertEqual(len(self.calls),0)
        s['requests'].pop();atomic_json(self.state/'ledger.json',s)
        self.runner().perform('assessment')
        row=self.runner().ledger.read()['requests'][-1]
        metadata={k:v for k,v in row.items() if k in {'purpose','body_sha256','packet_sha256',
            'code_sha','row_inputs','judge_items','execution_capacity','luna_repair',
            'luna_operation','pair_contract_sha256','repair_of'}}
        with self.assertRaises(Deferred):
            self.runner().ledger.reserve_experiment('openai','gpt-5.6-luna',2,'new-key',
                row['reserved_microusd'],1,trusted_route=True,
                input_tokens=row['reserved_input_tokens'],output_tokens=24000,execution_metadata=metadata)

    def test_bounded_final_text_capture_is_not_a_valid_result(self):
        value='x'*(diagnostic.MAX_TEXT+1)
        def post(*a,**kw):return Response({'model':'gpt-5.6-luna','status':'completed',
            'usage':{'input_tokens':10,'output_tokens':20},'output':[
                {'type':'message','content':[{'type':'output_text','text':value}]}]})
        runner=repair.RepairRunner(self.state,{},post=post)
        with self.assertRaises(ValueError):runner.perform('assessment')
        d=json.loads(next((self.state/'diagnostics').glob('*.json')).read_bytes())
        self.assertFalse(d['final_answer_complete']);self.assertFalse(d['accepted_cache'])
        self.assertLessEqual(len(d['final_answer_text'].encode('utf8')),diagnostic.MAX_TEXT)
        with self.assertRaises(RecoveryRequired):self.runner().perform('check')


if __name__=='__main__':unittest.main()
