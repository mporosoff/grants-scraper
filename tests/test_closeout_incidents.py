import json
from pathlib import Path
import shutil
import subprocess
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/refresh-opportunities.yml'
HARNESS = """
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
Date.now = () => Date.parse('2026-11-16T20:00:00Z');
const title = 'Funding Finder release checkpoint failed';
let issue = input.initial ? {number: 9, title, body: input.initial} : null;
const history = [], failures = [];
const core = {summary: {addRaw() {return this;}, async write() {}}, setFailed(value) {failures.push(value);}};
const github = {rest: {issues: {
  async listForRepo() {return {data: issue ? [issue] : []};},
  async create(data) {issue = {...data, number: 9}; history.push({method: 'create', ...data});},
  async update(data) {issue = {...issue, ...data}; history.push({method: 'update', ...data});},
}}};
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const run = new AsyncFunction('core', 'github', 'context', input.script);
(async () => {
  for (const entry of input.replays) {
    process.env.RESULTS = JSON.stringify(entry.needs);
    process.env.GITHUB_RUN_ATTEMPT = '1';
    await run(core, github, {runId: entry.id, eventName: 'schedule', sha: 'b'.repeat(40),
      serverUrl: 'https://github.com', repo: {owner: 'o', repo: 'r'}});
  }
  process.stdout.write(JSON.stringify({history, failures}));
})().catch(error => {console.error(error); process.exitCode = 1;});
"""


class CloseoutIncidents(unittest.TestCase):
    def run_closeout(self, categories, initial=None):
        flow = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))['jobs']['closeout']
        replays = []
        for index, kind in enumerate(categories, 1):
            needs = {name: {'result': 'skipped', 'outputs': {}} for name in flow['needs']}
            needs['plan'] = {'result': 'success', 'outputs': {
                'stage': 'noop', 'candidate_id': 'a' * 64, 'candidate_run': '500',
                'daily_window_start': '2026-11-16T10:17:00Z', 'daily_status': 'held',
                'catalog_generated_at': '2026-11-15T19:54:40Z',
                'reason': 'Retained candidate has terminal review findings in PR #412' if kind == 'review_hold'
                          else 'Retained candidate failed unchanged validation',
            }}
            if kind == 'publish':
                needs['publish']['result'] = 'failure'
            if kind == 'recovered':
                needs['verify-live'] = {'result': 'success', 'outputs': {'catalog_generated_at': '2026-11-16T10:18:00Z'}}
            replays.append({'id': 700 + index, 'needs': needs})
        raw = subprocess.check_output([shutil.which('node') or 'node', '-e', HARNESS],
            input=json.dumps({'script': flow['steps'][0]['with']['script'],
                              'replays': replays, 'initial': initial}).encode(), timeout=20)
        return json.loads(raw)

    def test_held_runs_update_the_same_issue_only_on_checkpoint_transition(self):
        result = self.run_closeout(['publish', 'held', 'held', 'recovered'])
        self.assertEqual([row['method'] for row in result['history']], ['create', 'update', 'update'])
        self.assertEqual(len(result['failures']), 3)
        first, latest, closed = (row['body'] for row in result['history'])
        self.assertIn('/runs/701#artifacts', first)
        self.assertIn('/runs/701#artifacts', latest)
        self.assertIn('/runs/702#artifacts', latest)
        self.assertNotIn('/runs/703#artifacts', closed)
        self.assertIn('/runs/701#artifacts', closed)
        self.assertIn('/runs/704#artifacts', closed)
        self.assertEqual(result['history'][-1]['state'], 'closed')

    def test_legacy_issue_report_is_preserved_on_first_update(self):
        result = self.run_closeout(['held', 'held'], initial='Original failure record')
        self.assertEqual(len(result['history']), 1)
        self.assertIn('## First observed failure\n\nOriginal failure record', result['history'][0]['body'])

    def test_same_candidate_new_hold_reason_updates_the_incident(self):
        result = self.run_closeout(['held', 'review_hold', 'review_hold'])
        self.assertEqual([row['method'] for row in result['history']], ['create', 'update'])
        self.assertIn('Retained candidate failed unchanged validation', result['history'][1]['body'])
        self.assertIn('terminal review findings in PR #412', result['history'][1]['body'])
