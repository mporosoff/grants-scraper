"""Inherited Actions outputs must not turn a failed-job retry into new spending."""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import shlex
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

from scripts.sources import sam_preflight
from scripts.sources.adapters.sam_gov import SamGovAdapter
from scripts.sources.registry import collect as collect_sources
from scripts.sources.sam_api import SamError
from tests.test_release_candidate_gate import evaluate_job_condition, skipped_needs
from tests.test_sam_review_continuity import anchored
from tests.test_sam_reviewed import configuration, NOTICE
from tools import generation_spend_checkpoint as spending
from tools import release_attempt_history as history
from tools import release_candidate as candidate
from tools import sam_refresh_preflight as cli
from tools.offline_spend import Ledger


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'mporosoff/grants-scraper'
RUN = '200'
PLAN_SHA = 'a' * 40
EVENT_SHA = 'b' * 40


class SamFailedJobPreflightIntegration(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); (self.root / 'config').mkdir()
        self.item = anchored()
        self.config_path = self.root / 'config/sam_gov.json'
        self.config_path.write_text(json.dumps(configuration(self.item)), encoding='utf8')
        self.receipt_path = self.root / 'sam-preflight/sam-preflight.json'
        self.now = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        self.environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': RUN, 'GITHUB_RUN_ATTEMPT': '2',
            'GITHUB_SHA': EVENT_SHA, 'SAM_PREFLIGHT_RELEASE_SHA': PLAN_SHA, 'RUNNER_TEMP': str(self.root)}
        self.workflow_raw = (ROOT / history.WORKFLOW).read_text(encoding='utf8')
        self.pages_raw = (ROOT / '.github/workflows/pages.yml').read_text(encoding='utf8')
        self.jobs = yaml.safe_load(self.workflow_raw)['jobs']
        self.steps = self.jobs['generate']['steps']
        self.public = Mock(side_effect=lambda identifier: (
            deepcopy(self.item['reviewed_snapshot']), {'request_count': 2}))
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(sam_preflight, 'checkout_sha', return_value=PLAN_SHA))
        self.stack.enter_context(patch.object(sam_preflight, 'utc_now', side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(sam_preflight, 'fetch_notice', self.public))
        self.stack.enter_context(patch.object(cli, 'CONFIG_PATH', self.config_path))
        outer = self
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None): return outer.now if tz is not None else outer.now.replace(tzinfo=None)
        self.stack.enter_context(patch.object(cli, 'datetime', Clock))
        self.stack.enter_context(patch.dict(os.environ, self.environment, clear=True))
        self.http = self.stack.enter_context(patch('urllib.request.OpenerDirector.open',
            side_effect=AssertionError('Only the bounded public SAM client may read source inputs')))
        self.paid = self.stack.enter_context(patch('requests.sessions.Session.request',
            side_effect=AssertionError('No paid HTTP before source admission')))
        self.downloads, self.uploads, self.executed = [], {}, []

    def receipt(self, attempt, *, checked_at=None):
        checked_at = checked_at or self.now
        return sam_preflight.build_receipt(self.config_path, checked_at.date(),
            environment=self.environment | {'GITHUB_RUN_ATTEMPT': str(attempt)},
            client=lambda identifier: (deepcopy(self.item['reviewed_snapshot']), {'request_count': 2}),
            checked_at=checked_at)

    def context(self, producer_attempt='1', *, complete=False):
        upstream = self.jobs['sam-preflight']
        source = next(step for step in upstream['steps'] if step.get('id') == 'source-check')
        emitted = {}
        for line in re.findall(r'echo "([^"]+)" >> "\$GITHUB_OUTPUT"', source['run']):
            line = line.replace('${GITHUB_RUN_ID}', RUN).replace('$GITHUB_RUN_ID', RUN)
            line = line.replace('${GITHUB_RUN_ATTEMPT}', str(producer_attempt)).replace('$GITHUB_RUN_ATTEMPT', str(producer_attempt))
            key, value = line.split('=', 1); emitted['steps.source-check.outputs.' + key] = value
        outputs = {name: self.render(value, emitted) for name, value in upstream['outputs'].items()}
        self.assertEqual(outputs, {'producer_attempt': str(producer_attempt),
            'artifact_name': f'sam-preflight-{RUN}-{producer_attempt}'})
        return {'github.run_attempt': 2, 'github.run_id': RUN,
            'needs.sam-preflight.result': 'success',
            'needs.sam-preflight.outputs.producer_attempt': outputs['producer_attempt'],
            'needs.sam-preflight.outputs.artifact_name': outputs['artifact_name'],
            'needs.plan.outputs.release_sha': PLAN_SHA,
            'steps.restore.outputs.candidate_id': 'c' * 64 if complete else ''}

    def expression(self, expression, context, *, successful=True):
        expression = str(expression).strip()
        if expression.startswith('${{'): expression = expression[3:-2].strip()
        if not re.search(r'\b(always|success|failure|cancelled)\s*\(', expression) and not successful:
            return False
        def value(match):
            key = match[0]
            if key not in context: return repr('')
            found = context[key]
            return repr(int(found) if isinstance(found, str) and found.isdigit() else found)
        expression = re.sub(r'(?:needs|steps|github|inputs)\.[A-Za-z0-9_.-]+', value, expression)
        expression = expression.replace('always()', 'True').replace('success()', repr(successful))
        expression = expression.replace('failure()', repr(not successful)).replace('cancelled()', 'False')
        expression = expression.replace('&&', ' and ').replace('||', ' or ')
        expression = re.sub(r'!(?!=)', ' not ', expression)
        return bool(eval(expression.strip(), {'__builtins__': {},
            'fromJSON': lambda value: json.loads(value) if isinstance(value, str) else value,
            'contains': lambda values, value: value in values}))

    def render(self, value, context):
        return re.sub(r'\$\{\{\s*([^}]+?)\s*\}\}',
            lambda match: str(context.get(match[1].strip(), '')), str(value))

    def before_budget(self, context, artifacts):
        """Execute the actual pre-spend YAML conditions and public CLI commands."""
        start = next(index for index, step in enumerate(self.steps)
            if step.get('uses', '').startswith('actions/download-artifact@') and 'sam-preflight' in str(step))
        end = next(index for index, step in enumerate(self.steps)
            if 'python -m tools.generation_spend_checkpoint' in step.get('run', ''))
        successful = True
        results = {}
        for step in self.steps[start:end]:
            name = step.get('id', step.get('name', step.get('uses', 'run')))
            if not self.expression(step.get('if', 'success()'), context, successful=successful):
                results[name] = 'skipped'
            elif step.get('uses', '').startswith('actions/download-artifact@'):
                artifact = self.render(step['with']['name'], context)
                self.downloads.append(artifact)
                self.assertIn(artifact, artifacts, 'must not request a nonexistent current-attempt artifact')
                self.receipt_path.parent.mkdir(exist_ok=True)
                self.receipt_path.write_bytes(artifacts[artifact])
                results[name] = 'success'
            elif step.get('uses', '').startswith('actions/upload-artifact@'):
                artifact = self.render(step['with']['name'], context)
                self.assertTrue(self.receipt_path.is_file())
                self.uploads[artifact] = self.receipt_path.read_bytes()
                results[name] = 'success'
            elif 'python -m tools.sam_refresh_preflight' in step.get('run', ''):
                self.assertEqual(step.get('env', {}).get('SAM_PREFLIGHT_RELEASE_SHA'),
                    '${{ needs.plan.outputs.release_sha }}')
                command = step['run'].replace('$RUNNER_TEMP', str(self.root))
                argv = shlex.split(command)
                self.assertEqual(argv[:3], ['python', '-m', 'tools.sam_refresh_preflight'])
                self.executed.append(name)
                with redirect_stdout(io.StringIO()): result = cli.main(argv[3:])
                results[name] = 'success' if result == 0 else 'failure'
            else:
                self.fail('Unexpected work before generation allowance: ' + str(step))
            if step.get('id'):
                context['steps.' + step['id'] + '.outcome'] = results[name]
            if results[name] == 'failure': successful = False
        eligible = self.expression(self.steps[end].get('if', 'success()'), context, successful=successful)
        return eligible, results

    def assert_no_paid_transport(self):
        self.http.assert_not_called(); self.paid.assert_not_called()

    def native_generate_steps(self, attempt, failed):
        context = self.context('1') | {'github.run_attempt': attempt, 'inputs.qualification_pilot': False}
        successful, rows = True, []
        for number, step in enumerate(self.steps, 1):
            name = step.get('name') or ('Run ' + (step.get('uses') or
                (step.get('run', '').splitlines() or ['unnamed'])[0]))
            if not self.expression(step.get('if', 'success()'), context, successful=successful):
                conclusion = 'skipped'
            else:
                conclusion = 'failure' if step.get('id') == failed else 'success'
            if step.get('id'): context['steps.' + step['id'] + '.outcome'] = conclusion
            rows.append({'name': name, 'number': number, 'status': 'completed', 'conclusion': conclusion})
            if conclusion == 'failure': successful = False
        self.assertTrue(any(row['conclusion'] == 'failure' for row in rows))
        return rows

    def first_allocation_history(self):
        current = {'id': 200, 'run_attempt': 3, 'head_sha': EVENT_SHA, 'head_branch': 'main',
            'path': history.WORKFLOW, 'event': 'schedule', 'status': 'in_progress'}
        self.native_attempts = {attempt: current | {'run_attempt': attempt, 'status': 'completed',
            'conclusion': 'failure'} for attempt in (1, 2)}
        self.native_jobs = {}
        for attempt, names in ((1, set(self.jobs)), (2, {'generate', 'candidate', 'validate', 'publish',
                'pages', 'verify-live', 'closeout'})):
            rows = []
            for index, name in enumerate(sorted(names), 1):
                row = {'id': attempt * 1000 + index, 'name': name, 'run_id': 200, 'run_attempt': attempt,
                    'head_sha': EVENT_SHA, 'head_branch': 'main', 'status': 'completed',
                    'conclusion': 'success' if name in ('plan', 'sam-preflight') else
                        'failure' if name in ('generate', 'closeout') else 'skipped'}
                if name == 'generate':
                    row['steps'] = self.native_generate_steps(attempt,
                        'verify-sam-preflight' if attempt == 1 else 'rerun-sam-preflight')
                rows.append(row)
            self.native_jobs[attempt] = rows
        self.native_artifacts = [{'id': index, 'name': name, 'expired': False,
            'digest': 'sha256:' + str(index) * 64,
            'workflow_run': {'id': 200, 'head_branch': 'main', 'head_sha': EVENT_SHA}}
            for index, name in enumerate(('release-plan-1', 'sam-preflight-200-1',
                'sam-preflight-200-2', 'sam-preflight-200-3'), 1)]
        self.native_calls = []
        def api(repository, path):
            self.assertEqual(repository, REPOSITORY); self.native_calls.append(path)
            if path == 'actions/runs/200': return json.dumps(current)
            if path == 'actions/runs/200/artifacts?per_page=100&page=1':
                return json.dumps({'artifacts': self.native_artifacts, 'total_count': len(self.native_artifacts)})
            if path == 'actions/artifacts?per_page=100&page=1':
                return json.dumps({'artifacts': [], 'total_count': 0})
            match = re.fullmatch(r'actions/runs/200/attempts/([12])(?:/jobs\?per_page=100&page=1)?', path)
            if match:
                attempt = int(match[1])
                return json.dumps({'jobs': self.native_jobs[attempt], 'total_count': len(self.native_jobs[attempt])}
                    if '/jobs?' in path else self.native_attempts[attempt])
            self.fail('Unexpected history request: ' + path)
        def git(root, *args):
            self.assertEqual(args[0], 'show')
            if args[1] == EVENT_SHA + ':' + history.WORKFLOW: return self.workflow_raw
            if args[1] == EVENT_SHA + ':.github/workflows/pages.yml': return self.pages_raw
            self.fail('History must authenticate event workflow, separately from plan checkout: ' + repr(args))
        stack = ExitStack()
        stack.enter_context(patch.object(spending, 'api', side_effect=api))
        stack.enter_context(patch.object(candidate, 'git', side_effect=git))
        return stack

    def test_failed_job_retry_refreshes_inherited_attempt1_outputs_and_binds_current_attempt_before_budget(self):
        state = self.root / 'offline-200'
        book = Ledger(state / 'ledger.json', 'offline-200', 2, 300)
        token = book.reserve('anthropic', 'prior-model', 'documents', 'prior', 30, 1)
        book.complete(token, status='complete', charged_microusd=25)
        cache = state / 'cov4-cache/retained.json'; cache.parent.mkdir(); cache.write_bytes(b'{"retained":true}\n')
        before = {str(path.relative_to(state)): path.read_bytes() for path in state.rglob('*') if path.is_file()}
        old = json.dumps(self.receipt(1)).encode()
        eligible, results = self.before_budget(self.context(), {'sam-preflight-200-1': old})
        self.assertTrue(eligible, results)
        self.assertEqual(self.downloads, [])
        self.assertEqual(self.public.call_args_list[0].args, (NOTICE,)); self.assertEqual(self.public.call_count, 1)
        receipt = json.loads(self.receipt_path.read_bytes())
        self.assertEqual((receipt['run_id'], receipt['run_attempt']), ('200', '2'))
        self.assertEqual((receipt['release_sha'], receipt['github_sha']), (PLAN_SHA, EVENT_SHA))
        self.assertEqual(set(self.uploads), {'sam-preflight-200-2'})
        self.assertIn('verify-sam-preflight', self.executed)
        with patch.dict(os.environ, SAM_PREFLIGHT_RECEIPT=str(self.receipt_path)):
            rows, sources = collect_sources([SamGovAdapter(config_path=self.config_path)],
                context={'as_of': self.now.date()})
        self.assertTrue(sources[0].ok, sources[0].error)
        self.assertEqual(rows[0]['opportunity_id'], 'sam-gov:' + NOTICE)
        self.assertEqual(sources[0].diagnostics['request_count'], 0)
        self.assertEqual(self.public.call_count, 1)
        self.assertEqual({str(path.relative_to(state)): path.read_bytes() for path in state.rglob('*') if path.is_file()}, before)
        self.assert_no_paid_transport()

    def test_full_rerun_downloads_new_upstream_attempt2_receipt_without_duplicate_public_reads(self):
        artifact = json.dumps(self.receipt(2)).encode()
        eligible, _ = self.before_budget(self.context('2'), {'sam-preflight-200-2': artifact})
        self.assertTrue(eligible)
        self.assertEqual(self.downloads, ['sam-preflight-200-2'])
        self.assertEqual(self.uploads, {}); self.public.assert_not_called()
        self.assertEqual(self.executed, ['verify-sam-preflight'])
        self.assertEqual(self.receipt_path.read_bytes(), artifact)
        self.assert_no_paid_transport()

    def test_complete_candidate_skips_download_fresh_public_reads_and_verification(self):
        eligible, results = self.before_budget(self.context(complete=True), {})
        self.assertFalse(eligible); self.assertTrue(all(value == 'skipped' for value in results.values()))
        self.assertEqual(self.downloads, []); self.assertEqual(self.uploads, {}); self.assertEqual(self.executed, [])
        self.public.assert_not_called(); self.assertFalse(self.receipt_path.exists())
        self.assert_no_paid_transport()

    def test_failed_upstream_preflight_prevents_generate_even_with_inherited_plan_outputs(self):
        needs = skipped_needs('generate'); needs['sam-preflight']['result'] = 'failure'
        needs['sam-preflight']['outputs'] = {'producer_attempt': '1', 'artifact_name': 'sam-preflight-200-1'}
        self.assertFalse(evaluate_job_condition(self.jobs['generate'], needs))
        self.public.assert_not_called(); self.assert_no_paid_transport()

    def test_verify_only_rejects_stale_attempt_and_newly_expired_terms_before_budget_without_fetch(self):
        exact_age = json.dumps(self.receipt(2, checked_at=self.now - timedelta(hours=2))).encode()
        self.assertTrue(self.before_budget(self.context('2'), {'sam-preflight-200-2': exact_age})[0])
        for kind in ('wrong-attempt', 'stale', 'future'):
            with self.subTest(kind=kind):
                checked = self.now - timedelta(hours=2, seconds=1) if kind == 'stale' else (
                    self.now + timedelta(seconds=1) if kind == 'future' else self.now)
                artifact = json.dumps(self.receipt(1 if kind == 'wrong-attempt' else 2, checked_at=checked)).encode()
                eligible, results = self.before_budget(self.context('2'), {'sam-preflight-200-2': artifact})
                self.assertFalse(eligible); self.assertEqual(results['verify-sam-preflight'], 'failure')
                self.public.assert_not_called()
        self.assert_no_paid_transport()

    def test_transient_public_retry_failure_is_accounted_without_a_second_source_read(self):
        self.public.side_effect = SamError('public_source_unavailable', {'request_count': 2,
            'http_status': 503, 'failure_class': 'transient_transport'})
        eligible, results = self.before_budget(self.context(), {})
        self.assertTrue(eligible)
        self.assertEqual(results['rerun-sam-preflight'], 'success')
        self.assertEqual(results['verify-sam-preflight'], 'success')
        retained = json.loads(self.uploads['sam-preflight-200-2'])
        self.assertTrue(retained['completed']); self.assertEqual(retained['outcome'], 'verified_degraded')
        self.assertEqual(retained['diagnostics']['notice_observations'][0]['disposition'], 'source_unavailable')
        self.assertEqual(self.public.call_count, 1)
        self.assertEqual((retained['run_id'], retained['run_attempt']), ('200', '2'))
        self.assertFalse((self.root / 'offline-200/ledger.json').exists())
        self.assert_no_paid_transport()

    def test_recent_cross_midnight_receipt_is_verified_at_current_admission_date(self):
        self.item['cycles'][0]['entry'].update(date='2026-10-13', time='23:59:59')
        self.config_path.write_text(json.dumps(configuration(self.item)), encoding='utf8')
        checked = datetime(2026, 10, 13, 23, 59, tzinfo=timezone.utc)
        artifact = json.dumps(self.receipt(2, checked_at=checked)).encode()
        self.now = datetime(2026, 10, 14, 0, 1, tzinfo=timezone.utc)
        eligible, _ = self.before_budget(self.context('2'), {'sam-preflight-200-2': artifact})
        self.assertTrue(eligible)
        replay = sam_preflight.replay_client(self.receipt_path, self.config_path, self.now.date())
        rows, _ = sam_preflight.sam_reviewed.collect(configuration(self.item), self.now.date(), {}, client=replay)
        self.assertEqual(rows[0]['status'], 'expired')
        self.assertEqual(replay.preflight_provenance['checked_at'], checked.isoformat())
        self.assertEqual(replay.preflight_provenance['admission_as_of'], '2026-10-14')
        self.public.assert_not_called(); self.assert_no_paid_transport()

    def test_native_preflight_only_failures_allow_first_reservation_after_inherited_failed_job_retry(self):
        state, reservation = self.root / 'offline-200', self.root / 'reservation.json'
        context = self.context('1') | {'github.run_attempt': 3}
        with patch.dict(os.environ, GITHUB_RUN_ATTEMPT='3'):
            eligible, results = self.before_budget(context, {})
            self.assertTrue(eligible, results)
            self.assertEqual(json.loads(self.uploads['sam-preflight-200-3'])['run_attempt'], '3')
            self.assertFalse((state / 'ledger.json').exists(), 'public admission precedes the first allowance')
            with self.first_allocation_history():
                spending.prepare(REPOSITORY, RUN, '3', state, reservation, 'maintenance')
        value = json.loads((state / 'ledger.json').read_bytes())
        self.assertEqual(value['logical_id'], 'offline-200'); self.assertEqual(value['requests'], [])
        self.assertEqual((value['limit_microusd'], value['max_requests']), (2_000_000, 300))
        proof = json.loads((state / 'initial-allocation-provenance.json').read_bytes())
        self.assertFalse(proof['prior_allowance_reserved']); self.assertFalse(proof['prior_provider_dispatch'])
        self.assertEqual([attempt['attempt'] for attempt in proof['prior_attempts']], [1, 2])
        self.assertIn('actions/runs/200/attempts/2/jobs?per_page=100&page=1', self.native_calls)
        self.assertEqual(json.loads(reservation.read_bytes())['first_allocation_proof_sha256'], spending.identity(proof))
        self.assertEqual(self.public.call_count, 1); self.assert_no_paid_transport()

    def test_missing_native_steps_started_source_or_spend_and_untrusted_prior_metadata_cannot_initialize_budget(self):
        for kind in ('missing-native-steps', 'started-source', 'started-spend', 'wrong-event-sha'):
            with self.subTest(kind=kind), self.first_allocation_history():
                generate = next(row for row in self.native_jobs[2] if row['name'] == 'generate')
                if kind == 'missing-native-steps': generate.pop('steps')
                elif kind == 'wrong-event-sha': self.native_attempts[2]['head_sha'] = 'f' * 40
                else:
                    name = ('Build and validate complete public opportunity catalog' if kind == 'started-source'
                        else 'Restore the logical spend checkpoint')
                    next(step for step in generate['steps'] if step['name'] == name)['conclusion'] = 'success'
                with self.assertRaises(ValueError):
                    spending.prepare(REPOSITORY, RUN, '3', self.root / 'offline-200',
                        self.root / 'reservation.json', 'maintenance')
                self.assertFalse((self.root / 'offline-200/ledger.json').exists())
                self.assertFalse((self.root / 'reservation.json').exists())
        self.public.assert_not_called(); self.assert_no_paid_transport()


if __name__ == '__main__':
    unittest.main()
