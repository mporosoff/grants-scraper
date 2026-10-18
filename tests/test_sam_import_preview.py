"""Offline preview contracts: bounded requests, safe reports, no catalog writes."""
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
from urllib.parse import quote, quote_plus

import yaml

from tools import sam_import_preview as sam


TODAY = date(2026, 10, 1)
KEY = 'synthetic-SAM-secret+with/slash and space'
IDS = tuple(character * 32 for character in 'abcd')
WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/sam-import-preview.yml'
CONTEXT = {'GITHUB_ACTIONS': 'true', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
           'GITHUB_REF': 'refs/heads/main', 'GITHUB_REPOSITORY': 'mporosoff/grants-scraper',
           'GITHUB_WORKFLOW_REF': 'mporosoff/grants-scraper/.github/workflows/sam-import-preview.yml@refs/heads/main',
           'SAM_API_KEY': KEY}


def notice(notice_id=IDS[0], **changes):
    return {'noticeId': notice_id, 'title': 'Broad Agency Announcement for research',
            'solicitationNumber': 'DARPA-PA-26-02-02',
            'fullParentPathName': 'DEPT OF DEFENSE.DEFENSE ADVANCED RESEARCH PROJECTS AGENCY (DARPA)',
            'postedDate': '2026-09-30', 'type': 'Solicitation', 'active': 'Yes',
            'responseDeadLine': '2026-11-30T17:00:00-05:00', 'naicsCode': '541715',
            'classificationCode': 'AD11', 'typeOfSetAside': '',
            'description_route': 'v1',
            **changes}


class SamImportPreviewTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.original = {}
        for name in ('data/opportunities.js', 'data/source_records.json', 'config/sam_gov.json'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('unchanged ' + name).encode())
            self.original[name] = path.read_bytes()
        self.rows = [notice()]
        self.records = []
        self.diagnostics = {'request_count': 1, 'http_status': 200, 'total_records': 1,
                            'complete': True, 'rate_limit': {}}
        self.listing = Mock(side_effect=lambda *_args, **_kwargs: (deepcopy(self.rows), deepcopy(self.diagnostics)))
        self.description = Mock(return_value=('University researchers may submit proposals. ' + 'x' * 3000,
                                             {'http_status': 200, 'request_count': 1}))
        self.summary = {'validation': {'ok': True}, 'sources': [{'slug': 'sam-gov', 'status': 'refreshed'}]}

    def run_preview(self, selected=(), *, key=KEY, old_enrich='original-setting'):
        adapter = Mock()
        constructor = Mock(return_value=adapter)

        def merge(**kwargs):
            self.assertIs(kwargs['adapters'][0], adapter)
            self.assertIs(kwargs['write'], False)
            self.assertIs(kwargs['include_disabled'], True)
            self.assertEqual(kwargs['as_of'], TODAY)
            self.assertEqual(kwargs['catalog_path'], self.root / 'data/opportunities.js')
            self.assertEqual(kwargs['cache_path'], self.root / 'data/source_records.json')
            self.assertEqual(os.environ['VPR_ENRICH_LINKS'], 'false')
            # Exercise the adapter's supplied listing client. It must reuse the
            # already fetched response, rather than perform a second query.
            self.assertEqual(constructor.call_args.kwargs['client']('unused', today=TODAY),
                             (self.rows, self.diagnostics))
            return deepcopy(self.summary)

        environment = {} if old_enrich is None else {'VPR_ENRICH_LINKS': old_enrich}
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(sam, 'load_config', return_value={'enabled': False, 'approved_notices': []}), \
                patch.object(sam, 'load_catalog', return_value={'opportunities': self.records}), \
                patch.object(sam, 'SamGovAdapter', constructor), \
                patch.object(sam, 'integrate', side_effect=merge) as integrate, \
                redirect_stdout(io.StringIO()) as stdout:
            report = sam.preview(key, selected, root=self.root, today=TODAY,
                                 listing=self.listing, description=self.description)
            self.assertEqual(os.environ.get('VPR_ENRICH_LINKS'), old_enrich)
        self.assertEqual(stdout.getvalue(), '')
        integrate.assert_called_once()
        constructor.assert_called_once()
        self.assertEqual(constructor.call_args.kwargs['config_path'], self.root / 'config/sam_gov.json')
        self.assertEqual({str(path.relative_to(self.root)).replace('\\', '/'): path.read_bytes()
                          for path in self.root.rglob('*') if path.is_file()}, self.original)
        self.assertFalse(report['catalog_changed'])
        return report

    def assert_no_secret(self, report):
        encoded = json.dumps(report)
        for value in (KEY, quote(KEY, safe=''), quote_plus(KEY, safe='')):
            self.assertNotIn(value, encoded)

    def test_default_preview_makes_one_listing_and_no_description_requests(self):
        report = self.run_preview(old_enrich=None)
        self.listing.assert_called_once_with(KEY, today=TODAY)
        self.description.assert_not_called()
        self.assertEqual(report['request_count'], 1)
        self.assertEqual(report['description_inspections'], [])
        self.assertFalse(report['production_enabled'])
        self.assertEqual(report['approved_notices'], 0)
        self.assertNotIn('description_route', report['candidates'][0])
        self.assertEqual(report['merge_preview'], self.summary)

    def test_absence_from_catalog_is_explicitly_not_a_grants_gov_absence_claim(self):
        report = self.run_preview()
        self.assertEqual(report['candidates'][0]['catalog_matches'],
                         {'same_sam_notice': [], 'same_number_requires_sponsor_check': []})
        self.assertEqual(report['comparison_scope'],
                         'Current catalog only; absence here does not establish absence from Grants.gov')

    def test_only_two_explicitly_selected_descriptions_are_attempted_once(self):
        self.rows = [notice(notice_id) for notice_id in IDS]
        report = self.run_preview((IDS[2], IDS[0]))
        self.listing.assert_called_once_with(KEY, today=TODAY)
        self.assertEqual(self.description.call_count, 2)
        self.assertEqual([call.args for call in self.description.call_args_list],
                         [(KEY, IDS[2]), (KEY, IDS[0])])
        self.assertEqual([call.kwargs['route'] for call in self.description.call_args_list],
                         [self.rows[2]['description_route'], self.rows[0]['description_route']])
        self.assertEqual(report['request_count'], 3)
        self.assertTrue(all(not item['eligibility_verified'] for item in report['description_inspections']))
        self.assertTrue(all(item['status'] == 'review_required' for item in report['description_inspections']))

    def test_invalid_description_selection_is_rejected_before_requests(self):
        for selected in (IDS[:3], (IDS[0], IDS[0]), ('invalid',), ('A' * 32,)):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                sam.preview(KEY, selected, root=self.root, today=TODAY,
                            listing=self.listing, description=self.description)
        self.listing.assert_not_called()
        self.description.assert_not_called()
        self.assertEqual(sam.description_ids('  ' + IDS[0].upper() + ', ' + IDS[1]), list(IDS[:2]))
        self.assertEqual(sam.description_ids(''), [])
        for value in (','.join(IDS[:3]), IDS[0] + ',' + IDS[0], 'not-a-notice'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                sam.description_ids(value)

    def test_absent_notice_and_unverified_description_route_consume_no_request(self):
        self.rows[0].pop('description_route')
        report = self.run_preview((IDS[0], IDS[1]))
        self.description.assert_not_called()
        self.assertEqual(report['request_count'], 1)
        self.assertEqual([item['status'] for item in report['description_inspections']],
                         ['no_verified_description_route', 'not_in_listing'])

    def test_description_failure_consumes_slot_and_does_not_retry(self):
        self.rows.append(notice(IDS[1]))
        self.description.side_effect = [sam.SamError('network_error'), ('Research remains review-only.', {})]
        report = self.run_preview(IDS[:2])
        self.assertEqual(self.description.call_count, 2)
        self.assertEqual(report['request_count'], 3)
        self.assertEqual([item['status'] for item in report['description_inspections']],
                         ['description_unavailable', 'review_required'])

    def test_description_report_contains_bounded_excerpts_not_full_body(self):
        text = ('research ' + 'x' * 700 + ' ') * 12 + 'UNREPORTED_RAW_TAIL'
        self.description.return_value = (text, {'http_status': 200})
        report = self.run_preview((IDS[0],))
        excerpts = report['description_inspections'][0]['excerpts']
        self.assertEqual(len(excerpts), 5)
        self.assertTrue(all(len(value) <= 415 for value in excerpts))
        self.assertNotIn(text, json.dumps(report))
        self.assertNotIn('UNREPORTED_RAW_TAIL', json.dumps(report))
        self.assertRegex(report['description_inspections'][0]['text_sha256'], r'^[a-f0-9]{64}$')

    def test_short_descriptions_are_not_retained_even_when_every_word_is_relevant(self):
        for body in ('University proposals are eligible for this unique short notice.',
                     'Research contact privacy-short@example.gov or (202) 555-0134.',
                     'proposal ' * 110):
            with self.subTest(body=body[:50]):
                self.description.return_value = (body, {'http_status': 200})
                report = self.run_preview((IDS[0],))
                inspection = report['description_inspections'][0]
                self.assertEqual(inspection['excerpts'], [])
                self.assertEqual(inspection['status'], 'review_required')
                self.assertFalse(inspection['eligibility_verified'])
                self.assertRegex(inspection['text_sha256'], r'^[a-f0-9]{64}$')
                self.assertNotIn(body, json.dumps(report))

    def test_excerpt_union_cannot_reconstruct_a_keyword_dense_description(self):
        # The old overlapping windows covered this entire response collectively.
        body = ''.join(f'research block {index:02d} ' + chr(65 + index) * 83 + ' '
                       for index in range(15)).strip()
        self.description.return_value = (body, {'http_status': 200})
        report = self.run_preview((IDS[0],))
        values = report['description_inspections'][0]['excerpts']
        self.assertTrue(values)
        covered, prior_end = set(), 0
        for value in values:
            start = body.index(value)
            end = start + len(value)
            self.assertGreaterEqual(start, prior_end)
            self.assertLessEqual(len(value), 400)
            covered.update(range(start, end))
            prior_end = end
        self.assertLessEqual(sum(map(len, values)), len(body) // 2)
        self.assertLess(len(covered), len(body))
        self.assertNotIn(body, json.dumps(report))

    def test_contacts_and_encoded_html_routes_are_scrubbed_before_window_selection(self):
        contacts = (
            ('private.contact@example.gov', 'private.contact'),
            ('private%2Econtact%40example.gov', 'private.contact'),
            ('private.contact&#64;example.gov', 'private.contact'),
            ('(202) 555-0134 ext. 29', '555-0134'),
            ('202.555.0134', '555.0134'),
            ('2025550134', '2025550134'),
            ('+44 (20) 7946 0958', '7946'),
            ('555-0134', '555-0134'),
            ('mailto:private.contact@example.gov?subject=Research', 'private.contact'),
            ('tel:%2B1-202-555-0134', '555-0134'),
            ('<a href="mailto:private.contact@example.gov">Write to us</a>', 'private.contact'),
            ('&lt;a href="tel:+1-202-555-0134"&gt;Call us&lt;/a&gt;', '555-0134'),
        )
        for contact, fragment in contacts:
            with self.subTest(contact=contact):
                # Contact text crosses the old first window's ending boundary.
                body = 'research ' + 'x' * 270 + ' ' + contact + ' proposal. ' + 'z' * 1500
                self.description.return_value = (body, {'http_status': 200})
                report = self.run_preview((IDS[0],))
                encoded = json.dumps(report)
                self.assertTrue(report['description_inspections'][0]['excerpts'])
                self.assertNotIn(contact, encoded)
                self.assertNotIn(fragment, encoded)
                self.assertNotIn('mailto:', encoded)
                self.assertNotIn('tel:', encoded)
                self.assertNotIn('<a ', encoded)

    def test_contact_scrubbing_keeps_submission_dates_and_scientific_context(self):
        body = ('Research proposals from academic institutions close September 25, 2028 at 16:30 Eastern. '
                'The ISO date is 2028-09-25; submit the BAA-23-100-SOL-00004 abstract. '
                'Contact private-science@example.gov at +1 (202) 555-0199. ' + 'x' * 2000)
        self.description.return_value = (body, {'http_status': 200})
        report = self.run_preview((IDS[0],))
        excerpts = ' '.join(report['description_inspections'][0]['excerpts'])
        for retained in ('academic institutions', 'September 25, 2028', '16:30 Eastern',
                         '2028-09-25', 'BAA-23-100-SOL-00004'):
            self.assertIn(retained, excerpts)
        self.assertIn('[contact omitted]', excerpts)
        self.assertNotIn('private-science', json.dumps(report))
        self.assertNotIn('555-0199', json.dumps(report))

    def test_description_exception_body_never_enters_report_or_logs(self):
        error = sam.SamError('network_error', {'request_count': 1, 'http_status': None,
                                              'outcome': 'network_error', 'rate_limit': {}})
        error.args = ('RAW DESCRIPTION: research private-error@example.gov (202) 555-0192',)
        self.description.side_effect = error
        report = self.run_preview((IDS[0],))
        inspection = report['description_inspections'][0]
        self.assertEqual(inspection['status'], 'description_unavailable')
        self.assertEqual(inspection['excerpts'], [])
        self.assertEqual(report['request_count'], 2)
        self.assertNotIn('text_sha256', inspection)
        for forbidden in ('RAW DESCRIPTION', 'private-error', '555-0192'):
            self.assertNotIn(forbidden, json.dumps(report))

    def test_raw_and_encoded_secret_echoes_are_redacted_before_excerpt_truncation(self):
        for echo in (KEY, quote(KEY, safe=''), quote_plus(KEY, safe=''),
                     quote(KEY, safe='').replace('%2F', '%2f').replace('%2B', '%2b')):
            with self.subTest(echo=echo):
                self.listing.reset_mock()
                self.description.reset_mock()
                self.description.return_value = ('research ' + 'x' * 270 + echo + ' ' + 'z' * 800, {})
                report = self.run_preview((IDS[0],))
                self.assert_no_secret(report)
                self.assertNotIn(echo[:25], json.dumps(report))
                self.assertIn('[redacted]', json.dumps(report))

    def test_decoded_credentials_are_redacted_before_a_window_can_split_them(self):
        echoes = (quote(quote(KEY, safe=''), safe=''),
                  KEY.replace('+', '&#43;').replace('/', '&#47;'))
        for echo in echoes:
            with self.subTest(echo=echo):
                body = 'x' * 100 + 'research ' + 'y' * 270 + echo + ' ' + 'z' * 1600
                self.description.return_value = (body, {'http_status': 200})
                report = self.run_preview((IDS[0],))
                self.assert_no_secret(report)
                encoded = json.dumps(report)
                self.assertNotIn('synthetic-SAM-secret', encoded)
                self.assertNotIn(echo, encoded)
                self.assertIn('[redacted]', encoded)

    def test_candidate_metadata_and_transport_secret_echoes_are_redacted(self):
        self.rows[0]['title'] += ' ' + KEY
        self.description.return_value = ('University research ' + quote(KEY, safe=''),
                                         {'echo': quote_plus(KEY, safe='')})
        self.diagnostics['echo'] = KEY
        report = self.run_preview((IDS[0],), key='  ' + KEY + '  ')
        self.assert_no_secret(report)

    def test_matching_numbers_remain_review_candidates_across_sponsors(self):
        row = notice()
        matches = sam.existing_matches(row, [
            {'opportunity_id': 'grants:1', 'source': 'Grants.gov', 'agency': 'DARPA',
             'opportunity_number': 'DARPA PA 26 02 02'},
            {'opportunity_id': 'other:2', 'source': 'Other source', 'agency': 'Different sponsor',
             'opportunity_number': 'DARPA-PA-26-02-02'},
            {'opportunity_id': 'vpr:3', 'source': 'VPR', 'agency': 'DARPA',
             'opportunity_number': 'UNRELATED', 'detail_page': f'https://sam.gov/workspace/contract/opp/{IDS[0]}/view'},
            {'opportunity_id': 'spoof:4', 'source': 'Other',
             'detail_page': f'https://sam.gov.evil.test/opp/{IDS[0]}/view'},
        ])
        self.assertEqual([item['opportunity_id'] for item in matches['same_sam_notice']], ['vpr:3'])
        self.assertEqual([item['opportunity_id'] for item in matches['same_number_requires_sponsor_check']],
                         ['grants:1', 'other:2'])
        self.assertEqual(sam.existing_matches(row, []),
                         {'same_sam_notice': [], 'same_number_requires_sponsor_check': []})

    def test_merge_failure_restores_unrelated_enrichment_setting(self):
        with patch.dict(os.environ, {'VPR_ENRICH_LINKS': 'preserve-me'}, clear=True), \
                patch.object(sam, 'load_config', return_value={'enabled': False, 'approved_notices': []}), \
                patch.object(sam, 'load_catalog', return_value={'opportunities': []}), \
                patch.object(sam, 'SamGovAdapter'), \
                patch.object(sam, 'integrate', side_effect=ValueError('merge failed')):
            with self.assertRaises(ValueError):
                sam.preview(KEY, root=self.root, today=TODAY, listing=self.listing)
            self.assertEqual(os.environ['VPR_ENRICH_LINKS'], 'preserve-me')

    def test_real_merge_previews_reviewed_disabled_adapter_without_writing_or_refetching(self):
        from scripts.build_catalog import build_catalog
        from scripts.sources.base import CanonicalOpportunity
        from scripts.sources.merge import save_catalog

        record = CanonicalOpportunity(title='Synthetic seed research grant', external_id='100001',
            opportunity_number='TEST-2026', agency='National Science Foundation',
            url='https://www.grants.gov/search-results-detail/100001',
            close_date='2026-12-31').to_record(slug='test', source='Grants.gov', source_type='Federal')
        catalog = build_catalog([record], datetime(2026, 10, 1, tzinfo=timezone.utc), 'synthetic.xml', 0)
        save_catalog(catalog, self.root / 'data/opportunities.js')
        (self.root / 'data/source_records.json').write_text(json.dumps({'schema_version': 1, 'sources': {}}))
        approval = {'notice_id': IDS[0], 'solicitation_number': self.rows[0]['solicitationNumber'],
                    'organization_path': self.rows[0]['fullParentPathName'],
                    'sponsor': 'Defense Advanced Research Projects Agency (DARPA)',
                    'evidence_url': f'https://sam.gov/opp/{IDS[0]}/view',
                    'academic_eligibility_quote': 'Universities are eligible to submit research proposals.',
                    'verified_on': '2026-10-01', 'review_after': '2026-10-20'}
        (self.root / 'config/sam_gov.json').write_text(json.dumps(
            {'schema_version': 1, 'enabled': False, 'approved_notices': [approval]}))
        before = {str(path.relative_to(self.root)): path.read_bytes()
                  for path in self.root.rglob('*') if path.is_file()}
        with patch.dict(os.environ, {'SAM_API_KEY': KEY}, clear=True), \
                patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Unexpected network call')), \
                patch('requests.Session.request', side_effect=AssertionError('Unexpected provider call')):
            report = sam.preview(KEY, root=self.root, today=TODAY,
                                 listing=self.listing, description=self.description)
        self.listing.assert_called_once_with(KEY, today=TODAY)
        self.description.assert_not_called()
        self.assertEqual(report['request_count'], 1)
        self.assertFalse(report['production_enabled'])
        self.assertFalse(report['merge_preview']['written'])
        self.assertTrue(report['merge_preview']['validation']['ok'])
        self.assertEqual(report['merge_preview']['stats']['external_added'], 1)
        self.assertEqual([source['status'] for source in report['merge_preview']['sources']], ['refreshed'])
        self.assertEqual(before, {str(path.relative_to(self.root)): path.read_bytes()
                                 for path in self.root.rglob('*') if path.is_file()})


class SamReviewedPreviewTests(unittest.TestCase):
    """Use the real adapter and canonical merge with offline public snapshots."""

    def setUp(self):
        from scripts.build_catalog import build_catalog
        from scripts.sources.base import CanonicalOpportunity
        from scripts.sources.merge import save_catalog

        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / 'data').mkdir()
        (self.root / 'config').mkdir()
        seed = CanonicalOpportunity(title='Synthetic seed research grant', external_id='100001',
            opportunity_number='TEST-2026', agency='National Science Foundation',
            url='https://www.grants.gov/search-results-detail/100001',
            close_date='2026-12-31').to_record(slug='test', source='Grants.gov', source_type='Federal')
        save_catalog(build_catalog([seed], datetime(2026, 10, 1, tzinfo=timezone.utc), 'synthetic.xml', 0),
                     self.root / 'data/opportunities.js')
        (self.root / 'data/source_records.json').write_text(json.dumps({'schema_version': 1, 'sources': {}}))
        self.config = {'schema_version': 2, 'enabled': False, 'approved_notices': []}
        self.snapshots = {}
        for index, notice_id in enumerate(IDS[:2]):
            number = f'NASA-RESEARCH-2026-{index + 1}'
            source_url = f'https://sam.gov/opp/{notice_id}/view'
            entry = {'kind': 'concept_paper', 'date': '2026-11-30', 'time': '17:00',
                     'timezone': 'America/New_York', 'required': True, 'invitation_required': False,
                     'note': 'Submit the required concept paper through the official portal.',
                     'source_url': source_url, 'quote': 'Concept papers are required by November 30, 2026.'}
            full = dict(entry, kind='full_application', date=None, time=None, timezone=None,
                        required=False, invitation_required=True,
                        note='Full proposals follow invitation; the invitation supplies the due date.',
                        quote='Only invited applicants may submit a full proposal.')
            approval = {'notice_id': notice_id, 'solicitation_number': number, 'organization_id': '12345',
                        'sponsor': 'National Aeronautics and Space Administration', 'evidence_url': source_url,
                        'academic_eligibility_quote': 'Universities are eligible to submit research proposals.',
                        'verified_on': '2026-10-01', 'review_after': '2026-10-31',
                        'review_sha256': str(index + 1) * 64,
                        'summary': 'Research into propulsion and materials science.', 'scope_note': '',
                        'cycles': [{'name': 'Current research cycle', 'entry': entry, 'full': full}]}
            snapshot = {'notice_id': notice_id, 'latest_notice_id': notice_id, 'latest': True,
                        'status': 'published', 'archived': False, 'cancelled': False, 'deleted': False,
                        'title': f'Synthetic NASA research call {index + 1}',
                        'solicitation_number': number, 'organization_id': '12345', 'notice_type': 'o',
                        'classification_code': 'AD11', 'naics_codes': ['541715'], 'set_asides': [],
                        'posted_at': '2026-09-30', 'modified_at': '2026-09-30',
                        'response_deadline': '2026-11-30T17:00:00', 'response_timezone': 'America/New_York',
                        'archive_date': '2026-12-30', 'description_sha256': 'd' * 64,
                        'resources_sha256': 'e' * 64, 'review_sha256': approval['review_sha256']}
            self.config['approved_notices'].append(approval)
            self.snapshots[notice_id] = snapshot
        self.save_config()
        self.public_notice = Mock(side_effect=lambda notice_id: (
            deepcopy(self.snapshots[notice_id]), {'request_count': 2, 'http_status': 200, 'outcome': 'ok'}))
        self.listing = Mock(side_effect=AssertionError('Legacy credentialed listing is forbidden'))
        self.description = Mock(side_effect=AssertionError('Legacy descriptions are forbidden'))

    def save_config(self):
        (self.root / 'config/sam_gov.json').write_text(json.dumps(self.config), encoding='utf8')

    def files(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def run_preview(self):
        before = self.files()
        original_get = os.environ.get

        def no_key_read(name, *args):
            if name == 'SAM_API_KEY':
                raise AssertionError('Reviewed public mode must not read the API key')
            return original_get(name, *args)

        with patch.dict(os.environ, {'SAM_API_KEY': KEY, 'VPR_ENRICH_LINKS': 'preserve-me'}, clear=True), \
                patch.object(os.environ, 'get', side_effect=no_key_read), \
                patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Unexpected network call')), \
                patch('requests.Session.request', side_effect=AssertionError('Unexpected provider call')), \
                redirect_stdout(io.StringIO()) as stdout:
            report = sam.preview(root=self.root, today=TODAY, public_notice=self.public_notice,
                                 listing=self.listing, description=self.description)
            self.assertEqual(os.environ['VPR_ENRICH_LINKS'], 'preserve-me')
        self.assertEqual(before, self.files())
        self.assertEqual(stdout.getvalue(), '')
        self.listing.assert_not_called()
        self.description.assert_not_called()
        self.assertNotIn(KEY, json.dumps(report))
        self.assertFalse(report['catalog_changed'])
        return report

    def test_real_merge_reuses_each_reviewed_snapshot_once_without_key_or_writes(self):
        report = self.run_preview()
        self.assertCountEqual([call.args for call in self.public_notice.call_args_list], [(i,) for i in IDS[:2]])
        self.assertEqual(self.public_notice.call_count, 2)
        self.assertEqual(report['schema_version'], 2)
        self.assertEqual(report['request_count'], 4)
        self.assertEqual(report['credentialed_requests'], 0)
        self.assertEqual(report['request_mode'], 'anonymous_public_reviewed_notices')
        self.assertEqual(report['description_inspections'], [])
        self.assertTrue(report['reviewed_notices_match'])
        self.assertFalse(report['production_enabled'])
        self.assertFalse(report['merge_preview']['written'])
        self.assertTrue(report['merge_preview']['validation']['ok'])
        self.assertEqual(report['merge_preview']['stats']['external_added'], 2)
        self.assertEqual([item['status'] for item in report['merge_preview']['sources']], ['refreshed'])
        for candidate in report['candidates']:
            self.assertEqual(candidate['catalog_matches'],
                             {'same_sam_notice': [], 'same_number_requires_sponsor_check': []})
        self.assertEqual(report['comparison_scope'],
                         'Current catalog only; absence here does not establish absence from Grants.gov')

    def test_v2_rejects_legacy_description_selection_before_any_request(self):
        with self.assertRaises(ValueError):
            sam.preview(root=self.root, today=TODAY, selected_ids=[IDS[0]],
                        public_notice=self.public_notice, listing=self.listing, description=self.description)
        self.public_notice.assert_not_called()
        self.listing.assert_not_called()
        self.description.assert_not_called()

    def test_invalid_or_oversized_reviewed_config_is_rejected_before_public_calls(self):
        self.config['approved_notices'] = self.config['approved_notices'][:1] * 101
        self.save_config()
        with self.assertRaises(sam.SamError):
            sam.preview(root=self.root, today=TODAY, public_notice=self.public_notice,
                        listing=self.listing, description=self.description)
        self.public_notice.assert_not_called()
        self.listing.assert_not_called()
        self.description.assert_not_called()

    def test_public_inventory_fetch_has_four_workers_and_no_unapproved_ids(self):
        from concurrent.futures import ThreadPoolExecutor
        with patch.object(sam, 'ThreadPoolExecutor', wraps=ThreadPoolExecutor) as executor:
            self.run_preview()
        executor.assert_called_once_with(max_workers=4)
        self.assertEqual({call.args[0] for call in self.public_notice.call_args_list}, set(IDS[:2]))

    def test_changed_snapshot_marks_preview_unmatched_without_silently_readmitting(self):
        self.snapshots[IDS[0]]['review_sha256'] = 'f' * 64
        report = self.run_preview()
        self.assertFalse(report['reviewed_notices_match'])
        candidates = {item['notice_id']: item for item in report['candidates']}
        self.assertEqual(candidates[IDS[0]]['admission_reasons'], ['reviewed_evidence_changed'])
        self.assertEqual(candidates[IDS[1]]['admission_reasons'], [])
        self.assertEqual(self.public_notice.call_count, 2)

    def test_preview_and_merge_use_the_same_bounded_exact_successor_reconciliation(self):
        from scripts.sources.sam_public import digest
        item = self.config['approved_notices'][0]
        anchor = self.snapshots[IDS[0]]
        anchor['review_sha256'] = digest({key: value for key, value in anchor.items() if key != 'review_sha256'})
        item.update(review_sha256=anchor['review_sha256'], reviewed_snapshot=deepcopy(anchor))
        current = dict(deepcopy(anchor), notice_id=IDS[2], latest_notice_id=IDS[2],
                       posted_at='2026-10-01', modified_at='2026-10-01')
        current['review_sha256'] = digest({key: value for key, value in current.items() if key != 'review_sha256'})
        self.snapshots[IDS[2]] = current
        self.snapshots[IDS[0]].update(latest=False, latest_notice_id=IDS[2])
        self.save_config()
        report = self.run_preview()
        self.assertTrue(report['reviewed_notices_match'])
        self.assertEqual(self.public_notice.call_count, 3)
        self.assertEqual(report['request_count'], 6)
        candidate = next(row for row in report['candidates'] if row['approved_notice_id'] == IDS[0])
        self.assertEqual(candidate['notice_id'], IDS[2])
        self.assertEqual(candidate['admission_reasons'], [])
        self.assertEqual(candidate['disposition'], 'admitted')
        self.assertEqual(report['merge_preview']['stats']['external_added'], 2)

    def test_public_failure_is_not_retried_or_merged_and_omits_error_text(self):
        def public(notice_id):
            if notice_id == IDS[0]:
                error = sam.SamError('public_notice_unavailable',
                    {'request_count': 1, 'http_status': 503, 'raw_body': 'PRIVATE ' + KEY})
                error.args = ('RAW EXCEPTION ' + KEY,)
                raise error
            return deepcopy(self.snapshots[notice_id]), {'request_count': 2, 'http_status': 200}
        self.public_notice.side_effect = public
        before = self.files()
        with patch.object(sam, 'integrate') as integrate, self.assertRaises(sam.SamError) as caught:
            sam.preview(root=self.root, today=TODAY, public_notice=self.public_notice,
                        listing=self.listing, description=self.description)
        integrate.assert_not_called()
        self.assertEqual(before, self.files())
        self.assertEqual(self.public_notice.call_count, 2)
        self.assertEqual(caught.exception.diagnostics['request_count'], 3)
        self.assertEqual(caught.exception.diagnostics['failures'], [{'notice_id': IDS[0], 'http_status': 503, 'failure_class': 'invalid_client'}])
        encoded = json.dumps(caught.exception.diagnostics) + str(caught.exception)
        for forbidden in ('PRIVATE', 'RAW EXCEPTION', KEY):
            self.assertNotIn(forbidden, encoded)

    def test_public_snapshot_keeps_only_hashes_of_private_body_and_contact_fields(self):
        from scripts.sources.sam_public import snapshot
        notice_id = IDS[0]
        payload = {'opportunityId': notice_id, 'id': notice_id,
                   'latest': True, 'archived': False, 'cancelled': False, 'deleted': False,
                   'status': {'code': 'published'},
                   '_links': {'opportunity:publish:latest': {'href': f'/opps/v2/opportunities/{notice_id}'}},
                   'postedDate': '2026-09-30', 'modifiedDate': '2026-09-30',
                   'description': [{'opportunityId': notice_id, 'descriptionId': 'synthetic',
                                    'body': 'RAW BODY private@example.gov (202) 555-0199 ' + KEY}],
                   'pointOfContact': [{'email': 'private@example.gov'}],
                   'data2': {'title': 'Synthetic NASA research call',
                             'solicitationNumber': self.config['approved_notices'][0]['solicitation_number'],
                             'organizationId': '12345', 'type': 'o', 'naics': [],
                             'solicitation': {'deadlines': {'response': '2026-11-30T17:00:00'}}}}
        resources = {'_embedded': {'opportunityAttachmentList': [
            {'opportunityId': notice_id, 'attachments': [{'attachmentId': 'a', 'resourceId': 'b',
                'name': 'Reviewed call.pdf', 'accessLevel': 'public', 'createdBy': 'private@example.gov'}]}]}}
        self.snapshots[notice_id] = snapshot(payload, resources, notice_id)
        self.config['approved_notices'][0]['review_sha256'] = self.snapshots[notice_id]['review_sha256']
        self.save_config()
        report = self.run_preview()
        encoded = json.dumps(report)
        for forbidden in ('RAW BODY', 'private@example.gov', '555-0199', KEY, 'pointOfContact', 'createdBy'):
            self.assertNotIn(forbidden, encoded)
        self.assertRegex(report['candidates'][0]['description_sha256'], r'^[a-f0-9]{64}$')
        self.assertRegex(report['candidates'][0]['resources_sha256'], r'^[a-f0-9]{64}$')

    def test_cli_fails_when_reviewed_evidence_changed_even_if_merge_validation_passed(self):
        report = {'schema_version': 2, 'outcome': 'preview_completed', 'request_count': 2,
                  'reviewed_notices_match': False, 'catalog_changed': False,
                  'merge_preview': {'validation': {'ok': True}, 'sources': [{'status': 'refreshed'}]}}
        target = self.root / 'report.json'
        with patch.dict(os.environ, CONTEXT, clear=True), \
                patch('sys.argv', ['sam_import_preview', '--report', str(target)]), \
                patch.object(sam, 'preview', return_value=report) as preview, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(sam.main(), 1)
        preview.assert_called_once_with(None, [])
        self.assertFalse(json.loads(target.read_text())['reviewed_notices_match'])


class SamPreviewWorkflowTests(unittest.TestCase):
    def test_catalog_refresh_scopes_sam_secret_to_additional_sources_only(self):
        workflow = yaml.safe_load((sam.ROOT / '.github/workflows/refresh-opportunities.yml').read_text(encoding='utf8'))
        self.assertNotIn('SAM_API_KEY', workflow.get('env', {}))
        secret_steps = []
        for job in workflow['jobs'].values():
            self.assertNotIn('SAM_API_KEY', job.get('env', {}))
            secret_steps.extend(step for step in job.get('steps', []) if 'SAM_API_KEY' in json.dumps(step))
        self.assertEqual(len(secret_steps), 1)
        self.assertEqual(secret_steps[0]['id'], 'additional-sources')
        self.assertEqual(secret_steps[0]['env']['SAM_API_KEY'], '${{ secrets.SAM_API_KEY }}')
        self.assertIn('python -m scripts.sources merge', secret_steps[0]['run'])

    def test_sam_admission_config_invalidates_generation_and_source_fingerprints(self):
        policy = json.loads((sam.ROOT / 'config/release_dependencies.json').read_text(encoding='utf8'))
        self.assertIn('config/sam_gov.json', policy['generation'])
        self.assertIn('config/sam_gov.json', policy['dependency_groups']['source']['patterns'])

    def test_workflow_is_manual_main_read_only_and_secret_is_scoped_to_preview(self):
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding='utf8'))
        self.assertEqual(set(workflow.get('on') or workflow[True]), {'workflow_dispatch'})
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        self.assertNotIn('env', workflow)
        self.assertIs(workflow['concurrency']['cancel-in-progress'], False)
        self.assertEqual(set(workflow['jobs']), {'preview'})
        job = workflow['jobs']['preview']
        self.assertEqual(job['if'], "github.repository == 'mporosoff/grants-scraper' && github.ref == 'refs/heads/main' && github.event_name == 'workflow_dispatch'")
        # Up to 100 notices plus one exact successor each, four workers:
        # 51m40s bounded transport plus installation/report overhead.
        self.assertEqual(job['timeout-minutes'], 60)
        self.assertNotIn('env', job)
        secret_steps = [step for step in job['steps'] if 'secrets.' in json.dumps(step)]
        self.assertEqual(len(secret_steps), 1)
        step = secret_steps[0]
        self.assertEqual(step['env'], {'SAM_API_KEY': '${{ secrets.SAM_API_KEY }}',
                                      'DESCRIPTION_NOTICE_IDS': '${{ inputs.description_notice_ids }}'})
        self.assertIn('python -m tools.sam_import_preview', step['run'])
        self.assertIn('--description-notice-ids "$DESCRIPTION_NOTICE_IDS"', step['run'])
        self.assertNotIn('${{', step['run'])
        commands = [item['run'] for item in job['steps'] if 'run' in item]
        self.assertEqual(len(commands), 2)
        self.assertIn('python -m pip install -r requirements.txt', commands)
        upload = next(item for item in job['steps'] if item.get('uses', '').startswith('actions/upload-artifact@'))
        self.assertEqual(upload['if'], 'always()')
        self.assertEqual(upload['with']['path'], '${{ runner.temp }}/sam-import-preview/report.json')
        checkout = next(item for item in job['steps'] if item.get('uses', '').startswith('actions/checkout@'))
        self.assertIs(checkout['with']['persist-credentials'], False)

    def test_invalid_workflow_context_and_invalid_ids_prevent_all_api_calls(self):
        cases = [({'GITHUB_EVENT_NAME': 'schedule'}, ''), ({'GITHUB_REF': 'refs/heads/feature'}, ''),
                 ({'GITHUB_REPOSITORY': 'someone/fork'}, ''), ({'GITHUB_WORKFLOW_REF': 'other'}, ''),
                 ({'GITHUB_EVENT_NAME': ''}, ''), ({}, 'invalid'), ({}, ','.join(IDS[:3]))]
        with tempfile.TemporaryDirectory() as directory:
            for index, (changes, selected) in enumerate(cases):
                report_path = Path(directory) / str(index) / 'report.json'
                with self.subTest(changes=changes, selected=selected), \
                        patch.dict(os.environ, CONTEXT | changes, clear=True), \
                        patch('sys.argv', ['sam_import_preview', '--report', str(report_path), '--description-notice-ids', selected]), \
                        patch.object(sam, 'preview') as preview, redirect_stdout(io.StringIO()) as stdout:
                    self.assertEqual(sam.main(), 1)
                preview.assert_not_called()
                self.assertEqual(json.loads(report_path.read_text())['outcome'], 'preview_failed')
                self.assertNotIn(KEY, stdout.getvalue() + report_path.read_text())

    def test_cli_failure_omits_exception_text_from_report_and_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'report.json'
            with patch.dict(os.environ, CONTEXT, clear=True), \
                    patch('sys.argv', ['sam_import_preview', '--report', str(target)]), \
                    patch.object(sam, 'preview', side_effect=ValueError('RAW_EXCEPTION ' + KEY)), \
                    redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(sam.main(), 1)
            for text in (target.read_text(), stdout.getvalue()):
                self.assertNotIn(KEY, text)
                self.assertNotIn('RAW_EXCEPTION', text)


if __name__ == '__main__':
    unittest.main()
