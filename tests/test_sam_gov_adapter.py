"""Offline contracts for bounded SAM discovery and reviewed catalog admission."""

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date, timedelta
from email.message import Message
import io
import json
import os
from pathlib import Path
import tempfile
import traceback
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, quote_plus, urlsplit
from urllib.request import Request

from scripts.sources import sam_api
from scripts.sources.adapters.sam_gov import SamGovAdapter, discovery_candidates, load_config
from scripts.sources.merge import merge_records, resolve_live_records
from scripts.sources.registry import collect


AS_OF = date(2026, 10, 1)
KEY = 'synthetic-SAM-secret+with/slash and space'
NOTICE_ID = 'a' * 32
SPONSOR = 'Defense Advanced Research Projects Agency (DARPA)'
ORGANIZATION = 'DEPT OF DEFENSE.DEFENSE ADVANCED RESEARCH PROJECTS AGENCY (DARPA)'


def notice(**changes):
    return {'noticeId': NOTICE_ID,
            'title': 'Broad Agency Announcement for quantum sensing research',
            'solicitationNumber': 'DARPA-PA-26-02-02',
            'fullParentPathName': ORGANIZATION, 'postedDate': '2026-09-25',
            'type': 'Solicitation', 'active': 'Yes',
            'responseDeadLine': '2026-11-30T17:00:00-05:00',
            'naicsCode': '541715', 'classificationCode': 'AD11',
            'typeOfSetAside': '', 'typeOfSetAsideDescription': '', **changes}


def approval(**changes):
    return {'notice_id': NOTICE_ID, 'solicitation_number': 'DARPA-PA-26-02-02',
            'organization_path': ORGANIZATION, 'sponsor': SPONSOR,
            'evidence_url': f'https://sam.gov/opp/{NOTICE_ID}/view',
            'academic_eligibility_quote': 'Universities and other institutions of higher education are eligible to submit proposals.',
            'verified_on': '2026-10-01', 'review_after': '2026-10-20', **changes}


def listing(rows, **changes):
    return {'totalRecords': len(rows), 'opportunitiesData': rows, **changes}


class Response:
    def __init__(self, body, *, status=200, headers=None):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status = status
        self.headers = headers or {}
        self.read_sizes = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def read(self, size):
        self.read_sizes.append(size)
        return self.body[:size]


class TransportTests(unittest.TestCase):
    def assert_safe(self, value):
        encoded = json.dumps(value, default=str)
        for secret in (KEY, quote(KEY, safe=''), quote_plus(KEY, safe=''),
                       'RAW_EXCEPTION', 'RAW_DESCRIPTION', 'private@example.test'):
            self.assertNotIn(secret, encoded)
        self.assertNotIn('api_key=', encoded)

    def fetch(self, body, **kwargs):
        response = Response(body, **kwargs)
        opener = Mock()
        opener.open.return_value = response
        with redirect_stdout(io.StringIO()) as output:
            result = sam_api.fetch_listing(KEY, today=AS_OF, opener=opener)
        self.assertEqual(output.getvalue(), '')
        opener.open.assert_called_once()
        self.assertEqual(response.read_sizes, [8 * 1024 * 1024 + 1])
        self.assertTrue(response.closed)
        self.assert_safe(result)
        return result, opener

    def test_one_fixed_host_get_has_bounded_window_and_no_detail_requests(self):
        (rows, diagnostics), opener = self.fetch(listing([notice()]))
        request = opener.open.call_args.args[0]
        parsed = urlsplit(request.full_url)
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path),
                         ('https', 'api.sam.gov', '/opportunities/v2/search'))
        self.assertEqual(parse_qs(parsed.query), {
            'postedFrom': ['10/02/2025'], 'postedTo': ['10/01/2026'],
            'title': ['Broad Agency Announcement'], 'limit': ['500'],
            'offset': ['0'], 'api_key': [KEY]})
        self.assertEqual(request.get_method(), 'GET')
        self.assertIsNone(request.data)
        self.assertEqual(opener.open.call_args.kwargs, {'timeout': 30})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['noticeId'], NOTICE_ID)
        self.assertEqual(diagnostics['request_count'], 1)

    def test_empty_complete_result_is_healthy_and_does_not_trigger_another_query(self):
        (rows, diagnostics), _ = self.fetch(listing([]))
        self.assertEqual(rows, [])
        self.assertEqual(diagnostics['request_count'], 1)

    def test_missing_key_performs_no_request(self):
        for key in ('', ' \t\n', None):
            with self.subTest(key=key), patch.object(sam_api, 'build_opener') as build:
                opener = Mock()
                with self.assertRaises(sam_api.SamError) as raised:
                    sam_api.fetch_listing(key, today=AS_OF, opener=opener)
                self.assert_safe(str(raised.exception))
                opener.open.assert_not_called()
                build.assert_not_called()

    def test_raw_descriptions_links_contacts_and_secret_echoes_never_leave_client(self):
        for echo in (KEY, quote(KEY, safe=''), quote_plus(KEY, safe='')):
            with self.subTest(encoding=echo == KEY):
                row = notice(title='Broad Agency Announcement ' + echo,
                    description='RAW_DESCRIPTION ' + KEY,
                    uiLink='https://sam.gov/opp/' + NOTICE_ID + '/view?api_key=' + echo,
                    resourceLinks=['https://example.test/?api_key=' + echo],
                    pointOfContact=[{'email': 'private@example.test'}],
                    award={'awardee': 'private@example.test'})
                (rows, _), _ = self.fetch(listing([row]))
                self.assertEqual(len(rows), 1)
                for field in ('description', 'uiLink', 'resourceLinks', 'pointOfContact', 'award'):
                    self.assertNotIn(field, rows[0])
                self.assertIn('[redacted]', rows[0]['title'])

    def test_only_exact_official_description_links_become_route_tokens(self):
        for route, segment in (('v1', ''), ('prod-v1', '/prod')):
            url = f'https://api.sam.gov{segment}/opportunities/v1/noticedesc?noticeid={NOTICE_ID}&api_key={quote_plus(KEY)}'
            (rows, _), _ = self.fetch(listing([notice(description=url)]))
            self.assertEqual(rows[0]['description_route'], route)
            self.assertNotIn('description', rows[0])
        invalid = [
            f'https://api.sam.gov.evil.test/opportunities/v1/noticedesc?noticeid={NOTICE_ID}',
            f'https://evil.test@api.sam.gov/opportunities/v1/noticedesc?noticeid={NOTICE_ID}',
            f'http://api.sam.gov/opportunities/v1/noticedesc?noticeid={NOTICE_ID}',
            f'https://api.sam.gov:444/opportunities/v1/noticedesc?noticeid={NOTICE_ID}',
            f'https://api.sam.gov/opportunities/v1/noticedesc?noticeid={"b" * 32}',
            f'https://api.sam.gov/opportunities/v1/noticedesc?noticeid={NOTICE_ID}&noticeid={NOTICE_ID}',
            f'https://api.sam.gov/opportunities/v1/noticedesc?noticeid={NOTICE_ID}&redirect=evil',
        ]
        for url in invalid:
            with self.subTest(url=url):
                (rows, _), _ = self.fetch(listing([notice(description=url)]))
                self.assertNotIn('description_route', rows[0])
                self.assertNotIn('description', rows[0])

    def test_headers_preserve_only_bounded_numeric_quota_information(self):
        (_, diagnostics), _ = self.fetch(listing([]), headers={
            'X-RateLimit-Limit': '10', 'X-RateLimit-Remaining': '7', 'Retry-After': '60',
            'Authorization': KEY, 'Set-Cookie': KEY})
        self.assertEqual(diagnostics['rate_limit'], {
            'X-RateLimit-Limit': 10, 'X-RateLimit-Remaining': 7, 'Retry-After': 60})
        for value in (KEY, '-1', '99999999999', '1.5', '12\n'):
            with self.subTest(value=value):
                (_, diagnostics), _ = self.fetch(listing([]), headers={
                    name: value for name in ('X-RateLimit-Limit', 'X-RateLimit-Remaining', 'Retry-After')})
                self.assertEqual(diagnostics['rate_limit'], {})

    def test_incomplete_duplicate_and_invalid_responses_fail_instead_of_healthy_zero(self):
        invalid = [b'RAW_EXCEPTION ' + KEY.encode(), b'\xff', [], {},
                   listing([notice()], totalRecords=True), listing([], totalRecords='0'),
                   listing([], totalRecords=-1), listing([], totalRecords=1),
                   listing([notice()], totalRecords=501), listing([notice(), notice()]),
                   listing([{}]), listing(['bad']),
                   listing([notice(noticeId='not-a-notice-id')])]
        for body in invalid:
            with self.subTest(body=type(body).__name__):
                response = Response(body)
                opener = Mock()
                opener.open.return_value = response
                with self.assertRaises(sam_api.SamError) as raised:
                    sam_api.fetch_listing(KEY, today=AS_OF, opener=opener)
                opener.open.assert_called_once()
                self.assertEqual(response.read_sizes, [8 * 1024 * 1024 + 1])
                self.assert_safe((str(raised.exception), raised.exception.diagnostics))

    def test_oversized_body_is_read_once_and_not_partially_admitted(self):
        response = Response(b' ' * (8 * 1024 * 1024 + 1))
        opener = Mock()
        opener.open.return_value = response
        with self.assertRaises(sam_api.SamError):
            sam_api.fetch_listing(KEY, today=AS_OF, opener=opener)
        opener.open.assert_called_once()
        self.assertEqual(response.read_sizes, [8 * 1024 * 1024 + 1])

    def test_network_and_http_failures_never_retry_or_expose_sensitive_error_context(self):
        failures = [URLError('RAW_EXCEPTION ' + KEY), TimeoutError('RAW_EXCEPTION ' + KEY),
                    HTTPError('https://api.sam.gov/?api_key=' + quote_plus(KEY), 429,
                              'RAW_EXCEPTION ' + KEY,
                              {'X-RateLimit-Limit': '10', 'X-RateLimit-Remaining': '0',
                               'Retry-After': '60', 'Authorization': KEY},
                              io.BytesIO(json.dumps({'error': {'code': 'OVER_RATE_LIMIT',
                                                             'message': 'RAW_EXCEPTION ' + KEY}}).encode()))]
        for error in failures:
            with self.subTest(error=type(error).__name__):
                opener = Mock()
                opener.open.side_effect = error
                with self.assertRaises(sam_api.SamError) as raised:
                    sam_api.fetch_listing(KEY, today=AS_OF, opener=opener)
                opener.open.assert_called_once()
                self.assert_safe((str(raised.exception), raised.exception.diagnostics))
                self.assert_safe(''.join(traceback.format_exception(raised.exception)))

    def test_default_client_refuses_redirect_before_followup_request(self):
        client = Mock()
        client.open.side_effect = HTTPError('https://api.sam.gov/', 302, 'redirect', {}, io.BytesIO(b''))
        with patch.object(sam_api, 'build_opener', return_value=client) as build:
            with self.assertRaises(sam_api.SamError):
                sam_api.fetch_listing(KEY, today=AS_OF)
        handler = build.call_args.args[0]
        handler.parent = Mock()
        headers = Message()
        headers['Location'] = 'https://other.example/?api_key=' + quote_plus(KEY)
        request = Request('https://api.sam.gov/?api_key=' + quote_plus(KEY))
        self.assertIsNone(handler.http_error_302(request, io.BytesIO(b''), 302, 'redirect', headers))
        handler.parent.open.assert_not_called()
        client.open.assert_called_once()

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'sam.json'
        self.environment = patch.dict(os.environ, {'SAM_API_KEY': KEY})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def config(self, entries=None, **changes):
        data = {'schema_version': 1, 'enabled': True,
                'approved_notices': [approval()] if entries is None else entries, **changes}
        self.path.write_text(json.dumps(data), encoding='utf8')
        return data

    def adapter(self, rows=None, *, entries=None, enabled=True):
        self.config(entries, enabled=enabled)
        client = Mock(return_value=([notice()] if rows is None else rows,
                                    {'request_count': 1, 'http_status': 200}))
        instance = SamGovAdapter(config_path=self.path, client=client)
        return instance, client

    def observed(self, rows=None, *, entries=None, as_of=AS_OF):
        instance, client = self.adapter(rows, entries=entries)
        records, results = collect([instance], context={'as_of': as_of})
        return records, results, client

    def test_disabled_configuration_requires_no_key_or_client(self):
        instance, client = self.adapter(enabled=False)
        with patch.dict(os.environ, {}, clear=True):
            records, results = collect([instance], context={'as_of': AS_OF})
        self.assertEqual((records, results), ([], []))
        client.assert_not_called()

    def test_disabled_approved_config_supports_explicit_preview_but_empty_stage_calls_nothing(self):
        instance, client = self.adapter(enabled=False)
        instance.set_context({'as_of': AS_OF})
        self.assertFalse(instance.enabled)
        records = instance.collect()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['opportunity_id'], 'sam-gov:' + NOTICE_ID)
        client.assert_called_once_with(KEY, today=AS_OF)
        instance, client = self.adapter(entries=[], enabled=False)
        instance.set_context({'as_of': AS_OF})
        self.assertEqual(instance.collect(), [])
        client.assert_not_called()

    def test_reviewed_notice_is_canonical_with_bounded_evidence_lifetime(self):
        records, results, client = self.observed()
        self.assertTrue(results[0].ok, results[0].error)
        self.assertEqual(len(records), 1)
        record = records[0]
        client.assert_called_once_with(KEY, today=AS_OF)
        self.assertEqual(record['opportunity_id'], 'sam-gov:' + NOTICE_ID)
        self.assertEqual(record['opportunity_number'], 'DARPA-PA-26-02-02')
        self.assertEqual(record['agency'], SPONSOR)
        self.assertEqual(record['source'], 'SAM.gov')
        self.assertEqual(record['source_type'], 'Federal')
        self.assertEqual(record['status'], 'posted')
        self.assertEqual(record['detail_page'], f'https://sam.gov/opp/{NOTICE_ID}/view')
        self.assertEqual(record['close_date'], '2026-11-30')
        self.assertEqual(record['deadlines'][0]['time'], '17:00:00')
        self.assertEqual(record['deadlines'][0]['timezone'], '-05:00')
        self.assertEqual(record['source_review_after'], '2026-10-08')
        self.assertFalse(results[0].snapshot_complete)
        self.assertFalse(results[0].retain_on_failure)
        self.assertEqual((results[0].min_records, results[0].max_records), (0, 200))
        self.assertIn('Universities', record['eligibility_text'])
        self.assertNotIn(KEY, json.dumps(records))

    def test_approval_expiry_shorter_than_observation_bound_is_preserved(self):
        records, results, _ = self.observed(entries=[approval(review_after='2026-10-03')])
        self.assertTrue(results[0].ok)
        self.assertEqual(records[0]['source_review_after'], '2026-10-03')

    def test_discovery_candidates_do_not_auto_admit_unreviewed_notices(self):
        records, results, _ = self.observed([notice(noticeId='b' * 32)])
        self.assertTrue(results[0].ok, results[0].error)
        self.assertEqual(records, [])
        candidates = discovery_candidates([notice()], AS_OF)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['noticeId'], NOTICE_ID)

    def test_identity_drift_and_unsupported_actionability_cannot_enter_live_catalog(self):
        changes = [
            {'solicitationNumber': 'UNRELATED-26-99'},
            {'fullParentPathName': 'DEPARTMENT OF ENERGY.OTHER OFFICE'},
            {'type': 'Sources Sought'}, {'type': 'Special Notice'},
            {'type': 'Presolicitation'}, {'active': 'Unknown'},
            {'title': 'Industry Day for Broad Agency Announcement'},
            {'title': 'Broad Agency Announcement Request for Information'},
            {'naicsCode': '238210', 'classificationCode': 'J019'},
            {'typeOfSetAside': 'SBA', 'typeOfSetAsideDescription': 'Total Small Business Set-Aside'},
            {'responseDeadLine': ''}, {'responseDeadLine': 'TBD'},
            {'reponseDeadLine': '2026-12-01'},
            {'responseDeadLine': '2099-01-01'}, {'postedDate': '2026-10-02'},
        ]
        for update in changes:
            with self.subTest(update=update):
                _, results, _ = self.observed([notice(**update)])
                live, _, _ = resolve_live_records(results, {}, AS_OF)
                self.assertEqual(live, [])

    def test_future_or_expired_review_never_admits_a_notice(self):
        cases = [approval(verified_on='2026-10-02'),
                 approval(verified_on='2026-09-01', review_after='2026-09-30')]
        for entry in cases:
            with self.subTest(entry=entry):
                _, results, _ = self.observed(entries=[entry])
                live, _, _ = resolve_live_records(results, {}, AS_OF)
                self.assertEqual(live, [])

    def test_terminal_observations_survive_canonical_conversion_and_retire_cached_open_call(self):
        initial, initial_results, _ = self.observed()
        live, initial_cache, _ = resolve_live_records(initial_results, {}, AS_OF)
        self.assertEqual(len(live), 1)
        for update in ({'active': 'No'}, {'type': 'Award Notice'},
                       {'responseDeadLine': '2026-09-30'}, {'archiveDate': '2026-09-30'},
                       {'title': 'Cancelled Broad Agency Announcement for quantum sensing research'}):
            with self.subTest(update=update):
                observations, results, _ = self.observed([notice(**update)])
                self.assertTrue(results[0].ok, results[0].error)
                self.assertEqual(len(observations), 1)
                self.assertNotEqual(observations[0]['status'], 'posted')
                current, cache, _ = resolve_live_records(results, deepcopy(initial_cache), AS_OF)
                self.assertEqual(current, [])
                self.assertEqual(cache['sources']['sam-gov']['records'], [])

    def test_invalid_replacement_retires_previous_approved_record(self):
        _, initial_results, _ = self.observed()
        _, initial_cache, _ = resolve_live_records(initial_results, {}, AS_OF)
        for update in ({'responseDeadLine': 'TBD'}, {'typeOfSetAside': 'SBA'},
                       {'solicitationNumber': 'UNRELATED-26-99'}):
            with self.subTest(update=update):
                _, results, _ = self.observed([notice(**update)])
                current, cache, _ = resolve_live_records(results, deepcopy(initial_cache), AS_OF)
                self.assertEqual(current, [])
                self.assertEqual(cache['sources']['sam-gov']['records'], [])

    def test_window_omission_carries_only_until_original_review_expires(self):
        _, initial_results, _ = self.observed()
        _, initial_cache, _ = resolve_live_records(initial_results, {}, AS_OF)
        _, omitted_results, _ = self.observed([], as_of=AS_OF + timedelta(days=1))
        current, cache, _ = resolve_live_records(omitted_results, deepcopy(initial_cache), AS_OF + timedelta(days=1))
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]['source_review_after'], '2026-10-08')
        self.assertEqual(current[0]['source_observation'], 'retained_outside_window')
        _, later_results, _ = self.observed([], as_of=AS_OF + timedelta(days=8))
        current, cache, _ = resolve_live_records(later_results, cache, AS_OF + timedelta(days=8))
        self.assertEqual(current, [])
        self.assertEqual(cache['sources']['sam-gov']['records'], [])

    def test_source_failure_clears_open_cache_instead_of_using_stale_success(self):
        _, initial_results, _ = self.observed()
        _, cache, _ = resolve_live_records(initial_results, {}, AS_OF)
        instance, client = self.adapter()
        client.side_effect = sam_api.SamError('network_error', {'request_count': 1})
        _, results = collect([instance], context={'as_of': AS_OF})
        self.assertFalse(results[0].ok)
        current, cache, summary = resolve_live_records(results, cache, AS_OF)
        self.assertEqual(current, [])
        self.assertEqual(cache['sources']['sam-gov']['records'], [])
        self.assertEqual(summary[0]['status'], 'failed_no_fallback')

    def test_grants_record_wins_and_existing_darpa_record_does_not_duplicate(self):
        records, _, _ = self.observed()
        sam_record = records[0]
        grants = {**sam_record, 'opportunity_id': '12345', 'source': 'Grants.gov',
                  'agency': 'DARPA - Defense Sciences Office',
                  'opportunity_number': 'darpa pa 26 02 02', 'title': 'Canonical grant title'}
        darpa = {**sam_record, 'opportunity_id': 'darpa-iarpa:DARPA-PA-26-02-02',
                 'source': 'DARPA / IARPA research solicitations',
                 'detail_page': 'https://www.darpa.mil/research/programs/quantum-benchmarking-initiative'}
        merged, stats = merge_records([grants], [darpa, sam_record])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['opportunity_id'], '12345')
        self.assertEqual(merged[0]['title'], 'Canonical grant title')
        self.assertEqual(merged[0]['source'], 'Grants.gov')
        self.assertEqual(stats['external_added'], 0)
        merged, stats = merge_records([], [darpa, sam_record])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['opportunity_id'], darpa['opportunity_id'])
        self.assertEqual(stats['external_added'], 1)

    def test_cached_approval_revocation_is_immediate_even_when_listing_omits_notice(self):
        _, initial_results, _ = self.observed()
        _, initial_cache, _ = resolve_live_records(initial_results, {}, AS_OF)
        entries = [
            [approval(notice_id='b' * 32, evidence_url='https://sam.gov/opp/' + 'b' * 32 + '/view')],
            [approval(verified_on='2026-09-01', review_after='2026-09-30')],
            [approval(organization_path='DEPT OF DEFENSE.OTHER OFFICE')],
            [approval(academic_eligibility_quote='Universities are eligible for a different reviewed scope.')],
        ]
        for approved in entries:
            with self.subTest(entries=approved):
                instance, _ = self.adapter([], entries=approved)
                snapshots = {'sam-gov': deepcopy(initial_cache['sources']['sam-gov']['records'])}
                _, results = collect([instance], context={'as_of': AS_OF, 'source_snapshots': snapshots})
                current, updated, _ = resolve_live_records(results, deepcopy(initial_cache), AS_OF)
                self.assertEqual(current, [])
                self.assertEqual(updated['sources']['sam-gov']['records'], [])

    def test_configuration_rejects_unsafe_or_ambiguous_approval_identity(self):
        invalid = [
            {'schema_version': 2}, {'schema_version': True}, {'enabled': 'false'}, {'approved_notices': {}},
            {'approved_notices': []},
            {'approved_notices': [approval(), approval()]},
            {'approved_notices': [approval(notice_id='invalid')]},
            {'approved_notices': [approval(solicitation_number='')]},
            {'approved_notices': [approval(organization_path='')]},
            {'approved_notices': [approval(sponsor='')]},
            {'approved_notices': [approval(academic_eligibility_quote='')]},
            {'approved_notices': [approval(evidence_url='https://sam.gov.evil.test/evidence')]},
            {'approved_notices': [approval(evidence_url='http://sam.gov/opp/' + NOTICE_ID + '/view')]},
            {'approved_notices': [approval(evidence_url='https://sam.gov/opp/' + 'b' * 32 + '/view')]},
            {'approved_notices': [approval(review_after='2026-11-01')]},
            {'approved_notices': [approval(review_after='2026-09-30')]},
            {'approved_notices': [approval(verified_on='bad-date')]},
        ]
        for update in invalid:
            with self.subTest(update=update):
                self.config(**update)
                with self.assertRaises(ValueError):
                    load_config(self.path)




class DescriptionTransportTests(unittest.TestCase):
    def test_description_uses_one_fixed_host_get_and_bound_body_without_following_content_links(self):
        response = Response({'description': '<p>Universities may submit proposals.</p><a href="https://example.test/attachment">Attachment</a>'})
        opener = Mock()
        opener.open.return_value = response
        text, diagnostics = sam_api.fetch_description(KEY, NOTICE_ID, route='v1', opener=opener)
        opener.open.assert_called_once()
        request = opener.open.call_args.args[0]
        parsed = urlsplit(request.full_url)
        self.assertEqual((parsed.scheme, parsed.netloc), ('https', 'api.sam.gov'))
        self.assertEqual(parse_qs(parsed.query).get('noticeid'), [NOTICE_ID])
        self.assertEqual(parse_qs(parsed.query).get('api_key'), [KEY])
        self.assertEqual(request.get_method(), 'GET')
        self.assertIn('Universities', text)
        self.assertLessEqual(len(text), 20000)
        self.assertEqual(len(response.read_sizes), 1)
        self.assertLessEqual(response.read_sizes[0], 8 * 1024 * 1024 + 1)
        self.assertEqual(diagnostics['request_count'], 1)

    def test_untrusted_route_or_notice_cannot_direct_credential_to_another_destination(self):
        cases = [('https://evil.example/description', NOTICE_ID),
                 ('//evil.example/description', NOTICE_ID),
                 ('v1', '../other'), ('v1', NOTICE_ID + '&api_key=stolen')]
        for route, identifier in cases:
            with self.subTest(route=route, identifier=identifier):
                opener = Mock()
                with self.assertRaises(sam_api.SamError):
                    sam_api.fetch_description(KEY, identifier, route=route, opener=opener)
                opener.open.assert_not_called()

    def test_description_redacts_secret_echoes_and_drops_scripts(self):
        response = Response({'description': '<p>Universities may apply. ' + KEY + ' ' + quote_plus(KEY, safe='') +
                             '</p><script>private@example.test</script>'})
        opener = Mock()
        opener.open.return_value = response
        text, diagnostics = sam_api.fetch_description(KEY, NOTICE_ID, route='v1', opener=opener)
        for value in (KEY, quote_plus(KEY, safe=''), 'private@example.test', '<script>'):
            self.assertNotIn(value, json.dumps((text, diagnostics)))
        opener.open.assert_called_once()


if __name__ == '__main__':
    unittest.main()
