"""Wall-clock limits for the serial official-notice pipeline on Actions Linux."""
from contextlib import contextmanager
import json
import math
import signal
import threading
import time


class WorkTimedOut(BaseException):
    """Escape parser/network broad Exception handlers without accepting partial work."""
    def __init__(self, phase, opportunity_id=''):
        self.phase, self.opportunity_id = str(phase), str(opportunity_id)
        super().__init__('Document work deadline exceeded: ' + self.phase)


class WorkBudget:
    def __init__(self, max_seconds, unit_seconds=120, reserve_seconds=60, *, clock=None):
        values = (max_seconds, unit_seconds, reserve_seconds)
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in values):
            raise ValueError('Document time limits must be finite numbers')
        if max_seconds <= 0 or unit_seconds <= 0 or reserve_seconds < 0:
            raise ValueError('Document time limits must be positive with a nonnegative reserve')
        self.clock = clock or time.monotonic
        self.unit_seconds = float(unit_seconds)
        self.total_deadline = self.clock() + float(max_seconds)
        self.work_deadline = self.total_deadline - min(float(reserve_seconds), float(max_seconds) / 2)
        self._active = []

    @property
    def deadline(self):
        return min([self.work_deadline, *self._active])

    def expired(self, finalize=False):
        end = min([self.total_deadline, *self._active]) if finalize else self.deadline
        return self.clock() >= end

    @staticmethod
    def _supported():
        if (not all(hasattr(signal, name) for name in ('SIGALRM', 'ITIMER_REAL', 'setitimer', 'getitimer'))
                or threading.current_thread() is not threading.main_thread()):
            raise RuntimeError('Bounded notice processing requires Unix timers on the main thread')

    @staticmethod
    def _log(phase, opportunity_id, event, elapsed=0, outcome=None):
        item = {'phase': str(phase)[:80], 'opportunity_id': str(opportunity_id)[:160],
                'event': event, 'elapsed_seconds': round(elapsed, 3)}
        if outcome is not None:
            item['outcome'] = outcome
        print('Document work: ' + json.dumps(item, sort_keys=True), flush=True)

    @contextmanager
    def guard(self, phase, opportunity_id='', *, finalize=False, seconds=None):
        self._supported()
        duration = self.unit_seconds if seconds is None else seconds
        if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                or not math.isfinite(duration) or duration <= 0):
            raise ValueError('Document unit limit must be finite and positive')
        started = self.clock()
        cap = self.total_deadline if finalize else self.work_deadline
        end = min([started + duration, cap, *self._active])
        if end <= started:
            self._log(phase, opportunity_id, 'end', outcome='deferred')
            raise WorkTimedOut(phase, opportunity_id)
        old_handler = signal.getsignal(signal.SIGALRM)
        old_delay, old_interval = signal.getitimer(signal.ITIMER_REAL)
        old_deadline = started + old_delay if old_delay > 0 else None
        if old_deadline is not None:
            end = min(end, old_deadline)
        def interrupt(signum, frame):
            raise WorkTimedOut(phase, opportunity_id)
        self._log(phase, opportunity_id, 'start')
        self._active.append(end)
        outcome = 'completed'
        try:
            signal.signal(signal.SIGALRM, interrupt)
            signal.setitimer(signal.ITIMER_REAL, max(0.000001, end - self.clock()))
            try:
                yield
            except WorkTimedOut:
                outcome = 'timed_out'
                raise
            except BaseException:
                outcome = 'failed'
                raise
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)
            self._active.pop()
            if old_deadline is not None:
                signal.setitimer(signal.ITIMER_REAL, max(0.000001, old_deadline - self.clock()), old_interval)
            self._log(phase, opportunity_id, 'end', self.clock() - started, outcome)


def require_document_publication(catalog):
    """Reject incomplete processing at creation and the independent publication gate."""
    diagnostics = catalog.get('diagnostics') or {}
    if 'document_work' not in diagnostics:
        return  # Previously published catalogs predate this processing marker.
    work = diagnostics['document_work']
    if not isinstance(work, dict) or work.get('publication_safe') is not True:
        raise ValueError('Document processing is incomplete; preserve the original run and complete recovery before publication')
