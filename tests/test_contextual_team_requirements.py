import copy
import unittest
from tools import contextual_team_requirements as rules
from tools.contextual_team_references import source_references
from tools.contextual_team_contract import verification_inputs
from tools.contextual_team_policy import inputs


class SelectedApproach(unittest.TestCase):
    def setUp(self):
        self.data = {'scope': {'id':'parent:child-a','parent_id':'parent',
            'science': {'title':'Laboratory research on materials and reaction mechanisms',
                'description':'Proposals must test stability and establish reaction mechanisms. '
                    'Either thermal conversion or electrochemical conversion is permitted. '
                    'Modeling can support either approach. Field deployment is optional.'},
            'conditions':{},'limitations':[]}}
        self.ref = source_references(self.data)[1]['source_ref']

    def role(self, number=1, **extra):
        return dict(id=f'role-{number}',label='Establish reaction mechanisms',
            kind='approach_necessary',applicability='applies',condition='',
            central=number==1,source_ref=self.ref,**extra)

    def value(self, roles):
        return {'state':'coherent','objective':'Study the documented reaction and materials.',
            'approach':'Investigate the thermal conversion approach in the laboratory.',
            'roles':roles,'limitations':[]}

    def resolve(self, roles):
        return rules.resolve('decomposition',self.value(roles),self.data)

    def test_genuine_conjunction_preserves_both_needs(self):
        a=self.role(); b=self.role(2); b.update(label='Test material stability',kind='sponsor_requirement')
        result=self.resolve([a,b]); self.assertEqual(len(rules.active_roles(result)),2)
        self.assertTrue(all(r['required'] for r in result['roles']))

    def test_optional_alternative_cannot_be_gap_or_admission(self):
        b=self.role(2); b.update(kind='optional_direction',label='Electrochemical alternative')
        result=self.resolve([self.role(),b]);self.assertFalse(result['roles'][1]['required'])
        data=self.data|{'interpretation':result,'people':inputs()['people'][:2]}
        self.assertEqual(list(rules.contract('adjudication',data)['schema']['properties']['edges_by_contribution']['properties']),['role-1'])
        projection=rules.projected_inputs('adjudication',data)
        self.assertEqual(len(projection['interpretation']['considered_directions']),1)
        with self.assertRaises(ValueError):rules.active_data(data|{'proposed_edges':[{'role_id':'role-2'}]})

    def test_conditional_not_applicable_and_unknown_are_not_waived(self):
        b=self.role(2);b.update(kind='sponsor_requirement',applicability='does_not_apply',condition='Only required for field deployment; this approach is laboratory research.')
        self.assertEqual(len(rules.active_roles(self.resolve([self.role(),b]))),1)
        b['applicability']='unknown';value=self.value([self.role(),b])
        with self.assertRaises(ValueError):rules.resolve('decomposition',value,self.data)
        value['limitations']=['Applicability of the field condition is unresolved.']
        result=rules.resolve('decomposition',value,self.data)
        self.assertFalse(result['roles'][1]['required'])

    def test_single_contribution_and_exact_cache_roundtrip(self):
        result=self.resolve([self.role()]);self.assertEqual(len(result['roles']),1)
        self.assertEqual(rules.validate_resolved('decomposition',result,self.data),result)
        result['roles'][0]['required']=False
        with self.assertRaises(ValueError):rules.validate_resolved('decomposition',result,self.data)

    def test_parent_child_references_are_not_interchangeable(self):
        for sid,parent in [('parent','parent'),('parent:child-b','parent'),('parent:child-a','other-parent')]:
            other=copy.deepcopy(self.data);other['scope'].update(id=sid,parent_id=parent)
            with self.assertRaises(ValueError):rules.resolve('decomposition',self.value([self.role()]),other)

    def test_required_gap_and_nonexclusive_shared_method_preserved(self):
        b=self.role(2);b['label']='Model mechanisms supporting either permitted laboratory approach'
        result=self.resolve([self.role(),b]);graph={'state':'ready','edges':[{'role_id':'role-1','coverage':'direct'}]}
        self.assertEqual(rules.graph_metadata(graph,result)['state'],'ready_with_gaps')
        graph['edges'].append({'role_id':'role-2','coverage':'method_transfer'})
        self.assertEqual(rules.graph_metadata(graph,result)['state'],'ready')

    def test_all_optional_or_inactive_central_rejected(self):
        r=self.role();r['kind']='optional_direction'
        with self.assertRaises(ValueError):self.resolve([r])
        r['central']=False
        with self.assertRaises(ValueError):self.resolve([r])

    def test_verifier_still_rejects_category_upgrade(self):
        interpretation=self.resolve([self.role()]);people=inputs()['people'][:1]
        data=self.data|{'interpretation':interpretation,'people':people}
        from tools.contextual_team_demand_contract import claim_table, edge_table
        ref=next(iter(claim_table(data)));pid=people[0]['person_id']
        wire={'people':{pid:{'outcome':'credible_transfer'}},'edges_by_contribution':{'role-1':[
            {'claim_ref':ref,'coverage':'method_transfer','central':True,'reason':'A supported transferable method in the retained evidence.','gap':'Different system.'}]}}
        value=rules.resolve('adjudication',wire,data);check=verification_inputs(data,value)
        edge=wire['edges_by_contribution']['role-1'][0];edge.pop('claim_ref');edge['edge_ref']=next(iter(edge_table(check)))
        wire['state']='coherent';edge['coverage']='direct';wire['people'][pid]['outcome']='supported'
        with self.assertRaises(ValueError):rules.resolve('verification',wire,check)


if __name__=='__main__':unittest.main()
