"""Normal UI stage control with complete synthetic science and zero provider calls.

The parent integration tests authenticate real input/ledger identities. These
tests isolate the assess/verify/integrity routing and credential-needed marker.
"""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import test_contextual_team_iteration3_integrity as fixture
from test_contextual_team_iteration2_contract import assessment
from tools import contextual_team_iteration3_continuation as route
from tools.offline_spend import ConfigurationFailure, Deferred, identity


class ContinuationStages(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('No network')))
        self.stack.enter_context(patch.object(route.Runner, 'request', side_effect=AssertionError('No provider')))
        self.history = self.stack.enter_context(patch.object(route.policy, 'history'))
        self.counts = self.stack.enter_context(patch.object(route.policy, 'counts', return_value=[]))
        self.saved = self.stack.enter_context(patch.object(route, 'save_graph'))
        self.runner = route.ContinuationRunner.__new__(route.ContinuationRunner)
        self.scope = {'id': '363268', 'fixture': 'stage-control-only'}
        self.runner.configuration = {'scopes': [self.scope]}
        self.runner.state = Path('unused-synthetic-stage-state')
        self.runner.ledger = Mock(); self.runner.ledger.read.return_value = {}
        self.runner.timings = []
        self.runner.execute_named = Mock()

    def actual(self, coverage='direct'):
        data, graph, eligible = fixture.setup(coverage, role_count=4)
        value = assessment(data, coverage)
        self.assertEqual(len(value['people']), 12)
        self.assertEqual(sum(len(p['decisions']) for p in value['people']), 48)
        return {'data': data, 'graph': graph, 'assessment': value,
                'verified': {'state': 'coherent'},
                'configuration': {'people': [{'person_id': p} for p in eligible]}}, eligible

    def test_assess_reads_the_complete_retained_assessment_and_cannot_generate(self):
        actual, _ = self.actual()
        with patch.object(route, 'retained_ai', return_value=actual) as retained:
            result = self.runner.run_stage(self.scope, 'assess')
        retained.assert_called_once_with(self.runner.state)
        self.assertEqual(result, {'state': 'stage_complete', 'stage': 'assess', 'scope_id': '363268'})
        self.assertTrue(self.runner.timings[0]['cache_hit'])
        self.assertEqual(self.runner.timings[0]['request_id'], route.AI_ASSESSMENT_ID)
        self.runner.execute_named.assert_not_called(); self.saved.assert_not_called()
        with patch.object(route, 'retained_ai', side_effect=ConfigurationFailure('retained assessment missing')):
            with self.assertRaisesRegex(ConfigurationFailure, 'retained assessment missing'):
                self.runner.run_stage(self.scope, 'assess')
        self.assertEqual(len(self.runner.timings), 1)

    def test_verify_marks_generation_only_for_real_validated_candidates(self):
        for coverage, expected in [('direct', True), ('adjacent', False)]:
            with self.subTest(coverage=coverage):
                actual, eligible = self.actual(coverage)
                self.assertEqual(bool(route.integrity.inputs(actual['data'], actual['graph'], eligible)['candidates']), expected)
                with patch.object(route, 'ai_graph', return_value=actual) as graph:
                    result = self.runner.run_stage(self.scope, 'verify')
                self.runner.execute_named.assert_called_with('ai_verify')
                graph.assert_called_once_with(self.runner.state, through='verify')
                self.assertEqual(self.runner.integrity_generation_required, expected)
                self.assertEqual(result['state'], 'stage_complete')
                self.saved.assert_not_called()

    def test_complete_verifier_abstentions_deliver_full_graph_without_integrity(self):
        for state in ('unsuitable', 'insufficient_source', 'needs_scope_selection'):
            actual, _ = self.actual()
            actual['verified']['state'] = state
            actual['graph']['state'] = state
            actual['graph']['graph_id'] = identity({k: v for k, v in actual['graph'].items() if k not in ('requests', 'graph_id')})
            with self.subTest(state=state), patch.object(route, 'ai_graph', return_value=actual), \
                    patch.object(route.integrity, 'inputs', side_effect=AssertionError('No candidate analysis for typed abstention')):
                result = self.runner.run_stage(self.scope, 'verify')
            self.assertEqual(result, actual['graph'])
            self.assertEqual(sum(len(p['decisions']) for p in result['pair_decisions']), 48)
            self.assertFalse(self.runner.integrity_generation_required)
            self.assertEqual(self.runner.execute_named.call_args.args, ('ai_verify',))
            self.saved.assert_called_with(self.runner.state, actual['graph'])

    def test_integrity_stage_delivers_complete_negative_without_spending_for_zero_candidates(self):
        actual, eligible = self.actual('adjacent')
        value = route.integrity.empty_result(actual['data'], actual['graph'], eligible)
        final = deepcopy(actual)
        final['graph'] = route.integrity.adapter(actual['data'], actual['graph'], value, eligible)
        with patch.object(route, 'ai_graph', side_effect=[actual, final]) as graph:
            result = self.runner.run_stage(self.scope, 'integrity')
        self.runner.execute_named.assert_not_called()
        self.assertEqual(graph.call_args_list[0].kwargs, {'through': 'verify'})
        self.assertEqual(graph.call_args_list[1].kwargs, {})
        self.assertEqual(result['version'], 'contextual-audited-graph-v4')
        self.assertEqual(result['state'], 'no_supported_group_in_assessed_set')
        self.assertEqual(result['pair_decisions'], actual['graph']['pair_decisions'])
        self.saved.assert_called_once_with(self.runner.state, result)

    def test_integrity_stage_requests_only_named_integrity_then_delivers_its_full_graph(self):
        actual, eligible = self.actual()
        value = route.integrity.resolve(fixture.wire(actual['data'], actual['graph'], eligible), actual['data'], actual['graph'], eligible)
        final = deepcopy(actual)
        final['graph'] = route.integrity.adapter(actual['data'], actual['graph'], value, eligible)
        with patch.object(route, 'ai_graph', side_effect=[actual, final]):
            result = self.runner.run_stage(self.scope, 'integrity')
        self.runner.execute_named.assert_called_once_with('ai_integrity')
        self.assertEqual(result, final['graph'])
        self.assertEqual(result['pair_decisions'], actual['graph']['pair_decisions'])
        self.saved.assert_called_once_with(self.runner.state, result)

    def test_wrong_stage_scope_or_new_history_uncertainty_stops_before_action(self):
        for scope, stage in [(self.scope, 'check'), (self.scope, 'interpret'),
                ({'id': '332894'}, 'verify'), (self.scope | {'extra': True}, 'verify')]:
            with self.subTest(scope=scope, stage=stage), self.assertRaisesRegex(ConfigurationFailure, 'exact_ai_build_stage'):
                self.runner.run_stage(scope, stage)
        self.history.assert_not_called(); self.counts.assert_not_called()
        self.history.side_effect = Deferred('new uncertainty')
        with self.assertRaisesRegex(Deferred, 'new uncertainty'):
            self.runner.run_stage(self.scope, 'verify')
        self.runner.execute_named.assert_not_called(); self.saved.assert_not_called()

    def test_failed_verifier_cannot_claim_stage_complete_or_enter_integrity(self):
        self.runner.execute_named.side_effect = ValueError('strict verifier rejected complete response')
        with patch.object(route, 'ai_graph') as graph, self.assertRaisesRegex(ValueError, 'strict verifier rejected'):
            self.runner.run_stage(self.scope, 'verify')
        self.assertFalse(getattr(self.runner, 'integrity_generation_required', False))
        graph.assert_not_called(); self.saved.assert_not_called()


if __name__ == '__main__':
    unittest.main()
