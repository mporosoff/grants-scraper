"""Failed acquisition identity, retry timing and bounded public diagnostics."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import tempfile
import unittest
from unittest.mock import patch

import requests

from scripts import extract_document_evidence as e
from tests.test_document_evidence import base_record, response


class DocumentRetryIdentityTests(unittest.TestCase):
    now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)

    def setUp(self):
        self.structure = e.notice_structure_cache.StructureCache(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(e, 'build_search_index', return_value={}))
        self.enterContext(patch.object(e, 'facet_counts', return_value={}))
        self.profile = self.enterContext(patch.object(e, 'document_acquisition_identity', return_value=None))
        self.record = base_record()
        self.source = e.source_for_record(self.record)
        self.original, _ = e.build_document_entry(self.record, self.source, response(), None,
                                                 self.now - timedelta(days=15))

    def refresh(self, record, cache, fetcher, now=None):
        return e.enrich_document_evidence({'opportunities': [record]}, cache,
            now=now or self.now, request_delay=0, structure_cache=self.structure, fetcher=fetcher)

    def selected_urls(self, records, entries, now=None):
        calls = []
        def fetch(url, headers):
            calls.append(url)
            raise requests.ConnectionError('Offline acquisition selection probe')
        e.enrich_document_evidence({'opportunities': records}, {'records': deepcopy(entries)},
            now=now or self.now, request_delay=0, structure_cache=self.structure,
            max_documents=1, fetcher=fetch)
        return calls

    def test_repaired_failed_profile_precedes_new_and_scientific_backlog_under_one_document_cap(self):
        failed_record = dict(self.record, opportunity_id='failed', close_date='2027-01-01',
                             primary_document_url='https://sam.gov/opp/' + 'a' * 32 + '/view')
        failed_source = e.source_for_record(failed_record)
        legacy = {'status': 'failed', 'last_error': 'ValueError', 'last_attempt_at': e.iso_utc(self.now),
                  'source_signature': e.source_signature(failed_record, failed_source),
                  'checked_at': e.iso_utc(self.now), 'document': {'url': failed_source['url']}, 'facts': []}
        new_record = dict(self.record, opportunity_id='new', close_date='2026-10-17',
                          primary_document_url='https://agency.example/new.html')
        scientific = dict(self.record, opportunity_id='scientific', close_date='2026-12-15',
                          primary_document_url='https://agency.example/scientific.html')
        science_source = e.source_for_record(scientific)
        science_entry = deepcopy(self.original)
        science_entry.update(source_signature=e.source_signature(scientific, science_source),
            source_url=science_source['url'], subtopic_reason='scientific_body_revalidation_pending', facts=[])
        science_entry['document']['url'] = science_source['url']
        self.profile.return_value = 'sam-public-description-v1'
        self.assertTrue(e.failed_acquisition_profile_changed(legacy, failed_source['url']))
        self.assertEqual(self.selected_urls([new_record, scientific, failed_record],
            {'failed': legacy, 'scientific': science_entry}), [failed_source['url']])

    def test_same_profile_failure_keeps_backoff_and_ordinary_retry_priority_when_it_expires(self):
        failed_record = dict(self.record, opportunity_id='failed', close_date='2027-01-01',
                             primary_document_url='https://sam.gov/opp/' + 'a' * 32 + '/view')
        source = e.source_for_record(failed_record)
        signature = e.source_signature(failed_record, source)
        failed = {'status': 'failed', 'last_error': 'ValueError', 'last_attempt_at': e.iso_utc(self.now),
                  'last_attempt_acquisition_identity': 'sam-public-description-v1',
                  'last_attempt_signature': e.failed_attempt_signature(signature, 'sam-public-description-v1'),
                  'document': {'url': source['url']}, 'facts': []}
        new_record = dict(self.record, opportunity_id='new', close_date='2026-10-17',
                          primary_document_url='https://agency.example/new.html')
        self.profile.return_value = 'sam-public-description-v1'
        self.assertFalse(e.failed_acquisition_profile_changed(failed, source['url']))
        self.assertFalse(e.due_for_check(failed, signature, self.now + timedelta(hours=1), 14))
        self.assertEqual(self.selected_urls([failed_record, new_record], {'failed': failed},
                         self.now + timedelta(hours=1)), [new_record['primary_document_url']])
        self.assertTrue(e.due_for_check(failed, signature, self.now + timedelta(days=1), 14))
        # A first failed attempt has no verified source signature; its absence
        # must not be mistaken for a changed verified source after backoff.
        self.assertEqual(self.selected_urls([failed_record, new_record], {'failed': failed},
                         self.now + timedelta(days=1)), [new_record['primary_document_url']])

    def test_current_verified_entry_is_not_promoted_for_a_new_acquisition_profile(self):
        verified_record = dict(self.record, opportunity_id='verified', close_date='2027-01-01',
                               primary_document_url='https://sam.gov/opp/' + 'a' * 32 + '/view')
        source = e.source_for_record(verified_record)
        verified = deepcopy(self.original)
        verified.update(source_signature=e.source_signature(verified_record, source), source_url=source['url'], facts=[])
        verified['document']['url'] = source['url']
        self.profile.return_value = 'sam-public-description-v1'
        self.profile.reset_mock()
        self.assertFalse(e.failed_acquisition_profile_changed(verified, source['url']))
        self.profile.assert_not_called()
        new_record = dict(self.record, opportunity_id='new', close_date='2026-10-17',
                          primary_document_url='https://agency.example/new.html')
        self.assertEqual(self.selected_urls([verified_record, new_record], {'verified': verified}),
                         [new_record['primary_document_url']])

    def test_changed_route_or_revision_failure_backs_off_its_attempt_without_altering_receipt(self):
        for change in ('url', 'revision'):
            with self.subTest(change=change):
                record = deepcopy(self.record)
                if change == 'url':
                    record['primary_document_url'] = 'https://agency.example/revised-notice.html'
                else:
                    record['api_revision'] += 1
                signature = e.source_signature(record, e.source_for_record(record))
                prior = deepcopy(self.original)
                output, cache = self.refresh(record, {'records': {record['opportunity_id']: prior}},
                    lambda *_: (_ for _ in ()).throw(requests.ConnectionError('PRIVATE_ERROR_MARKER')))
                failed = cache['records'][record['opportunity_id']]
                for key in ('source_signature', 'checked_at', 'document', 'facts', 'version_history', 'source_url'):
                    self.assertEqual(failed.get(key), self.original.get(key), key)
                self.assertEqual(failed['last_attempt_signature'], e.failed_attempt_signature(signature))
                self.assertEqual(failed['last_attempt_at'], e.iso_utc(self.now))
                self.assertIsNone(output['opportunities'][0]['document_evidence'])
                self.assertNotIn('PRIVATE_ERROR_MARKER', json.dumps(cache))
                self.assertFalse(e.due_for_check(failed, signature, self.now + timedelta(hours=23), 14,
                                               needs_subtopics=True))
                self.assertTrue(e.due_for_check(failed, signature, self.now + timedelta(days=1), 14))
                # Reverting to the verified route is also a new attempt identity.
                self.assertTrue(e.due_for_check(failed, self.original['source_signature'], self.now, 14))
                self.assertTrue(e.due_for_check(failed, signature + '|acquisition-profile-v2', self.now, 14))
                again, cache = self.refresh(record, cache, lambda *_: self.fail('Retry inside backoff'),
                                            self.now + timedelta(hours=1))
                self.assertEqual(again['diagnostics']['document_evidence']['parser_recovery']['source_requests'], 0)
                self.assertIsNone(again['opportunities'][0]['document_evidence'])

    def test_first_failure_records_only_redacted_attempt_identity(self):
        record = deepcopy(self.record)
        record['primary_document_url'] = 'https://user:PRIVATE_PASSWORD@agency.example/notice?key=PRIVATE_QUERY#PRIVATE_FRAGMENT'
        output, cache = self.refresh(record, {'records': {}},
            lambda *_: (_ for _ in ()).throw(ValueError('PRIVATE_REMOTE_BODY')))
        failed = cache['records'][record['opportunity_id']]
        self.assertNotIn('source_signature', failed)
        self.assertNotIn('checked_at', failed)
        self.assertEqual(failed['last_attempt_url'], 'https://agency.example/notice')
        self.assertEqual(failed['document']['url'], 'https://agency.example/notice')
        self.assertRegex(failed['last_attempt_signature'], r'^[a-f0-9]{64}$')
        metrics = output['diagnostics']['document_evidence']
        self.assertEqual(metrics['failed_request_count'], 1)
        self.assertEqual(metrics['failures'][0]['url'], 'https://agency.example/notice')
        self.assertNotIn('PRIVATE_', json.dumps({'cache': cache, 'metrics': metrics}))

    def test_new_acquisition_profile_retries_failed_identity_once_and_leaves_success_freshness_intact(self):
        record = deepcopy(self.record)
        record['primary_document_url'] = 'https://sam.gov/opp/' + 'a' * 32 + '/view'
        source = e.source_for_record(record)
        body = response()
        body['url'] = source['url']
        verified, _ = e.build_document_entry(record, source, body, None, self.now)
        signature = verified['source_signature']
        legacy = dict(deepcopy(verified), status='failed', last_error='ValueError', last_attempt_at=e.iso_utc(self.now))
        self.profile.return_value = 'sam-public-description-v1'
        self.assertTrue(e.due_for_check(legacy, signature, self.now, 14))
        output, cache = self.refresh(record, {'records': {record['opportunity_id']: legacy}},
            lambda *_: (_ for _ in ()).throw(ValueError('Unavailable notice')))
        failed = cache['records'][record['opportunity_id']]
        self.assertEqual(failed['last_attempt_acquisition_identity'], 'sam-public-description-v1')
        self.assertEqual(failed['last_attempt_signature'], e.failed_attempt_signature(signature, 'sam-public-description-v1'))
        self.assertFalse(e.due_for_check(failed, signature, self.now + timedelta(hours=1), 14))
        self.profile.return_value = 'sam-public-description-v2'
        self.assertTrue(e.due_for_check(failed, signature, self.now + timedelta(hours=1), 14))
        for key in ('source_signature', 'checked_at', 'document', 'facts'):
            self.assertEqual(failed[key], verified[key])
        self.assertIsNone(output['opportunities'][0]['document_evidence'])
        self.profile.reset_mock()
        self.assertFalse(e.due_for_check(verified, signature, self.now + timedelta(hours=1), 14))
        self.profile.assert_not_called()

    def test_legacy_attempts_do_not_acquire_invented_identity(self):
        legacy = deepcopy(self.original)
        legacy.update(status='failed', last_error='ValueError', last_attempt_at=e.iso_utc(self.now))
        original = deepcopy(legacy)
        self.assertFalse(e.due_for_check(legacy, legacy['source_signature'], self.now + timedelta(hours=1), 14))
        self.assertTrue(e.due_for_check(legacy, legacy['source_signature'] + '|new-profile', self.now, 14))
        self.assertEqual(legacy, original)
        for attempt_time in (None, True, 'bad', '2026-10-16T12:00:00', '2099-01-01T00:00:00Z'):
            with self.subTest(attempt_time=attempt_time):
                malformed = dict(legacy, last_attempt_signature=e.failed_attempt_signature(legacy['source_signature']),
                                 last_attempt_at=attempt_time)
                self.assertTrue(e.due_for_check(malformed, legacy['source_signature'], self.now, 14))

    def test_parse_failure_records_actual_phase_and_safe_http_success(self):
        output, cache = self.refresh(self.record, {'records': {}}, lambda *_: {
            'status_code': 200, 'content': b'', 'content_type': 'text/html', 'url': self.source['url']})
        failure = output['diagnostics']['document_evidence']['failures'][0]
        self.assertEqual((failure['phase'], failure['reason'], failure['http_status']),
                         ('notice_parse', 'unreadable_notice', 200))
        failed = cache['records'][self.record['opportunity_id']]
        self.assertEqual(failed['last_error_phase'], failure['phase'])
        self.assertEqual(failed['last_error_reason'], failure['reason'])

    def test_successful_unchanged_content_or_304_clears_failed_attempt_fields(self):
        for unchanged in ('same_bytes', '304'):
            with self.subTest(unchanged=unchanged):
                entry = deepcopy(self.original)
                entry.update(status='failed', last_error='HTTPError', last_attempt_at=e.iso_utc(self.now),
                    last_attempt_signature=e.failed_attempt_signature(entry['source_signature']),
                    last_attempt_acquisition_identity=None,
                    last_attempt_url=self.source['url'], last_error_phase='notice_refresh',
                    last_error_reason='http_error', last_error_http_status=503)
                if unchanged == 'same_bytes':
                    repaired, extracted = e.build_document_entry(self.record, self.source, response(), entry,
                                                                 self.now + timedelta(days=1))
                    self.assertFalse(extracted)
                else:
                    output, cache = self.refresh(self.record, {'records': {self.record['opportunity_id']: entry}},
                        lambda *_: {'status_code': 304, 'url': self.source['url']}, self.now + timedelta(days=1))
                    repaired = cache['records'][self.record['opportunity_id']]
                    self.assertEqual(output['diagnostics']['document_evidence']['not_modified_count'], 1)
                self.assertEqual(repaired['status'], 'current')
                self.assertIsNone(repaired['last_error'])
                self.assertFalse(any(key.startswith(('last_attempt_', 'last_error_')) for key in repaired))

    def test_diagnostics_never_serialize_remote_error_text_or_arbitrary_reason(self):
        http = requests.HTTPError('PRIVATE_RESPONSE_TEXT')
        http.response = requests.Response()
        http.response.status_code = 403
        http.response.url = 'https://PRIVATE_HOST/?token=PRIVATE_TOKEN'
        failure = e.document_failure('public-record', self.source, http, 'notice_refresh')
        self.assertEqual((failure['error'], failure['reason'], failure['http_status']), ('HTTPError', 'http_error', 403))
        sam = ValueError('PRIVATE_SAM_BODY')
        sam.document_reason = 'sam_notice_identity'
        sam.http_status = 404
        failure = e.document_failure('public-record', self.source, sam, 'notice_refresh')
        self.assertEqual((failure['reason'], failure['http_status']), ('sam_notice_identity', 404))
        for unsafe in ('PRIVATE_REASON', {'PRIVATE_KEY': 'PRIVATE_VALUE'}):
            sam.document_reason, sam.http_status = unsafe, True
            failure = e.document_failure('public-record', self.source, sam, 'PRIVATE_PHASE')
            self.assertEqual((failure['phase'], failure['reason'], failure['http_status']),
                             ('notice_processing', 'invalid_notice', None))
            self.assertNotIn('PRIVATE_', json.dumps(failure))

    def test_health_threshold_still_rejects_the_actual_failed_acquisition_batch(self):
        with self.assertRaisesRegex(RuntimeError, '82% of 45'):
            e.validate_refresh_health({'refreshed_count': 8, 'not_modified_count': 0, 'failed_request_count': 37})


if __name__ == '__main__':
    unittest.main()
