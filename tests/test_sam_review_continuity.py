"""Bounded SAM version continuity preserves reviewed terms and real closures."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.sources import sam_public, sam_reviewed
from scripts.sources.sam_api import SamError
from scripts.sources.adapters.sam_gov import SamGovAdapter
from scripts.sources.merge import integrate, load_catalog, save_catalog
from tests.test_sam_reviewed import approval, configuration, payload, resources, NOTICE, OTHER, TODAY
from tools.require_sam_refresh import require_complete_refresh

ROOT = Path(__file__).resolve().parents[1]


def signed(notice, **changes):
    notice = dict(deepcopy(notice), **changes)
    notice['review_sha256'] = sam_public.digest({k: v for k, v in notice.items() if k != 'review_sha256'})
    return notice


def anchored():
    item = approval()
    item['reviewed_snapshot'] = sam_public.snapshot(payload(), resources(), NOTICE)
    return item


def summary(diagnostics):
    return {'written': True, 'validation': {'ok': True}, 'sources': [
        {'slug': 'sam-gov', 'healthy': True, 'status': 'refreshed', 'diagnostics': diagnostics}]}


class ReviewContinuityTests(unittest.TestCase):
    def test_real_incremental_merge_replaces_old_version_without_losing_the_call(self):
        item = anchored()
        cached, _ = sam_reviewed.make_record(item['reviewed_snapshot'], item, TODAY)
        old = signed(item['reviewed_snapshot'], latest=False, latest_notice_id=OTHER)
        current = signed(item['reviewed_snapshot'], notice_id=OTHER, latest_notice_id=OTHER,
                         posted_at='2026-10-13T01:00:00+00:00', modified_at='2026-10-13T01:00:00+00:00')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / 'sam.json'
            config_path.write_text(json.dumps(configuration(item)), encoding='utf8')
            catalog = root / 'catalog.js'
            cache = root / 'cache.json'
            save_catalog({'generated_at': '2026-10-13T12:00:00Z', 'opportunities': [cached]}, catalog)
            cache.write_text(json.dumps({'schema_version': 1, 'sources': {'sam-gov': {
                'fetched_at': '2026-10-12T12:00:00Z', 'records': [cached]}}}), encoding='utf8')
            client = Mock(side_effect=lambda identifier: (old if identifier == NOTICE else current, {'request_count': 2}))
            adapter = SamGovAdapter(config_path=config_path, reviewed_client=client)
            with patch.dict('os.environ', {'VPR_ENRICH_LINKS': 'false'}):
                result = integrate(catalog_path=catalog, cache_path=cache, adapters=[adapter], as_of=TODAY, write=True)
            require_complete_refresh(configuration(item), result)
            records = load_catalog(catalog)['opportunities']
            self.assertEqual([row['opportunity_id'] for row in records], ['sam-gov:' + OTHER])
            self.assertEqual(records[0]['status'], 'posted')
            self.assertEqual(records[0]['sam_review_reconciliation']['approved_notice_id'], NOTICE)

    def test_exact_administrative_successor_relinks_canonical_identity_and_cached_successor_once(self):
        item = anchored()
        old = signed(item['reviewed_snapshot'], latest=False, latest_notice_id=OTHER)
        current = signed(item['reviewed_snapshot'], notice_id=OTHER, latest_notice_id=OTHER,
                         posted_at='2026-10-13T01:00:00+00:00', modified_at='2026-10-13T01:00:00+00:00')
        client = Mock(side_effect=lambda identifier: (old if identifier == NOTICE else current, {'request_count': 2}))
        cached, _ = sam_reviewed.make_record(current, dict(item, notice_id=OTHER, review_sha256=current['review_sha256']), TODAY)
        rows, diagnostics = sam_reviewed.collect(configuration(item), TODAY, {'sam-gov': [cached]}, client=client)
        self.assertEqual([call.args for call in client.call_args_list], [(NOTICE,), (OTHER,)])
        self.assertEqual(len(rows), 1)
        record = rows[0]
        self.assertEqual(record['opportunity_id'], 'sam-gov:' + OTHER)
        self.assertEqual(record['detail_page'], 'https://sam.gov/opp/' + OTHER + '/view')
        self.assertEqual(record['status'], 'posted')
        self.assertEqual(record['eligibility_text'], item['academic_eligibility_quote'])
        self.assertEqual([event['date'] for event in record['deadlines']], ['2026-10-20', '2026-12-10'])
        proof = record['sam_review_reconciliation']
        self.assertEqual(proof['approved_notice_id'], NOTICE)
        self.assertEqual(proof['current_notice_id'], OTHER)
        self.assertEqual(proof['approved_review_sha256'], item['review_sha256'])
        self.assertEqual(record['sam_approval_sha256'], sam_public.digest(item))
        self.assertEqual(diagnostics['request_count'], 4)
        require_complete_refresh(configuration(item), summary(diagnostics))

    def test_unchanged_terms_receive_fresh_bounded_currentness_after_original_review_date(self):
        item = anchored()
        item['cycles'][0]['entry']['date'] = '2026-11-20'
        original = deepcopy(item)
        as_of = date(2026, 11, 13)
        rows, diagnostics = sam_reviewed.collect(configuration(item), as_of, {}, client=Mock(
            return_value=(item['reviewed_snapshot'], {'request_count': 2})))
        record = rows[0]
        self.assertEqual(item, original)
        self.assertEqual(record['status'], 'posted')
        self.assertEqual(record['source_review_after'], '2026-11-20')
        self.assertEqual(record['page_field_provenance']['eligibility_text']['fetched_at'], '2026-10-13')
        self.assertEqual(record['sam_review_reconciliation'], {
            'approved_notice_id': NOTICE, 'current_notice_id': NOTICE,
            'approved_review_sha256': item['review_sha256'], 'current_review_sha256': item['review_sha256'],
            'reviewed_content_sha256': sam_public.digest(sam_reviewed.reviewed_content(item['reviewed_snapshot'])),
            'method': 'exact_reviewed_content', 'reviewed_on': '2026-10-13',
            'original_review_after': '2026-11-12', 'current_verified_on': '2026-11-13',
            'current_review_after': '2026-11-20'})
        self.assertEqual(diagnostics['notice_observations'][0]['disposition'], 'admitted')

    def test_same_id_metadata_change_is_accepted_but_future_approval_is_not(self):
        item = anchored()
        current = signed(item['reviewed_snapshot'], modified_at='2026-10-13T01:00:00+00:00')
        (record, reasons), proof = sam_reviewed.reconcile_notice(current, item, TODAY)
        self.assertEqual(reasons, [])
        self.assertEqual(record['sam_review_reconciliation'], proof)
        (_, reasons), proof = sam_reviewed.reconcile_notice(current, item, date(2026, 10, 12))
        self.assertIn('approval_not_current', reasons)
        self.assertIsNone(proof)

    def test_each_material_change_requires_review_even_after_original_approval_expiry(self):
        item = anchored()
        item['cycles'][0]['entry']['date'] = '2026-11-20'
        changes = {'description_sha256': '0' * 64, 'resources_sha256': '0' * 64,
                   'response_deadline': '2026-12-11T15:00:00', 'response_timezone': 'America/Denver',
                   'organization_id': '98765', 'solicitation_number': 'ANOTHER-CALL',
                   'title': 'A different research program', 'notice_type': 's',
                   'classification_code': 'AD11', 'naics_codes': ['541330']}
        for field, value in changes.items():
            with self.subTest(field=field):
                current = signed(item['reviewed_snapshot'], **{field: value})
                rows, diagnostics = sam_reviewed.collect(configuration(item), date(2026, 11, 13), {},
                    client=Mock(return_value=(current, {'request_count': 2})))
                self.assertNotEqual(rows[0]['status'], 'posted')
                self.assertNotIn('sam_review_reconciliation', rows[0])
                self.assertEqual(diagnostics['notice_observations'][0]['disposition'], 'review_required')
                with self.assertRaises(ValueError): require_complete_refresh(configuration(item), summary(diagnostics))

    def test_expired_entries_and_current_confirmed_withdrawals_remain_permitted(self):
        item = anchored()
        for changes in ({}, {'archived': True}, {'cancelled': True}, {'deleted': True},
                        {'status': 'withdrawn'}, {'set_asides': ['SBA']}):
            with self.subTest(changes=changes):
                current = signed(item['reviewed_snapshot'], **changes)
                as_of = TODAY if changes else date(2026, 10, 21)
                rows, diagnostics = sam_reviewed.collect(configuration(item), as_of, {},
                    client=Mock(return_value=(current, {'request_count': 2})))
                self.assertNotEqual(rows[0]['status'], 'posted')
                self.assertEqual(diagnostics['notice_observations'][0]['disposition'], 'verified_withdrawal')
                require_complete_refresh(configuration(item), summary(diagnostics))

    def test_active_amendment_extension_cannot_be_withdrawn_using_the_old_reviewed_entry(self):
        item = anchored()
        current = signed(item['reviewed_snapshot'], description_sha256='1' * 64,
                         resources_sha256='2' * 64, response_deadline='2026-12-20T15:00:00')
        rows, diagnostics = sam_reviewed.collect(configuration(item), date(2026, 10, 21), {},
            client=Mock(return_value=(current, {'request_count': 2})))
        observation = diagnostics['notice_observations'][0]
        self.assertEqual(observation['reasons'], ['reviewed_evidence_changed', 'entry_closed'])
        self.assertEqual(observation['disposition'], 'review_required')
        self.assertNotIn('withdrawal_basis', observation)
        with self.assertRaises(ValueError): require_complete_refresh(configuration(item), summary(diagnostics))
        self.assertNotEqual(rows[0]['status'], 'posted')

    def test_old_calendar_cannot_mask_other_unresolved_changes_or_another_successor(self):
        item = anchored()
        changes = [{'archive_date': '2026-10-20', 'description_sha256': '1' * 64,
                    'response_deadline': '2026-12-20T15:00:00'},
                   {'posted_at': '2026-10-22T12:00:00+00:00'}, {'notice_type': 'r'}]
        for change in changes:
            with self.subTest(change=change):
                current = signed(item['reviewed_snapshot'], **change)
                _, diagnostics = sam_reviewed.collect(configuration(item), date(2026, 10, 21), {},
                    client=Mock(return_value=(current, {'request_count': 2})))
                self.assertEqual(diagnostics['notice_observations'][0]['disposition'], 'review_required')
                with self.assertRaises(ValueError): require_complete_refresh(configuration(item), summary(diagnostics))
        old = signed(item['reviewed_snapshot'], latest=False, latest_notice_id=OTHER)
        for terminal in (False, True):
            intermediate = signed(old, notice_id=OTHER, latest_notice_id='c' * 32, archived=terminal)
            _, diagnostics = sam_reviewed.collect(configuration(item), date(2026, 10, 21), {},
                client=Mock(side_effect=[(old, {'request_count': 2}), (intermediate, {'request_count': 2})]))
            self.assertEqual(diagnostics['notice_observations'][0]['disposition'], 'review_required')
            with self.assertRaises(ValueError): require_complete_refresh(configuration(item), summary(diagnostics))

    def test_current_true_terminal_or_restricted_successor_can_withdraw_despite_changed_terms(self):
        item = anchored()
        old = signed(item['reviewed_snapshot'], latest=False, latest_notice_id=OTHER)
        for change in ({'cancelled': True}, {'archived': True}, {'deleted': True},
                       {'status': 'withdrawn'}, {'set_asides': ['SBA']}):
            current = signed(item['reviewed_snapshot'], notice_id=OTHER, latest_notice_id=OTHER,
                             description_sha256='1' * 64, resources_sha256='2' * 64,
                             response_deadline='2026-12-20T15:00:00', **change)
            with self.subTest(change=change):
                _, diagnostics = sam_reviewed.collect(configuration(item), date(2026, 10, 21), {},
                    client=Mock(side_effect=[(old, {'request_count': 2}), (current, {'request_count': 2})]))
                observation = diagnostics['notice_observations'][0]
                self.assertEqual(observation['disposition'], 'verified_withdrawal')
                self.assertEqual(observation['withdrawal_basis'], 'current_restrictive_set_aside'
                                 if 'set_asides' in change else 'current_terminal_notice')
                require_complete_refresh(configuration(item), summary(diagnostics))

    def test_unchanged_reviewed_archive_and_entry_dates_expire_without_a_new_approval(self):
        item = anchored()
        _, diagnostics = sam_reviewed.collect(configuration(item), date(2027, 1, 2), {},
            client=Mock(return_value=(item['reviewed_snapshot'], {'request_count': 2})))
        observation = diagnostics['notice_observations'][0]
        self.assertEqual(observation['disposition'], 'verified_withdrawal')
        self.assertEqual(observation['withdrawal_basis'], 'unchanged_reviewed_calendar')
        self.assertIn('entry_closed', observation['reasons'])
        self.assertIn('archive_date_passed', observation['reasons'])
        require_complete_refresh(configuration(item), summary(diagnostics))

    def test_legacy_approval_expiry_is_not_silently_renewed(self):
        item = approval()
        item['cycles'][0]['entry']['date'] = '2026-11-20'
        current = sam_public.snapshot(payload(), resources(), NOTICE)
        rows, diagnostics = sam_reviewed.collect(configuration(item), date(2026, 11, 13), {},
            client=Mock(return_value=(current, {'request_count': 2})))
        self.assertEqual(diagnostics['notice_observations'][0]['disposition'], 'approval_expired')
        self.assertEqual(rows[0]['status'], 'unverified')
        self.assertNotIn('sam_review_reconciliation', rows[0])

    def test_successor_fetch_failure_or_wrong_id_stops_partial_collection(self):
        item = anchored()
        old = signed(item['reviewed_snapshot'], latest=False, latest_notice_id=OTHER)
        for response in (SamError('unavailable', {'request_count': 1, 'failure_class': 'transient_transport'}),
                         (item['reviewed_snapshot'], {'request_count': 2})):
            client = Mock(side_effect=[(old, {'request_count': 2}), response])
            with self.subTest(response=response), self.assertRaises(SamError) as raised:
                sam_reviewed.collect(configuration(item), TODAY, {}, client=client)
            self.assertEqual(client.call_count, 2)
            self.assertEqual(raised.exception.diagnostics['request_count'], 3 if isinstance(response, SamError) else 4)

    def test_another_version_pointer_is_not_followed_unboundedly(self):
        item = anchored()
        old = signed(item['reviewed_snapshot'], latest=False, latest_notice_id=OTHER)
        intermediate = signed(old, notice_id=OTHER, latest_notice_id='c' * 32)
        client = Mock(side_effect=[(old, {'request_count': 2}), (intermediate, {'request_count': 2})])
        _, diagnostics = sam_reviewed.collect(configuration(item), TODAY, {}, client=client)
        self.assertEqual(client.call_count, 2)
        self.assertEqual(diagnostics['notice_observations'][0]['disposition'], 'review_required')

    def test_snapshot_anchor_is_exact_bounded_and_cannot_carry_private_extra_fields(self):
        for change in ({'organization_id': '9999'}, {'review_sha256': '0' * 64},
                       {'description_sha256': 'not-a-digest'}, {'set_asides': ['x' * 101]},
                       {'raw_description': 'private material'}, {'latest': False}):
            item = anchored()
            item['reviewed_snapshot'].update(change)
            with self.subTest(change=change), self.assertRaises(SamError):
                sam_reviewed.validate_config(configuration(item))

    def test_production_anchors_authenticate_and_current_imr_retains_reviewed_stage_contract(self):
        config = json.loads((ROOT / 'config/sam_gov.json').read_text(encoding='utf8'))
        sam_reviewed.validate_config(config)
        for item in config['approved_notices']:
            with self.subTest(notice_id=item['notice_id']):
                self.assertIn('reviewed_snapshot', item)
                sam_reviewed.validate_reviewed_snapshot(item['reviewed_snapshot'], item)
        current = json.loads((ROOT / 'tests/fixtures/sam_imr_reviewed_20261018.json').read_text(encoding='utf8'))
        item = next(item for item in config['approved_notices'] if item['solicitation_number'] == 'DARPA-PS-26-138')
        (record, reasons), _ = sam_reviewed.reconcile_notice(current, item, date(2026, 10, 18))
        self.assertEqual(reasons, [])
        self.assertEqual(record['opportunity_id'], 'sam-gov:e86bce2c7d594d8ba016060da00e8a59')
        self.assertEqual([event['date'] for event in record['deadlines']], ['2026-10-22', '2026-12-07'])
        self.assertTrue(record['deadlines'][1]['invitation_required'])
        self.assertIn('TA3', record['description'])
        self.assertIn('CMMC Level 2', record['description'])


if __name__ == '__main__':
    unittest.main()
