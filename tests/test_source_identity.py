"""Source identity and retained evidence reach normal shared entrypoints."""
from copy import deepcopy
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
import unittest

from scripts.build_catalog import record_identity
from scripts.sources.merge import merge_records
from scripts.source_documents import document_candidates
from scripts import extract_document_evidence as evidence, subtopic_sources
from scripts.notice_structure_cache import StructureCache
from tests.test_subtopic_sources import notice, TOPICS, BLAND, PDF_DOC, extract_containers


class SourceIdentityTests(unittest.TestCase):
    def record(self, identifier, agency, number='RFP-1', **values):
        return {'opportunity_id': identifier, 'opportunity_number': number, 'agency': agency,
                'title': 'Supported research call', 'source': 'Grants.gov', **values}

    def test_two_sponsors_and_unknown_sponsors_cannot_collapse_by_number_or_title(self):
        for agencies in [('Department of Energy', 'National Science Foundation'), (None, None), ('Unknown', 'Unknown')]:
            records = [self.record(str(i), agency) for i, agency in enumerate(agencies)]
            self.assertNotEqual(record_identity(records[0]), record_identity(records[1]))
            merged, _ = merge_records(records[:1], records[1:])
            self.assertEqual(len(merged), 2)

    def test_default_sponsor_alias_is_not_authoritative_identity(self):
        for agency in ('DOE', 'DARPA', 'Unknown sponsor'):
            records = [self.record(str(i), agency, agency_authority='source_default') for i in range(2)]
            self.assertNotEqual(record_identity(records[0]), record_identity(records[1]))
            merged, _ = merge_records(records[:1], records[1:])
            self.assertEqual(len(merged), 2)

    def test_true_duplicate_preserves_id_authority_alias_and_only_annex(self):
        base = self.record('123', 'Department of Energy', close_date='2027-05-01', award_ceiling=500000)
        supplemental = self.record('exchange:RFP-1', 'DOE EERE Exchange', source='DOE Exchange',
            close_date='2027-06-01', award_ceiling=900000, primary_document_url='https://example.gov/annex.html')
        original = deepcopy(base)
        merged, _ = merge_records([base], [supplemental])
        self.assertEqual(base, original)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['opportunity_id'], '123')
        self.assertEqual(merged[0]['award_ceiling'], 500000)
        self.assertEqual(merged[0]['close_date'], '2027-05-01')
        self.assertEqual(merged[0]['source_aliases'][0]['opportunity_id'], 'exchange:RFP-1')
        self.assertEqual(len(merged[0]['duplicate_source_conflicts']), 2)
        self.assertEqual(evidence.source_for_record(merged[0])['url'], supplemental['primary_document_url'])
        again, _ = merge_records(merged, [supplemental])
        self.assertEqual(again, merged)

    def test_duplicate_official_document_reaches_normal_enrichment_and_index(self):
        base = self.record('123', 'Department of Energy')
        supplemental = self.record('exchange:RFP-1', 'DOE', source='DOE Exchange',
            primary_document_url='https://example.gov/annex.html')
        merged, _ = merge_records([base], [supplemental])
        def fetch(url, headers):
            return {'url': url, 'content_type': 'text/html', 'content':
                    b'<h2>Eligibility</h2><p>Eligible applicants include institutions studying zeolite catalysis.</p>'}
        with TemporaryDirectory() as directory:
            output, _ = evidence.enrich_document_evidence({'opportunities': merged}, {'records': {}},
                now=datetime(2026, 9, 7, tzinfo=timezone.utc), request_delay=0,
                structure_cache=StructureCache(directory), fetcher=fetch)
        self.assertEqual(output['opportunities'][0]['document_evidence_status'], 'current')
        self.assertIn('zeolite', output['opportunities'][0]['document_search_text'])
        self.assertIn('zeolite', str(output['search_index']))

    def test_adapter_detail_url_survives_duplicate_without_a_primary_attachment(self):
        from scripts.sources.base import CanonicalOpportunity
        base = self.record('123', 'Department of Energy', close_date='2027-05-01', award_ceiling=500000)
        url = 'https://eere-exchange.energy.gov/#FoaId00000000-0000-0000-0000-000000000001'
        other = CanonicalOpportunity(title='Supported research call', external_id='RFP-1', opportunity_number='RFP-1',
            agency='Department of Energy', url=url).to_record(source='DOE EERE Exchange', source_type='Federal',
                slug='eere-exchange')
        merged, _ = merge_records([base], [other])
        self.assertEqual(len(merged), 1)
        self.assertEqual(evidence.source_for_record(merged[0])['url'], url)
        self.assertEqual(merged[0]['award_ceiling'], 500000)
        self.assertEqual(merged[0]['close_date'], '2027-05-01')
        self.assertIsNotNone(evidence.source_for_record({**base, 'funding_opportunity_url': url}))

    def test_duplicate_scientific_attachment_reaches_existing_bounded_selector(self):
        base = self.record('123', 'Department of Energy', primary_document_url=PDF_DOC['url'])
        supplemental = self.record('exchange:RFP-1', 'DOE', source='DOE Exchange',
            primary_document_url='https://example.gov/annex.pdf', primary_document_name='annex.pdf')
        merged, _ = merge_records([base], [supplemental])
        calls = []
        def fetch(url):
            calls.append(url)
            return {'url': url, 'content_type': 'application/pdf', 'content': notice(TOPICS)}
        result, document, _ = subtopic_sources.best_segmentation(merged[0], BLAND, PDF_DOC,
            extract_containers=extract_containers, download=fetch, detail_fetcher=lambda _: {}, collector=lambda _: [])
        self.assertEqual(calls, [supplemental['primary_document_url']])
        self.assertEqual(len(result.subtopics), 3)
        self.assertEqual(document['url'], supplemental['primary_document_url'])
        # The old secondary-document scientific confidence gate still applies.
        self.assertEqual(result.confidence, 'low')

    def test_unsafe_retained_document_candidates_never_reach_fetch_selection(self):
        record = self.record('123', 'DOE', document_urls=['http://127.0.0.1/x', 'http://localhost/x',
            'https://user:password@example.gov/x', 'https://example.gov/annex.pdf'])
        self.assertEqual([item['url'] for item in document_candidates(record)], ['https://example.gov/annex.pdf'])


if __name__ == '__main__':
    unittest.main()
