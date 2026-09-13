import copy
import unittest
from tools import contextual_team_demand_contract as wire
from tools.contextual_team_contract import verification_inputs
from tools.contextual_team_executor import scope_inputs
from tools.contextual_team_policy import inputs
from tools.contextual_team_references import source_references
from tools.offline_ai import request_body, response_value
from tools.offline_spend import Refusal


class ColdDemandContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.config=inputs()

    def fixture(self, count=2):
        source=scope_inputs(next(s for s in self.config['scopes'] if s['id']=='344592:ab-0025'))
        value={'state':'coherent','objective':'Synthetic contract fixture, not a scientific assessment.',
               'roles':[{'id':'role-1','label':'Fixture contribution','required':True,'central':True,
                         'source_ref':source_references(source)[0]['source_ref']}],'limitations':[]}
        interpretation=wire.resolve('decomposition',value,source)
        data=source|{'interpretation':interpretation,'people':self.config['people'][:count]}
        refs=wire.claim_table(data)
        edges=[{'claim_ref':next(k for k,v in refs.items() if v['person_id']==p['person_id']),
                'coverage':'method_transfer','central':True,'reason':'Fixture only: '+('é'*686), 'gap':'界'*300}
               for p in data['people'][:4]]
        answer={'people':{p['person_id']:{'outcome':'credible_transfer' if i<4 else 'insufficient_information'}
                          for i,p in enumerate(data['people'])},'edges_by_contribution':{'role-1':edges}}
        return data,answer

    def test_fresh_interpretation_native_schema_contains_exact_scope_reference_enum(self):
        data,_=self.fixture();source={'scope':data['scope']};c=wire.contract('decomposition',source)
        body=request_body(c['route'],c['settings'],c['prompt'],wire.projected_inputs('decomposition',source),c['schema'])
        expected=[r['source_ref'] for r in source_references(source)]
        self.assertEqual(body['output_config']['format']['schema']['properties']['roles']['items']['properties']['source_ref']['enum'],expected)
        self.assertEqual(wire.projected_inputs('decomposition',source)['scope'],source['scope'])
        bad=copy.deepcopy(data['interpretation']);bad.pop('quote',None)
        for r in bad['roles']:r.pop('quote');r.pop('source_field');r['source_ref']='src-'+'0'*64
        with self.assertRaises(ValueError):wire.resolve('decomposition',bad,source)

    def test_complete_unicode_reasons_and_exact_server_evidence_round_trip(self):
        data,answer=self.fixture();value=wire.resolve('adjudication',answer,data)
        self.assertEqual(wire.validate_resolved('adjudication',value,data),value)
        self.assertEqual(len(value['edges'][0]['reason']),700)
        self.assertEqual(len(value['edges'][0]['gap']),300)
        self.assertEqual(value['edges'][0]['evidence_quote'],data['people'][0]['claims'][0]['evidence'])

    def test_claim_reference_binds_owner_revision_not_caller_fields(self):
        data,answer=self.fixture()
        for key,val in [('claim_ref','clm-'+'0'*64),('person_id','other-person'),('claim_revision',999)]:
            bad=copy.deepcopy(answer);bad['edges_by_contribution']['role-1'][0][key]=val
            with self.assertRaises(ValueError):wire.resolve('adjudication',bad,data)
        retired=copy.deepcopy(data);retired['people'][0]['claims'][0]['revision']+=1
        with self.assertRaises(ValueError):wire.resolve('adjudication',answer,retired)

    def test_missing_extra_and_wrong_person_questions_are_rejected(self):
        data,answer=self.fixture()
        for change in ('missing','extra'):
            bad=copy.deepcopy(answer)
            if change=='missing':bad['people'].pop(data['people'][0]['person_id'])
            else:bad['people']['invented']={'outcome':'supported'}
            with self.assertRaises(ValueError):wire.resolve('adjudication',bad,data)

    def test_verification_keeps_relationships_and_can_downgrade_centrality(self):
        data,answer=self.fixture();assessed=wire.resolve('adjudication',answer,data);verify=verification_inputs(data,assessed)
        checked={'state':'coherent','people':copy.deepcopy(answer['people']),'edges_by_contribution':{'role-1':[
            {'edge_ref':ref,'coverage':'method_transfer','central':False,'reason':'Fixture verification reason.','gap':''}
            for ref in wire.edge_table(verify)]}}
        value=wire.resolve('verification',checked,verify)
        self.assertTrue(all(not e['central'] for e in value['edges']))
        self.assertEqual(wire.validate_resolved('verification',value,verify),value)
        checked['edges_by_contribution']['role-1'][0]['coverage']='direct'
        with self.assertRaises(ValueError):wire.resolve('verification',checked,verify)

    def test_sibling_reference_and_wrong_contribution_are_rejected(self):
        data,answer=self.fixture();sibling=copy.deepcopy(data);sibling['scope']['id']+='-sibling'
        self.assertTrue(set(r['source_ref'] for r in source_references(data)).isdisjoint(r['source_ref'] for r in source_references(sibling)))
        bad=copy.deepcopy(answer);bad['edges_by_contribution']['other-role']=bad['edges_by_contribution'].pop('role-1')
        with self.assertRaises(ValueError):wire.resolve('adjudication',bad,data)

    def test_realistic_maximum_structure_and_native_output_capacities(self):
        data,answer=self.fixture(12)
        data['interpretation']['roles']=[copy.deepcopy(data['interpretation']['roles'][0])|{'id':f'role-{i}'} for i in range(1,7)]
        answer['edges_by_contribution']={r['id']:copy.deepcopy(answer['edges_by_contribution']['role-1']) for r in data['interpretation']['roles']}
        value=wire.resolve('adjudication',answer,data);self.assertEqual(len(value['edges']),24)
        self.assertEqual(wire.validate_resolved('adjudication',value,data),value)
        verify=verification_inputs(data,value)
        for stage,source,limit in [('decomposition',{'scope':data['scope']},8000),('adjudication',data,16000),('verification',verify,24000)]:
            c=wire.contract(stage,source);body=request_body(c['route'],c['settings'],c['prompt'],wire.projected_inputs(stage,source),c['schema'])
            self.assertEqual(body['max_tokens'],limit)
            self.assertEqual(body['model'],'claude-sonnet-5')
            self.assertEqual(wire.projected_inputs(stage,source)['scope'],source['scope'])

    def test_noncoherent_verification_and_empty_graph_remain_distinct(self):
        data,_=self.fixture();verify=verification_inputs(data,{'edges':[]})
        value={'state':'coherent','people':{p['person_id']:{'outcome':'insufficient_information'} for p in data['people']},'edges_by_contribution':{'role-1':[]}}
        self.assertEqual(wire.resolve('verification',value,verify)['state'],'coherent')
        value['state']='insufficient_source'
        self.assertEqual(wire.resolve('verification',value,verify)['state'],'insufficient_source')

    def test_complete_response_required_before_resolution(self):
        for stop in ('max_tokens','pause_turn','refusal'):
            with self.assertRaises((ValueError,Refusal)):response_value('anthropic',{'stop_reason':stop,'content':[{'type':'text','text':'{}'}]})


if __name__=='__main__':unittest.main()
