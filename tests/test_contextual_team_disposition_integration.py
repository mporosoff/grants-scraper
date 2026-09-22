"""Closed scope stops before cached science, body construction or provider use."""
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml

import test_contextual_team_iteration2 as lifecycle
from test_contextual_team_checkpoint_disposition import fixture_plan
from tools import contextual_team_checkpoint_disposition as disposition
from tools import contextual_team_iteration2 as workflow
from tools import contextual_team_iteration2_check as check
from tools import contextual_team_iteration2_policy as policy
from tools.offline_spend import atomic_json, identity, Deferred


class ProtectedRecoveryEntry(unittest.TestCase):
    def test_real_cli_routes_only_the_declared_recovery_key(self):
        from tools import contextual_team_check as entry
        from tools import contextual_team_checkpoint_recovery as recovery
        with patch.dict(os.environ, {'CONTEXTUAL_CHECK': json.dumps(recovery.SELECTOR)}), \
             patch('sys.argv', ['check', 'execute', '--state', 'state', '--reservation', 'reservation', '--result', 'result']), \
             patch.object(entry.existing, 'trusted_environment') as trusted, \
             patch.object(recovery, 'run') as run:
            entry.main()
        trusted.assert_called_once()
        self.assertEqual(run.call_args.args[0].action, 'execute')
        self.assertEqual(run.call_args.args[0].state, Path('state'))

    def test_execute_can_authenticate_owner_without_provider_credentials(self):
        root = Path(__file__).resolve().parents[1]
        flow = yaml.safe_load((root/'.github/workflows/team-recommender-offline.yml').read_bytes())
        self.assertEqual(flow['permissions'], {'contents': 'read', 'actions': 'read'})
        steps = flow['jobs']['prepare-evaluate']['steps']
        step = next(s for s in steps if s.get('name') == 'Execute the authenticated zero-provider check')
        self.assertEqual(step['env']['GH_TOKEN'], '${{ github.token }}')
        self.assertEqual(set(step['env']), {'GH_TOKEN', 'CONTEXTUAL_CHECK'})
        self.assertEqual(step['if'], "steps.contextual_check_prepare.outcome == 'success' && steps.contextual_check_prepare.outputs.text_provider == 'none'")
        paid = next(s for s in steps if s.get('name') == 'Execute the single bounded independent check')
        self.assertNotIn('GH_TOKEN', paid['env'])
        self.assertEqual(paid['if'], "steps.contextual_check_prepare.outcome == 'success' && steps.contextual_check_prepare.outputs.text_provider != 'none'")
        self.assertEqual(paid['run'], step['run'])


class ClosedScopeIntegration(unittest.TestCase):
    def setUp(self):
        self.f = lifecycle.Iteration2('runTest'); self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.p['scope_ids'][2] = '341997'
        self.f.p['release_id'] = identity({k:v for k,v in self.f.p.items() if k != 'release_id'})
        self.f.config['snapshot_id'] = self.f.p['release_id']
        self.scope = copy.deepcopy(self.f.scope) | {'id': '341997'}
        self.f.config['scopes'].append(self.scope)
        self.ledger = self.f.install()
        state = self.ledger.read()
        counts = json.loads((self.f.state/'checkpoint.json').read_bytes())['phase2_token_preflight']['rows']
        self.plan = fixture_plan(state, counts)
        changed = patch.object(disposition, 'plan', return_value=self.plan)
        changed.start(); self.addCleanup(changed.stop)
        state['events'].append(disposition.event())
        atomic_json(self.f.state/'ledger.json', state)
        self.before = (self.f.state/'ledger.json').read_bytes()
        # A late or corrupt Math result must not even become a source of science.
        path = workflow.result_path(self.f.state, self.scope['id'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('untrusted late result must not be read', encoding='utf-8')

    def tearDown(self):
        self.assertEqual((self.f.state/'ledger.json').read_bytes(), self.before)
        self.assertEqual(self.f.calls, [])
        self.assertEqual(self.f.count_calls, 0)

    def test_generation_stops_before_source_or_cached_result(self):
        with patch.object(workflow, 'scope_inputs', side_effect=AssertionError('closed source consumed')):
            with self.assertRaisesRegex(Deferred, 'scope_permanently_closed_no_replay'):
                self.f.runner().run_scope(self.scope)

    def test_direct_request_stops_before_cache_or_provider_validation(self):
        with self.assertRaisesRegex(Deferred, 'scope_permanently_closed_no_replay'):
            self.f.runner().request(policy.operation('341997','interpret'), [], {},
                lambda *_: self.fail('closed cached response validated'))

    def test_independent_check_cannot_read_late_scope_result(self):
        with self.assertRaisesRegex(Deferred, 'scope_permanently_closed_no_replay'):
            check.actual_result(self.f.state, self.f.config, '341997')

    def test_explicit_and_default_check_versions_cannot_reopen_closed_scope(self):
        with patch.object(workflow, 'configuration', return_value=self.f.config):
            for version in (None, check.VERSION, check.LEGACY_VERSION):
                with self.subTest(version=version):
                    with self.assertRaisesRegex(Deferred, 'scope_permanently_closed_no_replay'):
                        check.prepared(self.f.state, {'iteration2_check':'341997'}, version=version)


if __name__ == '__main__':
    unittest.main()
