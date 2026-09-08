from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from scripts import extract_document_evidence as e
from scripts.notice_structure_cache import StructureCache
from tools.verify_notice_publication import verify


class NoticePublicationTests(unittest.TestCase):
    def candidate(self):
        now = datetime(2026, 9, 7, tzinfo=timezone.utc)
        record = {'opportunity_id': 'fixture', 'primary_document_url': 'https://example.gov/notice.html',
                  'close_date': '2027-05-01'}
        source = e.source_for_record(record)
        entry, _ = e.build_document_entry(record, source, {'url': source['url'], 'content_type': 'text/html',
            'content': b'<p>Cost sharing is not required.</p>'}, None, now)
        with tempfile.TemporaryDirectory() as directory:
            return e.enrich_document_evidence({'generated_at': e.iso_utc(now), 'opportunities': [record]},
                {'records': {'fixture': entry}}, now=now, max_documents=0, structure_cache=StructureCache(directory))

    def test_current_projection_is_read_only_and_ready_without_source_calls(self):
        catalog, cache = self.candidate()
        before = deepcopy((catalog, cache))
        report = verify(catalog, cache)
        self.assertTrue(report['publication_ready'])
        self.assertEqual((report['source_requests'], report['provider_requests']), (0, 0))
        self.assertEqual((catalog, cache), before)

    def test_feed_submission_frame_does_not_advance_with_bookkeeping_timestamp(self):
        from scripts.build_feeds import build_feeds
        import xml.etree.ElementTree as ET
        record = {'opportunity_id': 'fixture', 'title': 'Source-owned schedule', 'status': 'posted',
                  'close_date': '2027-05-01', 'deadlines': [
                      {'kind': 'concept_paper', 'date': '2026-09-08', 'required': True},
                      {'kind': 'application', 'date': '2027-05-01'}]}
        summaries = []
        with tempfile.TemporaryDirectory() as directory:
            for merged in ('2026-09-07T12:00:00Z', '2026-09-20T12:00:00Z'):
                catalog = {'generated_at': '2026-09-07T00:00:00Z', 'opportunities': [record],
                           'diagnostics': {'additional_sources': {'merged_at': merged}}}
                build_feeds(catalog, Path(directory))
                root = ET.parse(Path(directory) / 'all.xml')
                summaries.append(root.find('.//{http://www.w3.org/2005/Atom}summary').text)
        self.assertEqual(summaries[0], summaries[1])
        self.assertIn('Concept Paper 2026-09-08', summaries[0])

    def test_stale_public_fact_or_selection_blocks_before_publication(self):
        for field in ('fact', 'next_submission'):
            catalog, cache = self.candidate()
            if field == 'fact':
                catalog['opportunities'][0]['document_evidence']['facts'][0]['value'] = True
            else:
                catalog['opportunities'][0].pop('next_submission')
            self.assertFalse(verify(catalog, cache)['publication_ready'])

    def test_written_deadline_references_are_equivalent_but_wrong_citations_are_not(self):
        from scripts.build_catalog import write_catalog
        from scripts.enrich_catalog import read_catalog
        now = datetime(2026, 9, 7, tzinfo=timezone.utc)
        record = {'opportunity_id': 'fixture', 'primary_document_url': 'https://example.gov/notice.html',
                  'deadlines': [{'kind': 'application', 'date': '2027-05-01'}]}
        source = e.source_for_record(record)
        entry, _ = e.build_document_entry(record, source, {'url': source['url'], 'content_type': 'text/html',
            'content': b'<p>Application deadline: May 1, 2027 at 5 PM Eastern.</p>'}, None, now)
        with tempfile.TemporaryDirectory() as directory:
            catalog, cache = e.enrich_document_evidence({'generated_at': e.iso_utc(now), 'record_count': 1, 'opportunities': [record]},
                {'records': {'fixture': entry}}, now=now, max_documents=0, structure_cache=StructureCache(directory))
            path = Path(directory) / 'opportunities.js'
            write_catalog(catalog, path)
            published = read_catalog(path)
        deadline = published['opportunities'][0]['deadlines'][0]
        self.assertTrue(deadline['document_evidence_id'])
        self.assertNotIn('citation', deadline)
        self.assertTrue(verify(published, cache)['publication_ready'])
        deadline['citation'] = {'quote': 'An unrelated deadline statement.'}
        self.assertFalse(verify(published, cache)['publication_ready'])

    def test_pending_recovery_is_allowed_only_with_its_current_safe_projection(self):
        catalog, cache = self.candidate()
        cache['records']['fixture']['parser_dependencies']['cost_share'] = 'old'
        self.assertFalse(verify(catalog, cache)['publication_ready'])
        with tempfile.TemporaryDirectory() as directory:
            catalog, cache = e.enrich_document_evidence(catalog, cache, max_documents=0,
                now=datetime(2026, 9, 7, tzinfo=timezone.utc), structure_cache=StructureCache(directory))
        self.assertTrue(verify(catalog, cache)['publication_ready'])

    def failed_changed_source(self):
        catalog, cache = self.candidate()
        catalog['opportunities'][0]['primary_document_url'] = 'https://example.gov/revised-notice.html'
        def failed_fetch(*_):
            raise ValueError('Unavailable official document')
        with tempfile.TemporaryDirectory() as directory:
            return e.enrich_document_evidence(catalog, cache,
                now=datetime(2026, 9, 7, tzinfo=timezone.utc), max_documents=1, request_delay=0,
                fetcher=failed_fetch, structure_cache=StructureCache(directory))

    def test_failed_changed_source_replays_without_fetch_or_losing_failure_diagnostics(self):
        catalog, cache = self.failed_changed_source()
        before = deepcopy((catalog, cache))
        report = verify(catalog, cache, candidate_id='retained-candidate')
        self.assertTrue(report['publication_ready'])
        self.assertEqual(report['changes'], [])
        self.assertEqual(report['replay_observations'][0], {
            'opportunity_id': 'fixture', 'field': 'document_evidence_status',
            'before': 'failed', 'after': 'source_changed',
            'reason': 'generation_retrieval_failure_not_replayed',
            'generation_attempt_at': catalog['document_evidence_generated_at']})
        self.assertEqual((report['source_requests'], report['provider_requests']), (0, 0))
        self.assertEqual((catalog, cache), before)

    def test_failed_source_status_requires_exact_current_failure_and_withheld_evidence(self):
        for change in ('missing_failure', 'wrong_url', 'wrong_error', 'old_attempt', 'old_evidence', 'wrong_deadline'):
            with self.subTest(change=change):
                catalog, cache = self.failed_changed_source()
                failures = catalog['diagnostics']['document_evidence']['failures']
                if change == 'missing_failure':
                    failures.clear()
                elif change == 'wrong_url':
                    failures[0]['url'] = 'https://example.gov/unrelated.html'
                elif change == 'wrong_error':
                    failures[0]['error'] = 'DifferentFailure'
                elif change == 'old_attempt':
                    cache['records']['fixture']['last_attempt_at'] = '2025-01-01T00:00:00Z'
                elif change == 'old_evidence':
                    catalog['opportunities'][0]['document_search_text'] = 'Old source facts must remain withheld'
                else:
                    catalog['opportunities'][0]['next_submission'] = {'date': '2099-01-01'}
                self.assertFalse(verify(catalog, cache)['publication_ready'])

    def test_obsolete_scientific_children_block_even_when_parent_facts_match(self):
        catalog, cache = self.candidate()
        cache['records']['fixture'].update(subtopic_method='hgeo_declared_topics', subtopics=[])
        children = {'records': {'fixture': {'subtopics': [{'opportunity_id': 'fixture:a-1'}]}}}
        self.assertFalse(verify(catalog, cache, children)['publication_ready'])
        children['records']['fixture']['subtopics'] = []
        self.assertTrue(verify(catalog, cache, children)['publication_ready'])


if __name__ == '__main__':
    unittest.main()
