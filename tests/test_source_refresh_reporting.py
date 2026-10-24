"""Operational reports distinguish notice review from a failed publication."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

from tests import test_catalog_correction_retry as closeout_contract
from tests.test_sam_refresh_guard import receipt
from tests.test_sam_review_continuity import anchored
from tests.test_sam_reviewed import configuration, TODAY
from scripts.sources import sam_reviewed
from scripts.sources.sam_api import SamError
from tools.require_sam_refresh import main as verify_accounting


ROOT = Path(__file__).resolve().parents[1]
# Bounded observation from native preflight 40131924791, not a fabricated status.
NGA_REVIEW = {
    'notice_id': '4984511e4bbc4d01a21df55b30a88f02',
    'observed_notice_id': '854d837d8dc842719d9fec95764d8ceb',
    'latest_notice_id': '854d837d8dc842719d9fec95764d8ceb',
    'review_sha256': '98eb17d9e97616fac43ef74fae9ef5ac0d1e0f4eb065ff39b73cd05aabd0dab4',
    'reasons': ['identity_changed', 'superseded_notice', 'reviewed_evidence_changed'],
    'disposition': 'review_required',
}


class SourceIssueReporting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flow = yaml.safe_load((ROOT / '.github/workflows/refresh-opportunities.yml').read_text(encoding='utf8'))
        cls.step = next(step for step in cls.flow['jobs']['generate']['steps']
                        if step.get('name') == 'Alert the project owner about a degraded external source')

    def render(self, observations, *, sam='success'):
        script = self.step['with']['script']
        for name, outcome in [('additional-sources', 'failure'), ('sam-health', sam), ('document_evidence', 'success')]:
            script = script.replace('${{ steps.' + name + '.outcome }}', outcome)
        source = {'source': 'SAM.gov', 'slug': 'sam-gov', 'status': 'partial_refresh', 'healthy': False,
                  'failure_class': 'review_required', 'publication_decision': 'publish_verified_quarantine_changed',
                  'diagnostics': {'notice_observations': observations}}
        with tempfile.TemporaryDirectory() as temporary:
            Path(temporary, 'source-refresh-summary.json').write_text(
                json.dumps({'written': True, 'validation': {'ok': True}, 'sources': [source]}), encoding='utf8')
            harness = r"""
                const fs = require('node:fs');
                const input = JSON.parse(fs.readFileSync(0, 'utf8'));
                process.env.RUNNER_TEMP = input.temp;
                const observed = {writes: [], warnings: []};
                const core = {warning(value) { observed.warnings.push(value); }};
                const github = {rest: {issues: {
                    async listForRepo() { return {data: [{number: 367, title: 'External funding source refresh degraded'}]}; },
                    async create(value) { observed.writes.push(value); },
                    async update(value) { observed.writes.push(value); }
                }}};
                const context = {runId: 40131924791, serverUrl: 'https://github.com', repo: {owner: 'mporosoff', repo: 'grants-scraper'}};
                const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
                new AsyncFunction('require', 'core', 'github', 'context', input.script)(require, core, github, context)
                  .then(() => process.stdout.write(JSON.stringify(observed)))
                  .catch(error => { console.error(error); process.exitCode = 1; });
            """
            raw = subprocess.check_output([shutil.which('node') or 'node', '-e', harness],
                input=json.dumps({'script': script, 'temp': temporary}).encode(), cwd=ROOT, timeout=30)
        return json.loads(raw)

    def test_real_changed_notice_renders_reason_links_and_review_action_in_same_issue(self):
        result = self.render([deepcopy(NGA_REVIEW), {'disposition': 'admitted'},
                              {'disposition': 'verified_withdrawal'}])
        self.assertEqual(result['warnings'], [])
        self.assertEqual(len(result['writes']), 1)
        self.assertEqual(result['writes'][0]['issue_number'], 367)
        self.assertEqual(result['writes'][0]['state'], 'open')
        body = result['writes'][0]['body']
        self.assertIn('1 admitted; 1 awaiting review; 0 unavailable; 1 verified withdrawals', body)
        self.assertIn('https://sam.gov/opp/' + NGA_REVIEW['notice_id'] + '/view', body)
        self.assertIn('https://sam.gov/opp/' + NGA_REVIEW['latest_notice_id'] + '/view', body)
        self.assertIn('identity_changed, superseded_notice, reviewed_evidence_changed', body)
        self.assertIn('Review the changed official content and eligibility', body)
        self.assertIn('quarantined while verified records can refresh', body)
        self.assertNotIn('generation stopped', body)

    def test_unavailable_notice_and_invalid_accounting_are_not_reported_as_withdrawal(self):
        def failed_read(identifier):
            raise SamError('unavailable', {'request_count': 2, 'failure_class': 'transient_transport', 'http_status': 503})
        _, diagnostics = sam_reviewed.collect(configuration(anchored()), TODAY, {}, client=failed_read)
        self.assertEqual(diagnostics['notice_observations'][0]['disposition'], 'source_unavailable')
        result = self.render(diagnostics['notice_observations'], sam='failure')
        body = result['writes'][0]['body']
        self.assertIn('0 awaiting review; 1 unavailable; 0 verified withdrawals', body)
        self.assertIn('unavailable evidence is not proof that a call closed', body)
        self.assertIn('previously published catalog remains in service', body)

    def test_notice_details_are_bounded_and_links_require_valid_official_identifiers(self):
        rows = [deepcopy(NGA_REVIEW) for _ in range(14)]
        rows[0].update(notice_id='https://evil.test/secret', latest_notice_id='[attack](javascript:bad)',
                       reasons=['bad](https://evil.test)'])
        body = self.render(rows)['writes'][0]['body']
        self.assertIn('14 awaiting review', body)
        self.assertIn('4 more unresolved notices', body)
        self.assertNotIn('evil.test', body)
        self.assertNotIn('javascript:', body)
        self.assertEqual(body.count('https://sam.gov/opp/'), 18)

    def test_accounting_guard_exports_completeness_without_ignoring_validation(self):
        generate = self.flow['jobs']['generate']
        guard = next(step for step in generate['steps'] if step.get('id') == 'sam-health')
        self.assertIn('--github-output "$GITHUB_OUTPUT"', guard['run'])
        self.assertNotIn('continue-on-error', guard)
        self.assertEqual(generate['outputs']['source_completeness'], '${{ steps.sam-health.outputs.source_completeness }}')

    def test_cli_exports_completeness_only_after_valid_accounting_and_counts_other_sources(self):
        for state in ('complete', 'degraded', 'invalid'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'config.json').write_text(json.dumps(configuration()), encoding='utf8')
                summary = receipt()
                if state == 'degraded':
                    summary['sources'].append({'slug': 'other', 'healthy': False})
                if state == 'invalid':
                    summary['written'] = False
                (root / 'summary.json').write_text(json.dumps(summary), encoding='utf8')
                output = root / 'outputs'
                args = ['--config', str(root / 'config.json'), '--summary', str(root / 'summary.json'),
                        '--github-output', str(output)]
                if state == 'invalid':
                    with self.assertRaises(SystemExit):
                        verify_accounting(args)
                    self.assertFalse(output.exists())
                else:
                    verify_accounting(args)
                    self.assertEqual(output.read_text(), f'source_completeness={state}\n')


class PartialReleaseCloseout(unittest.TestCase):
    def test_verified_partial_refresh_succeeds_without_closing_source_review_issue(self):
        closeout_contract.CloseoutRetry.setUpClass()
        runner = closeout_contract.CloseoutRetry()
        result = runner.run_script(stage='generate', event='schedule',
            issues=[{'number': 367, 'title': 'External funding source refresh degraded'},
                    {'number': 368, 'title': 'Funding Finder release checkpoint failed'}],
            jobs={'generate': {'result': 'success', 'outputs': {'source_completeness': 'degraded', 'sources_healthy': 'false'}},
                  'verify-live': {'result': 'success'}})
        self.assertEqual(result['failures'], [])
        self.assertIn('Stage: completed\n', result['body'])
        self.assertIn('Source completeness: degraded\n', result['body'])
        self.assertEqual([write['issue_number'] for write in result['writes']], [368])

    def test_reused_candidate_does_not_claim_a_new_complete_source_scan(self):
        closeout_contract.CloseoutRetry.setUpClass()
        result = closeout_contract.CloseoutRetry().run_script(stage='publish', jobs={'verify-live': {'result': 'success'}})
        self.assertIn('Source completeness: not assessed for this continuation', result['body'])


if __name__ == '__main__':
    unittest.main()
