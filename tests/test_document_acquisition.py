"""Exact public notice transport never substitutes shells or private resources."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import ssl
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler

import requests

from scripts import document_acquisition as acquisition
from scripts.sources import sam_public
from scripts.sources.sam_api import NoRedirect
from scripts.sources.http import LEGACY_RSA_SUITE
from tests.test_sam_reviewed import NOTICE, OTHER, PRIVATE, payload, resources


URL = 'https://sam.gov/opp/' + NOTICE + '/view'
API = 'https://sam.gov/api/prod/opps/v2/opportunities/' + NOTICE
RESOURCES = ('https://sam.gov/api/prod/opps/v3/opportunities/' + NOTICE
             + '/resources?excludeDeleted=true&withScanResult=false')
BODY = '<h2>Research submission</h2><p>Full proposal deadline: December 10, 2026.</p>'


class Response:
    def __init__(self, value, url, *, status=200, on_read=None):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.stream, self.status, self.url = io.BytesIO(raw), status, url
        self.headers, self.sizes, self.closed, self.on_read = {}, [], False, on_read

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def geturl(self):
        return self.url

    def read1(self, size):
        self.sizes.append(size)
        if self.on_read:
            on_read, self.on_read = self.on_read, None
            on_read()
        return self.stream.read(size)


def notice():
    value = payload()
    value['description'][0]['body'] = BODY
    return value


class SamDocumentAcquisitionContracts(unittest.TestCase):
    def read(self, value=None, files=None, *, headers=None, maximum_bytes=sam_public.MAX_BYTES):
        value = notice() if value is None else value
        files = resources() if files is None else files
        opener = Mock()
        opener.open.side_effect = [Response(value, API), Response(files, RESOURCES)]
        with patch.object(sam_public, 'build_opener', return_value=opener):
            result = acquisition.read_document(URL, headers, maximum_bytes=maximum_bytes)
        return result, opener

    def test_exact_route_identity_and_policy_do_not_claim_lookalikes_or_credential_urls(self):
        for url in (URL, URL + '/', URL.replace('/opp/', '/workspace/contract/opp/'), URL.replace('sam.gov/', 'sam.gov:443/')):
            with self.subTest(url=url):
                self.assertEqual(acquisition.sam_notice_id(url), NOTICE)
                self.assertEqual(acquisition.acquisition_identity(url), acquisition.SAM_POLICY)
        invalid = (URL.replace('https:', 'http:'), URL.replace('sam.gov', 'sam.gov.evil.test'),
                   URL.replace('sam.gov', 'user:password@sam.gov'), URL + '?api_key=SECRET',
                   URL + '#source', URL.replace('/view', '/preview'), URL.replace(NOTICE, NOTICE.upper()),
                   URL.replace('sam.gov', 'sam.gov:444'), URL + '\n', 'https://sam.gov/search/', None)
        with patch.object(sam_public, 'fetch_notice_description') as fetch:
            for url in invalid:
                with self.subTest(url=url):
                    self.assertIsNone(acquisition.sam_notice_id(url))
                    self.assertIsNone(acquisition.read_document(url))
        fetch.assert_not_called()

    def test_owned_body_only_with_exact_provenance_and_no_auth_or_synthetic_not_modified(self):
        headers = {'Authorization': PRIVATE, 'Cookie': PRIVATE, 'If-None-Match': 'old-shell',
                   'If-Modified-Since': 'yesterday', 'User-Agent': PRIVATE}
        value, files = notice(), resources()
        value['description'][0]['body'] += ('<script>' + PRIVATE + '</script>'
            '<a href="https://user:password@private.test/file?api_key=SECRET">Official details</a>')
        files['_embedded']['opportunityAttachmentList'][0]['attachments'][0].update(
            accessLevel='private', explicitAccess='1', exportControlled='1',
            uri='https://private.test/restricted?token=SECRET')
        response, opener = self.read(value, files, headers=headers)
        self.assertEqual(response['status_code'], 200)
        self.assertIsNone(response['etag'])
        self.assertIsNone(response['last_modified'])
        self.assertIn(BODY.encode(), response['content'])
        self.assertNotIn(PRIVATE, str(response))
        self.assertNotIn('private.test', str(response))
        self.assertNotIn('SECRET', str(response))
        provenance = response['retrieval_provenance']
        self.assertEqual(set(provenance), {'schema_version', 'policy', 'representation', 'notice_id', 'api_url',
                                         'body_sha256', 'review_sha256', 'organization_id', 'solicitation_number'})
        self.assertEqual(provenance['notice_id'], NOTICE)
        self.assertEqual(provenance['api_url'], API)
        self.assertEqual(provenance['body_sha256'], hashlib.sha256(response['content']).hexdigest())
        self.assertEqual(provenance['review_sha256'], sam_public.snapshot(value, files, NOTICE)['review_sha256'])
        self.assertEqual(provenance['organization_id'], value['data2']['organizationId'])
        self.assertEqual(provenance['solicitation_number'], value['data2']['solicitationNumber'])
        self.assertEqual([call.args[0].full_url for call in opener.open.call_args_list], [API, RESOURCES])
        for call in opener.open.call_args_list:
            self.assertLessEqual(call.kwargs['timeout'], sam_public.REQUEST_TIMEOUT)
            request_headers = dict(call.args[0].header_items())
            self.assertEqual(set(request_headers), {'Accept', 'User-agent'})
            self.assertNotIn(PRIVATE, str(request_headers))

    def test_document_opener_disables_environment_proxy_and_redirect_credentials(self):
        opener = Mock(); opener.open.side_effect = [Response(notice(), API), Response(resources(), RESOURCES)]
        with patch.object(sam_public, 'build_opener', return_value=opener) as build:
            acquisition.read_document(URL)
        proxy, redirect = build.call_args.args
        self.assertIsInstance(proxy, ProxyHandler)
        self.assertEqual(proxy.proxies, {})
        self.assertIsInstance(redirect, NoRedirect)
        self.assertIsNone(redirect.redirect_request(None, None, 302, '', {}, 'https://private.test/'))

    def test_wrong_notice_description_or_resource_identity_cannot_fall_back_to_a_shell(self):
        mutations = ('id', 'opportunityId', 'description', 'resource')
        for mutation in mutations:
            value, files = notice(), resources()
            if mutation == 'description':
                value['description'][0]['opportunityId'] = OTHER
            elif mutation == 'resource':
                files['_embedded']['opportunityAttachmentList'][0]['opportunityId'] = OTHER
            else:
                value[mutation] = OTHER
            with self.subTest(mutation=mutation), self.assertRaises(acquisition.DocumentAcquisitionError) as raised:
                self.read(value, files)
            self.assertEqual(raised.exception.document_reason, 'sam_notice_schema')

    def test_superseded_unpublished_archived_cancelled_or_deleted_notice_is_not_current_evidence(self):
        for field in ('latest', 'archived', 'cancelled', 'deleted', 'status', 'latest_id'):
            value = notice()
            if field == 'status':
                value['status']['code'] = 'draft'
            elif field == 'latest_id':
                value['latest'] = False
                value['_links']['opportunity:publish:latest']['href'] = '/opps/v2/opportunities/' + OTHER
            else:
                value[field] = field != 'latest'
            with self.subTest(field=field), self.assertRaises(acquisition.DocumentAcquisitionError) as raised:
                self.read(value)
            self.assertEqual(raised.exception.document_reason, 'sam_notice_not_current')

    def test_missing_or_executable_only_description_cannot_be_a_healthy_document(self):
        for body in ('', ' \n', '<script>' + PRIVATE + '</script>', '<p>&nbsp;</p>'):
            value = notice(); value['description'][0]['body'] = body
            with self.subTest(body=body), self.assertRaises(acquisition.DocumentAcquisitionError) as raised:
                self.read(value)
            self.assertEqual(raised.exception.document_reason, 'sam_description_missing')

    def test_duplicate_description_identity_is_rejected_and_owned_parts_order_is_stable(self):
        value = notice()
        value['description'].append(deepcopy(value['description'][0]))
        with self.assertRaises(acquisition.DocumentAcquisitionError):
            self.read(value)
        value['description'][1].update(descriptionId='description-two', body='<p>Second owned part.</p>')
        first, _ = self.read(value)
        value['description'].reverse()
        second, _ = self.read(value)
        self.assertEqual(first['content'], second['content'])
        self.assertEqual(first['retrieval_provenance'], second['retrieval_provenance'])

    def test_representation_and_raw_api_payload_limits_are_enforced(self):
        with self.assertRaises(acquisition.DocumentAcquisitionError) as raised:
            self.read(maximum_bytes=30)
        self.assertEqual(raised.exception.document_reason, 'sam_description_oversize')
        opener = Mock(); response = Response(b'x' * 257, API); opener.open.return_value = response
        with patch.object(sam_public, 'MAX_BYTES', 256), patch.object(sam_public, 'build_opener', return_value=opener):
            with self.assertRaises(acquisition.DocumentAcquisitionError):
                acquisition.read_document(URL)
        self.assertEqual(opener.open.call_count, 1)
        self.assertLessEqual(max(response.sizes), 257)
        self.assertTrue(response.closed)

    def test_one_total_deadline_spans_both_endpoint_reads(self):
        clock = [100.0]
        def elapsed(seconds):
            clock[0] += seconds
        opener = Mock(); opener.open.side_effect = [Response(notice(), API, on_read=lambda: elapsed(16)),
                                                   Response(resources(), RESOURCES, on_read=lambda: elapsed(15))]
        with patch.object(acquisition, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(sam_public, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(sam_public, 'build_opener', return_value=opener):
            with self.assertRaises(acquisition.DocumentAcquisitionError) as raised:
                acquisition.read_document(URL, timeout=30)
        self.assertEqual(raised.exception.document_reason, 'sam_acquisition_timeout')
        self.assertEqual([call.kwargs['timeout'] for call in opener.open.call_args_list], [15, 14])

    def test_long_retry_after_and_redirects_do_not_render_errors_or_follow_any_other_route(self):
        for status, headers in ((429, {'Retry-After': '120'}), (302, {'Location': 'https://private.test/' + PRIVATE})):
            opener = Mock(); opener.open.side_effect = HTTPError(API, status, PRIVATE, headers, io.BytesIO(PRIVATE.encode()))
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr), patch.object(sam_public, 'build_opener', return_value=opener):
                with self.assertRaises(acquisition.DocumentAcquisitionError) as raised:
                    acquisition.read_document(URL)
            self.assertEqual(opener.open.call_count, 1)
            self.assertEqual(raised.exception.http_status, status)
            self.assertNotIn(PRIVATE, str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertEqual(stdout.getvalue() + stderr.getvalue(), '')

    def test_unexpected_response_origin_is_rejected_without_reading_its_body(self):
        response = Response(notice(), 'https://private.test/redirected')
        opener = Mock(); opener.open.return_value = response
        with patch.object(sam_public, 'build_opener', return_value=opener):
            with self.assertRaises(acquisition.DocumentAcquisitionError):
                acquisition.read_document(URL)
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(response.sizes, [])
        self.assertTrue(response.closed)


class NasaSessionProfileContracts(unittest.TestCase):
    def test_profile_is_scoped_to_exact_two_https_origins_and_keeps_certificate_checks(self):
        with requests.Session() as session:
            default = session.get_adapter('https://example.gov/')
            verify, trust_env = session.verify, session.trust_env
            acquisition.configure_session(session)
            for host in acquisition.NASA_HOSTS:
                for port in ('', ':443'):
                    url = 'https://' + host + port + '/official-notice'
                    self.assertEqual(acquisition.acquisition_identity(url), acquisition.NASA_POLICY)
                    adapter = session.get_adapter(url)
                    self.assertIsNot(adapter, default)
                    context = adapter.poolmanager.connection_pool_kw['ssl_context']
                    original = ssl.create_default_context()
                    self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                    self.assertTrue(context.check_hostname)
                    self.assertEqual(context.security_level, original.security_level)
                    old = {item['name'] for item in original.get_ciphers()}
                    new = {item['name'] for item in context.get_ciphers()}
                    self.assertEqual(new, old | {LEGACY_RSA_SUITE})
                    self.assertEqual(old - new, set())
                for other in ('https://' + host + '.evil.test/', 'https://' + host + ':444/', 'http://' + host + '/'):
                    self.assertIsNone(acquisition.acquisition_identity(other))
                    if other.startswith('https:'):
                        self.assertIs(session.get_adapter(other), default)
            self.assertIs(session.get_adapter('https://example.gov/redirect-target'), default)
            self.assertEqual((session.verify, session.trust_env), (verify, trust_env))


if __name__ == '__main__':
    unittest.main()
