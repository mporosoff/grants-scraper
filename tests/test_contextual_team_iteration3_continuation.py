"""Finite route integration. New science here is synthetic; no provider traffic."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from tools import contextual_team_iteration3_continuation as route
from tools import contextual_team_iteration3_continuation_policy as policy
from tools import contextual_team_verifier_states as states
from tools import contextual_team_executor as base
from tools import contextual_team_ec_disposition as ec
from tools.offline_spend import ConfigurationFailure, Deferred, atomic_json, identity
import test_contextual_team_iteration2_contract as fixture


class Continuation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        blocker = patch('socket.socket.connect', side_effect=AssertionError('No network in focused tests'))
        blocker.start(); cls.addClassCleanup(blocker.stop)

    def test_exact_plan_tampering_cannot_rehash_new_authority_or_budget(self):
        original = policy.plan()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); target = root/'config/contextual_team/iteration3-continuation-v1.json'
            for key, value in [('additional_allowance', 50000000), ('max_requests', 7),
                ('input_token_ceiling', 179999), ('confirmation_outputs_sealed', False),
                ('locked_packets', {}), ('operations', {})]:
                altered = deepcopy(original); altered[key] = value; altered.pop('release_id')
                altered['release_id'] = identity(altered); atomic_json(target, altered)
                with self.subTest(key=key), patch.object(policy, 'ROOT', root), self.assertRaisesRegex(ConfigurationFailure, 'exact_plan_pin'):
                    policy.plan()

    def test_only_six_corrections_and_original_failures_have_distinct_lineage(self):
        p = policy.plan()
        self.assertEqual(len(p['operations']), 6)
        self.assertEqual(sum(x['output_tokens']*10+180000*2 for x in p['operations'].values()), 3000000)
        for name in ('assess', 'interpret', 'eclipse', 'math', 'registry', 'ai_verify_retry'):
            with self.subTest(name=name), self.assertRaises(Deferred): policy.operation(name)
        self.assertEqual(p['operations']['ai_verify']['repair_of'], '20c86e4e4caf4b5caee73802bec82906')
        self.assertEqual(p['operations']['ec_check']['repair_of'], ec.REQUEST_ID)
        self.assertNotEqual(p['operations']['ec_check']['purpose'], ec.CLOSED_PURPOSE)
        self.assertEqual(p['operations']['ai_verify']['output_tokens'], 24000)
        self.assertTrue(all(x['model'] == 'claude-sonnet-5' for x in p['operations'].values()))

    def test_production_selector_uses_coupled_helper_without_rebuying_assessment(self):
        data = fixture.selected(fixture.fixture.real_data())
        assessment = fixture.assessment(data)
        actual = {'data': data, 'assessment': assessment}
        with patch.object(route, 'retained_ai', return_value=actual), patch.object(base.Runner, 'request', side_effect=AssertionError('No inference in packet preparation')):
            contract, body, _, report, input_id = route.prepared(Path('unused'), 'ai_verify')
        expected, expected_body = states.verifier_body(data, assessment)
        self.assertEqual((contract, body), (expected, expected_body))
        self.assertEqual(input_id, identity(route.scientific.verification_inputs(data, assessment)))
        self.assertEqual(contract['version'], states.VERSION)
        self.assertNotIn('Fixture assessor rationale', body['messages'][0]['content'])
        self.assertEqual(report['accepted_assessment_request'], route.AI_ASSESSMENT_ID)

    def test_timeout_change_is_exact_replacement_only_and_has_no_retry(self):
        runner = route.ContinuationRunner.__new__(route.ContinuationRunner)
        ordinary = base.Runner.__new__(base.Runner)
        for name in policy.OPERATIONS:
            body = {'max_tokens': policy.OPERATIONS[name][2]}
            expected = 240 if name in ('ai_verify', 'ec_check') else 120
            self.assertEqual(runner.provider_read_timeout(policy.operation(name), 'anthropic', body), expected)
        self.assertEqual(ordinary.provider_read_timeout(ec.CLOSED_PURPOSE, 'anthropic', {'max_tokens': 12000}), 120)
        self.assertEqual(ordinary.provider_read_timeout('cb-p2-repair-assess', 'anthropic', {'max_tokens': 24000}), 420)

    def test_new_entry_point_rejects_broader_selectors_before_restore(self):
        args = Mock(action='prepare')
        for requested in ({'iteration3_continuation': 'registry'}, {'iteration3_continuation': 'ai_verify', 'extra': True},
            {'iteration3_continuation': 'ec_check', 'iteration3_check': '344592:ab-0025'}):
            with self.subTest(requested=requested), patch.object(route.existing, 'trusted_environment'), \
                patch.object(route.existing, 'restore', side_effect=AssertionError('No restore for invalid selector')), \
                patch.dict('os.environ', {'CONTEXTUAL_CHECK': json.dumps(requested)}, clear=True), self.assertRaises(Deferred):
                route.run(args)

    def test_historical_failed_transport_cannot_enter_new_cache(self):
        contract = {'version': 'old-failed-contract'}; body = {'model': 'claude-sonnet-5', 'max_tokens': 24000,
            'thinking': {'type': 'disabled'}, 'messages': [{'role': 'user', 'content': '{}'}]}
        with self.assertRaisesRegex(ConfigurationFailure, 'packet_pin_changed'):
            policy.packet_event('ai_verify', body, contract, '0'*64)


if __name__ == '__main__':
    unittest.main()
