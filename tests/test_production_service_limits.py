"""Run/task reservations and independent service gates without provider calls."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import offline_ai as ai, offline_spend as spend, team_provider, team_maintenance
from tests.test_sonnet_structured_transport import sonnet_response


class ProductionLimits(unittest.TestCase):
    def test_transient_exhaustion_stops_only_this_invocation_and_schema_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = spend.Ledger(Path(tmp) / 'ledger.json', 'run', 2)
            for index in range(3):
                token = ledger.reserve('anthropic', 'sonnet', 'verification', str(index), 1, index + 1)
                ledger.complete(token, status='RequestException', diagnostics={'category': 'transient_transport'})
            with self.assertRaisesRegex(spend.Deferred, 'transient_run_stop'):
                spend.check_run_transport(ledger, 0)
            self.assertEqual(ledger.read()['blocked_providers'], {})
            spend.check_run_transport(ledger, 3)  # A later invocation can retry.
            ledger.complete(token, status='SchemaFailure', diagnostics={'category': 'schema_failure'})
            spend.check_run_transport(ledger, 0)

    def test_linked_checkpoint_preserves_newer_task_history_and_one_grant(self):
        from tools import generation_spend_checkpoint as checkpoint, offline_ai_checkpoint as task_checkpoint
        from tools.evaluate_offline_ai import TASK
        authorization = json.loads((spend.ROOT / 'config/sonnet_production_qualification.json').read_bytes())['authorization']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = spend.Ledger(root / 'authoritative.json', TASK, 15)
            first = task.reserve('anthropic', 'sonnet', 'verification', 'earlier', 100, 1)
            task.complete(first, status='valid')
            task = spend.authorize_allowance(task.path, TASK, authorization)
            task.reserve('anthropic', 'sonnet', 'verification', 'in-flight', 100, 1)
            retained = task.read()
            def restore(repo, destination, reservation):
                spend.atomic_json(destination / 'ledger.json', retained)
                spend.atomic_json(reservation, {'task': TASK})
            def api(repo, path):
                return json.dumps({'artifacts': []} if 'artifacts?' in path else {
                    'path': task_checkpoint.PILOT_WORKFLOW,
                    'head_branch': 'main', 'event': 'workflow_dispatch'}).encode()
            settings = spend.config() | {'generation_provider_pauses': {}}
            destination = root / 'production'
            with patch.object(checkpoint, 'api', side_effect=api), patch.object(task_checkpoint, 'prepare', side_effect=restore), \
                    patch.object(checkpoint, 'config', return_value=settings), patch.object(spend, 'config', return_value=settings):
                for _ in range(2):
                    checkpoint.prepare('owner/repo', '123', '1', destination, root / 'reservation.json', 'pilot', qualification_pilot=True)
                    linked = spend.production_ledger(destination, 'pilot')
                    self.assertEqual(linked.task.read(), retained)
                    self.assertEqual(len([e for e in linked.task.read()['events'] if e['kind'] == 'task_allowance']), 1)
                (destination / 'task/ledger.json').unlink()
                with self.assertRaisesRegex(spend.ConfigurationFailure, 'task_history_required'):
                    spend.production_ledger(destination, 'pilot')

    def test_both_limits_apply_before_dispatch_and_actual_usage_is_linked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = spend.Ledger(root / 'local.json', 'production', 2)
            task = spend.Ledger(root / 'task.json', 'task', .01, 1)
            linked = spend.LinkedLedger(local, task)
            token = linked.reserve('anthropic', 'claude-sonnet-5', 'verification', 'exact', 1000, 1)
            row = local.read()['requests'][0]
            self.assertEqual(task.read()['requests'][0]['id'], row['task_request_id'])
            self.assertEqual(task.read()['requests'][0]['production_request_id'], token)
            self.assertEqual(sum(row['charged_microusd'] for row in task.read()['requests']), 1000)
            linked.complete(token, charged_microusd=600, status='valid')
            self.assertEqual(task.read()['requests'][0]['charged_microusd'], 600)
            self.assertEqual(local.read()['requests'][0]['charged_microusd'], 600)
            with self.assertRaises(spend.Deferred):
                linked.reserve('anthropic', 'claude-sonnet-5', 'verification', 'next', 1000, 1)
            self.assertEqual(len(task.read()['requests']), 1)
            self.assertEqual(local.read()['requests'][-1]['status'], 'not_dispatched_task_limit')
            self.assertEqual(local.read()['requests'][-1]['charged_microusd'], 0)
            task.block('anthropic', 'new_account_denial')
            self.assertEqual(linked.read()['blocked_providers']['anthropic'], 'new_account_denial')
            self.assertEqual(linked.summary()['task_accounting']['requests'], 1)
            # A production cap also prevents reservation against the task.
            tiny = spend.LinkedLedger(spend.Ledger(root / 'tiny.json', 'tiny', .0001), task)
            before = task.read()
            with self.assertRaises(spend.Deferred):
                tiny.reserve('anthropic', 'claude-sonnet-5', 'verification', 'no', 1000, 1)
            self.assertEqual(task.read(), before)

    def test_interrupted_correction_reserves_once_in_each_ledger_on_resume(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'):
            root = Path(tmp)
            local = spend.Ledger(root / 'local.json', 'production', 2)
            task = spend.Ledger(root / 'task.json', 'task', 10, 200)
            stage = team_provider.stage_contract('verification')
            def invoke():
                client = ai.Client(spend.LinkedLedger(local, task), root / 'cache')
                return client.json(stage['route'], 'verification', stage['prompt'], {'scope': 'Synthetic'},
                    stage['schema'], lambda value: value, stage_config=stage['settings'])
            invalid = {'suitable_for_team': True, 'edges': [{}]}
            valid = {'suitable_for_team': True, 'edges': []}
            with patch('requests.post', side_effect=[sonnet_response(invalid), sonnet_response(valid)]) as post:
                with patch.object(ai.time, 'sleep', side_effect=KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        invoke()
                prior_local, prior_task = copy.deepcopy(local.read()['requests'][0]), copy.deepcopy(task.read()['requests'][0])
                self.assertEqual(invoke(), valid)
                self.assertEqual(post.call_count, 2)
                self.assertIn('Format diagnostic:', post.call_args_list[1].kwargs['json']['system'])
                self.assertEqual(local.read()['requests'][0], prior_local)
                self.assertEqual(task.read()['requests'][0], prior_task)
                for ledger in (local, task):
                    self.assertEqual([row['attempt'] for row in ledger.read()['requests']], [1, 2])
                    self.assertEqual([row['status'] for row in ledger.read()['requests']], ['SchemaFailure', 'valid'])
                self.assertEqual(invoke(), valid)
                self.assertEqual(post.call_count, 2)

    def test_quality_stops_are_independent_and_account_denials_remain_global(self):
        settings = spend.config()
        settings['production_services'] = {
            'teams': {'enabled': True, 'request_contract': spend.identity(team_provider.contract()),
                      'scientific_contract': team_maintenance.science_contract()},
            'cov4': {'enabled': False}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(spend, 'config', return_value=settings), \
                patch('requests.post', side_effect=AssertionError('No provider calls')):
            ledger = spend.Ledger(Path(tmp) / 'ledger.json', 'synthetic', 2)
            spend.require_production_service('teams', ledger)
            with self.assertRaisesRegex(spend.ConfigurationFailure, 'cov4_quality_gate_pending'):
                spend.require_production_service('cov4', ledger)
            self.assertEqual(ledger.read()['blocked_providers'], {})
            spend.require_production_service('teams', ledger)
            ledger.block('anthropic', 'new_account_denial')
            with self.assertRaisesRegex(spend.ConfigurationFailure, 'new_account_denial'):
                spend.require_production_service('teams', ledger)
            changed = copy.deepcopy(settings)
            changed['production_services']['teams']['request_contract'] = 'unqualified'
            with patch.object(spend, 'config', return_value=changed):
                with self.assertRaisesRegex(spend.ConfigurationFailure, 'qualified_contract_changed'):
                    spend.require_production_service('teams', ledger)

    def test_task_link_is_required_for_declared_pilot_without_an_extra_grant(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, QUALIFICATION_PILOT='true'):
            state = Path(tmp) / 'production'
            with self.assertRaisesRegex(spend.ConfigurationFailure, 'task_checkpoint_required'):
                spend.production_ledger(state, 'pilot')
            self.assertEqual(json.loads((state / 'ledger.json').read_bytes())['requests'], [])


if __name__ == '__main__':
    unittest.main()
