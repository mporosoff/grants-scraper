"""Clock and alarm boundaries for serial notice work; no network or providers."""
from contextlib import ExitStack
import json
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import document_work_budget as work


class Clock:
    def __init__(self, now=100):
        self.now = float(now)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Alarm:
    """Signal stand-in with real absolute-deadline semantics on every platform."""
    SIGALRM = 14
    ITIMER_REAL = 0

    def __init__(self, clock):
        self.clock = clock
        self.handler = object()
        self.at = None
        self.interval = 0
        self.arms = []

    def getsignal(self, number):
        return self.handler

    def signal(self, number, handler):
        previous, self.handler = self.handler, handler
        return previous

    def getitimer(self, timer):
        return (max(0, self.at - self.clock()) if self.at is not None else 0, self.interval)

    def setitimer(self, timer, seconds, interval=0):
        previous = self.getitimer(timer)
        self.at = self.clock() + seconds if seconds else None
        self.interval = interval
        self.arms.append((self.at, interval))
        return previous

    def fire(self):
        self.handler(self.SIGALRM, None)


class WorkBudgetContracts(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.alarm = Alarm(self.clock)
        self.contexts = ExitStack()
        self.addCleanup(self.contexts.close)
        self.contexts.enter_context(patch.object(work, 'signal', self.alarm))
        self.log = self.contexts.enter_context(patch('builtins.print'))

    def budget(self, max_seconds=300, **kwargs):
        return work.WorkBudget(max_seconds, clock=self.clock, **kwargs)

    def events(self):
        return [json.loads(call.args[0].removeprefix('Document work: '))
                for call in self.log.call_args_list]

    def test_deadlines_keep_finalization_reserve_without_renewing_elapsed_time(self):
        budget = self.budget(unit_seconds=120, reserve_seconds=60)
        self.assertEqual(budget.total_deadline, 400)
        self.assertEqual(budget.deadline, 340)
        self.clock.advance(239)
        self.assertFalse(budget.expired())
        self.clock.advance(1)
        self.assertTrue(budget.expired())
        self.assertFalse(budget.expired(finalize=True))
        self.clock.advance(60)
        self.assertTrue(budget.expired(finalize=True))
        self.assertEqual(budget.total_deadline, 400)
        self.assertEqual(budget.deadline, 340)

    def test_short_total_budget_still_retains_time_for_work_and_finalization(self):
        budget = self.budget(20)
        self.assertEqual(budget.deadline, 110)
        self.assertEqual(budget.total_deadline, 120)

    def test_invalid_constructor_limits_are_rejected(self):
        for field in ('max_seconds', 'unit_seconds', 'reserve_seconds'):
            invalid = [True, False, None, '10', float('inf'), float('-inf'), float('nan'), -1]
            if field != 'reserve_seconds':
                invalid.append(0)
            for value in invalid:
                with self.subTest(field=field, value=value):
                    limits = {'max_seconds': 300, 'unit_seconds': 120, 'reserve_seconds': 60}
                    limits[field] = value
                    with self.assertRaises(ValueError):
                        work.WorkBudget(**limits, clock=self.clock)
        self.assertEqual(self.budget(reserve_seconds=0).deadline, 400)

    def test_invalid_unit_override_never_starts_body_or_arms_an_alarm(self):
        budget = self.budget()
        for value in (True, False, 0, -1, '10', float('inf'), float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                with budget.guard('read_notice', seconds=value):
                    self.fail('Invalid unit budget entered guarded work')
        self.assertEqual(self.alarm.arms, [])

    def test_elapsed_budget_defers_without_running_or_rearming(self):
        budget = self.budget(20, reserve_seconds=0)
        self.clock.advance(20)
        with self.assertRaises(work.WorkTimedOut) as caught:
            with budget.guard('read_notice', '123'):
                self.fail('An expired budget entered guarded work')
        self.assertEqual(caught.exception.phase, 'read_notice')
        self.assertEqual(caught.exception.opportunity_id, '123')
        self.assertEqual(self.alarm.arms, [])
        self.assertEqual(self.events()[-1]['outcome'], 'deferred')

    def test_active_unit_deadline_caps_nested_work_without_extension(self):
        budget = self.budget()
        original_handler = self.alarm.handler
        with budget.guard('read_notice', '123', seconds=20):
            outer_handler = self.alarm.handler
            self.assertEqual(budget.deadline, 120)
            self.clock.advance(5)
            with budget.guard('classify_notice', '123', seconds=100):
                self.assertEqual(budget.deadline, 120)
                self.assertEqual(self.alarm.at, 120)
                self.clock.advance(6)
            self.assertIs(self.alarm.handler, outer_handler)
            self.assertEqual(self.alarm.at, 120)
            self.assertEqual(self.alarm.getitimer(self.alarm.ITIMER_REAL), (9, 0))
            self.assertEqual(budget.deadline, 120)
        self.assertIs(self.alarm.handler, original_handler)
        self.assertEqual(self.alarm.getitimer(self.alarm.ITIMER_REAL), (0, 0))
        self.assertEqual(budget.deadline, 340)

    def test_an_existing_alarm_is_restored_with_elapsed_time_deducted(self):
        original_handler = self.alarm.handler
        self.alarm.setitimer(self.alarm.ITIMER_REAL, 30, 7)
        budget = self.budget()
        with budget.guard('read_notice', seconds=100):
            self.assertEqual(budget.deadline, 130)
            self.assertEqual(self.alarm.at, 130)
            self.clock.advance(12)
        self.assertIs(self.alarm.handler, original_handler)
        self.assertEqual(self.alarm.getitimer(self.alarm.ITIMER_REAL), (18, 7))

    def test_alarm_timeout_escapes_broad_exception_handlers_and_restores_nested_alarm(self):
        budget = self.budget()
        original_handler = self.alarm.handler
        swallowed = False
        with self.assertRaises(work.WorkTimedOut):
            with budget.guard('notice', '123', seconds=20):
                with budget.guard('parse', '123', seconds=100):
                    try:
                        self.clock.advance(20)
                        self.alarm.fire()
                    except Exception:
                        swallowed = True
        self.assertFalse(swallowed)
        self.assertFalse(issubclass(work.WorkTimedOut, Exception))
        self.assertIs(self.alarm.handler, original_handler)
        self.assertEqual(self.alarm.getitimer(self.alarm.ITIMER_REAL), (0, 0))
        self.assertEqual(budget.deadline, 340)
        ends = [event for event in self.events() if event['event'] == 'end']
        self.assertEqual([event['outcome'] for event in ends], ['timed_out', 'timed_out'])
        self.assertEqual([event['elapsed_seconds'] for event in ends], [20, 20])

    def test_ordinary_failure_preserves_exception_and_external_alarm(self):
        self.alarm.setitimer(self.alarm.ITIMER_REAL, 40, 2)
        original_handler = self.alarm.handler
        error = ValueError('Private document text must not appear in progress output')
        with self.assertRaises(ValueError) as caught:
            with self.budget().guard('parse', '123'):
                self.clock.advance(8)
                raise error
        self.assertIs(caught.exception, error)
        self.assertIs(self.alarm.handler, original_handler)
        self.assertEqual(self.alarm.getitimer(self.alarm.ITIMER_REAL), (32, 2))
        self.assertEqual(self.events()[-1]['outcome'], 'failed')
        self.assertNotIn(str(error), str(self.log.call_args_list))

    def test_finalization_can_use_reserved_time_but_cannot_extend_active_work(self):
        budget = self.budget(100, reserve_seconds=20)
        with budget.guard('notice', seconds=10):
            with budget.guard('save_partial', finalize=True, seconds=100):
                self.assertEqual(self.alarm.at, 110)
        self.clock.advance(80)
        self.assertTrue(budget.expired())
        with budget.guard('persist', finalize=True, seconds=100):
            self.assertEqual(self.alarm.at, 200)
            self.assertFalse(budget.expired(finalize=True))
        self.clock.advance(20)
        with self.assertRaises(work.WorkTimedOut):
            with budget.guard('persist', finalize=True):
                self.fail('Expired total budget entered finalization')

    def test_every_guard_is_capped_by_remaining_total_work_time(self):
        budget = self.budget(40, reserve_seconds=10)
        self.clock.advance(29)
        with budget.guard('notice', seconds=120):
            self.assertEqual(self.alarm.at, 130)
            self.assertEqual(budget.deadline, 130)
        self.clock.advance(1)
        with self.assertRaises(work.WorkTimedOut):
            with budget.guard('next_notice'):
                self.fail('Starting another notice renewed the total budget')

    def test_progress_is_flushed_bounded_single_line_json_with_success_duration(self):
        phase = 'read\n"notice"' + 'x' * 100
        opportunity_id = '123\r\nforged-log' + 'x' * 180
        with self.budget().guard(phase, opportunity_id):
            self.clock.advance(1.25)
        events = self.events()
        self.assertEqual([event['event'] for event in events], ['start', 'end'])
        self.assertEqual(events[-1]['elapsed_seconds'], 1.25)
        self.assertEqual(events[-1]['outcome'], 'completed')
        for call, event in zip(self.log.call_args_list, events):
            self.assertIs(call.kwargs.get('flush'), True)
            self.assertNotIn('\n', call.args[0])
            self.assertNotIn('\r', call.args[0])
            self.assertLessEqual(len(event['phase']), 80)
            self.assertLessEqual(len(event['opportunity_id']), 160)

    def test_missing_unix_timer_fails_explicitly_before_work(self):
        with patch.object(work, 'signal', SimpleNamespace()):
            with self.assertRaisesRegex(RuntimeError, 'Unix timers.*main thread'):
                with self.budget().guard('notice'):
                    self.fail('Unsupported timer backend entered work')

    def test_non_main_thread_fails_explicitly_before_work(self):
        failures = []
        entered = []

        def worker():
            try:
                with self.budget().guard('notice'):
                    entered.append(True)
            except BaseException as error:
                failures.append(error)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(entered, [])
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], RuntimeError)
        self.assertIn('main thread', str(failures[0]))
        self.assertEqual(self.alarm.arms, [])


def _busy_parser():
    # Keep the CPU-bound parser in its own frame, like the real extractor calls.
    # Python 3.13 can leave a final loop backedge outside an inline with block's
    # exception table; the caller's guarded CALL still catches its alarm.
    started = time.monotonic()
    try:
        while time.monotonic() - started < 2:
            pass
    except Exception:
        return  # Ordinary broad parser handlers must not swallow WorkTimedOut.


def _run_realtime_alarm_probe():
    check = unittest.TestCase()
    budget = work.WorkBudget(3, unit_seconds=0.05, reserve_seconds=0)
    original_handler = signal.getsignal(signal.SIGALRM)
    started = time.monotonic()
    try:
        with check.assertRaises(work.WorkTimedOut) as caught:
            with budget.guard('busy_parser', '123'):
                _busy_parser()
        check.assertEqual(caught.exception.phase, 'busy_parser')
        check.assertEqual(caught.exception.opportunity_id, '123')
        check.assertLess(time.monotonic() - started, 1)
        check.assertIs(signal.getsignal(signal.SIGALRM), original_handler)
        check.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0, 0))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, original_handler)


@unittest.skipUnless(all(hasattr(signal, name) for name in ('SIGALRM', 'ITIMER_REAL', 'setitimer', 'getitimer')),
                     'Realtime Unix alarm unavailable on this platform')
class RealtimeAlarmContract(unittest.TestCase):
    def test_busy_parser_is_interrupted_without_cooperative_checks(self):
        # A failed OS-timer probe must never leak a handler/timer into the suite.
        result = subprocess.run(
            [sys.executable, '-c',
             'import sys; sys.path.insert(0, sys.argv[1]); '
             'from test_document_work_budget import _run_realtime_alarm_probe; '
             '_run_realtime_alarm_probe()', str(Path(__file__).resolve().parent)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"outcome": "timed_out"', result.stdout)


if __name__ == '__main__':
    unittest.main()
