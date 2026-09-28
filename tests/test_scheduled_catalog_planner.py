"""Hermetic integration contracts for scheduled selection in the release entry point."""
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import plan_release as planner


class ScheduledCatalogPlanner(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.candidate = 'a' * 64
        self.base = {'stage': 'generate', 'release_sha': 'b' * 40,
                     'candidate_id': self.candidate, 'candidate_run': '100'}
        planner.c.write_json(self.root / 'release/candidate-source.json',
                             {'candidate_id': self.candidate, 'artifact_run': '100'})
        self.environment = {
            'GITHUB_EVENT_NAME': 'schedule', 'REQUESTED_STAGE': 'auto',
            'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_RUN_ID': '300',
            'GITHUB_RUN_ATTEMPT': '1', 'RUNNER_TEMP': str(self.root),
            'GITHUB_OUTPUT': str(self.root / 'output'),
            'GITHUB_STEP_SUMMARY': str(self.root / 'summary'),
        }
        self.live = {'candidate_id': self.candidate, 'verified': True}
        self.publication = {'run': '120', 'attempt': '1'}
        self.receipt = {'candidate_id': self.candidate, 'identity': 'validation-identity'}
        self.daily = {'daily_window_start': '2026-09-28T10:17:00Z',
                      'catalog_generated_at': '2026-09-27T10:18:00Z',
                      'daily_status': 'due', 'recovery_run': ''}

    def invoke(self, *, environment=None, pending=None, resumed=None, planned=None,
               resolution=None, automatic_paid_hold=False):
        env = self.environment | (environment or {})
        for name in ('output', 'summary'):
            (self.root / name).write_text('', encoding='utf-8')

        def latest(repository, candidate, kind, destination):
            return {'live': ('130', self.live), 'validation': ('110', self.receipt),
                    'publication': ('120', self.publication)}[kind]

        def resolve(root, environment, result, destination, **kwargs):
            return result | self.daily | (resolution or {})

        with patch.dict(os.environ, env, clear=True), \
                patch.object(planner.c, 'ROOT', self.root), \
                patch.object(planner, 'pending_publication', return_value=pending) as pending_call, \
                patch.object(planner, 'completed_attempt', return_value=resumed) as resume_call, \
                patch.object(planner, 'latest_report', side_effect=latest) as reports, \
                patch.object(planner, 'plan', return_value=dict(planned or self.base)) as plan_call, \
                patch('tools.scheduled_catalog.resolve', side_effect=resolve) as daily_call, \
                patch('tools.team_provider.provider_names', return_value=('anthropic',)) as providers, \
                patch('sys.stdout', new=io.StringIO()):
            planner.main(automatic_paid_hold=automatic_paid_hold)

        return {
            'result': json.loads((self.root / 'release-plan.json').read_bytes()),
            'outputs': (self.root / 'output').read_text(encoding='utf-8').splitlines(),
            'summary': (self.root / 'summary').read_text(encoding='utf-8'),
            'pending': pending_call, 'resume': resume_call, 'reports': reports,
            'plan': plan_call, 'daily': daily_call, 'providers': providers,
        }

    def test_automatic_schedule_resolves_after_base_plan_and_keeps_recovery_receipt(self):
        for requested in ('', 'auto'):
            with self.subTest(requested=requested):
                run = self.invoke(environment={'REQUESTED_STAGE': requested}, resolution={
                    'stage': 'publish', 'daily_status': 'recovering', 'recovery_run': '200',
                    'candidate_run': '200', 'candidate_id': 'c' * 64, 'receipt_run': '210',
                })
                run['daily'].assert_called_once()
                args, kwargs = run['daily'].call_args
                self.assertEqual(args[0], self.root)
                self.assertEqual(args[1]['REQUESTED_STAGE'], requested)
                self.assertEqual(args[2]['receipt_run'], '110')
                self.assertEqual(Path(args[3]).name, 'daily')
                self.assertFalse(kwargs['explicit_resume'])
                self.assertIs(kwargs['reports'], run['reports'])
                self.assertIs(kwargs['live'], self.live)
                self.assertIs(kwargs['publication'], self.publication)
                self.assertEqual(run['result']['receipt_run'], '210')
                self.assertEqual(run['result']['candidate_run'], '200')
                self.assertEqual(run['result']['candidate_id'], 'c' * 64)
                self.assertEqual(run['result']['daily_status'], 'recovering')
                self.assertIn('receipt_run=210', run['outputs'])
                self.assertNotIn('receipt_run=110', run['outputs'])
                self.assertIn('"receipt_run": "210"', run['summary'])

    def test_pending_publication_keeps_original_automatic_schedule_recovery(self):
        pending = {'REQUESTED_STAGE': 'publish', 'CANDIDATE_RUN': '200', 'CANDIDATE_ID': 'c' * 64}
        selected = self.base | {'stage': 'publish', 'candidate_run': '200', 'candidate_id': 'c' * 64}
        run = self.invoke(pending=pending, planned=selected, resolution={'daily_status': 'recovering'})
        run['pending'].assert_called_once()
        run['resume'].assert_not_called()
        run['plan'].assert_called_once()
        run['daily'].assert_called_once()
        args, kwargs = run['daily'].call_args
        self.assertTrue(kwargs['explicit_resume'])
        self.assertEqual(args[1]['REQUESTED_STAGE'], 'publish')
        self.assertEqual(args[1]['CANDIDATE_RUN'], '200')
        self.assertEqual(args[2]['candidate_id'], pending['CANDIDATE_ID'])
        self.assertEqual(args[2]['receipt_run'], '110')
        self.assertEqual([call.args[2] for call in run['reports'].call_args_list], ['validation'])
        self.assertEqual(run['result']['daily_status'], 'recovering')

    def test_same_run_retry_resumes_exact_candidate_before_daily_resolution(self):
        resumed = {'candidate_id': 'd' * 64}
        selected = self.base | {'stage': 'publish', 'candidate_run': '300', 'candidate_id': 'd' * 64}
        run = self.invoke(environment={'GITHUB_RUN_ATTEMPT': '2'}, resumed=resumed,
                          planned=selected, resolution={'daily_status': 'recovering'})
        run['pending'].assert_not_called()
        run['resume'].assert_called_once()
        self.assertIs(run['plan'].call_args.kwargs['resumed'], resumed)
        self.assertEqual([call.args[1] for call in run['reports'].call_args_list], ['d' * 64] * 3)
        run['daily'].assert_called_once()
        args, kwargs = run['daily'].call_args
        self.assertTrue(kwargs['explicit_resume'])
        self.assertEqual(args[2]['candidate_run'], '300')
        self.assertEqual(args[2]['candidate_id'], resumed['candidate_id'])
        self.assertEqual(run['result']['daily_status'], 'recovering')

    def test_manual_and_push_plans_do_not_invoke_daily_resolver(self):
        for event in ('workflow_dispatch', 'push'):
            for requested in ('auto', 'generate'):
                with self.subTest(event=event, requested=requested):
                    run = self.invoke(environment={'GITHUB_EVENT_NAME': event, 'REQUESTED_STAGE': requested})
                    run['daily'].assert_not_called()
                    self.assertEqual(run['result']['stage'], 'generate')
                    self.assertNotIn('daily_status', run['result'])

    def test_named_scheduled_checkpoint_does_not_invoke_automatic_resolver(self):
        for selection in (
            {'REQUESTED_STAGE': 'publish', 'CANDIDATE_RUN': '200', 'CANDIDATE_ID': 'c' * 64},
            {'REQUESTED_STAGE': 'auto', 'CANDIDATE_RUN': '200', 'CANDIDATE_ID': 'c' * 64},
        ):
            with self.subTest(selection=selection):
                run = self.invoke(environment=selection)
                run['pending'].assert_not_called()
                run['daily'].assert_not_called()
                self.assertNotIn('daily_status', run['result'])

    def test_paid_hold_marks_daily_result_held_before_writing_outputs(self):
        for stage in ('generate', 'teams', 'backfill'):
            with self.subTest(stage=stage):
                run = self.invoke(resolution={'stage': stage}, automatic_paid_hold=True)
                run['daily'].assert_called_once()
                run['providers'].assert_not_called()
                result = run['result']
                self.assertEqual((result['stage'], result['held_stage'], result['daily_status']),
                                 ('noop', stage, 'held'))
                self.assertEqual(result['daily_window_start'], self.daily['daily_window_start'])
                self.assertEqual(result['catalog_generated_at'], self.daily['catalog_generated_at'])
                self.assertEqual((result['openai'], result['anthropic']), ('false', 'false'))
                self.assertEqual([line for line in run['outputs'] if line.startswith('stage=')], ['stage=noop'])
                self.assertIn('daily_status=held', run['outputs'])
                self.assertNotIn('daily_status=due', run['outputs'])

    def test_paid_hold_preserves_an_existing_daily_recovery_hold(self):
        reason = 'Scheduled refresh held: retained generation requires recovery'
        run = self.invoke(resolution={'stage': 'noop', 'daily_status': 'held',
                                      'recovery_run': '200', 'reason': reason}, automatic_paid_hold=True)
        self.assertEqual(run['result']['daily_status'], 'held')
        self.assertEqual(run['result']['recovery_run'], '200')
        self.assertEqual(run['result']['reason'], reason)
        self.assertNotIn('held_stage', run['result'])
        run['providers'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
