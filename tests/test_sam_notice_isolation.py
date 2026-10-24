"""Replay real October source amendments without making them global outages."""
from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.currentness import record_is_current
from scripts.sources import sam_preflight, sam_reviewed
from scripts.sources.sam_api import SamError
from tests.test_sam_preflight import HEAD, EVENT
from tests.test_sam_review_continuity import anchored, signed
from tests.test_sam_reviewed import configuration, NOTICE, OTHER, TODAY
from tools.require_sam_refresh import require_complete_refresh

FIXTURE = Path(__file__).parent / 'fixtures/sam_release_amendments_20261024.json'


class SamNoticeIsolationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / 'config').mkdir()
        self.config_path = self.root / 'config/sam_gov.json'
        self.receipt_path = self.root / 'preflight.json'
        self.environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '1234',
            'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': EVENT, 'SAM_PREFLIGHT_RELEASE_SHA': HEAD}
        mocked_git = patch.object(sam_preflight, 'checkout_sha', return_value=HEAD)
        mocked_git.start()
        self.addCleanup(mocked_git.stop)

    def build(self, config, client, checked):
        self.config_path.write_text(json.dumps(config), encoding='utf8')
        receipt = sam_preflight.build_receipt(self.config_path, checked.date(), client=client,
                                             environment=self.environment, checked_at=checked)
        self.receipt_path.write_text(json.dumps(receipt), encoding='utf8')
        return receipt

    def replay(self, checked):
        return sam_preflight.replay_client(self.receipt_path, self.config_path, checked.date(),
                                          environment=self.environment, now=checked)

    def test_real_october21_and24_amendments_quarantine_only_the_changed_calls(self):
        fixture = json.loads(FIXTURE.read_text(encoding='utf8'))
        config = fixture['config']
        for case in fixture['cases']:
            with self.subTest(original_run=case['run_id']):
                checked = datetime.fromisoformat(case['checked_at'])
                public = Mock(side_effect=lambda ident: (deepcopy(case['snapshots'][ident]), {'request_count': 2}))
                receipt = self.build(config, public, checked)
                self.assertTrue(receipt['completed'])
                self.assertEqual(receipt['outcome'], 'verified_degraded')
                self.assertEqual(receipt['failed_reads'], {})
                expected = set(case['expected_review_ids'])
                with patch.object(sam_preflight, 'fetch_notice', side_effect=AssertionError('No fresh source collection')):
                    replay = self.replay(checked)
                    rows, diagnostics = sam_reviewed.collect(config, checked.date(), {}, client=replay)
                observations = diagnostics['notice_observations']
                self.assertEqual({o['notice_id'] for o in observations if o['disposition'] == 'review_required'}, expected)
                self.assertEqual(len(observations), len(config['approved_notices']))
                self.assertEqual(diagnostics['pending_reviews'], [o for o in observations if o['notice_id'] in expected])
                for row in rows:
                    ident = row['opportunity_id'].removeprefix('sam-gov:')
                    if ident in expected:
                        self.assertEqual(row['status'], 'unverified')
                        self.assertFalse(record_is_current(row, checked.date())[0])
                    else:
                        self.assertTrue(record_is_current(row, checked.date())[0])
                require_complete_refresh(config, {'written': True, 'validation': {'ok': True}, 'sources': [
                    {'slug': 'sam-gov', 'status': 'partial_refresh', 'healthy': False, 'diagnostics': diagnostics}]})

    def test_transport_failure_permits_bounded_carry_but_schema_or_successor_failure_does_not(self):
        item = anchored()
        config = configuration(item)
        checked = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        previous, _ = sam_reviewed.reconcile_notice(item['reviewed_snapshot'], item, TODAY)
        cached = previous[0]
        for failure_class, status, successor, fallback in (
                ('transient_transport', 503, False, True), ('timeout', None, False, True),
                ('response_schema', None, False, False), ('nonretry_http', 404, False, False),
                ('transient_transport', 503, True, False)):
            with self.subTest(failure_class=failure_class, successor=successor):
                old = signed(item['reviewed_snapshot'], latest=False, latest_notice_id=OTHER)
                def public(identifier):
                    if successor and identifier == NOTICE:
                        return old, {'request_count': 2}
                    raise SamError('unavailable', {'request_count': 2, 'failure_class': failure_class,
                                                 'http_status': status})
                receipt = self.build(config, public, checked)
                self.assertEqual(receipt['outcome'], 'verified_degraded')
                replay = self.replay(checked)
                rows, diagnostics = sam_reviewed.collect(config, TODAY, {'sam-gov': [cached]}, client=replay)
                self.assertEqual(rows, [])
                observation = diagnostics['notice_observations'][0]
                self.assertEqual(observation['disposition'], 'source_unavailable')
                self.assertIs(observation['fallback_allowed'], fallback)
                self.assertEqual(observation['observed_notice_id'], NOTICE if successor else None)
                self.assertEqual(observation['latest_notice_id'], OTHER if successor else None)

    def test_direct_outage_does_not_turn_previously_reconciled_successor_into_a_new_observation(self):
        item = anchored()
        current = signed(item['reviewed_snapshot'], notice_id=OTHER, latest_notice_id=OTHER)
        (cached, _), _ = sam_reviewed.reconcile_notice(current, item, TODAY)
        self.assertEqual(cached['sam_review_reconciliation']['approved_notice_id'], NOTICE)
        rows, diagnostics = sam_reviewed.collect(configuration(item), TODAY, {'sam-gov': [cached]},
            client=Mock(side_effect=SamError('unavailable', {'request_count': 2,
                'failure_class': 'transient_transport', 'http_status': 503})))
        self.assertEqual(rows, [])
        self.assertTrue(diagnostics['notice_observations'][0]['fallback_allowed'])
        self.assertEqual(cached['source_review_after'], '2026-10-20')

    def test_failed_read_tampering_cannot_change_retention_or_skip_accounting(self):
        checked = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        valid = self.build(configuration(anchored()), Mock(side_effect=SamError('unavailable', {
            'request_count': 2, 'http_status': 503, 'failure_class': 'transient_transport'})), checked)
        variants = []
        altered = deepcopy(valid); altered['failed_reads'] = {}; variants.append(altered)
        altered = deepcopy(valid); altered['failed_reads'][NOTICE]['raw_body'] = 'private'; variants.append(altered)
        altered = deepcopy(valid); altered['failed_reads'][NOTICE]['http_status'] = 200; variants.append(altered)
        altered = deepcopy(valid); altered['failed_reads'][OTHER] = deepcopy(altered['failed_reads'][NOTICE]); variants.append(altered)
        altered = deepcopy(valid); altered['outcome'] = 'verified'; variants.append(altered)
        altered = deepcopy(valid); altered['diagnostics']['accounting_complete'] = False; variants.append(altered)
        altered = deepcopy(valid); altered['diagnostics']['notice_observations'][0]['fallback_allowed'] = False; variants.append(altered)
        altered = deepcopy(valid); altered['snapshots'][NOTICE] = anchored()['reviewed_snapshot']; variants.append(altered)
        for index, receipt in enumerate(variants):
            self.receipt_path.write_text(json.dumps(receipt), encoding='utf8')
            with self.subTest(index=index), patch.object(sam_preflight, 'fetch_notice',
                    side_effect=AssertionError('Invalid receipt must not refetch')), self.assertRaises((ValueError, SamError)):
                self.replay(checked)

    def test_failure_of_one_notice_preserves_exact_verified_peer_in_same_receipt(self):
        first = anchored()
        second = deepcopy(first)
        second.update(notice_id=OTHER, solicitation_number='DARPA-TEST-26-02')
        second['reviewed_snapshot'] = signed(first['reviewed_snapshot'], notice_id=OTHER,
            latest_notice_id=OTHER, solicitation_number=second['solicitation_number'])
        second['review_sha256'] = second['reviewed_snapshot']['review_sha256']
        config = configuration(first)
        config['approved_notices'].append(second)
        def public(identifier):
            if identifier == OTHER:
                raise SamError('unavailable', {'request_count': 2, 'http_status': 503,
                                               'failure_class': 'transient_transport'})
            return deepcopy(first['reviewed_snapshot']), {'request_count': 2}
        checked = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        receipt = self.build(config, public, checked)
        self.assertEqual(set(receipt['snapshots']), {NOTICE})
        self.assertEqual(set(receipt['failed_reads']), {OTHER})
        rows, diagnostics = sam_reviewed.collect(config, TODAY, {}, client=self.replay(checked))
        self.assertEqual([r['opportunity_id'] for r in rows], ['sam-gov:' + NOTICE])
        self.assertEqual(rows[0]['status'], 'posted')
        self.assertEqual(diagnostics['request_count'], 0)
        self.assertEqual(diagnostics['admitted'], 1)


if __name__ == '__main__':
    unittest.main()
