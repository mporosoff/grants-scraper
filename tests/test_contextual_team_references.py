import copy
import unittest
from tools.contextual_team_policy import inputs
from tools.contextual_team_executor import scope_inputs
from tools.contextual_team_contract import verification_inputs
from tools.contextual_team_references import (contract, projected_inputs, resolve,
    validate_resolved, source_references, OUTPUT_LIMITS)
from tools.offline_ai import request_body, response_value
from tools.offline_spend import Refusal


class ReferenceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.config=inputs()

    def fixture(self):
        scope=next(s for s in self.config['scopes'] if s['id']=='344592:ab-0025')
        data=scope_inputs(scope);refs=source_references(data)
        interpretation={'state':'coherent','objective':'Fixture, not a scientific decision.',
          'roles':[{'id':'role-1','label':'Fixture contribution','required':True,
          'central':True,'source_ref':refs[0]['source_ref']}],'limitations':[]}
        interpretation=resolve('decomposition',interpretation,data)
        person=self.config['people'][0];claim=person['claims'][0]
        data|={'interpretation':interpretation,'people':[person]}
        edge={'role_id':'role-1','person_id':person['person_id'],'claim_id':claim['claim_id'],
          'claim_revision':claim['revision'],'coverage':'method_transfer','central':True,
          'reason':'Fixture only. '+('x'*246),'gap':'No scientific evaluation occurred.'}
        value={'people':[{'person_id':person['person_id'],'outcome':'credible_transfer'}],'edges':[edge]}
        return data,value

    def test_context_and_exact_unicode_spans_preserved_with_child_ownership(self):
        for scope in self.config['scopes']:
            data=scope_inputs(scope);projection=projected_inputs(data)
            self.assertEqual(projection['scope'],data['scope'])
            refs=projection['source_references']
            self.assertEqual(refs,source_references(copy.deepcopy(data)))
            for ref in refs:
                self.assertEqual(ref['text'],data['scope']['science'][ref['field']][ref['start']:ref['end']])
                self.assertEqual(ref['scope_id'],scope['id'])
                self.assertEqual(ref['parent_id'],scope['parent_id'])
        data,value=self.fixture();other=copy.deepcopy(data);other['scope']['id']='another-child'
        self.assertTrue(set(r['source_ref'] for r in source_references(data)).isdisjoint(r['source_ref'] for r in source_references(other)))

    def test_known_224_and_260_character_cases_and_boundaries_without_clipping(self):
        data,value=self.fixture()
        for length in (224,260,700):
            value['edges'][0]['reason']='r'*length
            result=resolve('adjudication',value,data)
            self.assertEqual(result['edges'][0]['reason'],'r'*length)
            self.assertEqual(result['edges'][0]['evidence_quote'],data['people'][0]['claims'][0]['evidence'])
            self.assertEqual(validate_resolved('adjudication',result,data),result)
        for field,length in [('reason',701),('gap',301)]:
            changed=copy.deepcopy(value);changed['edges'][0][field]='x'*length
            with self.assertRaises(ValueError):resolve('adjudication',changed,data)

    def test_wrong_claim_owner_revision_retired_cache_and_fabricated_reference_rejected(self):
        data,value=self.fixture()
        for field,replacement in [('person_id','not-this-person'),('claim_id','not-this-claim'),('claim_revision',999)]:
            changed=copy.deepcopy(value);changed['edges'][0][field]=replacement
            with self.assertRaises(ValueError):resolve('adjudication',changed,data)
        result=resolve('adjudication',value,data);result['edges'][0]['evidence_quote']='invented'
        with self.assertRaises(ValueError):validate_resolved('adjudication',result,data)
        role=copy.deepcopy(data['interpretation']);role['roles'][0].pop('quote');role['roles'][0].pop('source_field')
        role['roles'][0]['source_ref']='src-'+'0'*64
        with self.assertRaises(ValueError):resolve('decomposition',role,data)

    def test_verifier_still_cannot_upgrade_add_edges_or_manufacture_a_supported_person(self):
        data,value=self.fixture();assessed=resolve('adjudication',value,data)
        verify=verification_inputs(data,assessed)
        self.assertNotIn('reason',verify['proposed_edges'][0])
        result=resolve('verification',value|{'state':'coherent'},verify)
        self.assertEqual(result['edges'],assessed['edges'])
        changed=copy.deepcopy(value)|{'state':'coherent'};changed['edges'][0]['coverage']='direct';changed['people'][0]['outcome']='supported'
        with self.assertRaises(ValueError):resolve('verification',changed,verify)
        with self.assertRaises(ValueError):resolve('verification',value|{'state':'unsuitable'},verify)

    def test_every_stage_uses_actual_structured_api_and_rejects_incomplete_text(self):
        data,_=self.fixture()
        for stage in OUTPUT_LIMITS:
            c=contract(stage);body=request_body(c['route'],c['settings'],c['prompt'],projected_inputs(data),c['schema'])
            self.assertEqual(body['output_config']['format']['type'],'json_schema')
            self.assertEqual(body['max_tokens'],OUTPUT_LIMITS[stage])
            def supported(node):
                if isinstance(node,dict):
                    self.assertNotIn('maxLength',node);self.assertNotIn('maxItems',node)
                    for child in node.values():supported(child)
                elif isinstance(node,list):
                    for child in node:supported(child)
            supported(body['output_config'])
        for stop in ('max_tokens','pause_turn','refusal'):
            with self.assertRaises((ValueError,Refusal)):response_value('anthropic',{'stop_reason':stop,'content':[{'type':'text','text':'{}'}]})
        self.assertEqual(response_value('anthropic',{'stop_reason':'end_turn','content':[{'type':'thinking','thinking':'not JSON'}, {'type':'text','text':'{}'}]}),{})


if __name__=='__main__':unittest.main()
