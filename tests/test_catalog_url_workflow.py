"""Exclusive provider-free URL recovery routing and checkpoint contracts."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import yaml

from tools import catalog_correction_release as bridge


STAGE = 'catalog-url-correction'
PARENT = '051d6844ea23709628b9c9209f4a947e309d2427928b0dc19e8ffb8eb8f3cfc4'


class UrlWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flow = yaml.safe_load((bridge.ROOT / '.github/workflows/refresh-opportunities.yml').read_text(encoding='utf8'))
        cls.jobs = cls.flow['jobs']
        cls.job = cls.jobs[STAGE]
        cls.steps = cls.job['steps']
        cls.by_id = {s['id']: s for s in cls.steps if 'id' in s}

    def test_exclusive_provider_free_job_has_no_allowance_or_generation_entrypoint(self):
        self.assertIn(STAGE, self.flow[True]['workflow_dispatch']['inputs']['stage']['options'])
        self.assertEqual(self.job['needs'], 'plan')
        self.assertEqual(self.job['env']['REQUESTED_STAGE'], STAGE)
        self.assertEqual(self.job['if'], "needs.plan.outputs.stage == 'catalog-url-correction'")
        text = json.dumps(self.job)
        self.assertNotRegex(text, r'(?i)OPENAI_API_KEY|ANTHROPIC_API_KEY|VOYAGE_API_KEY|secrets\.|max(?:imum)?_.*spend|run_budgeted_documents|build_search_v2_voyage_vectors|build_opportunity_teams|offline_ai\.reserve|playwright|test:e2e')
        self.assertEqual(self.job['env']['CANDIDATE_RUN'], '${{ needs.plan.outputs.candidate_run }}')
        self.assertEqual(self.job['env']['CANDIDATE_ID'], '${{ needs.plan.outputs.candidate_id }}')
        settings = json.loads((bridge.ROOT / 'config/offline_ai.json').read_bytes())
        self.assertIs(settings['production_services']['teams']['enabled'], False)

    def test_restore_precedes_projection_and_receipt_stays_separate(self):
        restore, persist = self.by_id['restore'], self.by_id['persist']
        self.assertEqual(restore['run'], 'python -m tools.restore_generation_checkpoint')
        self.assertLess(self.steps.index(restore), self.steps.index(persist))
        self.assertIn('python -m tools.catalog_url_correction --parent-bundle', persist['run'])
        self.assertIn('--receipt "$RUNNER_TEMP/url-correction/receipt.json"', persist['run'])
        self.assertNotIn('tools.catalog_source_recovery', persist['run'])
        for step in self.steps[self.steps.index(restore) + 1:]:
            self.assertIn("steps.restore.outputs.candidate_id == ''", step['if'])
        uploads = [s for s in self.steps if s.get('uses') == 'actions/upload-artifact@v4']
        self.assertEqual([s['with']['path'] for s in uploads],
                         ['${{ runner.temp }}/candidate', '${{ runner.temp }}/url-correction'])
        self.assertEqual(uploads[1]['with']['name'], 'url-correction-${{ github.run_id }}-${{ github.run_attempt }}')
        self.assertIs(uploads[0]['with']['include-hidden-files'], True)
        self.assertIn("steps.persist.outcome == 'success'", uploads[0]['if'])
        for upload in uploads:
            self.assertIsNot(upload['with'].get('overwrite'), True)

    def test_candidate_and_closeout_keep_child_identity_and_normal_gates(self):
        candidate = self.jobs['candidate']
        self.assertIn(STAGE, candidate['needs'])
        self.assertIn("needs.catalog-url-correction.result == 'success'", candidate['if'])
        self.assertIn("needs.catalog-url-correction.result == 'skipped'", candidate['if'])
        select = next(s for s in candidate['steps'] if s.get('id') == 'select')
        self.assertIn('needs.catalog-url-correction.outputs.candidate_id', select['env']['GENERATED_ID'])
        self.assertIn('candidate_run=$GITHUB_RUN_ID', select['run'])
        self.assertEqual(self.jobs['validate']['needs'], ['plan', 'candidate'])
        self.assertIn('validate', self.jobs['publish']['needs'])
        self.assertIn(STAGE, self.jobs['closeout']['needs'])
        self.assertIn("'catalog-url-correction'", self.jobs['closeout']['steps'][0]['with']['script'])
        self.assertEqual(self.jobs['catalog-identity-correction']['if'],
                         "needs.plan.outputs.stage == 'catalog-identity-correction'")
        self.assertEqual(self.jobs['catalog-access-correction']['if'],
                         "needs.plan.outputs.stage == 'catalog-access-correction'")
        original = self.jobs['catalog-source-recovery']
        self.assertEqual(original['if'], "needs.plan.outputs.stage == 'catalog-source-recovery'")
        self.assertIn('tools.catalog_source_recovery', next(s['run'] for s in original['steps'] if s.get('id') == 'persist'))


class UrlBridgeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.helper = ModuleType('tools.catalog_url_correction')
        self.helper.plan = Mock(return_value={'stage': STAGE, 'candidate_run': '38280685194',
            'candidate_id': PARENT, 'release_sha': 'a' * 40, 'openai': 'false', 'anthropic': 'false'})
        modules = patch.dict(sys.modules, {'tools.catalog_url_correction': self.helper})
        modules.start()
        self.addCleanup(modules.stop)
        self.env = {'REQUESTED_STAGE': STAGE, 'RUNNER_TEMP': str(self.root),
                    'CANDIDATE_RUN': '38280685194', 'CANDIDATE_ID': PARENT}

    def test_only_explicit_new_mode_calls_url_planner_and_preserves_exact_result(self):
        with patch.dict(os.environ, self.env, clear=True), patch.object(bridge, 'output') as output, \
                patch.object(bridge, 'correction_complete', side_effect=AssertionError('must not use ordinary planning')):
            bridge.plan()
        self.helper.plan.assert_called_once_with(bridge.ROOT, self.env)
        value = json.loads((self.root / 'release-plan.json').read_bytes())
        self.assertEqual(value, self.helper.plan.return_value)
        output.assert_called_once_with(value)

    def test_auto_and_named_validation_never_enter_the_new_correction(self):
        with patch.dict(os.environ, self.env | {'REQUESTED_STAGE': 'auto'}, clear=True), \
                patch.object(bridge, 'correction_complete', return_value=False), patch.object(bridge, 'output'), \
                patch.object(bridge.release, 'git', return_value='a' * 40):
            bridge.plan()
        self.assertEqual(json.loads((self.root / 'release-plan.json').read_bytes())['stage'], 'noop')
        with patch.dict(os.environ, self.env | {'REQUESTED_STAGE': 'validate'}, clear=True), \
                patch('tools.plan_release.main', return_value='named-checkpoint') as ordinary:
            self.assertEqual(bridge.plan(), 'named-checkpoint')
        ordinary.assert_called_once_with()
        self.helper.plan.assert_not_called()

    def test_original_source_recovery_keeps_its_existing_planner(self):
        expected = {'stage': 'catalog-source-recovery', 'openai': 'false', 'anthropic': 'false'}
        with patch.dict(os.environ, self.env | {'REQUESTED_STAGE': 'catalog-source-recovery'}, clear=True), \
                patch('tools.catalog_source_recovery.plan', return_value=expected) as original, \
                patch.object(bridge, 'output') as output:
            bridge.plan()
        original.assert_called_once()
        output.assert_called_once_with(expected)
        self.helper.plan.assert_not_called()


if __name__ == '__main__':
    unittest.main()
