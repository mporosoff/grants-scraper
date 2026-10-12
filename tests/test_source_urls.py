"""Source URLs retain routing data through canonical projection and link checks."""
from copy import deepcopy
from datetime import date
import unittest

from scripts.build_catalog import clean_text, safe_http_url
from scripts.check_links import annotate_catalog_link_health, catalog_urls, select_urls
from scripts.sources.adapters.nyserda import NyserdaAdapter
from scripts.submission_schedule import project


CORRECT = ('https://portal.nyserda.ny.gov/CORE_Solicitation_Detail_Page'
           '?SolicitationId=a0rcr00001NP7i5AAD')


class SourceUrlTests(unittest.TestCase):
    def test_url_punctuation_and_heading_words_are_not_prose(self):
        for url in (
            CORRECT,
            'https://agency.gov/path!Notice?PurposeText=a,b;c:d#OverviewDetails',
            'https://Agency.Example/EligibilityRules/notice.Version?Query=value',
            'https://agency.gov/path?first=a%20b+c&second=%26Encoded%3B&blank=&flag',
            'https://agency.gov/path?ID=one&ID=two',
        ):
            with self.subTest(url=url):
                self.assertEqual(safe_http_url(url), url)
                self.assertEqual(safe_http_url(safe_http_url(url)), url)

    def test_existing_markup_entities_whitespace_and_scheme_handling_remain(self):
        self.assertEqual(safe_http_url(' <p>https://agency.gov/path?A=one&amp;amp;B=two</p> '),
                         'https://agency.gov/path?A=one&B=two')
        self.assertEqual(safe_http_url('\twww.nsf.gov/funding\n'), 'https://www.nsf.gov/funding')
        self.assertEqual(safe_http_url('http://agency.gov/path?Question=Yes'),
                         'https://agency.gov/path?Question=Yes')
        self.assertEqual(safe_http_url('http://example.org/path?Question=Yes'),
                         'http://example.org/path?Question=Yes')
        for value in (None, '', 42, {}, '/relative', 'javascript:alert(1)', 'file:///tmp/notice'):
            with self.subTest(value=value):
                self.assertIsNone(safe_http_url(value))

    def test_clean_text_still_repairs_scientific_prose(self):
        self.assertEqual(clean_text('Partner.Projects follow.ObjectivesEach project applies.'),
                         'Partner. Projects follow. Objectives: Each project applies.')

    def test_no_unscoped_repair_of_already_malformed_source_query(self):
        # Retained corruption is repaired by a pinned release projection, not
        # by guessing identifiers or changing arbitrary third-party query keys.
        malformed = CORRECT.replace('?SolicitationId', '? SolicitationId')
        self.assertEqual(safe_http_url(malformed), malformed)

    def test_adapter_preserves_official_url_through_canonical_and_schedule_projection(self):
        item = {'SolicitationName': 'Offshore Wind Project Predevelopment',
                'SolicitationNumber': 'OSWPON26-1', 'ShortDescription': 'Unchanged source science.',
                'DetailPageLink': CORRECT, 'RevisedDate': '10/01/2026',
                'SolicitationLinkPDF': 'https://www.nyserda.ny.gov/notice.pdf',
                'SolicitationContacts': [{'Name': 'Public program contact', 'Email': 'contact@example.gov'}],
                'SolicitationRounds': [
                    {'Round': '1', 'Status': 'Open', 'DueDate': '12/31/2028 5:00 PM'},
                    {'Round': '2', 'Status': 'Open', 'DueDate': '12/31/2029 5:00 PM'}]}
        original = deepcopy(item)
        payload = {'FundingOpportunities': [{'FundingOpportunities': [item]}]}
        opportunity = NyserdaAdapter().parse_payload(payload, date(2026, 10, 12))[0]
        record = project(opportunity.to_record(slug='nyserda', source='NYSERDA', source_type='State'),
                         date(2026, 10, 12))
        self.assertEqual(item, original)
        self.assertEqual(record['detail_page'], CORRECT)
        self.assertEqual(record['funding_opportunity_url'], CORRECT)
        self.assertTrue(all(event['source_url'] == CORRECT for event in record['deadlines']))
        self.assertEqual(record['contacts'][0]['source_url'], CORRECT)
        self.assertEqual(record['next_submission']['event']['source_url'], CORRECT)
        self.assertEqual(record['description'], 'Unchanged source science.')
        self.assertEqual(record['last_updated'], '2026-10-01')
        self.assertEqual(record['primary_document_url'], 'https://www.nyserda.ny.gov/notice.pdf')

    def test_historical_malformed_link_observation_cannot_match_corrected_url(self):
        malformed = CORRECT.replace('?SolicitationId', '? SolicitationId')
        catalog = {'opportunities': [{'opportunity_id': 'nyserda:OSWPON26-1',
                                     'detail_page': CORRECT, 'funding_opportunity_url': CORRECT}]}
        state = {'generated_at': '2026-10-12T16:13:12Z', 'records': {
            malformed: {'status': 404, 'ok': False, 'checked_at': '2026-10-12T16:13:12Z'}}}
        original_state = deepcopy(state)
        urls = catalog_urls(catalog)
        self.assertEqual(urls, {CORRECT: ['nyserda:OSWPON26-1']})
        self.assertEqual(select_urls(urls, state['records'], 1), [CORRECT])
        self.assertEqual(annotate_catalog_link_health(catalog, state), 0)
        self.assertNotIn('link_health_broken_urls', catalog['opportunities'][0])
        self.assertEqual(state, original_state)


if __name__ == '__main__':
    unittest.main()
