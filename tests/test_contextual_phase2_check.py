"""Complete-response fixtures for the once-only Phase 2 output checks."""
import copy
import json
import unittest
from tests import test_contextual_phase2 as cold
from tools import contextual_team_phase2_check as check
from tools.offline_spend import identity, ConfigurationFailure


class OutputCheck(unittest.TestCase):
    def setUp(self):
        self.cold=cold.ColdDemand();self.cold.setUp();self.addCleanup(self.cold.doCleanups)
        self.scope=self.cold.config['scopes'][0]
        self.graph=self.cold.runner().run_scope(self.scope)

    def response(self,body):
        fields=body['output_config']['format']['schema']['properties']['verdicts']['properties']
        value={'verdicts':{k:{'verdict':v['properties']['verdict']['enum'][0],
            'evidence_ref':v['properties']['evidence_ref']['enum'][0],
            'reason':'Fixture only — complete Unicode reasoning. '*20} for k,v in fields.items()}}
        return {'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(value)}]}

    def test_exact_preview_composer_and_complete_owned_answers(self):
        requested={'phase2_output_check':self.scope['id'],'release_id':check.RELEASE,'result_id':identity(self.graph)}
        config,scope,selection,packets=check.prepared(self.cold.state,requested)
        self.assertEqual(len(selection['groups']),1);self.assertEqual(len(selection['groups'][0]),2)
        self.assertEqual(len(packets),2)
        for op,body,validator in packets:
            raw=self.response(body);accepted=validator(raw,False)
            self.assertEqual(validator(accepted,True),accepted)
            self.assertGreater(len(accepted['verdicts'][0]['reason']),60)
            data=json.loads(body['messages'][0]['content'])
            self.assertEqual(data['scope'],check.scope_inputs(scope)['scope'])
            for person in data['profile_documents']:
                self.assertEqual(person,next(p for p in config['people'] if p['person_id']==person['person_id']))
            if op['stage']=='check-group':
                self.assertFalse(any('assertion' in q for q in data['items']))
                self.assertEqual(len(data['items']),3)
            value=json.loads(raw['content'][0]['text']);keys=list(value['verdicts'])
            del value['verdicts'][keys[0]];raw['content'][0]['text']=json.dumps(value)
            with self.assertRaises(ValueError):validator(raw,False)
            raw=self.response(body);raw['stop_reason']='max_tokens'
            with self.assertRaises(ValueError):validator(raw,False)
            raw=self.response(body);value=json.loads(raw['content'][0]['text'])
            value['verdicts'][keys[0]]['evidence_ref']='scope.science.title'
            raw['content'][0]['text']=json.dumps(value)
            with self.assertRaises(ValueError):validator(raw,False)

    def test_question_owner_enums_and_person_dedup_across_options(self):
        # Selection fixture tests projection only, never scientific acceptance.
        people=self.cold.config['people'];ids=[p['person_id'] for p in people[:3]]
        selection={'groups':[ids[:2],ids[1:]],'primary_view':[]}
        op,body,validator=check.packet(self.scope,self.graph,selection,'group',self.cold.config)
        data=json.loads(body['messages'][0]['content']);self.assertEqual(len(data['items']),5)
        self.assertEqual(len(data['profile_documents']),3)
        fields=body['output_config']['format']['schema']['properties']['verdicts']['properties']
        refs=fields['person-1']['properties']['evidence_ref']['enum']
        self.assertNotIn(people[1]['claims'][0]['claim_id'],refs)
        self.assertIn(people[0]['claims'][0]['claim_id'],refs)

    def test_bounded_negative_preserves_assessed_denominator_without_fake_group(self):
        graph=copy.deepcopy(self.graph);graph['state']='no_supported_group_in_assessed_set';graph['edges']=[]
        selection={'groups':[],'primary_view':[]}
        op,body,validator=check.packet(self.scope,graph,selection,'group',self.cold.config)
        data=json.loads(body['messages'][0]['content'])
        self.assertEqual(len(data['profile_documents']),12);self.assertEqual(len(data['items']),1)
        self.assertEqual(data['items'][0]['task_type'],'explanation_audit')
        self.assertIsNone(check.packet(self.scope,graph,selection,'explanation',self.cold.config))
        self.assertEqual(len(validator(self.response(body),False)['verdicts']),1)

    def test_result_or_explanation_mismatch_fails_before_provider(self):
        requested={'phase2_output_check':self.scope['id'],'release_id':check.RELEASE,'result_id':'f'*64}
        with self.assertRaises(ConfigurationFailure):check.prepared(self.cold.state,requested)
        selection=check.select(self.graph);selection['primary_view'][0]['evidence']['evidence_phrase']='missing unsupported quotation'
        with self.assertRaises(ValueError):check.packet(self.scope,self.graph,selection,'explanation',self.cold.config)


if __name__=='__main__':unittest.main()
