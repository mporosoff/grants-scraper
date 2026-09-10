import unittest
from tools.team_recommender_evaluation import deduplicate, balanced_orientation, request_contract, agreement
from tools.offline_spend import Deferred

class EvaluationContract(unittest.TestCase):
    def item(self):return {'scope_id':'359696','task_type':'individual','source_evidence':'Original call', 'profile_evidence':'Original public passage','algorithm':'B','rank':1}
    def test_exact_shared_judgments_keep_occurrences_and_hide_arms(self):
        item=self.item(); rows, occurrences=deduplicate([item,{**item,'algorithm':'A','rank':2}]);self.assertEqual(len(rows),1);self.assertEqual(len(occurrences),2);self.assertNotIn('algorithm',rows[0])
    def test_holdout_and_nonmanifest_scopes_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'outside_development'):deduplicate([{**self.item(),'scope_id':'not-development'}])
    def test_semantic_items_cannot_see_explanations(self):
        with self.assertRaisesRegex(ValueError,'persuasive'):deduplicate([{**self.item(),'explanation':'Very qualified'}])
    def test_order_balance_is_reproducible(self):
        rows=[{'item_id':str(i)} for i in range(11)]; first=balanced_orientation(rows);self.assertEqual(sum(x['swap'] for x in first),5);self.assertEqual(first,balanced_orientation(rows[::-1]))
    def test_input_bound_rejects_without_cropping_or_dispatch(self):
        rows,_=deduplicate([self.item()]);schema={'type':'object','properties':{},'required':[],'additionalProperties':False}
        result=request_contract(rows,'Fixed rubric',schema);self.assertEqual(result['provider_calls'],0);self.assertLessEqual(result['reserve_microusd'],15360)
        rows[0]['source_evidence']='x'*20000
        with self.assertRaises(Deferred):request_contract(rows,'Fixed rubric',schema)
    def test_no_labels_cannot_be_called_agreement(self):
        self.assertIsNone(agreement({}, {})['exact_agreement'])
        self.assertFalse(agreement({}, {})['calibrated_human_preference'])
