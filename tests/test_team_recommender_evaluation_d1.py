import unittest
from tools.team_recommender_evaluation_d1 import item_identity,map_verdicts,winner,order_audit


class D1Mapping(unittest.TestCase):
    def test_identity_includes_task_aspect_and_original_fields(self):
        item={'task_type':'call_person','profile_evidence':[{'claim_id':'c1','revision':1,'text':'retained'}],'candidates':['p1']}
        a=item_identity('dev',{'original':'call'},[],item)
        self.assertEqual(a,item_identity('dev',{'original':'call'},[],item))
        self.assertNotEqual(a,item_identity('dev',{'original':'changed'},[],item))
        self.assertNotEqual(a,item_identity('dev',{'original':'call'},[],dict(item,task_type='aspect_person',target_aspect='a1')))
        for field in ('algorithm','score','prior_verdict','explanation'):
            with self.assertRaises(ValueError):item_identity('dev',{},[],dict(item,**{field:'hidden'}))

    def test_exact_dedup_preserves_occurrences_without_independence_claim(self):
        unique={};occ=[]
        item={'task_type':'call_person','profile_evidence':[{'id':'p'}],'candidates':['p']}
        for arm in ('A','B','B-alternative'):
            k=item_identity('dev',{},[],item);unique.setdefault(k,item);occ.append((arm,k))
        self.assertEqual(len(unique),1);self.assertEqual(len(occ),3)

    def test_verdict_order_missing_duplicate_and_unknown(self):
        aliases={'i01':'first','i02':'second'}
        good={'verdicts':[{'item_id':'i02','verdict':'unrelated'},{'item_id':'i01','verdict':'plausible'}]}
        self.assertEqual(map_verdicts(good,aliases)['first']['verdict'],'plausible')
        for rows in [good['verdicts'][:1],[good['verdicts'][0]]*2,[{'item_id':'i03'},{'item_id':'i01'}]]:
            with self.assertRaises(ValueError):map_verdicts({'verdicts':rows},aliases)

    def test_balanced_order_inverse_mapping_ties_and_conflicts(self):
        left=['x','y'];right=['z','w']
        for swap in (False,True):
            c={'A':right if swap else left,'B':left if swap else right}
            self.assertEqual(winner('B' if swap else 'A',c,left),'left')
            self.assertEqual(winner('tie',c,left),'tie')
        self.assertEqual(order_audit('A','B'),'consistent')
        self.assertEqual(order_audit('A','A'),'conflict-unresolved')
        self.assertEqual(order_audit('tie','tie'),'consistent')
        self.assertEqual(order_audit('A',None),'missing')
        self.assertEqual(order_audit('unresolved','A'),'unresolved')
