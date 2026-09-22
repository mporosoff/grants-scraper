import json
import os
import unittest
from unittest.mock import patch

from tools import contextual_team_workflow as workflow
from tools.contextual_team_iteration2_policy import plan
from tools.contextual_team_iteration3_policy import plan as iteration3_plan
from tools.offline_spend import encoded, ConfigurationFailure


class Response:
    status_code = 200
    def iter_content(self, size):
        yield b'{"accepted":true}'
    def close(self):
        pass


class WorkflowTransportTests(unittest.TestCase):
    def envelope(self):
        graph = {'state': 'ready_with_gaps', 'wire_boundary_fixture': ''}
        size = plan()['maximum_graph_bytes'] - len(encoded(graph))
        graph['wire_boundary_fixture'] = 'α' * (size // 2) + 'x' * (size % 2)
        self.assertEqual(len(encoded(graph)), plan()['maximum_graph_bytes'])
        return {'job_id': 'a'*64, 'release_id': plan()['release_id'], 'run_id': '123',
                'code_sha': 'b'*40, 'result': graph, 'attempts': 688, 'charged_microusd': 7424346,
                'stage_timings': [{'stage': 'fixture-boundary', 'seconds': 123.45}]*20}

    @patch.dict(os.environ, {'REGISTRY_WORKFLOW_TOKEN': 'fixture-only'})
    def test_exact_unicode_callback_bytes_preserve_maximum_graph(self):
        value = self.envelope()
        self.assertGreater(len(encoded(value)), plan()['maximum_graph_bytes'])
        self.assertGreater(len(json.dumps(value).encode()), workflow.ITERATION2_CALLBACK_BYTES)
        with patch.object(workflow.requests, 'post', return_value=Response()) as post:
            self.assertEqual(workflow.send('result', value), {'accepted': True})
        sent = post.call_args.kwargs
        self.assertNotIn('json', sent)
        self.assertEqual(sent['data'], encoded(value))
        self.assertEqual(json.loads(sent['data']), value)
        self.assertLess(len(sent['data']), workflow.ITERATION2_CALLBACK_BYTES)
        self.assertEqual(sent['headers']['Content-Type'], 'application/json; charset=utf-8')
        self.assertFalse(sent['allow_redirects'])

    @patch.dict(os.environ, {'REGISTRY_WORKFLOW_TOKEN': 'fixture-only'})
    def test_oversized_whole_envelope_fails_without_truncation_or_send(self):
        value = self.envelope() | {'padding': 'x'*workflow.ITERATION2_CALLBACK_BYTES}
        original = encoded(value)
        with patch.object(workflow.requests, 'post') as post:
            with self.assertRaisesRegex(ConfigurationFailure, 'complete_callback_bound'):
                workflow.send('result', value)
            post.assert_not_called()
        self.assertEqual(encoded(value), original)

    @patch.dict(os.environ, {'REGISTRY_WORKFLOW_TOKEN': 'fixture-only'})
    def test_historical_transport_is_unchanged(self):
        value = {'release_id': 'historical', 'result': {'state': 'failed'}}
        with patch.object(workflow.requests, 'post', return_value=Response()) as post:
            workflow.send('result', value)
        self.assertEqual(post.call_args.kwargs['json'], value)
        self.assertNotIn('data', post.call_args.kwargs)

    @patch.dict(os.environ, {'REGISTRY_WORKFLOW_TOKEN': 'fixture-only'})
    def test_iteration3_preserves_complete_unicode_envelope_and_rejects_oversize_before_send(self):
        value = self.envelope() | {'release_id': iteration3_plan()['release_id']}
        self.assertEqual(len(encoded(value['result'])), iteration3_plan()['maximum_graph_bytes'])
        with patch.object(workflow.requests, 'post', return_value=Response()) as post:
            self.assertEqual(workflow.send('result', value), {'accepted': True})
        sent = post.call_args.kwargs
        self.assertEqual(sent['data'], encoded(value))
        self.assertEqual(json.loads(sent['data']), value)
        self.assertNotIn('json', sent)
        self.assertLessEqual(len(sent['data']), workflow.ITERATION3_CALLBACK_BYTES)
        oversized = value | {'padding': 'x' * workflow.ITERATION3_CALLBACK_BYTES}
        original = encoded(oversized)
        with patch.object(workflow.requests, 'post') as post:
            with self.assertRaisesRegex(ConfigurationFailure, 'iteration3_complete_callback_bound_no_truncation'):
                workflow.send('result', oversized)
            post.assert_not_called()
        self.assertEqual(encoded(oversized), original)
