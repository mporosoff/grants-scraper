"""SAM source admission precedes reservations and replays only exact safe inputs."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date, datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

from scripts.sources import sam_preflight, sam_public
from scripts.sources.adapters.sam_gov import SamGovAdapter
from scripts.sources.registry import collect as registry_collect
from scripts.sources.sam_api import SamError
from tests.test_sam_reviewed import configuration, NOTICE, OTHER, PRIVATE, TODAY
from tests.test_sam_review_continuity import anchored, signed
from tools import sam_refresh_preflight

ROOT = Path(__file__).resolve().parents[1]
HEAD = 'a' * 40
EVENT = 'b' * 40


class SamPreflightContracts(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / 'config').mkdir()
        self.config_path = self.root / 'config/sam_gov.json'
        self.item = anchored()
        self.config_path.write_text(json.dumps(configuration(self.item)), encoding='utf8')
        self.path = self.root / 'sam-preflight.json'
        self.environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '1234', 'GITHUB_RUN_ATTEMPT': '2',
                            'GITHUB_SHA': EVENT, 'SAM_PREFLIGHT_RELEASE_SHA': HEAD}
        git = patch.object(sam_preflight, 'checkout_sha', return_value=HEAD)
        git.start()
        self.addCleanup(git.stop)
        clock = patch.object(sam_preflight, 'utc_now', return_value=datetime(2026, 10, 13, 12, tzinfo=timezone.utc))
        clock.start()
        self.addCleanup(clock.stop)

    def build(self, client=None):
        client = client or Mock(return_value=(deepcopy(self.item['reviewed_snapshot']), {'request_count': 2}))
        return sam_preflight.build_receipt(self.config_path, TODAY, environment=self.environment, client=client)

    def save(self, receipt):
        self.path.write_text(json.dumps(receipt), encoding='utf8')

    def replay(self, *, as_of=TODAY, environment=None):
        return sam_preflight.replay_client(self.path, self.config_path, as_of,
                                          environment=environment or self.environment)

    def test_safe_same_run_receipt_replays_real_adapter_without_http_or_provider_calls(self):
        receipt = self.build()
        self.save(receipt)
        self.assertTrue(receipt['completed'])
        self.assertEqual(receipt['release_sha'], HEAD)
        self.assertEqual(receipt['github_sha'], EVENT)
        self.assertEqual(receipt['diagnostics']['request_count'], 2)
        self.assertNotIn(PRIVATE, self.path.read_text(encoding='utf8'))
        self.assertEqual(set(receipt['snapshots'][NOTICE]), sam_preflight.sam_reviewed.SNAPSHOT_FIELDS)
        adapter = SamGovAdapter(config_path=self.config_path)
        with patch.dict(os.environ, dict(self.environment, SAM_PREFLIGHT_RECEIPT=str(self.path)), clear=True), \
                patch.object(sam_public, 'fetch_notice', side_effect=AssertionError('No new public read')), \
                patch.object(sam_preflight, 'fetch_notice', side_effect=AssertionError('No receipt fallback')), \
                patch('scripts.sources.sam_reviewed.fetch_notice', side_effect=AssertionError('No collection fallback')), \
                patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('No HTTP')), \
                patch('requests.Session.request', side_effect=AssertionError('No provider')):
            rows, results = registry_collect([adapter], context={'as_of': TODAY})
        self.assertTrue(results[0].ok, results[0].error)
        self.assertEqual(rows[0]['opportunity_id'], 'sam-gov:' + NOTICE)
        self.assertEqual(results[0].diagnostics['request_count'], 0)
        proof = results[0].diagnostics['preflight']
        self.assertEqual(proof['public_request_count'], 2)
        self.assertEqual(proof['release_sha'], HEAD)
        self.assertEqual(proof['github_sha'], EVENT)

    def test_one_exact_successor_is_retained_once_and_replays_same_reconciliation(self):
        old = signed(self.item['reviewed_snapshot'], latest=False, latest_notice_id=OTHER)
        current = signed(self.item['reviewed_snapshot'], notice_id=OTHER, latest_notice_id=OTHER,
                         posted_at='2026-10-13', modified_at='2026-10-13')
        client = Mock(side_effect=[(old, {'request_count': 2}), (current, {'request_count': 2})])
        receipt = self.build(client)
        self.assertEqual(client.call_count, 2)
        self.assertTrue(receipt['completed'])
        self.assertEqual(set(receipt['snapshots']), {NOTICE, OTHER})
        self.save(receipt)
        replay = self.replay()
        rows, _ = sam_preflight.sam_reviewed.collect(configuration(self.item), TODAY, {}, client=replay)
        self.assertEqual(rows[0]['opportunity_id'], 'sam-gov:' + OTHER)
        self.assertEqual(rows[0]['sam_review_reconciliation']['approved_notice_id'], NOTICE)

    def test_recent_receipt_crosses_midnight_without_relabelling_source_proof(self):
        before = datetime(2026, 10, 13, 23, 59, tzinfo=timezone.utc)
        after = datetime(2026, 10, 14, 0, 1, tzinfo=timezone.utc)
        with patch.object(sam_preflight, 'utc_now', return_value=before):
            self.save(self.build())
        with patch.object(sam_preflight, 'utc_now', return_value=after):
            replay = self.replay(as_of=after.date())
            rows, _ = sam_preflight.sam_reviewed.collect(configuration(self.item), after.date(), {}, client=replay)
        self.assertEqual(rows[0]['status'], 'posted')
        self.assertEqual(replay.preflight_provenance['checked_at'], before.isoformat())
        self.assertEqual(replay.preflight_provenance['as_of'], before.date().isoformat())
        self.assertEqual(replay.preflight_provenance['admission_as_of'], after.date().isoformat())

    def test_recent_receipt_rechecks_newly_expired_entry_at_merge_date_despite_old_catalog_date(self):
        from scripts.sources.merge import resolve_live_records
        self.item['cycles'][0]['entry'].update(date=TODAY.isoformat(), time='23:59:59')
        self.config_path.write_text(json.dumps(configuration(self.item)), encoding='utf8')
        before = datetime(2026, 10, 13, 23, 59, tzinfo=timezone.utc)
        after = datetime(2026, 10, 14, 0, 1, tzinfo=timezone.utc)
        with patch.object(sam_preflight, 'utc_now', return_value=before):
            receipt = self.build()
            self.save(receipt)
        self.assertEqual(receipt['diagnostics']['admitted'], 1)
        adapter = SamGovAdapter(config_path=self.config_path)
        with patch.object(sam_preflight, 'utc_now', return_value=after), \
                patch.dict(os.environ, dict(self.environment, SAM_PREFLIGHT_RECEIPT=str(self.path)), clear=True), \
                patch('scripts.sources.sam_reviewed.fetch_notice', side_effect=AssertionError('No fresh read')):
            rows, results = registry_collect([adapter], context={'as_of': before.date()})
        self.assertTrue(results[0].ok, results[0].error)
        self.assertEqual(rows[0]['status'], 'expired')
        self.assertEqual(results[0].diagnostics['notice_observations'][0]['disposition'], 'verified_withdrawal')
        live, _, _ = resolve_live_records(results, {}, after.date())
        self.assertEqual(live, [])
        self.assertEqual(results[0].diagnostics['preflight']['checked_at'], before.isoformat())

    def test_two_hour_source_age_limit_and_future_timestamp_fail_closed(self):
        self.save(self.build())
        with patch.object(sam_preflight, 'utc_now', return_value=datetime(2026, 10, 13, 14, tzinfo=timezone.utc)):
            self.replay()
        for now in (datetime(2026, 10, 13, 14, 0, 1, tzinfo=timezone.utc),
                    datetime(2026, 10, 13, 11, 59, 59, tzinfo=timezone.utc)):
            with self.subTest(now=now), patch.object(sam_preflight, 'utc_now', return_value=now), self.assertRaises(ValueError):
                self.replay()
        receipt = self.build()
        receipt['checked_at'] = '2026-10-12T12:00:00+00:00'
        self.save(receipt)
        with self.assertRaises(ValueError): self.replay()

    def test_changed_active_terms_leave_accounted_quarantine_receipt_before_generation(self):
        changed = signed(self.item['reviewed_snapshot'], description_sha256='c' * 64)
        receipt = self.build(Mock(return_value=(changed, {'request_count': 2})))
        self.assertTrue(receipt['completed'])
        self.assertEqual(receipt['outcome'], 'verified_degraded')
        self.assertEqual(receipt['diagnostics']['notice_observations'][0]['disposition'], 'review_required')
        self.assertEqual(receipt['snapshots'][NOTICE]['description_sha256'], 'c' * 64)
        self.save(receipt)
        client = self.replay()
        rows, diagnostics = sam_preflight.sam_reviewed.collect(configuration(self.item), TODAY, {}, client=client)
        self.assertEqual(rows[0]['status'], 'unverified')
        self.assertEqual(diagnostics['outcome'], 'degraded')

    def test_old_entry_closure_cannot_complete_or_replay_a_changed_active_amendment(self):
        checked = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
        changed = signed(self.item['reviewed_snapshot'], description_sha256='1' * 64,
                         resources_sha256='2' * 64, response_deadline='2026-12-20T15:00:00')
        with patch.object(sam_preflight, 'utc_now', return_value=checked):
            receipt = sam_preflight.build_receipt(self.config_path, checked.date(), environment=self.environment,
                client=Mock(return_value=(changed, {'request_count': 2})))
        self.assertTrue(receipt['completed'])
        self.assertEqual(receipt['outcome'], 'verified_degraded')
        observation = receipt['diagnostics']['notice_observations'][0]
        self.assertEqual(observation['reasons'], ['reviewed_evidence_changed', 'entry_closed'])
        self.assertEqual(observation['disposition'], 'review_required')
        # A receipt produced by the old buggy rule is independently reevaluated.
        receipt.update(completed=True, outcome='verified')
        observation['disposition'] = 'verified_withdrawal'
        observation['withdrawal_basis'] = 'unchanged_reviewed_calendar'
        self.save(receipt)
        with patch.object(sam_preflight, 'utc_now', return_value=checked), \
                patch.object(sam_preflight, 'fetch_notice', side_effect=AssertionError('No fallback')), self.assertRaises(ValueError):
            self.replay(as_of=checked.date())

    def test_source_failure_retains_sanitized_counts_without_raw_exception_or_private_body(self):
        receipt = self.build(Mock(side_effect=SamError('RAW EXCEPTION ' + PRIVATE, {
            'request_count': 2, 'http_status': 503, 'failure_class': 'transient_transport', 'raw_body': PRIVATE})))
        self.assertTrue(receipt['completed'])
        self.assertEqual(receipt['outcome'], 'verified_degraded')
        self.assertEqual(receipt['diagnostics']['request_count'], 2)
        encoded = json.dumps(receipt)
        for forbidden in (PRIVATE, 'RAW EXCEPTION', 'raw_body'):
            self.assertNotIn(forbidden, encoded)
        self.save(receipt)
        with patch.object(sam_preflight, 'fetch_notice', side_effect=AssertionError('No second source read')):
            replay = self.replay()
            rows, diagnostics = sam_preflight.sam_reviewed.collect(configuration(self.item), TODAY, {}, client=replay)
        self.assertEqual(rows, [])
        self.assertEqual(diagnostics['request_count'], 0)
        self.assertTrue(diagnostics['notice_observations'][0]['fallback_allowed'])

    def test_run_attempt_event_checkout_and_config_each_bind_replay(self):
        self.save(self.build())
        for key, value in [('GITHUB_RUN_ID', '5678'), ('GITHUB_RUN_ATTEMPT', '3'),
                           ('GITHUB_SHA', 'c' * 40), ('SAM_PREFLIGHT_RELEASE_SHA', 'c' * 40)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.replay(environment=dict(self.environment, **{key: value}))
        with self.assertRaises(ValueError): self.replay(as_of=date(2026, 10, 14))
        self.config_path.write_text(self.config_path.read_text(encoding='utf8') + '\n', encoding='utf8')
        with self.assertRaises(ValueError): self.replay()

    def test_malformed_incomplete_extra_missing_or_tampered_snapshots_cannot_replay(self):
        valid = self.build()
        variants = []
        for key, value in [('completed', False), ('schema_version', True), ('outcome', 'review_required'),
                           ('snapshots', {}), ('private_body', PRIVATE)]:
            item = deepcopy(valid); item[key] = value; variants.append(item)
        item = deepcopy(valid); item['snapshots'][NOTICE]['raw_description'] = PRIVATE; variants.append(item)
        item = deepcopy(valid); item['snapshots'][NOTICE]['description_sha256'] = 'c' * 64; variants.append(item)
        item = deepcopy(valid); item['snapshots'][OTHER] = signed(item['snapshots'][NOTICE], notice_id=OTHER, latest_notice_id=OTHER); variants.append(item)
        item = deepcopy(valid); item['diagnostics']['notice_observations'][0]['reasons'] = ['entry_closed']; variants.append(item)
        for index, item in enumerate(variants):
            self.save(item)
            with self.subTest(index=index), self.assertRaises((ValueError, SamError)):
                self.replay()
        for value in ('not-json', 'x' * (sam_preflight.MAX_RECEIPT_BYTES + 1)):
            self.path.write_text(value, encoding='utf8')
            with self.assertRaises(ValueError): self.replay()

    def test_invalid_receipt_env_never_falls_back_to_fresh_collection(self):
        self.path.write_text('{}', encoding='utf8')
        adapter = SamGovAdapter(config_path=self.config_path)
        with patch.dict(os.environ, dict(self.environment, SAM_PREFLIGHT_RECEIPT=str(self.path)), clear=True), \
                patch('scripts.sources.sam_reviewed.fetch_notice', side_effect=AssertionError('No fallback')) as public:
            rows, results = registry_collect([adapter], context={'as_of': TODAY})
        self.assertFalse(results[0].ok)
        self.assertEqual(rows, [])
        public.assert_not_called()

    def test_mismatched_checkout_fails_before_a_public_read(self):
        client = Mock()
        with patch.object(sam_preflight, 'checkout_sha', return_value='c' * 40), self.assertRaises(ValueError):
            self.build(client)
        client.assert_not_called()

    def test_cli_persists_success_and_sanitized_context_failure(self):
        receipt = self.build()
        for value in (receipt, ValueError('RAW ' + PRIVATE)):
            with patch.object(sam_refresh_preflight, 'build_receipt', side_effect=[value]), \
                    redirect_stdout(io.StringIO()) as stdout:
                result = sam_refresh_preflight.main(['--config', str(self.config_path), '--output', str(self.path)])
            saved = json.loads(self.path.read_text(encoding='utf8'))
            self.assertEqual(result, 0 if isinstance(value, dict) else 1)
            self.assertEqual(saved['completed'], isinstance(value, dict))
            self.assertNotIn(PRIVATE, self.path.read_text(encoding='utf8') + stdout.getvalue())
        self.assertFalse(self.path.with_suffix('.json.tmp').exists())

    def test_cli_verify_only_replays_current_binding_without_fetching_or_rewriting(self):
        self.save(self.build())
        saved = self.path.read_bytes()
        now = datetime(2026, 10, 13, 12, 5, tzinfo=timezone.utc)
        with patch.dict(os.environ, self.environment, clear=True), \
                patch.object(sam_refresh_preflight, 'datetime') as clock, \
                patch.object(sam_refresh_preflight, 'build_receipt', side_effect=AssertionError('No source collection')), \
                patch.object(sam_preflight, 'fetch_notice', side_effect=AssertionError('No HTTP')), \
                redirect_stdout(io.StringIO()) as stdout:
            clock.now.return_value = now
            result = sam_refresh_preflight.main(['--verify-only', '--config', str(self.config_path), '--output', str(self.path)])
        self.assertEqual(result, 0)
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertEqual(json.loads(stdout.getvalue()), {'completed': True, 'outcome': 'verified', 'request_count': 0})

    def test_cli_verify_only_holds_invalid_receipt_and_preserves_failed_evidence(self):
        valid = self.build()
        for variant in ('attempt', 'age', 'failed', 'config', 'missing'):
            with self.subTest(variant=variant):
                receipt = deepcopy(valid)
                environment = dict(self.environment)
                now = datetime(2026, 10, 13, 12, 5, tzinfo=timezone.utc)
                if variant == 'attempt': environment['GITHUB_RUN_ATTEMPT'] = '3'
                if variant == 'age': now = datetime(2026, 10, 13, 14, 0, 1, tzinfo=timezone.utc)
                if variant == 'failed': receipt.update(completed=False, outcome='review_required')
                if variant == 'config': receipt['config_sha256'] = 'f' * 64
                self.save(receipt)
                if variant == 'missing': self.path.unlink()
                before = self.path.read_bytes() if self.path.exists() else None
                with patch.dict(os.environ, environment, clear=True), \
                        patch.object(sam_refresh_preflight, 'datetime') as clock, \
                        patch.object(sam_refresh_preflight, 'build_receipt', side_effect=AssertionError('No fallback')), \
                        patch.object(sam_preflight, 'fetch_notice', side_effect=AssertionError('No HTTP')), \
                        redirect_stdout(io.StringIO()) as stdout:
                    clock.now.return_value = now
                    result = sam_refresh_preflight.main(['--verify-only', '--config', str(self.config_path), '--output', str(self.path)])
                self.assertEqual(result, 1)
                self.assertEqual(self.path.read_bytes() if self.path.exists() else None, before)
                self.assertEqual(json.loads(stdout.getvalue())['request_count'], 0)


class SamPreflightWorkflowContracts(unittest.TestCase):
    def test_preflight_gates_generation_before_reservation_and_uses_same_run_public_receipt(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/refresh-opportunities.yml').read_text(encoding='utf8'))
        jobs = workflow['jobs']
        preflight = jobs['sam-preflight']
        self.assertEqual(preflight['needs'], 'plan')
        self.assertEqual(preflight['if'], "needs.plan.outputs.stage == 'generate'")
        self.assertEqual(preflight['env']['SAM_PREFLIGHT_RELEASE_SHA'], '${{ needs.plan.outputs.release_sha }}')
        checkout = preflight['steps'][0]
        self.assertEqual(checkout['with']['ref'], '${{ needs.plan.outputs.release_sha }}')
        serialized = json.dumps(preflight)
        self.assertIn('python -m tools.sam_refresh_preflight --output', serialized)
        for forbidden in ('secrets.', 'generation_spend_checkpoint', 'scripts.build_catalog', 'scripts.enrich_catalog'):
            self.assertNotIn(forbidden, serialized)
        upload = next(step for step in preflight['steps'] if step.get('uses', '').startswith('actions/upload-artifact@'))
        self.assertEqual(upload['with']['name'], 'sam-preflight-${{ github.run_id }}-${{ github.run_attempt }}')
        self.assertEqual(upload['if'], 'always()')
        self.assertIn('sam-preflight', jobs['generate']['needs'])
        self.assertNotIn('always()', jobs['generate']['if'])
        steps = jobs['generate']['steps']
        source = next(step for step in preflight['steps'] if step.get('id') == 'source-check')
        for key in ('producer_attempt', 'artifact_name'):
            self.assertEqual(preflight['outputs'][key], '${{ steps.source-check.outputs.' + key + ' }}')
            self.assertIn('echo "' + key + '=', source['run'])
        download = next(step for step in steps if step.get('id') == 'download-sam-preflight')
        self.assertTrue(download['uses'].startswith('actions/download-artifact@'))
        self.assertEqual(download['with']['name'], '${{ needs.sam-preflight.outputs.artifact_name }}')
        self.assertIn('needs.sam-preflight.outputs.producer_attempt == github.run_attempt', download['if'])
        fresh = next(step for step in steps if step.get('id') == 'rerun-sam-preflight')
        self.assertIn("needs.sam-preflight.result == 'success'", fresh['if'])
        self.assertIn('fromJSON(needs.sam-preflight.outputs.producer_attempt) < fromJSON(github.run_attempt)', fresh['if'])
        retained = next(step for step in steps if step.get('id') == 'retain-rerun-sam-preflight')
        self.assertIn('always()', retained['if'])
        self.assertEqual(retained['with']['name'], upload['with']['name'])
        verify = next(step for step in steps if step.get('id') == 'verify-sam-preflight')
        self.assertIn('--verify-only', verify['run'])
        spend = next(step for step in steps if 'python -m tools.generation_spend_checkpoint' in step.get('run', ''))
        self.assertLess(steps.index(retained), steps.index(verify))
        self.assertLess(steps.index(verify), steps.index(spend))
        for step in (download, fresh, verify):
            self.assertIn("steps.restore.outputs.candidate_id == ''", step['if'])
        for step in (fresh, verify):
            self.assertEqual(step['env']['SAM_PREFLIGHT_RELEASE_SHA'], '${{ needs.plan.outputs.release_sha }}')
            self.assertNotIn('secrets.', json.dumps(step))
        merge = next(step for step in steps if step.get('id') == 'additional-sources')
        self.assertEqual(merge['env']['SAM_PREFLIGHT_RECEIPT'], '${{ runner.temp }}/sam-preflight/sam-preflight.json')
        self.assertEqual(merge['env']['SAM_PREFLIGHT_RELEASE_SHA'], '${{ needs.plan.outputs.release_sha }}')
        self.assertIn('sam-preflight', jobs['closeout']['needs'])
        policy = json.loads((ROOT / 'config/release_dependencies.json').read_text(encoding='utf8'))
        for values in (policy['generation'], policy['dependency_groups']['source']['patterns']):
            self.assertIn('tools/sam_refresh_preflight.py', values)
            self.assertIn('scripts/sources/**/*.py', values)


if __name__ == '__main__':
    unittest.main()
