"""Named output-capacity recovery fixtures. No scientific or provider evidence."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch
from tests import test_contextual_phase2 as cold_fixture
from tests import test_contextual_phase2_check as check_fixture
from tools import contextual_team_phase2 as p2
from tools import contextual_team_phase2_capacity as capacity
from tools import contextual_team_phase2_check as check
from tools.contextual_team_executor import resolve_job, RecoveryRequired
from tools.contextual_team_option1 import configuration_for_job
from tools.offline_spend import atomic_json, identity, Deferred, ConfigurationFailure


class Capacity(unittest.TestCase):
    def setUp(self):
        self.cold=cold_fixture.ColdDemand();self.cold.setUp();self.addCleanup(self.cold.doCleanups)
        self.scope=self.cold.config['scopes'][1]
        runner=self.cold.runner();ledger=runner.ledger.read()
        for i,op in enumerate([o for o in p2.base_plan()['operations'] if o['scope_id']==p2.base_plan()['first_scope_id']]):
            ledger['requests'].append({'id':f'{9000+i:032x}','key':f'{9000+i:064x}',
                'provider':op['provider'],'model':'fixture','stage':2,'attempt':1,'status':'valid','charged_microusd':0,
                'phase2_lock':p2.RELEASE,'phase2_operation':op['id'],'purpose':op['purpose']})
        atomic_json(runner.ledger.path,ledger)
        original=self.cold.provider
        def fail_assessment(url,**kw):
            body=kw['json']
            if 'output_config' in body and 'people' in body['output_config']['format']['schema']['properties']:
                self.cold.calls.append(body)
                return cold_fixture.Response({'model':'claude-sonnet-5','stop_reason':'max_tokens',
                    'usage':{'input_tokens':10,'output_tokens':16000},'content':[{'type':'text','text':'{'}]})
            return original(url,**kw)
        runner.post=fail_assessment
        with self.assertRaises(ValueError):runner.run_scope(self.scope)
        ledger=runner.ledger.read();self.assertEqual(len(ledger['requests']),671)
        row=ledger['requests'][-1];receipt=self.cold.state/'receipts'/(row['id']+'.json')
        self.a=capacity.amendment()|{'prior_rows_sha256':identity(ledger['requests']),
            'repair_of':row['id'],'repair_original_body_sha256':row['body_sha256'],
            'repair_receipt_sha256':hashlib.sha256(receipt.read_bytes()).hexdigest()}
        base=p2.plan();self.original_plan=base
        amend=patch.object(capacity,'amendment',return_value=self.a);amend.start();self.addCleanup(amend.stop)
        override=patch.object(p2,'plan',side_effect=lambda:capacity.apply(base));override.start();self.addCleanup(override.stop)
        self.cold.config['phase2_repair']=True
        self.row=row;self.before=len(self.cold.calls)

    def test_one_linked_repair_reuses_interpretation_and_query_exactly(self):
        result=self.cold.runner().run_scope(self.scope)
        self.assertEqual(len(self.cold.calls)-self.before,2)
        self.assertEqual(self.cold.calls[-2]['max_tokens'],24000)
        unchanged=copy.deepcopy(self.cold.calls[-2]);unchanged['max_tokens']=16000
        self.assertEqual(identity(unchanged),self.row['body_sha256'])
        rows=self.cold.runner().ledger.read()['requests']
        self.assertEqual(rows[670],self.row)
        self.assertEqual(rows[671]['repair_of'],self.row['id'])
        self.assertEqual(result['execution_capacity']['repair_of'],self.row['id'])
        before=len(self.cold.calls)
        for _ in range(3):self.cold.runner().run_scope(self.scope)
        self.assertEqual(len(self.cold.calls),before)

    def test_receipt_or_scientific_changes_cannot_authorize_repair(self):
        path=self.cold.state/'receipts'/(self.row['id']+'.json');raw=path.read_bytes()
        for wrong in (b'{}',raw+b' '):
            path.write_bytes(wrong)
            with self.assertRaises(RecoveryRequired):self.cold.runner().run_scope(self.scope)
        path.write_bytes(raw)
        self.a['repair_original_body_sha256']='f'*64
        with self.assertRaises(RecoveryRequired):self.cold.runner().run_scope(self.scope)
        self.assertEqual(len(self.cold.calls),self.before)

    def test_unknown_valid_or_changed_history_is_not_completed_failure(self):
        runner=self.cold.runner();original=runner.ledger.read()
        for status in ('valid','reserved_unknown'):
            state=copy.deepcopy(original);state['requests'][-1]['status']=status
            self.a['prior_rows_sha256']=identity(state['requests'])
            with self.assertRaises(RecoveryRequired):capacity.check_original(state,self.a)
        self.a['prior_rows_sha256']=identity(original['requests'])
        changed=copy.deepcopy(original);changed['requests'][0]['charged_microusd']+=1
        with self.assertRaises(RecoveryRequired):p2.ensure_remaining_plan_fits(changed)

    def test_crash_boundaries_never_repeat_corrective_provider_dispatch(self):
        # Each boundary gets its own immutable pre-repair state copy.
        import shutil
        boundaries=('after_reserve','after_reservation_checkpoint','after_dispatch','before_reconcile',
                    'after_reconcile','after_cache','after_receipt')
        for boundary in boundaries:
            state=self.cold.state.parent/boundary;shutil.copytree(self.cold.state,state)
            class Crash(BaseException):pass
            def crash(name):
                if name==boundary:raise Crash()
            runner=p2.Phase2Runner(state,self.cold.config,post=self.cold.provider,counter_post=self.cold.count,crash=crash)
            before=len(self.cold.calls)
            with self.assertRaises(Crash):runner.run_scope(self.scope)
            for _ in range(3):
                resumed=p2.Phase2Runner(state,self.cold.config,post=self.cold.provider,counter_post=self.cold.count)
                try:resumed.run_scope(self.scope)
                except RecoveryRequired:pass
            corrective=[b for b in self.cold.calls[before:] if b.get('max_tokens')==24000 and
                        'proposed_edges' not in json.loads(b['messages'][0]['content'])]
            self.assertLessEqual(len(corrective),1,boundary)

    def test_remaining_inventory_reserves_phase_ceiling_and_request_slots(self):
        state=self.cold.runner().ledger.read();p2.ensure_remaining_plan_fits(state)
        ops=p2.plan()['operations'];self.assertEqual(len(ops),18)
        self.assertEqual(sum(o['stage']=='repair-assess' for o in ops),1)
        self.assertEqual(sum(o['stage']=='check-group-pair' for o in ops),1)
        self.assertEqual(sum(o['stage']=='check-explanation' for o in ops),3)
        for _ in range(10):state['requests'].append({'id':'extra','status':'valid','charged_microusd':0})
        with self.assertRaises(Deferred):p2.ensure_remaining_plan_fits(state)


class Pairing(unittest.TestCase):
    def test_complete_independent_contexts_and_owned_questions_without_rationales(self):
        cold=cold_fixture.ColdDemand();cold.setUp();self.addCleanup(cold.doCleanups)
        graph=cold.runner().run_scope(cold.config['scopes'][0]);selection=check.select(graph)
        with patch.object(p2,'plan',side_effect=lambda:capacity.apply(p2.base_plan())):
            cases=[(scope,graph,selection) for scope in cold.config['scopes'][1:]]
            op,body,validate=check.paired_packet(cases,cold.config)
            data=json.loads(body['messages'][0]['content']);self.assertEqual(len(data['source_contexts']),2)
            self.assertEqual(len(data['items']),6)
            self.assertTrue(all('assertion' not in q for q in data['items']))
            for context,(scope,_,_) in zip(data['source_contexts'],cases):
                self.assertEqual(context['scope'],check.scope_inputs(scope)['scope'])
                for person in context['profile_documents']:
                    self.assertEqual(person,next(p for p in cold.config['people'] if p['person_id']==person['person_id']))
            raw=check_fixture.OutputCheck.response(self,body);accepted=validate(raw,False)
            self.assertEqual(validate(accepted,True),accepted)
            value=json.loads(raw['content'][0]['text']);key=next(iter(value['verdicts']))
            value['verdicts'][key]['evidence_ref']='351715:scope.science'
            raw['content'][0]['text']=json.dumps(value)
            with self.assertRaises(ValueError):validate(raw,False)
            with self.assertRaises(ConfigurationFailure):check.paired_packet(list(reversed(cases)),cold.config)

    def test_only_exact_named_job_can_select_repair_configuration(self):
        a=capacity.amendment();job={'release_id':a['base_release_id'],'scope_id':a['repair_scope_id'],
                                  'person_id':'','job_id':a['repair_job_id']}
        self.assertTrue(configuration_for_job(job)['phase2_repair'])
        self.assertEqual(resolve_job(configuration_for_job(job),job)['id'],a['repair_scope_id'])
        for changed in (job|{'scope_id':'351715'},job|{'job_id':'f'*64}):
            with self.assertRaises(ValueError):resolve_job(configuration_for_job(changed),changed)


if __name__=='__main__':unittest.main()
