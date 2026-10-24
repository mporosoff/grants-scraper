"""Offline contracts for evidence-pinned public SAM import and stage revocation."""
from copy import deepcopy
from datetime import date
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import urlsplit

from scripts.sources import sam_public, sam_reviewed
from scripts.sources.sam_api import SamError, NoRedirect
from scripts.sources.adapters.sam_gov import SamGovAdapter, load_config
from scripts.sources.registry import collect as registry_collect
from scripts.sources.merge import resolve_live_records


NOTICE = 'a' * 32
OTHER = 'b' * 32
TODAY = date(2026, 10, 13)
PRIVATE = 'private.person@example.test RAW_DESCRIPTION api_key=SYNTHETIC_SECRET'


def payload():
    return {'opportunityId': NOTICE, 'id': NOTICE, 'latest': True, 'archived': False,
            'cancelled': False, 'deleted': False, 'status': {'code': 'published'},
            'postedDate': '2026-10-01T12:00:00+00:00',
            'modifiedDate': '2026-10-12T12:00:00+00:00',
            '_links': {'opportunity:publish:latest': {'href': '/opps/v2/opportunities/' + NOTICE}},
            'description': [{'opportunityId': NOTICE, 'descriptionId': 'description-one', 'body': PRIVATE}],
            'pointOfContact': [{'email': PRIVATE}],
            'data2': {'title': 'Open quantum research program', 'solicitationNumber': 'DARPA-TEST-26-01',
                      'organizationId': '12345', 'type': 'o', 'classificationCode': 'AR11',
                      'naics': [{'code': ['541715']}],
                      'solicitation': {'setAside': 'NONE',
                                       'deadlines': {'response': '2026-12-10T15:00:00', 'responseTz': 'America/New_York'}},
                      'archive': {'date': '2027-01-01'}}}


def resources():
    return {'_embedded': {'opportunityAttachmentList': [
        {'opportunityId': NOTICE, 'attachments': [
            {'attachmentId': 'attachment-one', 'resourceId': 'c' * 32,
             'name': 'Official solicitation.pdf', 'type': 'file', 'accessLevel': 'public',
             'explicitAccess': '0', 'exportControlled': '0', 'deletedFlag': '0',
             'postedDate': '2026-10-01T12:00:00+00:00', 'size': 2000,
             'privateContact': PRIVATE}]}]}}


def event(kind='preproposal', deadline='2026-10-20', *, invited=False):
    return {'kind': kind, 'date': deadline, 'time': '15:00' if deadline else None,
            'timezone': 'America/New_York' if deadline else None, 'required': True,
            'invitation_required': invited, 'note': 'Required abstract; subsequent full proposal by invitation.',
            'source_url': 'https://agency.gov/research/call.pdf',
            'quote': 'Abstracts are required by October 20, 2026 at 3 PM Eastern Time.' if not invited
                     else 'Full proposals will be accepted only upon invitation.'}


def approval():
    return {'notice_id': NOTICE, 'solicitation_number': 'DARPA-TEST-26-01', 'organization_id': '12345',
            'sponsor': 'Defense Advanced Research Projects Agency (DARPA)',
            'evidence_url': 'https://agency.gov/research/call.pdf',
            'academic_eligibility_quote': 'Universities and nonprofit research institutions may submit proposals.',
            'verified_on': '2026-10-13', 'review_after': '2026-11-12',
            'review_sha256': sam_public.snapshot(payload(), resources(), NOTICE)['review_sha256'],
            'summary': 'Research quantum sensing and materials.', 'scope_note': 'Only public unclassified research.',
            'cycles': [{'name': 'Fall', 'entry': event(),
                        'full': event('full_application', '2026-12-10', invited=True)}]}


def configuration(entry=None):
    return {'schema_version': 2, 'enabled': True, 'approved_notices': [entry or approval()]}


class ProductionReviewContracts(unittest.TestCase):
    def test_reviewed_inventory_replays_without_network_and_preserves_actual_entry_stages(self):
        from scripts.submission_schedule import project
        root = Path(__file__).resolve().parents[1]
        config_path = root / 'tests/fixtures/sam_reviewed_config_20261013.json'
        config = load_config(config_path)
        observed = json.loads((root / 'tests/fixtures/sam_reviewed_inventory_20261013.json').read_text(encoding='utf8'))
        self.assertEqual(len(observed), 42)
        client = Mock(side_effect=lambda identifier: (deepcopy(observed[identifier]), {'request_count': 0}))
        adapter = SamGovAdapter(config_path=config_path, reviewed_client=client)
        with patch.dict(os.environ, {}, clear=True), \
                patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Live request forbidden')), \
                patch('requests.Session.request', side_effect=AssertionError('Provider forbidden')):
            records, results = registry_collect([adapter], context={'as_of': TODAY})
        self.assertTrue(results[0].ok, results[0].error)
        self.assertEqual(len(records), 42)
        self.assertEqual(client.call_count, 42)
        self.assertTrue(all(record['status'] == 'posted' for record in records))
        by_number = {row['opportunity_number']: row for row in records}
        expected = {
            'DARPA-PA-27-01': ('preproposal', '2026-11-05'),
            'DARPA-PS-26-137': ('preproposal', '2026-10-19'),
            'N0002427S0001': ('preproposal', '2026-11-30'),
            'PHMSA-26HM-BAA': ('white_paper', '2026-11-18'),
            'BAA-23-100-SOL-00004': ('full_application', '2028-09-25'),
            'SP800026BBAA0': ('white_paper', '2028-05-01'),
        }
        for number, (kind, deadline) in expected.items():
            with self.subTest(number=number):
                selected = project(by_number[number], TODAY)['next_submission']
                self.assertEqual((selected['event']['kind'], selected['date'], selected['access']),
                                 (kind, deadline, 'open'))
        firefox_full = [event for event in by_number['DARPA-PS-26-137']['deadlines']
                        if event['kind'] == 'full_application']
        self.assertEqual(len(firefox_full), 1)
        self.assertIsNone(firefox_full[0]['date'])
        self.assertTrue(firefox_full[0]['invitation_required'])
        self.assertEqual(by_number['PHMSA-26HM-BAA']['opportunity_id'],
                         'sam-gov:b7f83ec10df84ff0ad8ec6290dba7176')
        self.assertEqual(by_number['PHMSA-26HM-BAA']['last_updated'], '2026-10-13')
        self.assertEqual(len({row['notice_id'] for row in config['approved_notices']}), 42)


class Response:
    def __init__(self, body, status=200):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status = status
        self.sizes = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def read(self, size):
        self.sizes.append(size)
        return self.body[:size]


class PublicNoticeTests(unittest.TestCase):
    def test_interrupted_response_body_retries_only_the_failed_endpoint(self):
        from http.client import IncompleteRead
        broken = Response(b'')
        broken.read = Mock(side_effect=IncompleteRead(b'PRIVATE partial body'))
        opener = Mock()
        opener.open.side_effect = [Response(payload()), broken, Response(resources())]
        with patch.object(sam_public, 'sleep') as sleep:
            result, diagnostics = sam_public.fetch_notice(NOTICE, opener=opener)
        self.assertEqual(result['notice_id'], NOTICE)
        self.assertEqual(diagnostics['request_count'], 3)
        sleep.assert_called_once_with(1)
        self.assertEqual(opener.open.call_args_list[1].args[0].full_url,
                         opener.open.call_args_list[2].args[0].full_url)
        self.assertTrue(broken.closed)

    def test_empty_hal_manifest_requires_exact_notice_and_collection_links(self):
        href = f'https://sam.gov/opps/v3/opportunities/{NOTICE}/resources?withScanResult=false&excludeDeleted=true'
        empty = {'_links': {'self': {'href': href}, 'opportunity:publish:latest': {'href': href}}}
        observed = sam_public.snapshot(payload(), empty, NOTICE)
        self.assertEqual(observed['resources_sha256'], sam_public.digest([]))
        for malformed in ({}, {'_links': {}},
                          {'_links': {'self': {'href': href.replace(NOTICE, OTHER)},
                                      'opportunity:publish:latest': {'href': href}}}):
            with self.subTest(malformed=malformed), self.assertRaises(SamError):
                sam_public.snapshot(payload(), malformed, NOTICE)

    def test_two_bounded_fixed_host_reads_use_no_auth_and_omit_raw_contacts(self):
        replies = [Response(payload()), Response(resources())]
        opener = Mock()
        opener.open.side_effect = replies
        with patch.dict(os.environ, {'SAM_API_KEY': 'SYNTHETIC_SECRET'}, clear=True):
            result, diagnostics = sam_public.fetch_notice(NOTICE, opener=opener)
        self.assertEqual(diagnostics['request_count'], 2)
        self.assertEqual(opener.open.call_count, 2)
        for call in opener.open.call_args_list:
            request = call.args[0]
            self.assertEqual(urlsplit(request.full_url).netloc, 'sam.gov')
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(call.kwargs, {'timeout': 15})
            headers = {k.lower(): v for k, v in request.header_items()}
            self.assertEqual(headers['accept'], '*/*')
            self.assertNotIn('authorization', headers)
            self.assertNotIn('cookie', headers)
            self.assertNotIn('api_key', request.full_url)
            self.assertNotIn('SYNTHETIC_SECRET', str(request.header_items()))
        self.assertEqual(opener.open.call_args_list[0].args[0].full_url,
                         f'https://sam.gov/api/prod/opps/v2/opportunities/{NOTICE}')
        self.assertEqual(opener.open.call_args_list[1].args[0].full_url,
                         f'https://sam.gov/api/prod/opps/v3/opportunities/{NOTICE}/resources?excludeDeleted=true&withScanResult=false')
        for reply in replies:
            self.assertEqual(reply.sizes, [sam_public.MAX_BYTES + 1])
            self.assertTrue(reply.closed)
        serialized = json.dumps((result, diagnostics))
        for forbidden in ('private.person', 'RAW_DESCRIPTION', 'SYNTHETIC_SECRET', 'privateContact'):
            self.assertNotIn(forbidden, serialized)

    def test_invalid_identifier_does_not_open_transport(self):
        for identifier in ('../opportunities', NOTICE + '?api_key=secret', None, 'A' * 32):
            with self.subTest(identifier=identifier):
                opener = Mock()
                with self.assertRaises(SamError):
                    sam_public.fetch_notice(identifier, opener=opener)
                opener.open.assert_not_called()

    def test_default_transport_disables_redirects(self):
        fake = Mock()
        fake.open.side_effect = [Response(payload()), Response(resources())]
        with patch.object(sam_public, 'build_opener', return_value=fake) as build:
            sam_public.fetch_notice(NOTICE)
        self.assertEqual(build.call_count, 2)
        for call in build.call_args_list:
            self.assertIsInstance(call.args[0], NoRedirect)
            self.assertIsNone(call.args[0].redirect_request(None, None, 302, '', {}, 'https://evil.test'))

    def test_temporary_http_failures_retry_only_failed_endpoint_with_exact_counts(self):
        for status in (403, 429, 500, 502, 503, 504, 599):
            for endpoint in ('notice', 'resources'):
                with self.subTest(status=status, endpoint=endpoint):
                    error = HTTPError('https://sam.gov/' + PRIVATE, status, PRIVATE,
                                      {}, io.BytesIO(PRIVATE.encode()))
                    replies = ([error, Response(payload()), Response(resources())] if endpoint == 'notice'
                               else [Response(payload()), error, Response(resources())])
                    opener = Mock(); opener.open.side_effect = replies
                    with patch.object(sam_public, 'sleep') as delay:
                        result, diagnostics = sam_public.fetch_notice(NOTICE, opener=opener)
                    self.assertEqual(diagnostics['request_count'], 3)
                    delay.assert_called_once_with(1)
                    self.assertTrue(error.closed)
                    routes = [call.args[0].full_url for call in opener.open.call_args_list]
                    notice_url = f'https://sam.gov/api/prod/opps/v2/opportunities/{NOTICE}'
                    resource_url = (f'https://sam.gov/api/prod/opps/v3/opportunities/{NOTICE}'
                                    '/resources?excludeDeleted=true&withScanResult=false')
                    self.assertEqual(routes, [notice_url, notice_url, resource_url] if endpoint == 'notice'
                                     else [notice_url, resource_url, resource_url])
                    self.assertEqual(sum('/resources?' not in route for route in routes),
                                     2 if endpoint == 'notice' else 1)
                    headers = [call.args[0].header_items() for call in opener.open.call_args_list]
                    self.assertTrue(all(value == headers[0] for value in headers))
                    self.assertNotIn(PRIVATE, json.dumps((result, diagnostics)))

    def test_retry_limit_is_per_endpoint_and_counts_every_failed_open(self):
        opener = Mock()
        opener.open.side_effect = [HTTPError('', 503, PRIVATE, {}, io.BytesIO()), Response(payload()),
                                   HTTPError('', 429, PRIVATE, {}, io.BytesIO()), Response(resources())]
        with patch.object(sam_public, 'sleep') as delay:
            _, diagnostics = sam_public.fetch_notice(NOTICE, opener=opener)
        self.assertEqual(diagnostics['request_count'], 4)
        self.assertEqual(delay.call_count, 2)
        self.assertEqual([call.args[0] for call in delay.call_args_list], [1, 1])
        self.assertEqual(sam_public.MAX_ATTEMPTS, 2)
        self.assertEqual(sam_public.REQUEST_TIMEOUT, 15)
        self.assertEqual(sam_public.RETRY_DELAY, 1)
        self.assertLess(25 * 2 * (2 * sam_public.REQUEST_TIMEOUT + sam_public.RETRY_DELAY), 30 * 60)

    def test_exhausted_http_failure_has_typed_sanitized_diagnostics(self):
        for endpoint in ('notice', 'resources'):
            with self.subTest(endpoint=endpoint):
                errors = [HTTPError('https://sam.gov/' + PRIVATE, 503, PRIVATE,
                                    {}, io.BytesIO(PRIVATE.encode())) for _ in range(2)]
                opener = Mock()
                opener.open.side_effect = ([Response(payload())] if endpoint == 'resources' else []) + errors
                with patch.object(sam_public, 'sleep') as delay, self.assertRaises(SamError) as raised:
                    sam_public.fetch_notice(NOTICE, opener=opener)
                expected = 3 if endpoint == 'resources' else 2
                self.assertEqual(opener.open.call_count, expected)
                self.assertEqual(raised.exception.diagnostics['request_count'], expected)
                self.assertEqual(raised.exception.diagnostics['failure_class'], 'transient_transport')
                self.assertEqual(raised.exception.diagnostics['endpoint'], endpoint)
                self.assertEqual(raised.exception.diagnostics['http_status'], 503)
                self.assertTrue(all(error.closed for error in errors))
                delay.assert_called_once_with(1)
                self.assertNotIn(PRIVATE, str(raised.exception) + json.dumps(raised.exception.diagnostics))

    def test_network_timeout_retries_but_unexpected_client_error_does_not(self):
        from urllib.error import URLError
        for error in (URLError(PRIVATE), TimeoutError(PRIVATE), ConnectionResetError(PRIVATE)):
            with self.subTest(error=type(error).__name__):
                opener = Mock(); opener.open.side_effect = [error, Response(payload()), Response(resources())]
                with patch.object(sam_public, 'sleep') as delay:
                    _, diagnostics = sam_public.fetch_notice(NOTICE, opener=opener)
                self.assertEqual(diagnostics['request_count'], 3)
                delay.assert_called_once_with(1)
        for error in (TimeoutError(PRIVATE), RuntimeError(PRIVATE)):
            opener = Mock(); opener.open.side_effect = error
            with patch.object(sam_public, 'sleep'), self.assertRaises(SamError) as raised:
                sam_public.fetch_notice(NOTICE, opener=opener)
            retryable = isinstance(error, TimeoutError)
            self.assertEqual(opener.open.call_count, 2 if retryable else 1)
            self.assertEqual(raised.exception.diagnostics['request_count'], 2 if retryable else 1)
            self.assertEqual(raised.exception.diagnostics['failure_class'],
                             'transient_transport' if retryable else 'invalid_client')
            self.assertNotIn(PRIVATE, str(raised.exception) + json.dumps(raised.exception.diagnostics))

    def test_read_timeout_after_http_success_is_still_a_network_failure(self):
        first = Response(payload())
        first.read = Mock(side_effect=TimeoutError(PRIVATE))
        opener = Mock(); opener.open.side_effect = [first, Response(payload()), Response(resources())]
        with patch.object(sam_public, 'sleep') as delay:
            _, diagnostics = sam_public.fetch_notice(NOTICE, opener=opener)
        self.assertEqual(diagnostics['request_count'], 3)
        self.assertTrue(first.closed)
        delay.assert_called_once_with(1)

    def test_nonretry_http_and_redirects_are_not_retried(self):
        for status in (301, 302, 307, 400, 401, 404, 410, 422):
            with self.subTest(status=status):
                opener = Mock()
                opener.open.side_effect = HTTPError('https://sam.gov/' + PRIVATE, status, PRIVATE,
                                                    {'Location': 'https://evil.test/' + PRIVATE}, io.BytesIO())
                with patch.object(sam_public, 'sleep') as delay, self.assertRaises(SamError) as raised:
                    sam_public.fetch_notice(NOTICE, opener=opener)
                self.assertEqual(opener.open.call_count, 1)
                self.assertEqual(raised.exception.diagnostics['failure_class'], 'nonretry_http')
                delay.assert_not_called()
                self.assertNotIn(PRIVATE, json.dumps(raised.exception.diagnostics))

    def test_long_or_unparseable_retry_after_stops_within_budget(self):
        for retry_after in ('2', '120', 'Wed, 14 Oct 2026 00:00:00 GMT', PRIVATE):
            with self.subTest(retry_after=retry_after):
                opener = Mock()
                opener.open.side_effect = HTTPError('', 429, PRIVATE,
                                                    {'Retry-After': retry_after}, io.BytesIO())
                with patch.object(sam_public, 'sleep') as delay, self.assertRaises(SamError) as raised:
                    sam_public.fetch_notice(NOTICE, opener=opener)
                self.assertEqual(opener.open.call_count, 1)
                self.assertEqual(raised.exception.diagnostics['failure_class'], 'transient_transport')
                delay.assert_not_called()
                self.assertNotIn(PRIVATE, json.dumps(raised.exception.diagnostics))

    def test_http_error_response_objects_follow_same_bounded_status_policy(self):
        error = Response(PRIVATE.encode(), 503)
        opener = Mock(); opener.open.side_effect = [Response(payload()), error, Response(resources())]
        with patch.object(sam_public, 'sleep') as delay:
            _, diagnostics = sam_public.fetch_notice(NOTICE, opener=opener)
        self.assertEqual(diagnostics['request_count'], 3)
        self.assertEqual(error.sizes, [])
        self.assertTrue(error.closed)
        delay.assert_called_once_with(1)

    def test_structurally_invalid_snapshot_is_not_a_transient_failure(self):
        broken = resources()
        broken['_embedded']['opportunityAttachmentList'][0]['opportunityId'] = OTHER
        opener = Mock(); opener.open.side_effect = [Response(payload()), Response(broken)]
        with patch.object(sam_public, 'sleep') as delay, self.assertRaises(SamError) as raised:
            sam_public.fetch_notice(NOTICE, opener=opener)
        self.assertEqual(opener.open.call_count, 2)
        self.assertEqual(raised.exception.diagnostics['request_count'], 2)
        self.assertEqual(raised.exception.diagnostics['failure_class'], 'response_schema')
        delay.assert_not_called()

    def test_oversized_or_non_json_body_fails_before_second_request(self):
        for body in (b'x' * (sam_public.MAX_BYTES + 1), b'<html>private error</html>'):
            opener = Mock()
            opener.open.return_value = Response(body)
            with patch.object(sam_public, 'sleep') as delay, self.assertRaises(SamError) as raised:
                sam_public.fetch_notice(NOTICE, opener=opener)
            self.assertEqual(opener.open.call_count, 1)
            self.assertEqual(raised.exception.diagnostics['request_count'], 1)
            self.assertEqual(raised.exception.diagnostics['failure_class'], 'response_schema')
            delay.assert_not_called()

    def test_fingerprint_binds_description_deadline_and_resource_manifest(self):
        original = sam_public.snapshot(payload(), resources(), NOTICE)['review_sha256']
        changes = []
        row = payload(); row['description'][0]['body'] += ' eligibility changed'; changes.append((row, resources()))
        row = payload(); row['data2']['solicitation']['deadlines']['response'] = '2026-10-01'; changes.append((row, resources()))
        files = resources(); files['_embedded']['opportunityAttachmentList'][0]['attachments'][0]['accessLevel'] = 'restricted'; changes.append((payload(), files))
        files = resources(); files['_embedded']['opportunityAttachmentList'][0]['attachments'][0]['resourceId'] = 'd' * 32; changes.append((payload(), files))
        files = resources(); files['_embedded']['opportunityAttachmentList'][0]['attachments'][0]['accessStatus'] = 'restricted'; changes.append((payload(), files))
        for row, files in changes:
            self.assertNotEqual(sam_public.snapshot(row, files, NOTICE)['review_sha256'], original)

    def test_changed_link_destination_invalidates_review_fingerprint(self):
        files = resources()
        attachment = files['_embedded']['opportunityAttachmentList'][0]['attachments'][0]
        attachment.update(type='link', uri='https://agency.gov/old-call.pdf')
        first = sam_public.snapshot(payload(), files, NOTICE)
        attachment['uri'] = 'https://agency.gov/revised-call.pdf'
        second = sam_public.snapshot(payload(), files, NOTICE)
        self.assertNotEqual(first['review_sha256'], second['review_sha256'])

    def test_nested_setaside_cannot_be_hidden_by_legacy_none_alias(self):
        row = payload()
        row['data2']['setAside'] = 'NONE'
        row['data2']['solicitation']['setAside'] = 'SBA'
        notice = sam_public.snapshot(row, resources(), NOTICE)
        self.assertEqual(notice['set_asides'], ['NONE', 'SBA'])
        pinned = approval(); pinned['review_sha256'] = notice['review_sha256']
        record, reasons = sam_reviewed.make_record(notice, pinned, TODAY)
        self.assertIn('restrictive_set_aside', reasons)
        self.assertEqual(record['status'], 'unverified')
        self.assertFalse(record.get('eligibility_text'))

    def test_identity_latest_flags_and_resource_ownership_fail_closed(self):
        cases = []
        row=payload(); row['id']=OTHER; cases.append((row,resources()))
        row=payload(); row['archived']='false'; cases.append((row,resources()))
        row=payload(); row['_links']['opportunity:publish:latest']['href']='https://evil.test/'+NOTICE; cases.append((row,resources()))
        row=payload(); row['_links']['opportunity:publish:latest']['href']='/opps/v2/opportunities/'+OTHER; cases.append((row,resources()))
        files=resources(); files['_embedded']['opportunityAttachmentList'][0]['opportunityId']=OTHER; cases.append((payload(),files))
        files=resources(); group=files['_embedded']['opportunityAttachmentList'][0]; group['attachments'].append(deepcopy(group['attachments'][0])); cases.append((payload(),files))
        for row, files in cases:
            with self.subTest(row=row.get('id')):
                with self.assertRaises(SamError):
                    sam_public.snapshot(row, files, NOTICE)


class ReviewedAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.notice = sam_public.snapshot(payload(), resources(), NOTICE)
        self.approval = approval()

    def test_public_entry_and_invited_full_are_preserved_as_distinct_stages(self):
        from scripts.submission_schedule import project
        record, reasons = sam_reviewed.make_record(self.notice, self.approval, TODAY)
        self.assertEqual(reasons, [])
        self.assertEqual(record['status'], 'posted')
        self.assertTrue(record['preliminary_required'])
        selected=project(record, TODAY)['next_submission']
        self.assertEqual((selected['event']['kind'], selected['date'], selected['access']),
                         ('preproposal', '2026-10-20', 'open'))
        events=record['deadlines']
        required=[e for e in events if e.get('kind')=='preproposal'][0]
        full=[e for e in events if e.get('kind')=='full_application'][0]
        self.assertTrue(required['required'])
        self.assertEqual(required['requirement_citation']['quote'], self.approval['cycles'][0]['entry']['quote'])
        self.assertTrue(full['invitation_required'])
        self.assertEqual(full['prerequisite'], 'invitation')
        self.assertEqual(full['time'], '15:00')
        self.assertEqual(full['timezone'], 'America/New_York')

    def test_passed_required_abstract_closes_call_despite_future_full_deadline(self):
        record, reasons = sam_reviewed.make_record(self.notice, self.approval, date(2026,10,21))
        self.assertIn('entry_closed', reasons)
        self.assertEqual(record['status'], 'expired')
        self.assertFalse(record.get('eligibility_text'))

    def test_later_cycle_does_not_inherit_expired_cycle_prerequisite(self):
        self.approval['cycles'].append({'name':'Winter', 'entry':event('preproposal','2026-11-01'),
                                        'full':event('full_application','2027-01-01',invited=True)})
        record, reasons=sam_reviewed.make_record(self.notice,self.approval,date(2026,10,21))
        self.assertEqual(reasons,[])
        self.assertEqual({e.get('cycle') for e in record['deadlines'] if e.get('cycle')},{'Winter'})
        self.assertFalse(any(e.get('date')=='2026-10-20' for e in record['deadlines']))

    def test_direct_full_entry_does_not_invent_mandatory_abstract_or_invitation(self):
        self.approval['cycles']=[{'name':'Direct','entry':event('full_application','2026-11-01'),'full':None}]
        record,reasons=sam_reviewed.make_record(self.notice,self.approval,TODAY)
        self.assertEqual(reasons,[])
        self.assertFalse(record['has_preliminary_stage'])
        self.assertFalse(record['preliminary_required'])
        self.assertFalse(any(e.get('invitation_required') for e in record['deadlines']))

    def test_undated_invited_full_stays_unknown_not_umbrella_deadline(self):
        self.approval['cycles'][0]['full']=event('full_application',None,invited=True)
        record,_=sam_reviewed.make_record(self.notice,self.approval,TODAY)
        full=[e for e in record['deadlines'] if e['kind']=='full_application'][0]
        self.assertIsNone(full.get('date'))
        self.assertTrue(full['invitation_required'])
        self.assertEqual(record['close_date'],'2026-10-20')

    def test_changed_evidence_identity_and_lifecycle_revoke_eligibility(self):
        cases=[('review_sha256','0'*64,'reviewed_evidence_changed'),
               ('solicitation_number','OTHER-CALL','identity_changed'),
               ('organization_id','98765','identity_changed'),
               ('latest',False,'superseded_notice'),
               ('latest_notice_id',OTHER,'superseded_notice'),
               ('archived',True,'not_open_notice'),
               ('cancelled',True,'not_open_notice'),
               ('deleted',True,'not_open_notice'),
               ('notice_type','r','not_open_notice'),
               ('archive_date','2026-10-12','archive_date_passed'),
               ('posted_at','2026-10-14','invalid_posted_date')]
        for key,value,reason in cases:
            with self.subTest(key=key):
                notice=dict(self.notice,**{key:value})
                record,reasons=sam_reviewed.make_record(notice,self.approval,TODAY)
                self.assertIn(reason,reasons)
                self.assertNotEqual(record['status'],'posted')
                self.assertFalse(record.get('eligibility_text'))
                self.assertNotIn('page_field_provenance',record)

    def test_approval_not_yet_valid_or_expired_cannot_admit_later_deadline(self):
        for as_of in (date(2026,10,12),date(2026,11,13)):
            record,reasons=sam_reviewed.make_record(self.notice,self.approval,as_of)
            self.assertIn('approval_not_current',reasons)
            self.assertNotEqual(record['status'],'posted')

    def test_removed_approval_explicitly_revokes_previous_snapshot(self):
        cached,_=sam_reviewed.make_record(self.notice,self.approval,TODAY)
        cfg={'schema_version':2,'enabled':False,'approved_notices':[]}
        client=Mock(side_effect=AssertionError('No approved notice should be fetched'))
        rows,diagnostics=sam_reviewed.collect(cfg,TODAY,{'sam-gov':[cached]},client=client)
        client.assert_not_called()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['status'],'unverified')
        self.assertEqual(diagnostics['admitted'],0)

    def test_required_fetch_failure_accounts_for_missing_notice_and_keeps_verified_peer(self):
        other=deepcopy(self.approval)
        other.update(notice_id=OTHER,solicitation_number='DARPA-TEST-26-02')
        cfg=configuration(self.approval);cfg['approved_notices'].append(other)
        def fetch(identifier):
            if identifier==OTHER:raise SamError('public_http_error',{'request_count':1,'http_status':503,'failure_class':'transient_transport'})
            return self.notice,{'request_count':2}
        rows,diagnostics=sam_reviewed.collect(cfg,TODAY,{},client=fetch)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['status'],'posted')
        self.assertEqual(diagnostics['outcome'],'degraded')
        self.assertEqual(diagnostics['request_count'],3)
        self.assertEqual(diagnostics['failures'],[
            {'notice_id':OTHER,'reason':'public_notice_unavailable','http_status':503,'failure_class':'transient_transport'}])
        self.assertEqual(diagnostics['notice_observations'][1]['disposition'],'source_unavailable')
        sam_reviewed.require_reviewed_observations(cfg,diagnostics)

    def test_config_rejects_unsafe_urls_ambiguous_cycles_and_impossible_stages(self):
        changes=[]
        for field,value in [('review_sha256','bad'),('review_after','2026-11-13'),
                            ('evidence_url','https://agency.gov/call?api_key=secret'),
                            ('evidence_url','https://agency.gov.evil.test/call'),
                            ('evidence_url','https://person:secret@agency.gov/call')]:
            item=approval();item[field]=value;changes.append(item)
        for field,value in [('date',None),('invitation_required',True),('required','yes'),
                            ('timezone','not-a-timezone'),('time','25:00'),('kind','registration')]:
            item=approval();item['cycles'][0]['entry'][field]=value;changes.append(item)
        item=approval();item['cycles'][0]['full']['date']='2026-10-19';changes.append(item)
        item=approval();item['cycles'][0]['full']=event('full_application',None,invited=False);changes.append(item)
        item=approval();item['cycles'].append(deepcopy(item['cycles'][0]));changes.append(item)
        for item in changes:
            with self.subTest(item=item):
                with self.assertRaises(SamError):sam_reviewed.validate_config(configuration(item))

    def test_v2_adapter_uses_reviewed_public_transport_without_key_or_listing(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sam.json';path.write_text(json.dumps(configuration()),encoding='utf8')
            listing=Mock(side_effect=AssertionError('Old broad listing must not run'))
            reviewed=Mock(return_value=(self.notice,{'request_count':2,'outcome':'ok'}))
            adapter=SamGovAdapter(config_path=path,client=listing,reviewed_client=reviewed)
            with patch.dict(os.environ,{},clear=True),patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Network disabled')):
                rows,results=registry_collect([adapter],context={'as_of':TODAY})
            self.assertTrue(results[0].ok,results[0].error)
            listing.assert_not_called();reviewed.assert_called_once_with(NOTICE)
            self.assertEqual(len(rows),1)
            self.assertEqual(results[0].diagnostics['request_count'],2)
            live,_,_=resolve_live_records(results,{},TODAY)
            self.assertEqual(len(live),1)


if __name__ == '__main__':
    unittest.main()
