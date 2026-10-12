"""Offline contracts for the measured consolidated DOE Exchange listing."""
import copy
from datetime import date
import hashlib
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.sources.adapters.doe_exchange import ArpaEAdapter, EereExchangeAdapter
from scripts.sources.adapters.doe_exchange_listing import LIST_URL, MAX_BYTES
from scripts.sources.base import CanonicalOpportunity
from scripts.sources.merge import resolve_live_records
from scripts.sources.registry import collect
from scripts.sources import intake

AS_OF = date(2026, 10, 8)
ASPECT = '4d0f9925-93dc-4997-b8f9-652937afbce3'
SCALEUP = 'deda37c5-b4c7-46cc-bc8f-11a453428235'
CMMA = 'b2296432-4f64-4dd7-b0e3-730ef4584226'


def notice(reference, guid, number, title, office, **changes):
    return {'$id': reference, 'FoaId': guid, 'FoaNumber': number,
        'FoaTitle': title, 'OrganizationId': office,
        'OrganizationName': {1: 'ARPA-E', 2: 'CMEI', 4: 'Indian Energy'}[office],
        'SubProgramOfficeName': None,
        'FOATypeName': 'Notice Of Funding Opportunity (NOFO)',
        'AnnouncementStatus': 'Open', 'IsDeleted': False, 'Archived': False,
        'ApprovedForPublic': True, 'AllowSubmissions': True,
        'ModifiedDate': '2026-10-08T10:11:32.173',
        # Published is false for real Open/public records; it is not the gate.
        'Published': False, **changes}


def topic(guid, name='General', **changes):
    return {'FoaId': guid, 'TopicName': name, 'AnnouncementStatus': 'Active',
        'ConceptPaperUpldDeadline': None, 'FullAppSubmissionDeadline': None,
        'SubmissionRegistrationDeadline': None, 'RenewalPhaseSubmissionDeadline': None,
        **changes}


def fixture():
    # Sanitized scalar projection of the complete 2026-10-08 official response.
    return {
        'dbFOAList': [
            notice('1', ASPECT, 'DE-FOA-0003647', 'ASPECT chemical technologies', 2,
                SubProgramOfficeName='CMEI: Alternative Fuel and Feedstocks Office (AFFO)'),
            notice('2', SCALEUP, 'DE-FOA-0003467', 'SCALEUP Ready', 1),
            notice('3', CMMA, 'DE-TA1-0003589', 'Critical Minerals and Materials Accelerator', 2,
                AnnouncementStatus='Closed', ModifiedDate='2026-10-02T12:13:03'),
            {'$ref': '1'}, {'$ref': '2'}, {'$ref': '3'},
        ],
        'dbOrganizations': [
            {'OrganizationId': 1, 'Name': 'ARPA-E', 'IsDeleted': False,
             'FullName': 'Advanced Research Projects Agency (ARPA-E)'},
            {'OrganizationId': 2, 'Name': 'CMEI', 'IsDeleted': False,
             'FullName': 'Office of Critical Minerals and Energy Innovation (CMEI)'},
        ],
        'dbfoaListDetails': [
            *[topic(ASPECT, name, ConceptPaperUpldDeadline='2026-10-09T17:00:00',
                FullAppSubmissionDeadline='2026-12-01T17:00:00')
              for name in ('Topic Area 1a', 'Topic Area 1b', 'Topic Area 2a', 'Topic Area 2b')],
            topic(SCALEUP),
        ],
    }


def page(data):
    return '<html><script>\n' + '\n'.join(
        'const ' + key + ' = ' + json.dumps(value) + ' || [];'
        for key, value in data.items()) + '\n</script></html>'


def parsed(data=None, cls=EereExchangeAdapter):
    adapter = cls()
    adapter.set_context({'as_of': AS_OF})
    with patch.object(adapter, 'fetch', return_value=page(data or fixture())):
        records = adapter.collect()
    return adapter, records


class DoeExchangeMigrationTests(unittest.TestCase):
    def test_office_partition_stable_ids_and_official_detail_route(self):
        _, cmei = parsed()
        _, arpa = parsed(cls=ArpaEAdapter)
        self.assertEqual([r['opportunity_id'] for r in cmei], ['eere-exchange:DE-FOA-0003647'])
        self.assertEqual([r['opportunity_id'] for r in arpa], ['arpa-e:DE-FOA-0003467'])
        self.assertEqual(cmei[0]['detail_page'], 'https://exchange.energy.gov/FoaDetails.aspx?FoaId=' + ASPECT)
        self.assertEqual(cmei[0]['agency'], 'CMEI: Alternative Fuel and Feedstocks Office (AFFO)')
        self.assertEqual(cmei[0]['last_updated'], '2026-10-08')
        self.assertIsNone(arpa[0]['close_date'])
        self.assertFalse(arpa[0]['rolling'])
        self.assertTrue(arpa[0]['status_verification_required'])

    def test_owned_topic_stages_preserve_times_without_guessing_timezone_or_requirement(self):
        _, records = parsed()
        record = records[0]
        self.assertEqual(record['close_date'], '2026-12-01')
        self.assertEqual(record['close_date_kind'], 'submission_window_end')
        self.assertEqual(len(record['deadlines']), 8)
        self.assertEqual({d['kind'] for d in record['deadlines']}, {'concept_paper', 'application'})
        self.assertEqual({d['track'] for d in record['deadlines']},
            {'Topic Area 1a', 'Topic Area 1b', 'Topic Area 2a', 'Topic Area 2b'})
        for event in record['deadlines']:
            self.assertEqual(event['time'], '17:00:00')
            self.assertIsNone(event['timezone'])
            self.assertIsNone(event['required'])
            self.assertEqual(event['obligation'], 'unknown')
            self.assertEqual(event['source_url'], record['detail_page'])

    def test_explicit_offsets_and_renewal_class_survive(self):
        data = fixture()
        data['dbfoaListDetails'] = [topic(ASPECT,
            RenewalPhaseSubmissionDeadline='2026-12-03T17:00:00-05:00'), topic(SCALEUP)]
        event = parsed(data)[1][0]['deadlines'][0]
        self.assertEqual(event['timezone'], '-05:00')
        self.assertEqual(event['application_class'], 'renewal')

    def test_phase_qualifiers_survive_and_conflicting_same_phase_fails(self):
        data = fixture()
        data['dbfoaListDetails'] = [topic(ASPECT, PhaseName='Phase I',
            FullAppSubmissionDeadline='2026-12-01T17:00:00'), topic(ASPECT, PhaseName='Phase II',
            FullAppSubmissionDeadline='2027-01-01T17:00:00'), topic(SCALEUP)]
        self.assertEqual({d['cycle'] for d in parsed(data)[1][0]['deadlines']}, {'Phase I', 'Phase II'})
        data['dbfoaListDetails'][1]['PhaseName'] = 'Phase I'
        with self.assertRaisesRegex(ValueError, 'conflicting topic deadlines'):
            parsed(data)

    def test_registration_is_not_a_new_application_window(self):
        data = fixture()
        data['dbfoaListDetails'] = [topic(ASPECT,
            FullAppSubmissionDeadline='2026-10-01T17:00:00',
            SubmissionRegistrationDeadline='2026-12-01T17:00:00'), topic(SCALEUP)]
        adapter, records = parsed(data)
        self.assertEqual(records, [])
        self.assertEqual(adapter.diagnostics['observed_terminal_records'][0]['status'], 'expired')

    def test_undated_active_topic_does_not_inherit_expired_sibling_date(self):
        data = fixture()
        data['dbfoaListDetails'] = [topic(ASPECT, 'Past',
            FullAppSubmissionDeadline='2026-10-01T17:00:00'), topic(ASPECT, 'Undated'), topic(SCALEUP)]
        _, records = parsed(data)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0]['close_date'])

    def test_closed_undated_cmma_withdraws_cache_and_preserves_source_observation(self):
        adapter = EereExchangeAdapter()
        old = CanonicalOpportunity(title='Critical Minerals and Materials Accelerator',
            external_id='DE-TA1-0003589', opportunity_number='DE-TA1-0003589',
            agency='DOE', url='https://eere-exchange.energy.gov/#FoaId' + CMMA).to_record(
                slug=adapter.slug, source=adapter.display_name, source_type=adapter.source_type)
        with patch.object(adapter, 'fetch', return_value=page(fixture())):
            _, results = collect([adapter], context={'as_of': AS_OF})
        live, cache, summary = resolve_live_records(results,
            {'sources': {adapter.slug: {'records': [old], 'fetched_at': '2026-09-30T00:00:00Z'}}}, AS_OF)
        self.assertTrue(summary[0]['healthy'])
        self.assertEqual([r['opportunity_number'] for r in live], ['DE-FOA-0003647'])
        self.assertEqual(cache['sources'][adapter.slug]['records'], live)
        observation = summary[0]['diagnostics']['observed_terminal_records'][0]
        self.assertEqual(observation['opportunity_id'], old['opportunity_id'])
        self.assertEqual(observation['status'], 'closed')
        self.assertEqual(observation['last_updated'], '2026-10-02T12:13:03')
        self.assertTrue(results[0].snapshot_complete)

    def test_complete_zero_open_source_is_healthy_without_changing_health_policy(self):
        data = fixture()
        data['dbFOAList'][0]['AnnouncementStatus'] = 'Closed'
        adapter = EereExchangeAdapter()
        with patch.object(adapter, 'fetch', return_value=page(data)):
            records, results = collect([adapter], context={'as_of': AS_OF})
        live, _, summary = resolve_live_records(results, {'sources': {}}, AS_OF)
        self.assertEqual(records, [])
        self.assertEqual(live, [])
        self.assertTrue(summary[0]['healthy'])
        self.assertEqual(len(summary[0]['diagnostics']['observed_terminal_records']), 2)
        self.assertEqual((adapter.min_records, adapter.max_records), (0, 300))

    def test_nonfunding_and_other_offices_are_not_admitted(self):
        for kind in ('Request for Information (RFI)', 'Notice of Intent to Publish Announcement (NOI)',
                     'Teaming Partner List'):
            with self.subTest(kind=kind):
                data = fixture()
                data['dbFOAList'][0]['FOATypeName'] = kind
                data['dbFOAList'].append(notice('4', '44444444-4444-4444-4444-444444444444',
                    'DE-FOA-0009999', 'Other office open grant', 4))
                self.assertEqual(parsed(data)[1], [])

    def test_terminal_and_unverified_states_never_become_posted(self):
        cases = [({'AnnouncementStatus': 'Closed'}, 'closed'),
            ({'AnnouncementStatus': 'Archived'}, 'archived'), ({'Archived': True}, 'archived'),
            ({'IsDeleted': True}, 'withdrawn'), ({'ApprovedForPublic': False}, 'unverified'),
            ({'AnnouncementStatus': 'Not Published'}, 'unverified'), ({'AllowSubmissions': False}, 'unverified')]
        for changes, status in cases:
            with self.subTest(changes=changes):
                data = fixture()
                data['dbFOAList'][0].update(changes)
                adapter, records = parsed(data)
                self.assertEqual(records, [])
                self.assertEqual(adapter.diagnostics['observed_terminal_records'][0]['status'], status)

    def test_incomplete_response_and_malformed_embedded_arrays_fail(self):
        text = page(fixture())
        mutations = [text[:-7], text.replace('const dbFOAList', 'const other'),
            text.replace(' || [];', ' + other;', 1), '<html>Portal has moved</html>',
            text.replace('"FoaId":', '"FoaId": null, "FoaId":', 1),
            text.replace('</script>', 'const dbOrganizations = [] || [];</script>')]
        for value in mutations:
            with self.subTest(value=value[:70]), self.assertRaises(ValueError):
                list(EereExchangeAdapter().parse(value))

    def test_bad_reference_and_notice_identity_fail_closed(self):
        for change in ('dangling', 'ref_fields', 'duplicate_object', 'duplicate_notice', 'duplicate_number'):
            with self.subTest(change=change):
                data = fixture()
                if change == 'dangling':
                    data['dbFOAList'].append({'$ref': 'missing'})
                elif change == 'ref_fields':
                    data['dbFOAList'].append({'$ref': '1', 'FoaTitle': 'override'})
                else:
                    row = copy.deepcopy(data['dbFOAList'][0])
                    if change != 'duplicate_object':
                        row['$id'] = 'new'
                    if change == 'duplicate_number':
                        row['FoaId'] = '44444444-4444-4444-4444-444444444444'
                    data['dbFOAList'].append(row)
                with self.assertRaises(ValueError):
                    parsed(data)

    def test_office_identity_and_source_schema_drift_fail(self):
        changes = [('dbOrganizations', 1, 'Name', 'Renamed'),
            ('dbFOAList', 0, 'OrganizationName', 'ARPA-E'),
            ('dbFOAList', 0, 'FOATypeName', None),
            ('dbFOAList', 0, 'AnnouncementStatus', 'Unknown'),
            ('dbFOAList', 0, 'Archived', 'false'),
            ('dbFOAList', 0, 'ModifiedDate', 'yesterday'),
            ('dbfoaListDetails', 0, 'FullAppSubmissionDeadline', '2026-02-31T17:00:00')]
        for group, index, key, value in changes:
            with self.subTest(key=key):
                data = fixture()
                data[group][index][key] = value
                with self.assertRaises(ValueError):
                    parsed(data)
        data = fixture()
        del data['dbfoaListDetails'][0]['FullAppSubmissionDeadline']
        with self.assertRaises(ValueError):
            parsed(data)
        data = fixture()
        data['dbfoaListDetails'] = []
        with self.assertRaises(ValueError):
            parsed(data)

    def test_notice_and_event_overflow_are_not_truncated(self):
        adapter = EereExchangeAdapter()
        adapter.max_records = 1
        with self.assertRaisesRegex(ValueError, 'health bound'):
            list(adapter.parse(page(fixture())))
        data = fixture()
        data['dbfoaListDetails'] = [topic(ASPECT, 'Topic ' + str(i),
            FullAppSubmissionDeadline='2026-12-01T17:00:00') for i in range(51)]
        with self.assertRaisesRegex(ValueError, 'deadline limit'):
            parsed(data)

    def test_fetch_uses_only_measured_doe_cap_and_preserves_provenance(self):
        from scripts.sources import http
        content = page(fixture()).encode('utf-8')
        response = {'url': LIST_URL, 'status_code': 200, 'content': content}
        with patch('scripts.extract_document_evidence.download_document', return_value=response) as download, \
             patch('scripts.sources.adapters.doe_exchange.PoliteClient') as client:
            client.return_value.timeout = (15, 60)
            adapter = EereExchangeAdapter()
            self.assertEqual(adapter.fetch(), content.decode())
            args, kwargs = download.call_args
            self.assertEqual(args[0], LIST_URL)
            self.assertIn('Funding-Finder-Sources', args[1]['User-Agent'])
            self.assertEqual(kwargs['maximum_bytes'], 32 * 1024 * 1024)
            self.assertEqual(MAX_BYTES, kwargs['maximum_bytes'])
            self.assertEqual(http.MAX_BYTES, 8 * 1024 * 1024)
            self.assertEqual(adapter.diagnostics['response_sha256'], hashlib.sha256(content).hexdigest())
            client.return_value._session.close.assert_called_once_with()

    def test_fetch_rejects_route_drift_and_closes_failed_session(self):
        with patch('scripts.extract_document_evidence.download_document', return_value={
                'url': 'https://exchange.energy.gov/', 'status_code': 200, 'content': b''}), \
             patch('scripts.sources.adapters.doe_exchange.PoliteClient') as client:
            with self.assertRaisesRegex(ValueError, 'route changed'):
                ArpaEAdapter().fetch()
            client.return_value._session.close.assert_called_once_with()


class DoeExchangeIntakeTests(unittest.TestCase):
    def test_old_and_current_notice_urls_use_current_office_parser_and_one_bounded_fetch(self):
        from scripts import extract_document_evidence as docs
        validate_public_url = docs.validate_public_url
        response = {'url': LIST_URL, 'status_code': 200, 'content': page(fixture()).encode('utf-8')}
        for slug, legacy, guid, number in (
                ('arpa-e', 'arpa-e-foa.energy.gov', SCALEUP, 'DE-FOA-0003467'),
                ('eere-exchange', 'eere-exchange.energy.gov', ASPECT, 'DE-FOA-0003647')):
            canonical = 'https://exchange.energy.gov/FoaDetails.aspx?FoaId=' + guid
            for url in (canonical, f'https://{legacy}/#FoaId{guid}',
                        f'https://{legacy}/Default.aspx#FoaId{guid.upper()}'):
                with self.subTest(slug=slug, url=url):
                    injected = Mock(timeout=(15, 60))
                    adapter = intake.supported_adapter(slug)
                    queried = []

                    def resolver(host, port):
                        queried.append(host)
                        if host in {'arpa-e-foa.energy.gov', 'eere-exchange.energy.gov'}:
                            raise socket.gaierror('fixture: retired host no longer resolves')
                        self.assertEqual(host, 'exchange.energy.gov')
                        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]

                    with patch.object(docs, 'validate_public_url',
                             side_effect=lambda value: validate_public_url(value, resolver=resolver)), \
                         patch('scripts.extract_document_evidence.download_document', return_value=response) as download, \
                         patch('requests.sessions.Session.request', side_effect=AssertionError('preview network forbidden')), \
                         patch.object(adapter, 'parse_html', side_effect=AssertionError('legacy parser used')):
                        entry, record = intake.preview_url(url, slug, client=injected, as_of=AS_OF)
                    self.assertEqual(queried, ['exchange.energy.gov'])
                    self.assertEqual(download.call_count, 1)
                    self.assertEqual(download.call_args.args[0], LIST_URL)
                    self.assertEqual(download.call_args.kwargs['maximum_bytes'], 32 * 1024 * 1024)
                    self.assertIs(download.call_args.kwargs['session'], injected._session)
                    injected.get_text.assert_not_called()
                    injected._session.close.assert_not_called()
                    self.assertEqual(entry, {'kind': 'url', 'adapter': slug, 'url': canonical})
                    self.assertEqual(record['opportunity_id'], slug + ':' + number)
                    self.assertEqual(record['detail_page'], canonical)
                    self.assertTrue(all(d['source_url'] == canonical for d in record['deadlines']))

    def test_current_dns_must_be_public_and_resolvable_before_any_listing_fetch(self):
        from scripts import extract_document_evidence as docs
        validate_public_url = docs.validate_public_url
        failures = {'private': 'non-public address', 'mixed': 'non-public address',
                    'unresolved': 'Could not resolve', 'empty': 'no public addresses'}
        for slug, legacy, guid in (
                ('arpa-e', 'arpa-e-foa.energy.gov', SCALEUP),
                ('eere-exchange', 'eere-exchange.energy.gov', ASPECT)):
            canonical = 'https://exchange.energy.gov/FoaDetails.aspx?FoaId=' + guid
            for url in (canonical, f'https://{legacy}/#FoaId{guid}',
                        f'https://{legacy}/Default.aspx#FoaId{guid}'):
                for outcome, message in failures.items():
                    with self.subTest(slug=slug, url=url, dns=outcome):
                        queried = []

                        def resolver(host, port):
                            queried.append(host)
                            self.assertEqual(host, 'exchange.energy.gov', 'retired selector host was queried')
                            if outcome == 'unresolved':
                                raise socket.gaierror('fixture: current host unavailable')
                            addresses = {'private': ['127.0.0.1'],
                                         'mixed': ['93.184.216.34', '10.0.0.1'], 'empty': []}[outcome]
                            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, port))
                                    for address in addresses]

                        with patch.object(docs, 'validate_public_url',
                                 side_effect=lambda value: validate_public_url(value, resolver=resolver)), \
                             patch.object(docs, 'download_document') as download, \
                             patch('requests.sessions.Session.request', side_effect=AssertionError('preview network forbidden')):
                            with self.assertRaisesRegex(RuntimeError, message):
                                intake.preview_url(url, slug, as_of=AS_OF)
                        self.assertEqual(queried, ['exchange.energy.gov'])
                        download.assert_not_called()

    def test_cross_office_closed_and_unlisted_guids_never_preview(self):
        response = {'url': LIST_URL, 'status_code': 200, 'content': page(fixture()).encode('utf-8')}
        for slug, guid in (('arpa-e', ASPECT), ('eere-exchange', SCALEUP),
                           ('eere-exchange', CMMA), ('arpa-e', '11111111-1111-1111-1111-111111111111')):
            with self.subTest(slug=slug, guid=guid), \
                 patch('scripts.extract_document_evidence.validate_public_url', side_effect=lambda value: value), \
                 patch('scripts.extract_document_evidence.download_document', return_value=response) as download:
                with self.assertRaisesRegex(ValueError, 'exactly one'):
                    intake.preview_url('https://exchange.energy.gov/FoaDetails.aspx?FoaId=' + guid,
                        slug, as_of=AS_OF)
                self.assertEqual(download.call_count, 1)

    def test_arbitrary_url_host_path_credentials_and_query_fail_before_listing_fetch(self):
        canonical = 'https://exchange.energy.gov/FoaDetails.aspx?FoaId=' + SCALEUP
        urls = [f'https://eere-exchange.energy.gov/#FoaId{SCALEUP}',
            canonical.replace('exchange.energy.gov', 'evil.exchange.energy.gov'),
            canonical.replace('/FoaDetails.aspx', '/arbitrary'),
            canonical.replace('https:', 'http:'), canonical.replace('https://', 'https://user:secret@'),
            canonical.replace('.gov/', '.gov:444/'), canonical + '&FoaId=' + SCALEUP,
            canonical + '&other=1', canonical + '#fragment', canonical + 'junk',
            'https://exchange.energy.gov/Default.aspx',
            f'https://arpa-e-foa.energy.gov/arbitrary#FoaId{SCALEUP}',
            f'https://arpa-e-foa.energy.gov/?other=1#FoaId{SCALEUP}']
        for url in urls:
            with self.subTest(url=url), \
                 patch('scripts.extract_document_evidence.validate_public_url', side_effect=lambda value: value), \
                 patch('scripts.extract_document_evidence.download_document') as download:
                with self.assertRaises(ValueError):
                    intake.preview_url(url, 'arpa-e', as_of=AS_OF)
                download.assert_not_called()

    def test_saved_legacy_and_new_selectors_normalize_without_mutating_input(self):
        old = {'kind': 'url', 'adapter': 'eere-exchange',
               'url': 'https://eere-exchange.energy.gov/#FoaId' + ASPECT}
        current = {'kind': 'url', 'adapter': 'arpa-e',
                   'url': 'https://exchange.energy.gov/FoaDetails.aspx?FoaId=' + SCALEUP}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'intake.json'
            path.write_text(json.dumps({'schema_version': 1, 'entries': [old, current]}), encoding='utf-8')
            before = path.read_bytes()
            adapter = intake.MaintainedInputs()
            adapter.set_context({'intake_path': path, 'as_of': AS_OF})
            with patch('requests.sessions.Session.request', side_effect=AssertionError('selector fetch')):
                self.assertEqual(adapter.collect(), [])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(adapter.diagnostics['native_url_selectors'], [
                {'adapter': old['adapter'], 'url': 'https://exchange.energy.gov/FoaDetails.aspx?FoaId=' + ASPECT},
                {'adapter': current['adapter'], 'url': current['url']}])

    def test_nsf_preview_keeps_its_existing_feed_path(self):
        url = 'https://www.nsf.gov/funding/opportunities/example'
        opportunity = CanonicalOpportunity(title='Research funding', external_id='example', url=url,
            close_date='2026-12-31')
        adapter = SimpleNamespace(slug='nsf-funding', display_name='NSF', source_type='Federal',
            feed_url='https://www.nsf.gov/funding/feed', parse=Mock(return_value=[opportunity]))
        client = Mock()
        with patch.object(intake, 'supported_adapter', return_value=adapter), \
             patch('scripts.extract_document_evidence.validate_public_url', side_effect=lambda value: value):
            entry, record = intake.preview_url(url, 'nsf-funding', client=client, as_of=AS_OF)
        client.get_text.assert_called_once_with(adapter.feed_url)
        adapter.parse.assert_called_once_with(client.get_text.return_value)
        self.assertEqual(entry['url'], url)
        self.assertEqual(record['opportunity_id'], 'nsf-funding:example')


if __name__ == '__main__':
    unittest.main()
