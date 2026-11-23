"""Topic recovery names one retained parent and cannot select generation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

import yaml
from tools import catalog_correction_release as existing
from tools import program_area_release as bridge, release_candidate as c


class TopicAreaRelease(unittest.TestCase):
    def environment(self, **changes):
        return {'GITHUB_REPOSITORY': 'mporosoff/grants-scraper',
                'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                'GITHUB_WORKFLOW_REF': 'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main',
                'REQUESTED_STAGE': 'topic-area-revalidation', 'CANDIDATE_RUN': '44593967977',
                'CANDIDATE_ID': 'f6f896f6ebef0e0562b5c51e5536c26e39d1549e6b92e5c538cf5973d6cdc9a6', **changes}

    def test_exact_parent_routes_only_to_unpaid_modern_projection(self):
        with patch.object(c, 'git', return_value='b' * 40):
            result = bridge.plan(Path('.'), self.environment())
        self.assertEqual(result['candidate_run'], '44593967977')
        self.assertEqual(result['candidate_id'], self.environment()['CANDIDATE_ID'])
        self.assertEqual((result['stage'], result['program_area_mode'], result['projection_kind']),
                         ('program-area-revalidation', 'modern', 'topic_area'))
        self.assertEqual((result['openai'], result['anthropic']), ('false', 'false'))

    def test_missing_mixed_automatic_and_historical_selectors_cannot_start(self):
        cases = [{'CANDIDATE_ID': ''}, {'CANDIDATE_RUN': ''}, {'RECEIPT_RUN': '9'},
                 {'PUBLICATION_RUN': '9'}, {'PUBLICATION_ATTEMPT': '2'}, {'QUALIFICATION_PILOT': 'true'},
                 {'GITHUB_EVENT_NAME': 'schedule'}, {'GITHUB_REF': 'refs/heads/other'},
                 {'CANDIDATE_ID': bridge.recovery.PARENT_CANDIDATE,
                  'CANDIDATE_RUN': str(bridge.recovery.PARENT_RUN)}]
        for values in cases:
            with self.subTest(values=values), patch.object(c, 'git') as git:
                with self.assertRaises(ValueError):
                    bridge.plan(Path('.'), self.environment(**values))
                git.assert_not_called()

    def test_outer_bridge_never_delegates_exact_topic_resume_to_auto(self):
        environment = self.environment(RUNNER_TEMP='.')
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(bridge, 'plan', return_value={'stage': 'program-area-revalidation',
                    'projection_kind': 'topic_area'}) as explicit, \
                patch.object(existing, 'atomic_json'), patch.object(existing, 'output'), \
                patch('tools.plan_release.main') as ordinary:
            existing.plan()
        explicit.assert_called_once_with(existing.ROOT, environment)
        ordinary.assert_not_called()

    def test_closeout_preserves_topic_recovery_after_projection_failure(self):
        flow = yaml.safe_load((c.ROOT / '.github/workflows/refresh-opportunities.yml').read_text(encoding='utf-8'))
        self.assertIn('topic-area-revalidation', flow[True]['workflow_dispatch']['inputs']['stage']['options'])
        closeout = flow['jobs']['closeout']
        script = closeout['steps'][0]['with']['script']
        needs = {name: {'result': 'skipped', 'outputs': {}} for name in closeout['needs']}
        needs['plan'] = {'result': 'success', 'outputs': {'stage': 'program-area-revalidation',
            'projection_kind': 'topic_area', 'candidate_id': 'a' * 64, 'candidate_run': '123'}}
        needs['program-area-revalidation']['result'] = 'failure'
        harness = """
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
process.env.RESULTS=JSON.stringify(input.needs);process.env.GITHUB_RUN_ATTEMPT='1';
const seen={};const core={summary:{addRaw(body){seen.body=body;return this;},async write(){}},setFailed(){}};
const github={rest:{issues:{async listForRepo(){return {data:[]};},async create(){},async update(){}}}};
const context={runId:700,eventName:'workflow_dispatch',sha:'b'.repeat(40),serverUrl:'https://github.com',repo:{owner:'o',repo:'r'}};
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('core','github','context',input.script)(core,github,context)
 .then(()=>process.stdout.write(JSON.stringify(seen))).catch(e=>{console.error(e);process.exitCode=1;});
"""
        result = json.loads(subprocess.check_output([shutil.which('node') or 'node', '-e', harness],
            input=c.encoded({'script': script, 'needs': needs}), cwd=c.ROOT, timeout=30))
        self.assertIn('Original lifecycle stage: topic-area-revalidation\n', result['body'])
        self.assertIn('Allowed next retry: topic-area-revalidation\n', result['body'])
