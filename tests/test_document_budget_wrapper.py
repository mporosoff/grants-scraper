"""Production notice wrapper deadlines and durable spend retention, offline only."""
from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from scripts import document_work_budget as work
from scripts.document_work_budget import WorkBudget
from scripts import extract_document_evidence as extractor
from scripts import subtopic_cov4 as gate
from tools import offline_ai
from tools import run_budgeted_documents as wrapper


class Controller:
    def __init__(self, remaining=20):
        self.deadline = time.monotonic() + remaining
        self.active = False
        self.calls = []
        self.identifiers = []

    @contextmanager
    def guard(self, phase, opportunity_id='', **kwargs):
        self.calls.append((phase, kwargs))
        self.identifiers.append((phase, opportunity_id))
        previous_active = self.active
        self.active = True
        try:
            yield
        finally:
            self.active = previous_active


class DocumentBudgetWrapperContracts(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.ledger = offline_ai.Ledger(self.root / 'ledger.json', 'bounded-notice-fixture', 2)
        self.cache = self.root / 'cache'
        self.budget = Controller()
        self.original = gate.classify_fundability
        self.marker = self.stack.enter_context(patch.object(extractor, 'mark_document_work_incomplete', create=True))
        self.stack.enter_context(patch.dict(os.environ, {
            'OFFLINE_AI_STATE': str(self.root), 'TEAM_MODE': 'maintenance',
            'ANTHROPIC_API_KEY': 'synthetic-test-key',
            'GITHUB_RUN_ID': '', 'GITHUB_RUN_ATTEMPT': '',
        }))
        self.ledger_factory = self.stack.enter_context(patch.object(wrapper, 'production_ledger', return_value=self.ledger))
        self.cache_factory = self.stack.enter_context(patch.object(wrapper, 'response_cache', return_value=self.cache))
        self.budget_factory = self.stack.enter_context(patch.object(work, 'WorkBudget', return_value=self.budget))
        self.stack.enter_context(patch.object(wrapper, 'config', return_value={'max_seconds': 300}))
        self.service = self.stack.enter_context(patch.object(wrapper, 'require_production_service'))
        self.transport = self.stack.enter_context(patch.object(wrapper, 'check_run_transport'))
        self.fallback = self.stack.enter_context(patch.object(extractor, 'safe_timeout_fallback', return_value=17, create=True))
        self.network = self.stack.enter_context(patch('requests.post', side_effect=AssertionError('No live provider requests permitted')))

    def test_instrument_reads_current_deadline_and_preserves_ledger_cache_and_transport(self):
        classified = Mock(return_value={'accepted': False})
        session = SimpleNamespace(post=Mock())
        with patch.object(offline_ai, 'Client', side_effect=[object(), object()]) as client:
            classify = wrapper.instrument(self.ledger, self.cache, classified, work_budget=self.budget)
            original_deadline = self.budget.deadline
            classify({'title': 'Fixture'}, api_key='synthetic', session=session)
            self.budget.deadline -= 15
            classify({'title': 'Second fixture'}, api_key='synthetic', session=session)
        self.assertEqual(client.call_count, 2)
        for call, deadline in zip(client.call_args_list, [original_deadline, self.budget.deadline]):
            self.assertIs(call.args[0], self.ledger)
            self.assertEqual(call.args[1], self.cache)
            self.assertEqual(call.kwargs['deadline'], deadline)
            self.assertIs(call.kwargs['post'], session.post)
        self.assertEqual(classified.call_count, 2)
        self.network.assert_not_called()

    def test_ledger_setup_failure_leaves_initializing_marker_before_any_provider_work(self):
        error = RuntimeError('ledger identity mismatch')

        def fail_ledger(*_):
            self.marker.assert_called_once_with(phase='initializing')
            raise error

        self.ledger_factory.side_effect = fail_ledger
        with patch.object(extractor, 'main') as run:
            with self.assertRaises(RuntimeError) as caught:
                wrapper.main()
        self.assertIs(caught.exception, error)
        self.marker.assert_called_once_with(phase='initializing')
        run.assert_not_called()
        self.budget_factory.assert_not_called()
        self.cache_factory.assert_not_called()
        self.fallback.assert_not_called()
        self.network.assert_not_called()
        self.assertIs(gate.classify_fundability, self.original)
        self.assertEqual(self.ledger.read()['requests'], [])

    def test_classification_units_allow_serial_fanout_within_the_unchanged_global_budget(self):
        from tests.test_document_work_budget import Clock, Alarm
        clock = Clock()
        alarm = Alarm(clock)
        deadlines = []
        def classify(candidate, *, api_key, session, offline_client):
            self.assertEqual(budget.deadline, clock() + 120)
            self.assertEqual(alarm.at, budget.deadline)
            deadlines.append(offline_client.deadline)
            clock.advance(70)
            return {'accepted': True}
        def client(*_, deadline, **__):
            return SimpleNamespace(deadline=deadline)
        with patch.object(work, 'signal', alarm), patch('builtins.print'), \
                patch.object(offline_ai, 'Client', side_effect=client):
            budget = WorkBudget(1200, clock=clock)
            bounded = wrapper.instrument(self.ledger, self.cache, classify, work_budget=budget)
            with budget.guard('document_phase', finalize=True, seconds=1200):
                for number in range(3):
                    self.assertEqual(bounded({'parent_record_id': '363993', 'subtopic_id': str(number)}), {'accepted': True})
                self.assertEqual(budget.total_deadline, 1300)
                self.assertEqual(budget.work_deadline, 1240)
                self.assertEqual(budget.deadline, 1240)
                self.assertEqual(alarm.at, 1300)
        self.assertEqual(clock(), 310)
        self.assertEqual(deadlines, [220, 290, 360])
        self.assertEqual(self.ledger.read()['requests'], [])
        self.network.assert_not_called()

    def test_remaining_global_work_time_caps_next_classification_before_dispatch(self):
        from tests.test_document_work_budget import Clock, Alarm
        clock = Clock()
        alarm = Alarm(clock)
        with patch.object(work, 'signal', alarm), patch('builtins.print'), \
                patch.object(offline_ai, 'Client') as client:
            budget = WorkBudget(1200, clock=clock)
            classify = Mock()
            bounded = wrapper.instrument(self.ledger, self.cache, classify, work_budget=budget)
            with budget.guard('document_phase', finalize=True, seconds=1200):
                clock.advance(1140)
                with self.assertRaises(work.WorkTimedOut) as caught:
                    bounded({'parent_record_id': '363993'})
                self.assertEqual(caught.exception.phase, 'notice_classification')
                self.assertEqual(caught.exception.opportunity_id, '363993')
                self.assertEqual(budget.total_deadline, 1300)
            client.assert_not_called()
            classify.assert_not_called()
        self.assertEqual(self.ledger.read()['requests'], [])
        self.network.assert_not_called()

    def test_replay_and_native_classifier_work_share_the_candidate_guard(self):
        candidate = {'parent_record_id': '363993'}
        def classify(*_, **__):
            self.assertTrue(self.budget.active)
            return {'accepted': True}
        replay_client = SimpleNamespace()
        with patch('tools.evaluate_team_prompt_repair.ReplayClient', return_value=replay_client):
            bounded = wrapper.instrument(self.ledger, self.cache, classify, replay=True, work_budget=self.budget)
            self.assertEqual(bounded(candidate), {'accepted': True})
        self.assertIs(replay_client.ledger, self.ledger)
        self.assertEqual(self.budget.identifiers, [('notice_classification', '363993')])
        self.assertFalse(self.budget.active)
        self.network.assert_not_called()

    def test_unsupported_alarm_leaves_startup_marker_and_restores_classifier(self):
        error = RuntimeError('Bounded notice processing requires Unix timers on the main thread')

        def unsupported(*_, **__):
            self.marker.assert_called_once_with(phase='initializing')
            raise error

        self.budget.guard = Mock(side_effect=unsupported)
        with patch.object(extractor, 'main') as run:
            with self.assertRaises(RuntimeError) as caught:
                wrapper.main()
        self.assertIs(caught.exception, error)
        self.marker.assert_called_once_with(phase='initializing')
        run.assert_not_called()
        self.fallback.assert_not_called()
        self.network.assert_not_called()
        self.assertIs(gate.classify_fundability, self.original)
        self.assertEqual(self.ledger.read()['requests'], [])
        self.assertEqual(json.loads((self.root / 'usage-summary.json').read_bytes()), self.ledger.summary())

    def test_success_uses_one_controller_and_restores_classifier_and_usage_summary(self):
        def run(*, work_budget):
            self.assertIs(work_budget, self.budget)
            self.assertTrue(self.budget.active)
            self.assertIsNot(gate.classify_fundability, self.original)
            return 0

        with patch.object(extractor, 'main', side_effect=run):
            self.assertEqual(wrapper.main(), 0)
        self.assertIs(gate.classify_fundability, self.original)
        self.assertFalse(self.budget.active)
        self.assertEqual(self.budget.calls, [('document_phase', {'finalize': True, 'seconds': 300})])
        self.budget_factory.assert_called_once_with(300)
        self.ledger_factory.assert_called_once_with(self.root, 'maintenance')
        self.cache_factory.assert_called_once_with(self.ledger, 'cov4')
        self.fallback.assert_not_called()
        self.assertEqual(json.loads((self.root / 'usage-summary.json').read_bytes()), self.ledger.summary())
        self.network.assert_not_called()

    def test_provider_timeout_keeps_unknown_reservation_and_completed_cache_before_fallback(self):
        self.cache.mkdir()
        completed_cache = self.cache / 'earlier-completed.json'
        completed_cache.write_text('{"retained":"safe completed decision"}', encoding='utf-8')
        before_bytes = completed_cache.read_bytes()
        session = SimpleNamespace(post=Mock(side_effect=work.WorkTimedOut('classify_notice', '123')))
        candidate = {'parent_title': 'Fixture funding', 'title': 'Catalysis', 'excerpt': 'Research scope'}

        def run(*, work_budget):
            self.assertIs(work_budget, self.budget)
            self.assertTrue(self.budget.active)
            gate.classify_fundability(candidate, api_key='synthetic', session=session)
            self.fail('Timeout was swallowed by the classifier')

        def fallback(*, work_budget):
            self.assertIs(work_budget, self.budget)
            self.assertFalse(self.budget.active)
            rows = self.ledger.read()['requests']
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['status'], 'reserved_unknown')
            self.assertEqual(rows[0]['charged_microusd'], rows[0]['reserved_microusd'])
            self.assertIsNone(rows[0]['usage'])
            self.assertGreater(rows[0]['charged_microusd'], 0)
            return 17

        self.fallback.side_effect = fallback
        with patch.object(extractor, 'main', side_effect=run):
            self.assertEqual(wrapper.main(), 17)
        self.fallback.assert_called_once_with(work_budget=self.budget)
        self.assertIs(gate.classify_fundability, self.original)
        self.assertEqual(completed_cache.read_bytes(), before_bytes)
        self.assertEqual(session.post.call_count, 1)
        self.assertGreater(session.post.call_args.kwargs['timeout'], 0)
        self.assertLessEqual(session.post.call_args.kwargs['timeout'], 20)
        self.assertEqual(json.loads((self.root / 'usage-summary.json').read_bytes()), self.ledger.summary())
        self.assertEqual(len(self.ledger.read()['requests']), 1)
        self.service.assert_called_once_with('cov4', self.ledger)
        self.transport.assert_called_once_with(self.ledger, 0)
        self.network.assert_not_called()

    def test_expired_client_deadline_makes_no_provider_call_or_spend_reservation(self):
        self.budget.deadline = time.monotonic() - 1
        session = SimpleNamespace(post=Mock(side_effect=AssertionError('Expired work dispatched a request')))
        classify = wrapper.instrument(self.ledger, self.cache, self.original, work_budget=self.budget)
        result = classify({'title': 'Fixture', 'excerpt': 'Research scope'}, api_key='synthetic', session=session)
        self.assertEqual(result['fundability'], gate.UNRESOLVED)
        self.assertEqual(self.ledger.read()['requests'], [])
        session.post.assert_not_called()
        self.network.assert_not_called()

    def test_non_timeout_error_propagates_without_fallback_but_restores_and_summarizes(self):
        error = ValueError('fixture extraction failure')
        with patch.object(extractor, 'main', side_effect=error):
            with self.assertRaises(ValueError) as caught:
                wrapper.main()
        self.assertIs(caught.exception, error)
        self.assertIs(gate.classify_fundability, self.original)
        self.fallback.assert_not_called()
        self.assertEqual(json.loads((self.root / 'usage-summary.json').read_bytes()), self.ledger.summary())

    def test_actions_restores_before_extraction_and_captures_after_failed_extraction(self):
        from tools import generation_document_checkpoint as checkpoint
        order = []
        def run(*, work_budget):
            order.append('extract')
            raise ValueError('incomplete document phase')
        def capture(*_):
            self.assertIs(gate.classify_fundability, self.original)
            self.assertTrue((self.root / 'usage-summary.json').exists())
            order.append('capture')
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2'}), \
                patch.object(checkpoint, 'restore', side_effect=lambda *_: order.append('restore')) as restore, \
                patch.object(checkpoint, 'capture', side_effect=capture) as retained, \
                patch.object(extractor, 'main', side_effect=run):
            with self.assertRaisesRegex(ValueError, 'incomplete document phase'):
                wrapper.main()
        self.assertEqual(order, ['restore', 'extract', 'capture'])
        self.assertEqual(restore.call_args.args[1:], (self.root, '123', '2'))
        self.assertEqual(retained.call_args.args[1:], (self.root, '123', '2'))
        self.network.assert_not_called()

    def test_rejected_checkpoint_keeps_publication_closed_without_overwriting_retained_inputs(self):
        from tools import generation_document_checkpoint as checkpoint
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2'}), \
                patch.object(checkpoint, 'restore', side_effect=ValueError('checkpoint provenance mismatch')), \
                patch.object(checkpoint, 'capture') as capture, patch.object(extractor, 'main') as run:
            with self.assertRaisesRegex(ValueError, 'checkpoint provenance mismatch'):
                wrapper.main()
        self.marker.assert_called_once_with(phase='initializing')
        run.assert_not_called()
        capture.assert_not_called()
        self.network.assert_not_called()

    def test_timeout_fallback_failure_still_restores_classifier_and_preserves_spend(self):
        self.ledger.reserve('anthropic', gate.MODEL, 'cov4', 'previous-request', 12345, 1)
        before = self.ledger.read()
        error = RuntimeError('safe fallback unavailable')
        self.fallback.side_effect = error
        with patch.object(extractor, 'main', side_effect=work.WorkTimedOut('document_phase')):
            with self.assertRaises(RuntimeError) as caught:
                wrapper.main()
        self.assertIs(caught.exception, error)
        self.assertIs(gate.classify_fundability, self.original)
        self.assertEqual(self.ledger.read(), before)
        self.assertEqual(json.loads((self.root / 'usage-summary.json').read_bytes()), self.ledger.summary())
        self.network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
