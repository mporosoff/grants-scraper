import copy
import unittest
from tools.contextual_team_contract import contract, validate, verification_inputs
from tools.team_provider import stage_settings

class ContextualContractTests(unittest.TestCase):
    def setUp(self):
        self.scope={'science':{'title':'Material research','description':'Investigate transport through membranes using documented measurements.'}}
        self.role={'id':'role-1','label':'Investigate membrane transport','required':True,
                   'quote':'Investigate transport through membranes','source_field':'description','central':True}
        self.interpretation={'state':'coherent','objective':'Investigate membrane transport with source-supported methods.','roles':[self.role],'limitations':[]}
        self.person={'person_id':'p1','summary':'Studies transport.','claims':[{'claim_id':'p1-c1','revision':1,'evidence':'Measures diffusion through polymer membranes.'}]}
        self.inputs={'scope':self.scope,'interpretation':self.interpretation,'people':[self.person]}
        self.edge={'role_id':'role-1','person_id':'p1','claim_id':'p1-c1','claim_revision':1,'coverage':'method_transfer','central':True,
                   'evidence_quote':'Measures diffusion','reason':'Measure transport using the evidenced diffusion technique.','gap':'New application remains to be established.'}
        self.assessment={'people':[{'person_id':'p1','outcome':'credible_transfer'}],'edges':[self.edge]}

    def test_effective_legacy_model_and_output_allowances_are_preserved(self):
        for stage in ('decomposition','adjudication','verification'):
            c=contract(stage)
            self.assertEqual(c['route']['model'],'claude-sonnet-5')
            self.assertEqual(c['settings']['max_output_tokens'],stage_settings(stage)['max_output_tokens'])
            self.assertEqual(c['settings']['max_attempts'],1)
            self.assertTrue(c['settings']['durable_attempts'])

    def test_one_contribution_is_valid(self):
        self.assertEqual(validate('decomposition',self.interpretation,{'scope':self.scope}),self.interpretation)

    def test_source_span_must_exist_and_roles_cannot_be_invented_for_negative(self):
        v=copy.deepcopy(self.interpretation);v['roles'][0]['quote']='A missing source quotation';
        with self.assertRaisesRegex(ValueError,'source_span_not_exact'):validate('decomposition',v,{'scope':self.scope})
        v=copy.deepcopy(self.interpretation);v['state']='insufficient_source'
        with self.assertRaisesRegex(ValueError,'invalid_purpose_roles'):validate('decomposition',v,{'scope':self.scope})

    def test_all_assessed_people_have_an_explicit_disposition(self):
        self.assertEqual(validate('adjudication',self.assessment,self.inputs),self.assessment)
        v=copy.deepcopy(self.assessment);v['people']=[]
        with self.assertRaisesRegex(ValueError,'assessment_person_coverage'):validate('adjudication',v,self.inputs)

    def test_revision_and_exact_evidence(self):
        for field,value in [('claim_revision',2),('evidence_quote','Invented operation')]:
            v=copy.deepcopy(self.assessment);v['edges'][0][field]=value
            with self.assertRaisesRegex(ValueError,'claim_span_or_revision_mismatch'):validate('adjudication',v,self.inputs)

    def test_verifier_does_not_receive_prior_rationale(self):
        data=verification_inputs(self.inputs,self.assessment)
        self.assertNotIn('reason',data['proposed_edges'][0]);self.assertNotIn('gap',data['proposed_edges'][0])
        self.assertEqual(data['people'],self.inputs['people'])
        self.assertEqual(data['scope'],self.scope)

    def test_verifier_may_downgrade_but_not_upgrade_or_add(self):
        inputs=verification_inputs(self.inputs,self.assessment)
        v=copy.deepcopy(self.assessment)|{'state':'coherent'}
        self.assertEqual(validate('verification',v,inputs),v)
        v['edges'][0]['coverage']='direct';v['people'][0]['outcome']='supported'
        with self.assertRaisesRegex(ValueError,'verification_upgrade'):validate('verification',v,inputs)
        v['edges'][0]['coverage']='adjacent';v['people'][0]['outcome']='adjacent'
        self.assertEqual(validate('verification',v,inputs),v)

    def test_no_edges_is_not_a_source_rejection(self):
        v={'state':'coherent','people':[{'person_id':'p1','outcome':'insufficient_information'}],'edges':[]}
        self.assertEqual(validate('verification',v,verification_inputs(self.inputs,self.assessment)),v)

if __name__=='__main__':unittest.main()
