"""Provider-enforced question/reference grammar and irreversible fixture dispatch."""
import copy
import json
from pathlib import Path
from unittest.mock import patch
from tests import test_contextual_phase1 as previous
from tests.test_contextual_phase1 import answer, envelope
from tests.test_contextual_team_executor import Response
from tools.contextual_team_check import packet, OWNED_FORMAT, LEGACY_FORMAT, OWNED_RESPONSE_CONTRACT
from tools.contextual_team_phase1 import plan, prepared_packets
from tools.contextual_team_cost import text_reservation
from tools.offline_ai import validate_schema, SchemaFailure
from tools.offline_spend import identity, atomic_json, Deferred, ConfigurationFailure, Refusal


def wire_answer(body):
    return {'verdicts':{r['item_id']:{k:v for k,v in r.items() if k!='item_id'} for r in answer(body)['verdicts']}}


class ReferenceLifecycle(previous.CheckLifecycle):
    def setUp(self):
        super().setUp()
        self.p=plan(2)
        state=self.runner().ledger.read()
        state['requests'].append(copy.deepcopy(self.p['repair_of'])|{'provider':'anthropic','stage':2})
        self.p['starting_request_rows_sha256']=identity(state['requests'])
        atomic_json(self.state/'ledger.json',state)
        self.mock.stop()
        self.mock=patch('tools.contextual_team_phase1.plan',return_value=self.p)
        self.mock.start();self.addCleanup(self.mock.stop)
        self.locked=[]
        for op in self.p['operations']:
            body,check=packet(self.scope,self.graph,self.p['members'],op['kind'],self.config,owned_references=True)
            bound,cost=text_reservation(body)
            op.update(body_sha256=identity(body),input_token_bound=bound,maximum_microusd=cost)
            self.locked.append((op,body,check))

    def provider(self,url,**kwargs):
        # Exercise the actual converted provider schema, not just our validator.
        response=super().provider(url,**kwargs)
        if self.failure=='invalid' or (self.failure=='second_invalid' and len(self.calls)==2):return response
        value=wire_answer(kwargs['json'])
        validate_schema(value,kwargs['json']['output_config']['format']['schema'])
        return Response(envelope(value))

    def test_fixed_authority_graph_members_and_contract_are_not_caller_choices(self):
        self.assertEqual(self.p['response_contract_sha256'],identity(OWNED_RESPONSE_CONTRACT))
        self.assertEqual(self.p['starting_attempts'],660)
        self.assertEqual(self.p['maximum_new_attempts'],2)
        self.assertEqual(self.p['prior_phase1_microusd']+self.p['maximum_new_microusd'],250000)
        self.assertEqual(self.p['total_reserved_microusd'],131982)
        with self.assertRaises(ConfigurationFailure):prepared_packets(Path('absent'),[],self.p)

    def test_per_question_provider_grammar_and_full_rationale_roundtrip(self):
        for op,body,check in self.locked:
            original,_=packet(self.scope,self.graph,self.p['members'],op['kind'],self.config)
            self.assertEqual(body['messages'],original['messages'])
            self.assertEqual(body['system'],original['system'].replace(LEGACY_FORMAT,OWNED_FORMAT))
            value=wire_answer(body)
            for row in value['verdicts'].values():row['reason']='Unicode résumé: '+('Complete explanatory sentence. '*12)
            canonical=check(envelope(value),False)
            self.assertEqual(check(canonical,True),canonical)
            self.assertEqual(list(value['verdicts']),[r['item_id'] for r in canonical['verdicts']])
            self.assertEqual([r['reason'] for r in value['verdicts'].values()],[r['reason'] for r in canonical['verdicts']])
            key=next(k for k in value['verdicts'] if k.endswith('-1'))
            grammar=body['output_config']['format']['schema']
            for ref in ('scope.science.description',self.p['members'][1],self.p['members'][1]+'-c001','scope.science, '+self.p['members'][0]):
                bad=copy.deepcopy(value);bad['verdicts'][key]['evidence_ref']=ref
                with self.assertRaises(SchemaFailure):validate_schema(bad,grammar)
                with self.assertRaises(SchemaFailure) as caught:check(envelope(bad),False)
                self.assertIn(key,str(caught.exception.diagnostic))

    def test_all_reference_enums_resolve_to_only_the_question_evidence(self):
        for op,body,check in self.locked:
            data=json.loads(body['messages'][0]['content'])
            for q in data['items']:
                refs=body['output_config']['format']['schema']['properties']['verdicts']['properties'][q['item_id']]['properties']['evidence_ref']['enum']
                expected={'scope.science'}|set(q['people'])|{c['claim_id'] for p in data['profile_documents'] if p['person_id'] in q['people'] for c in p['claims']}
                self.assertEqual(set(refs),expected)
                for ref in refs:
                    value=wire_answer(body);value['verdicts'][q['item_id']]['evidence_ref']=ref
                    check(envelope(value),False)

    def test_missing_extra_wrong_question_cache_and_invalid_completion_fail_closed(self):
        for op,body,check in self.locked:
            value=wire_answer(body);key=next(iter(value['verdicts']))
            for mutation in ('missing','unknown','wrong_shape','extra'):
                bad=copy.deepcopy(value)
                if mutation=='missing':bad['verdicts'].pop(key)
                elif mutation=='unknown':bad['verdicts']['not-a-question']=bad['verdicts'].pop(key)
                elif mutation=='wrong_shape':bad['verdicts']=answer(body)['verdicts']
                else:bad['verdicts'][key]['item_id']=key
                with self.assertRaises(ValueError):check(envelope(bad),False)
            for stop,text in [('max_tokens',json.dumps(value)),('refusal','{}'),('end_turn','{"verdicts":')]:
                bad=envelope(value,stop);bad['content'][0]['text']=text
                with self.assertRaises((ValueError,Deferred,Refusal)):check(bad,False)
            canonical=check(envelope(value),False)
            canonical['verdicts'][-1]=copy.deepcopy(canonical['verdicts'][0])
            with self.assertRaises(ValueError):check(canonical,True)

    def test_previous_contract_purposes_cannot_be_replayed(self):
        from tools.contextual_team_policy import check_reservation
        for purpose in ('cb-p1-check-group','cb-p1-check-explanation'):
            with self.assertRaises(ConfigurationFailure):check_reservation(self.runner().ledger.read(),'anthropic',{'purpose':purpose},1000,100,512)
