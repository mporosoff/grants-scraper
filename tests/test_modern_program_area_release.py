"""Modern named continuation routing; no source or provider dispatch."""
from pathlib import Path
import os
import unittest
from unittest.mock import patch

import yaml

from tools import program_area_release as bridge, release_candidate as c


class ModernProgramAreaRelease(unittest.TestCase):
    def environment(self, run='123456', identifier='a' * 64):
        return {'GITHUB_REPOSITORY': 'mporosoff/grants-scraper',
            'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_WORKFLOW_REF': 'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main',
            'CANDIDATE_RUN': run, 'CANDIDATE_ID': identifier}

    def test_modern_named_parent_is_preserved_without_historical_case_ids(self):
        for run, identifier in [('123456', 'a' * 64), ('987654', 'f' * 64)]:
            with self.subTest(run=run), patch.object(c, 'git', return_value='b' * 40):
                value = bridge.plan(Path('.'), self.environment(run, identifier))
            self.assertEqual((value['candidate_run'], value['candidate_id']), (run, identifier))
            self.assertEqual(value['program_area_mode'], 'modern')
            self.assertEqual((value['openai'], value['anthropic']), ('false', 'false'))
            self.assertEqual(value['team_mode'], 'maintenance')

    def test_legacy_exact_parent_retains_legacy_mode(self):
        with patch.object(c, 'git', return_value='b' * 40):
            value = bridge.plan(Path('.'), self.environment(str(bridge.recovery.PARENT_RUN), bridge.recovery.PARENT_CANDIDATE))
        self.assertEqual(value['program_area_mode'], 'legacy')

    def test_invalid_or_mixed_selectors_fail_before_git(self):
        for delta in ({'CANDIDATE_RUN': ''}, {'CANDIDATE_RUN': '0'}, {'CANDIDATE_ID': 'a' * 63},
                      {'GITHUB_EVENT_NAME': 'schedule'}, {'PUBLICATION_RUN': '4'},
                      {'QUALIFICATION_PILOT': 'true'},
                      {'CANDIDATE_RUN': str(bridge.recovery.PARENT_RUN)},
                      {'CANDIDATE_ID': bridge.recovery.PARENT_CANDIDATE}):
            with self.subTest(delta=delta), patch.object(c, 'git') as git:
                with self.assertRaises(ValueError):
                    bridge.plan(Path('.'), self.environment() | delta)
                git.assert_not_called()

    def test_workflow_modern_budget_path_is_separate_from_legacy_reservation(self):
        workflow = yaml.safe_load((c.ROOT / '.github/workflows/refresh-opportunities.yml').read_text(encoding='utf8'))
        job = workflow['jobs']['program-area-revalidation']
        steps = {step['id']: step for step in job['steps'] if step.get('id')}
        self.assertIn('needs.plan.outputs.candidate_run', job['env']['CANDIDATE_RUN'])
        self.assertIn('needs.plan.outputs.candidate_id', job['env']['CANDIDATE_ID'])
        self.assertEqual(steps['restore']['if'], "needs.plan.outputs.program_area_mode != 'modern'")
        self.assertEqual(workflow['jobs']['plan']['outputs']['program_area_mode'], '${{ steps.plan.outputs.program_area_mode }}')
        for flag in ('--parent-run "$CANDIDATE_RUN"', '--parent-id "$CANDIDATE_ID"', '--state "$RUNNER_TEMP/program-area-modern"'):
            self.assertIn(flag, steps['prepare']['run'])
        for name in ('vectors-restore', 'reserve', 'reservation-upload', 'vectors', 'checkpoint', 'checkpoint-upload'):
            self.assertIn("steps.prepare.outputs.modern != 'true'", steps[name]['if'])
        modern = steps['modern-vectors']
        self.assertEqual(modern['run'], 'node tools/run_budgeted_vectors.mjs --production --write')
        self.assertEqual(modern['env']['CATALOG_VECTOR_OPERATION'], 'reconciliation')
        self.assertEqual(modern['env']['CATALOG_RECONCILE_STATE'], '${{ steps.prepare.outputs.vector_state }}')
        self.assertNotIn('GITHUB_RUN_ID', modern['env'])
        self.assertIn("steps.modern-reservation-upload.outcome == 'success'", modern['if'])
        self.assertIn("steps.prepare.outputs.vector_reused != 'true'", modern['if'])
        upload = steps['modern-state-upload']
        self.assertIn('always()', upload['if'])
        self.assertIn("steps.restore.outputs.candidate_id == ''", upload['if'])
        self.assertIn("steps.prepare.outputs.modern == 'true'", upload['if'])
        self.assertEqual(upload['with']['name'], '${{ steps.prepare.outputs.state_artifact }}')
        self.assertNotIn('overwrite', upload['with'])
        order = [step.get('id') for step in job['steps']]
        self.assertLess(order.index('modern-reservation-upload'), order.index('modern-vectors'))
        self.assertLess(order.index('modern-vectors'), order.index('modern-checkpoint'))
        self.assertLess(order.index('modern-checkpoint'), order.index('modern-state-upload'))
        self.assertLess(order.index('persist'), order.index('modern-state-upload'))
        self.assertIn('--state "$RUNNER_TEMP/program-area-modern"', steps['persist']['run'])
        self.assertIn('--output "$RUNNER_TEMP/candidate"', steps['prepare']['run'])
        self.assertIn('steps.prepare.outputs.candidate_id', job['outputs']['candidate_id'])
        self.assertIn('steps.prepare.outputs.artifact_run', job['outputs']['artifact_run'])
        for name in ('modern-reservation-upload', 'modern-vectors', 'modern-checkpoint', 'persist'):
            self.assertIn("steps.prepare.outputs.candidate_id == ''", steps[name]['if'])
        select = next(step for step in workflow['jobs']['candidate']['steps'] if step.get('id') == 'select')
        self.assertIn('needs.program-area-revalidation.outputs.artifact_run', select['env']['RECONCILED_RUN'])

    def test_modern_constructor_uses_original_state_and_checkpoints_complete_child(self):
        events = []
        def create(*args, **kwargs):
            self.assertEqual(os.environ['PROGRAM_AREA_VECTOR_STATE'], 'original-state')
            events.append('create')
            return {'candidate_id': 'd' * 64}
        def retain(state, bundle):
            self.assertEqual((state, bundle), ('original-state', 'bundle'))
            self.assertEqual(os.environ['PROGRAM_AREA_VECTOR_STATE'], 'prior-value')
            events.append('retain')
        with patch.object(bridge.recovery, 'MODERN_VERSION', 'program-area-revalidation-modern-1', create=True), \
                patch.object(c, 'read_json', return_value={'version': 'program-area-revalidation-modern-1'}), \
                patch.object(c, 'create', side_effect=create), \
                patch.object(bridge.recovery, 'record_modern_candidate', side_effect=retain, create=True), \
                patch.dict(os.environ, {'PROGRAM_AREA_VECTOR_STATE': 'prior-value'}):
            bridge.persist('root', 'parent', 'receipt', 'bundle', 'original-state')
        self.assertEqual(events, ['create', 'retain'])

    def test_same_run_completed_candidate_does_not_upload_twice_or_overwrite(self):
        workflow = yaml.safe_load((c.ROOT / '.github/workflows/refresh-opportunities.yml').read_text(encoding='utf8'))
        steps = workflow['jobs']['program-area-revalidation']['steps']
        upload = next(step for step in steps if step.get('with', {}).get('name') ==
            'candidate-${{ steps.prepare.outputs.candidate_id || steps.persist.outputs.candidate_id }}')
        self.assertEqual(upload['if'], "steps.restore.outputs.candidate_id == '' && (steps.prepare.outputs.candidate_id == '' || steps.prepare.outputs.upload_candidate == 'true')")
        self.assertNotIn('overwrite', upload['with'])
        # Evaluate the actual simple YAML predicate for initial publication,
        # same-run A2 restoration, and interrupted initial artifact upload.
        for prepared, permitted, expected in [('', '', True), ('d' * 64, 'false', False),
                                                ('d' * 64, 'false', False), ('d' * 64, 'true', True)]:
            expression = upload['if'].replace("steps.restore.outputs.candidate_id", repr(''))
            expression = expression.replace('steps.prepare.outputs.candidate_id', repr(prepared))
            expression = expression.replace('steps.prepare.outputs.upload_candidate', repr(permitted))
            expression = expression.replace('&&', 'and').replace('||', 'or')
            self.assertIs(eval(expression, {'__builtins__': {}}, {}), expected)

    def test_modern_missing_state_or_failed_constructor_never_marks_complete(self):
        with patch.object(bridge.recovery, 'MODERN_VERSION', 'program-area-revalidation-modern-1', create=True), \
                patch.object(c, 'read_json', return_value={'version': 'program-area-revalidation-modern-1'}), \
                patch.object(c, 'create', side_effect=ValueError('constructor-held')) as create, \
                patch.object(bridge.recovery, 'record_modern_candidate', create=True) as retain, \
                patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'original budget state'):
                bridge.persist('root', 'parent', 'receipt', 'bundle')
            create.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'constructor-held'):
                bridge.persist('root', 'parent', 'receipt', 'bundle', 'original-state')
            self.assertNotIn('PROGRAM_AREA_VECTOR_STATE', os.environ)
            retain.assert_not_called()


if __name__ == '__main__':
    unittest.main()
