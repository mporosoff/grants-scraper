"""Real local checkpoints/ZIPs and staged entry points; no paid or network calls."""
import copy
import io
import json
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
import warnings
import zipfile

import yaml
from tools import contextual_team_stage_retention as retention
from tools import contextual_team_executor as executor
from tools import contextual_team_workflow as callback
from tools import contextual_team_iteration3 as iteration3
from tools import contextual_team_iteration3_policy as policy
from tools import contextual_team_option1 as options
from tools import team_recommender_executor as existing
from tools.offline_spend import atomic_json, encoded, identity, ConfigurationFailure, Deferred


class StageRetention(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.state = self.root/'state'; self.state.mkdir()
        env = {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'a'*40,
            'GITHUB_REPOSITORY': existing.REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_WORKFLOW_REF': existing.REPOSITORY+'/'+existing.WORKFLOW+'@refs/heads/main',
            'GITHUB_OUTPUT': str(self.root/'outputs'), 'CONTEXTUAL_ACTION_CURRENT': 'true',
            'I3_PRIOR_ARTIFACT_ID': '17', 'GH_TOKEN': 'fixture-read-only'}
        self.bind(patch.dict(os.environ, env, clear=True))
        self.bind(patch.object(socket, 'create_connection', side_effect=AssertionError('no network')))
        self.bind(patch.object(existing, 'api', side_effect=AssertionError('explicit fixture API only')))
        self.job = {'job_id': 'b'*64, 'release_id': policy.plan()['release_id'], 'scope_id': '363268', 'person_id': ''}
        self.ledger = {'logical_id': existing.AUTHORIZATION_ID, 'requests': [], 'events': []}
        atomic_json(self.state/'ledger.json', self.ledger)
        atomic_json(self.state/'cache'/'retained-science.json', {'fixture': 'all original bytes remain'})
        atomic_json(self.root/'job.json', self.job)
        existing.checkpoint(self.state)

    def bind(self, patcher):
        value = patcher.start(); self.addCleanup(patcher.stop); return value

    def files(self):
        return {p.relative_to(self.state).as_posix(): p.read_bytes() for p in self.state.rglob('*.json')}

    def progress(self, stage):
        return {'state': 'stage_complete', 'scope_id': self.job['scope_id'], 'stage': stage}

    def archive(self, files=None, duplicate=False):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
            for name, raw in (self.files() if files is None else files).items(): z.writestr(name, raw)
            if duplicate:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore'); z.writestr('ledger.json', b'{}')
        return output.getvalue()

    def artifact(self, raw=None, prior='assess', mutation=None):
        raw = self.archive() if raw is None else raw
        digest = existing.sha(raw); os.environ['I3_PRIOR_ARTIFACT_DIGEST'] = digest
        metadata = {'id': 17, 'name': f'{existing.AUTHORIZATION_ID}-stage-{prior}-123-1',
            'digest': 'sha256:'+digest, 'expired': False, 'workflow_run': {'id': 123, 'head_sha': 'a'*40}}
        if mutation: mutation(metadata)
        calls = []
        def api(path):
            calls.append(path)
            if path == 'actions/artifacts/17': return encoded(metadata)
            if path == 'actions/artifacts/17/zip': return raw
            raise AssertionError('no owner fallback: '+path)
        return api, calls

    def sealed_assessment(self):
        retention.complete(self.state, self.job, 'assess', self.progress('assess'))
        api, calls = self.artifact()
        bound = retention.seal(self.state, self.job, 'verify', api)
        os.environ['I3_PRIOR_SEAL_SHA256'] = bound
        return api, calls

    def test_exact_archive_then_provider_local_barrier_preserve_every_original_byte(self):
        retention.complete(self.state, self.job, 'assess', self.progress('assess'))
        before = self.files(); api, calls = self.artifact()
        bound = retention.seal(self.state, self.job, 'verify', api)
        os.environ['I3_PRIOR_SEAL_SHA256'] = bound
        self.assertEqual(calls, ['actions/artifacts/17', 'actions/artifacts/17/zip'])
        with patch.dict(os.environ, {'GH_TOKEN': '', 'ANTHROPIC_API_KEY': 'fixture-only'}):
            retention.require_prior(self.state, self.job, 'verify')
        self.assertEqual(self.files(), before)
        self.assertEqual(retention.seal(self.state, self.job, 'verify', api), bound)
        self.assertEqual(self.files(), before)
        self.assertFalse(retention.seal_path(self.state, self.job, 'verify').is_relative_to(self.state))

    def test_missing_artifact_and_provider_credentials_stop_before_any_api(self):
        retention.complete(self.state, self.job, 'assess', self.progress('assess'))
        for env in ({'I3_PRIOR_ARTIFACT_ID': ''}, {'I3_PRIOR_ARTIFACT_ID': 'true'},
                    {'I3_PRIOR_ARTIFACT_DIGEST': 'not-a-sha'}, {'OPENAI_API_KEY': 'fixture-only'}):
            with self.subTest(env=env), patch.dict(os.environ, env):
                api = Mock(side_effect=AssertionError('must stop first'))
                with self.assertRaises(ConfigurationFailure): retention.seal(self.state, self.job, 'verify', api)
                api.assert_not_called()

    def test_metadata_wrong_run_head_expiry_name_digest_or_type_never_downloads_archive(self):
        retention.complete(self.state, self.job, 'assess', self.progress('assess'))
        changes = [lambda a: a.update(id=True), lambda a: a.update(id=18), lambda a: a.update(expired=True),
            lambda a: a.update(expired=0), lambda a: a.update(name='older-state'),
            lambda a: a.update(digest='sha256:'+'f'*64), lambda a: a['workflow_run'].update(id=True),
            lambda a: a['workflow_run'].update(id=122), lambda a: a['workflow_run'].update(head_sha='c'*40)]
        for change in changes:
            api, calls = self.artifact(mutation=change)
            with self.assertRaisesRegex(ConfigurationFailure, 'artifact_identity'): retention.seal(self.state, self.job, 'verify', api)
            self.assertEqual(calls, ['actions/artifacts/17'])

    def test_raw_digest_and_full_archive_names_bytes_checkpoint_and_duplicates_are_checked(self):
        retention.complete(self.state, self.job, 'assess', self.progress('assess'))
        before = self.files()
        fixtures = [self.archive(before | {'unapproved.json': b'{}'}),
            self.archive(before | {'../outside.json': b'{}'}),
            self.archive({k:v for k,v in before.items() if k != 'ledger.json'}),
            self.archive(before | {'ledger.json': b'{}'}),
            self.archive(before | {'checkpoint.json': b'{}'}), self.archive(duplicate=True)]
        for raw in fixtures:
            api, _ = self.artifact(raw)
            with self.assertRaises(ConfigurationFailure): retention.seal(self.state, self.job, 'verify', api)
            self.assertEqual(self.files(), before)
        api, _ = self.artifact(); os.environ['I3_PRIOR_ARTIFACT_DIGEST'] = 'f'*64
        # A valid-looking metadata digest cannot bless different actual bytes.
        def wrong_digest(path):
            value = api(path)
            if not path.endswith('/zip'):
                item = json.loads(value); item['digest'] = 'sha256:'+'f'*64; return encoded(item)
            return value
        with self.assertRaisesRegex(ConfigurationFailure, 'archive_digest'): retention.seal(self.state, self.job, 'verify', wrong_digest)
        api,_=self.artifact(b'upstream failure, not a finalized ZIP')
        with self.assertRaises(zipfile.BadZipFile):retention.seal(self.state,self.job,'verify',api)
        self.assertFalse(retention.seal_path(self.state,self.job,'verify').exists())

    def test_prior_receipt_requires_exact_complete_stage_scope_owner_and_result(self):
        retention.complete(self.state, self.job, 'assess', self.progress('assess'))
        path = retention.stage_path(self.state, self.job, 'assess'); raw = path.read_bytes()
        for key, value in [('result_state', 'failed'), ('result_state', 'unknown'), ('stage', 'verify'),
            ('scope_id', '341997'), ('attempt', True), ('run_id', '122'), ('code_sha', 'c'*40),
            ('result_sha256', 'd'*64), ('job_id', 'd'*64)]:
            row = json.loads(raw); row[key] = value; atomic_json(path, row); existing.checkpoint(self.state)
            api = Mock(side_effect=AssertionError('invalid receipt before authentication'))
            with self.assertRaisesRegex(ConfigurationFailure, 'complete_receipt'): retention.seal(self.state, self.job, 'verify', api)
            api.assert_not_called()
        path.unlink(); existing.checkpoint(self.state)
        with self.assertRaises(FileNotFoundError): retention.seal(self.state, self.job, 'verify', Mock())

    def test_local_seal_identity_and_any_changed_checkpoint_file_fail_before_provider(self):
        self.sealed_assessment(); before = self.files()
        for name, raw in [('cache/retained-science.json', b'{}'), ('extra.json', b'{}'), ('checkpoint.json', b'{}')]:
            target = self.state/name; previous = target.read_bytes() if target.exists() else None
            target.write_bytes(raw)
            with self.assertRaises(ConfigurationFailure): retention.require_prior(self.state, self.job, 'verify')
            if previous is None: target.unlink()
            else: target.write_bytes(previous)
        self.assertEqual(self.files(), before)
        atomic_json(self.state/'cache'/'retained-science.json', {'changed': True}); existing.checkpoint(self.state)
        with self.assertRaisesRegex(ConfigurationFailure, 'seal_identity'): retention.require_prior(self.state, self.job, 'verify')
        for name, raw in before.items(): (self.state/name).write_bytes(raw)
        path = retention.seal_path(self.state, self.job, 'verify'); raw = path.read_bytes()
        path.write_bytes(raw+b' ')
        with self.assertRaisesRegex(ConfigurationFailure, 'seal_changed'): retention.require_prior(self.state, self.job, 'verify')
        path.write_bytes(raw)
        with patch.dict(os.environ, {'I3_PRIOR_SEAL_SHA256': ''}):
            with self.assertRaisesRegex(ConfigurationFailure, 'authenticated_seal'): retention.require_prior(self.state, self.job, 'verify')

    def test_rebound_local_ack_cannot_change_job_run_head_stage_or_artifact_types(self):
        self.sealed_assessment();path=retention.seal_path(self.state,self.job,'verify');raw=path.read_bytes()
        for key,value in [('job_id','f'*64),('code_sha','c'*40),('attempt',True),('scope_id','341997'),
                ('run_id','124'),('stage','integrity'),('prior_stage','verify'),('artifact_name','old-owner'),
                ('checkpoint_sha256','f'*64),('artifact_id',17),('artifact_digest',17)]:
            row=json.loads(raw);row[key]=value;atomic_json(path,row)
            os.environ['I3_PRIOR_SEAL_SHA256']=existing.sha(path.read_bytes())
            with self.assertRaises(ConfigurationFailure):retention.require_prior(self.state,self.job,'verify')

    def test_completion_only_accepts_exact_progress_or_typed_terminal_and_never_replaces_first(self):
        for value in [{'state': x} for x in ('failed','recovery_required','budget_limited','action_blocked','invented')]+[
            self.progress('verify'), self.progress('assess')|{'scope_id':'341997'}, self.progress('assess')|{'extra':True}]:
            with self.assertRaises(ConfigurationFailure): retention.complete(self.state, self.job, 'assess', value)
        retention.complete(self.state, self.job, 'assess', self.progress('assess'))
        before = self.files(); retention.complete(self.state, self.job, 'assess', self.progress('assess'))
        self.assertEqual(self.files(), before)
        graph = {'graph_id':'d'*64,'version':'contextual-audited-graph-v3','state':'unsuitable','scope':{'id':self.job['scope_id']}}
        retention.complete(self.state, self.job, 'verify', graph)
        graph['state'] = 'insufficient_source'
        with self.assertRaisesRegex(ConfigurationFailure, 'first_result_conflict'): retention.complete(self.state, self.job, 'verify', graph)
        with self.assertRaisesRegex(ConfigurationFailure, 'complete_receipt'): retention.seal(self.state, self.job, 'integrity', Mock())

    def test_next_stage_needs_new_exact_archive_not_prior_stage_seal(self):
        self.sealed_assessment(); retention.require_prior(self.state, self.job, 'verify')
        retention.complete(self.state, self.job, 'verify', self.progress('verify'))
        with self.assertRaises(ConfigurationFailure): retention.require_prior(self.state, self.job, 'verify')
        api, _ = self.artifact(prior='verify')
        os.environ['I3_PRIOR_SEAL_SHA256'] = retention.seal(self.state, self.job, 'integrity', api)
        retention.require_prior(self.state, self.job, 'integrity')
        with self.assertRaises(ConfigurationFailure): retention.complete(self.state, self.job, 'integrity', self.progress('integrity'))

    def execute(self, stage, result=None, error=None):
        runner = Mock(); runner.ledger.read.return_value = self.ledger; runner.timings=[]
        runner.failure_state.return_value = 'failed'; runner.run_stage.side_effect = error
        runner.run_stage.return_value = self.progress(stage) if result is None else result
        argv = ['executor','execute','--state',str(self.state),'--job',str(self.root/'job.json'),
            '--result',str(self.root/'result.json'),'--stage',stage]
        with patch.object(sys,'argv',argv), patch.object(options,'configuration_for_job',return_value={'iteration3':True}), \
             patch.object(executor,'resolve_job',return_value={'id':self.job['scope_id']}), \
             patch.object(iteration3,'Iteration3Runner',return_value=runner):
            executor.main()
        return runner, json.loads((self.root/'result.json').read_bytes()), (self.root/'outputs').read_text()

    def test_executor_never_calls_next_stage_without_local_authenticated_seal(self):
        runner, result, output = self.execute('verify')
        runner.run_stage.assert_not_called(); self.assertEqual(result['result']['state'],'failed')
        self.assertIn('stage_complete=false',output)
        self.assertFalse(retention.stage_path(self.state,self.job,'verify').exists())

    def test_executor_records_stage_completion_and_preserves_verifier_abstention(self):
        _, result, output = self.execute('assess')
        self.assertEqual(result['result'],self.progress('assess')); self.assertIn('stage_complete=true',output)
        api, _ = self.artifact(); os.environ['I3_PRIOR_SEAL_SHA256']=retention.seal(self.state,self.job,'verify',api)
        graph={'graph_id':'d'*64,'version':'contextual-audited-graph-v3','state':'unsuitable','scope':{'id':self.job['scope_id']}}
        runner, result, output = self.execute('verify',graph)
        runner.run_stage.assert_called_once(); self.assertEqual(result['result'],graph)
        self.assertTrue(output.endswith('stage_complete=true\nrequires_integrity=false\n'))

    def test_executor_failed_stage_does_not_emit_completion_marker(self):
        runner, result, output=self.execute('assess',error=ValueError('fixture strict failure'))
        runner.run_stage.assert_called_once();self.assertEqual(result['result']['state'],'failed')
        self.assertIn('stage_complete=false',output)
        self.assertFalse(retention.stage_path(self.state,self.job,'assess').exists())

    def test_interrupted_callback_uses_new_uncertainty_and_preserves_original_progress_file(self):
        stamp={k:self.job[k] for k in ('job_id','release_id')}|{'run_id':'123','code_sha':'a'*40}
        original=stamp|{'result':self.progress('assess')}
        atomic_json(self.root/'result.json',original); before=(self.root/'result.json').read_bytes()
        argv=['callback','finish','--job',str(self.root/'job.json'),'--state',str(self.state),'--result',str(self.root/'result.json')]
        for history_error,count_error,expected in [(None,None,'failed'),(Deferred('new request uncertain'),None,'recovery_required'),
                (None,Deferred('new native count uncertain'),'recovery_required')]:
            with patch.object(sys,'argv',argv), patch.object(callback,'configuration_for_job',return_value={}), \
                 patch.object(callback,'resolve_job'), patch.object(callback,'send',return_value={'accepted':True}) as send, \
                 patch.object(policy,'history',side_effect=history_error) as history, \
                 patch.object(policy,'check_counts',side_effect=count_error) as counts:
                callback.main()
            history.assert_called_once_with(self.ledger)
            if not history_error:counts.assert_called_once_with(self.state)
            self.assertEqual(send.call_args.args[1]['result']['state'],expected)
            self.assertEqual((self.root/'result.json').read_bytes(),before)


class WorkflowBarriers(unittest.TestCase):
    def test_real_workflow_credentials_conditions_and_final_callback(self):
        flow=yaml.safe_load((existing.ROOT/existing.WORKFLOW).read_bytes()); job=flow['jobs']['prepare-evaluate']
        steps={s['id']:s for s in job['steps'] if 'id' in s}
        for stage,prior in [('verify','assess'),('integrity','verify')]:
            barrier=steps['i3_'+stage+'_barrier']; paid=steps['i3_'+stage]
            self.assertIn('GH_TOKEN',barrier['env']);self.assertFalse(any(k.endswith('_API_KEY') for k in barrier['env']))
            self.assertNotIn('GH_TOKEN',paid['env']);self.assertEqual([k for k in paid['env'] if k.endswith('_API_KEY')],['ANTHROPIC_API_KEY'])
            self.assertIn(f'steps.i3_{prior}_state.outputs.artifact-id',barrier['env']['I3_PRIOR_ARTIFACT_ID'])
            self.assertIn(f'steps.i3_{prior}_state.outputs.artifact-digest',barrier['env']['I3_PRIOR_ARTIFACT_DIGEST'])
            self.assertIn(f'steps.i3_{stage}_barrier.outputs.prior_seal_sha256',paid['env']['I3_PRIOR_SEAL_SHA256'])
            self.assertEqual(paid['if'],f"steps.i3_{stage}_barrier.outcome == 'success'")
            def permits(values):
                expression=re.sub(r'steps\.[a-z0-9_]+\.(?:outputs\.[a-z0-9_]+|outcome)',lambda m:repr(values.get(m[0],'')),barrier['if'])
                return eval(expression.replace('&&',' and ').replace('||',' or '),{'__builtins__':{}},{})
            good={f'steps.i3_{prior}.outputs.stage_complete':'true',f'steps.i3_{prior}_state.outcome':'success',
                f'steps.i3_{prior}.outputs.requires_integrity':'true'}
            self.assertTrue(permits(good))
            for key in (f'steps.i3_{prior}.outputs.stage_complete',f'steps.i3_{prior}_state.outcome'):
                for failed in ('','false','failure','skipped','cancelled'):
                    self.assertFalse(permits(good|{key:failed}))
            if stage=='integrity':self.assertFalse(permits(good|{f'steps.i3_{prior}.outputs.requires_integrity':'false'}))
        finish=next(s for s in job['steps'] if 'tools.contextual_team_workflow finish' in s.get('run',''))
        self.assertEqual(finish['if'],"always() && steps.contextual_prepare.outcome == 'success' && steps.persist_state.outcome == 'success'")
        self.assertFalse(any(k.endswith('_API_KEY') for k in finish['env']))
        for stage in ('assess','verify','integrity'):
            saved=steps['i3_'+stage+'_state'];self.assertTrue(saved['if'].startswith('always()'))
            self.assertEqual(saved['with']['path'],'${{ runner.temp }}/team-experiment')
            self.assertEqual(saved['with']['if-no-files-found'],'error')


if __name__=='__main__': unittest.main()
